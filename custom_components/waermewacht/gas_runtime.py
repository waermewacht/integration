"""Runtime of a gas boiler entry: analysis from the long-term statistics only.

No state listeners: shortly after the start and then once a day the last
365 days are read from the statistics and analysed (gas.py). With readings
by hand (readings.py) the gas comes from them instead; they are the only
thing stored, in a file of their own written when a reading is added or
removed. The heat pump runtime, its templates and health check are not
involved.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BOILER_EFFICIENCY,
    CONF_CALORIFIC_VALUE,
    CONF_DESIGN_TEMP,
    CONF_ENTITIES,
    CONF_GAS_BASE_PRICE,
    CONF_GAS_PRICE,
    CONF_MANUAL_UNIT,
    CONF_Z_NUMBER,
    DOMAIN,
    GAS_DHW,
    GAS_HEATING,
    GAS_TOTAL,
    KIND_GAS,
    MANUAL_UNITS,
    STORAGE_VERSION,
    VOLUME_UNIT,
)
from .costs import BOILER_EFFICIENCY_HS
from .counter import UNIT_FACTORS
from .energy import Totals
from .entity import own_entities
from .gas import GasAnalysis, analyse, heat_hours, split_dhw, volume_to_kwh, window
from .heat_load import HeatLoad
from .model import Signal
from .periods import local_midnight
from .readings import (
    Reading,
    add_reading,
    analyse_readings,
    check_reading,
    inside,
    periods,
    readings_signature,
    summer_base,
    to_kwh,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# Shortly after the start, then daily at this local hour (as the heat pump).
ANALYSIS_DELAY = timedelta(minutes=2)
ANALYSIS_HOUR = 3
# An hourly change above this (kWh, a large boiler with margin) or below 0 is
# a replaced meter or a glitch (own assumption).
MAX_KWH_PER_HOUR = 100.0

# Why the analysis has no result.
NO_RECORDER = "no_recorder"
UNIT = "gas_unit"
NO_CALORIFIC_VALUE = "no_calorific_value"
NOT_ANALYSED = "not_analysed_yet"
# Errors of the reading actions (translation keys of exceptions).
READING_IN_FUTURE = "reading_in_future"
READING_NOT_FOUND = "reading_not_found"


def _per_kwh(cents: float | None) -> float | None:
    return None if cents is None else cents / 100


class GasRuntime:
    """One gas boiler: figures of the last 365 days."""

    kind = KIND_GAS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.tz = dt_util.get_default_time_zone()
        configured: dict[str, str] = dict(entry.data[CONF_ENTITIES])
        if own := own_entities(hass, configured.values()):
            # From before the form refused them; the outdoor temperature
            # cannot be left out, so only a warning.
            _LOGGER.warning(
                "%s reads sensors of Wärmewacht itself (%s); choose the "
                "boiler's under Reconfigure",
                entry.title,
                ", ".join(own),
            )
        # Readings by hand: a meter for heating and hot water.
        self.manual_unit: str | None = MANUAL_UNITS.get(
            entry.data.get(CONF_MANUAL_UNIT) or ""
        )
        self.includes_dhw = GAS_TOTAL in configured or self.manual
        self.gas_entity = configured.get(GAS_TOTAL) or configured.get(GAS_HEATING, "")
        self.dhw_entity = configured.get(GAS_DHW)
        self.flow_entity = configured.get(Signal.FLOW_TEMP.value)
        # Keyed like the heat pump's for the shared actions.
        self.entities: dict[Signal, str] = {
            Signal.OUTDOOR_TEMP: configured[Signal.OUTDOOR_TEMP.value]
        }
        options = entry.options
        self.efficiency: float = options.get(
            CONF_BOILER_EFFICIENCY, BOILER_EFFICIENCY_HS
        )
        self.calorific_value: float | None = options.get(CONF_CALORIFIC_VALUE)
        self.z_number: float | None = options.get(CONF_Z_NUMBER)
        self.gas_price = _per_kwh(options.get(CONF_GAS_PRICE))
        self.gas_base_price: float | None = options.get(CONF_GAS_BASE_PRICE)
        self.design_temp: float | None = options.get(CONF_DESIGN_TEMP)
        self.analysis: GasAnalysis | None = None
        self.analysed_at: datetime | None = None
        self.problem: str | None = NOT_ANALYSED
        self._analysing = False
        self._again = False  # a reading came in during an analysis
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsubscribe: list[CALLBACK_TYPE] = []
        self.readings: list[Reading] = []
        self._readings_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.readings"
        )

    @property
    def manual(self) -> bool:
        """Readings by hand instead of a counter entity."""
        return self.manual_unit is not None

    # Lifecycle.

    async def async_start(self) -> None:
        if self.manual and (data := await self._readings_store.async_load()):
            self.readings = [
                Reading(datetime.fromisoformat(at), float(value))
                for at, value in data.get("readings", [])
            ]

        @callback
        def _soon(_now: datetime) -> None:
            # Bound to the entry: an unload cancels a running analysis.
            self.entry.async_create_background_task(
                self.hass, self.async_refresh(), "waermewacht_gas_refresh"
            )

        self._unsubscribe = [
            async_call_later(
                self.hass,
                ANALYSIS_DELAY,
                HassJob(_soon, "waermewacht_gas_first", cancel_on_shutdown=True),
            ),
            async_track_time_change(
                self.hass, _soon, hour=ANALYSIS_HOUR, minute=0, second=0
            ),
        ]

    async def async_stop(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = []

    async def async_remove(self) -> None:
        """Delete the readings (the only thing stored)."""
        await self._readings_store.async_remove()

    # Readings by hand.

    async def async_add_reading(self, at: datetime, value: float) -> None:
        """Add a reading (replacing one at the same minute); raises
        ServiceValidationError if it does not fit."""
        at = at.astimezone(dt_util.UTC).replace(second=0, microsecond=0)
        if at > dt_util.utcnow() + timedelta(minutes=1):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=READING_IN_FUTURE
            )
        if (error := check_reading(self.readings, at, value)) is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=error,
                translation_placeholders={"value": f"{value:g}"},
            )
        self.readings = add_reading(self.readings, Reading(at, value))
        await self._async_readings_changed()

    async def async_remove_reading(self, at: datetime) -> None:
        """Remove the reading at the minute of `at`."""
        at = at.astimezone(dt_util.UTC).replace(second=0, microsecond=0)
        kept = [r for r in self.readings if r.at != at]
        if len(kept) == len(self.readings):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=READING_NOT_FOUND
            )
        self.readings = kept
        await self._async_readings_changed()

    async def _async_readings_changed(self) -> None:
        await self._readings_store.async_save(
            {"readings": [[r.at.isoformat(), r.value] for r in self.readings]}
        )
        self._notify()
        # A task of the entry (not a background one): the new figures follow
        # at once, and an unload waits for it.
        self.entry.async_create_task(
            self.hass, self.async_refresh(), "waermewacht_gas_refresh"
        )

    def _readings_kwh(self) -> list[tuple[datetime, float]] | None:
        """The readings in kWh (Hs); None (with `problem`) without the
        calorific value and Z-number for a meter in m³."""
        volume = self.manual_unit == VOLUME_UNIT
        if volume and not (self.calorific_value and self.z_number):
            self.problem = NO_CALORIFIC_VALUE
            return None
        return to_kwh(
            self.readings,
            volume=volume,
            calorific_value=self.calorific_value,
            z_number=self.z_number,
        )

    async def async_readings_heat_load(
        self, start: datetime, end: datetime, design_temp: float | None
    ) -> HeatLoad | None:
        """Energy signature from the readings in [start, end) (action heat_load)."""
        if (readings := self._readings_kwh()) is None:
            return None
        outdoor = await self.async_outdoor_hours(start, end)
        found = inside(periods(readings, outdoor, self.tz), start, end)
        dhw_per_day, _ = summer_base(found)
        return readings_signature(
            found, dhw_per_day, self.efficiency, self.tz, design_temp=design_temp
        )

    @callback
    def add_listener(self, listener: CALLBACK_TYPE) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # Analysis.

    async def async_refresh(self) -> None:
        """Analyse the last 365 full days; never raises."""
        if self._analysing:
            self._again = True
            return
        self._analysing = True
        try:
            now = dt_util.utcnow()
            start, end = window(now, self.tz)
            first, last = local_midnight(start, self.tz), local_midnight(end, self.tz)
            if self.manual:
                if "recorder" not in self.hass.config.components:
                    self.problem = NO_RECORDER
                    return
                if (readings := self._readings_kwh()) is None:
                    return
                self.analysis = analyse_readings(
                    readings,
                    await self.async_outdoor_hours(first, last),
                    self.tz,
                    start,
                    end,
                    efficiency=self.efficiency,
                    design_temp=self.design_temp,
                    gas_price=self.gas_price,
                    gas_base_price=self.gas_base_price,
                )
                self.problem = None
                self.analysed_at = now
                return
            data = await self._async_gas(first, last)
            if data is None:  # the last result stays (entity briefly away)
                return
            gas, dhw = data
            outdoor = await self.async_outdoor_hours(first, last)
            flow = (
                await self._async_mean_hours(self.flow_entity, first, last)
                if self.flow_entity
                else None
            )
            self.analysis = analyse(
                gas,
                outdoor,
                self.tz,
                start,
                end,
                includes_dhw=self.includes_dhw,
                dhw=dhw,
                efficiency=self.efficiency,
                design_temp=self.design_temp,
                gas_price=self.gas_price,
                gas_base_price=self.gas_base_price,
                flow=flow,
            )
            self.problem = None
            self.analysed_at = now
        except Exception:  # keep running; the sensors stay as they were
            _LOGGER.exception("Analysing the gas consumption failed")
        finally:
            self._analysing = False
            self._notify()
            if self._again:
                self._again = False
                self.entry.async_create_task(
                    self.hass, self.async_refresh(), "waermewacht_gas_refresh"
                )

    async def async_analysis_data(
        self, start: datetime, end: datetime
    ) -> tuple[dict[datetime, Totals], dict[datetime, float]]:
        """Hourly heat (hot water apart) and outdoor means of [start, end),
        for the action heat_load."""
        data = await self._async_gas(start, end)
        outdoor = await self.async_outdoor_hours(start, end)
        if data is None:
            return {}, outdoor
        gas, dhw = data
        split = split_dhw(
            gas, outdoor, self.tz, includes_dhw=self.includes_dhw, dhw=dhw
        )
        return heat_hours(split, self.efficiency), outdoor

    async def _async_gas(
        self, start: datetime, end: datetime
    ) -> tuple[dict[datetime, float], dict[datetime, float] | None] | None:
        """Hourly gas (kWh Hs) of the main and the hot water counter; None
        (with `problem` set) when it cannot be read."""
        if "recorder" not in self.hass.config.components:
            self.problem = NO_RECORDER
            return None
        ids = [self.gas_entity, *([self.dhw_entity] if self.dhw_entity else [])]
        units = {entity_id: self._unit(entity_id) for entity_id in ids}
        if any(unit is None for unit in units.values()):
            self.problem = UNIT
            return None
        if VOLUME_UNIT in units.values() and not (
            self.calorific_value and self.z_number
        ):
            self.problem = NO_CALORIFIC_VALUE
            return None
        rows = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            end,
            set(ids),
            "hour",
            {"energy": "kWh", "volume": VOLUME_UNIT},
            {"change"},
        )
        hourly: dict[str, dict[datetime, float]] = {}
        for entity_id in ids:
            values: dict[datetime, float] = {}
            for row in rows.get(entity_id, []):
                change = row.get("change")
                if change is None or not change >= 0:
                    continue
                hour = row["start"]
                if not isinstance(hour, datetime):
                    hour = dt_util.utc_from_timestamp(hour)
                values[hour] = change
            if units[entity_id] == VOLUME_UNIT:
                assert self.calorific_value and self.z_number
                values = volume_to_kwh(values, self.calorific_value, self.z_number)
            hourly[entity_id] = {
                h: kwh for h, kwh in values.items() if kwh <= MAX_KWH_PER_HOUR
            }
        gas = hourly[self.gas_entity]
        dhw = hourly[self.dhw_entity] if self.dhw_entity else None
        return gas, dhw

    def _unit(self, entity_id: str) -> str | None:
        """kWh for any energy unit, VOLUME_UNIT, or None if unusable."""
        state = self.hass.states.get(entity_id)
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if state else None
        if unit in UNIT_FACTORS:
            return "kWh"
        return VOLUME_UNIT if unit == VOLUME_UNIT else None

    async def async_outdoor_hours(
        self, start: datetime, end: datetime
    ) -> dict[datetime, float]:
        """Hourly mean outdoor temperature from the long-term statistics."""
        return await self._async_mean_hours(
            self.entities[Signal.OUTDOOR_TEMP], start, end
        )

    async def _async_mean_hours(
        self, entity_id: str, start: datetime, end: datetime
    ) -> dict[datetime, float]:
        """Hourly mean of a temperature from the long-term statistics."""
        if start >= end or "recorder" not in self.hass.config.components:
            return {}
        rows = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            end,
            {entity_id},
            "hour",
            {"temperature": UnitOfTemperature.CELSIUS},
            {"mean"},
        )
        means: dict[datetime, float] = {}
        for row in rows.get(entity_id, []):
            if (mean := row.get("mean")) is None:
                continue
            hour = row["start"]
            if not isinstance(hour, datetime):
                hour = dt_util.utc_from_timestamp(hour)
            means[hour] = mean
        return means
