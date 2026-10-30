"""Runtime of a gas boiler entry: analysis from the long-term statistics only.

No state listeners and no store: shortly after the start and then once a day
the last 365 days are read from the statistics and analysed (gas.py). The
heat pump runtime, its templates and health check are not involved.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BOILER_EFFICIENCY,
    CONF_CALORIFIC_VALUE,
    CONF_DESIGN_TEMP,
    CONF_ENTITIES,
    CONF_GAS_BASE_PRICE,
    CONF_GAS_PRICE,
    CONF_Z_NUMBER,
    GAS_DHW,
    GAS_HEATING,
    GAS_TOTAL,
    KIND_GAS,
    VOLUME_UNIT,
)
from .costs import BOILER_EFFICIENCY_HS
from .counter import UNIT_FACTORS
from .energy import Totals
from .gas import GasAnalysis, analyse, heat_hours, split_dhw, volume_to_kwh, window
from .model import Signal
from .periods import local_midnight

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
        self.includes_dhw = GAS_TOTAL in configured
        self.gas_entity = configured.get(GAS_TOTAL) or configured[GAS_HEATING]
        self.dhw_entity = configured.get(GAS_DHW)
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
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsubscribe: list[CALLBACK_TYPE] = []

    # Lifecycle.

    async def async_start(self) -> None:
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
        """Nothing is stored."""

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
            return
        self._analysing = True
        try:
            now = dt_util.utcnow()
            start, end = window(now, self.tz)
            first, last = local_midnight(start, self.tz), local_midnight(end, self.tz)
            data = await self._async_gas(first, last)
            if data is None:  # the last result stays (entity briefly away)
                return
            gas, dhw = data
            outdoor = await self.async_outdoor_hours(first, last)
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
            )
            self.problem = None
            self.analysed_at = now
        except Exception:  # keep running; the sensors stay as they were
            _LOGGER.exception("Analysing the gas consumption failed")
        finally:
            self._analysing = False
            self._notify()

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
        entity_id = self.entities[Signal.OUTDOOR_TEMP]
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
        outdoor: dict[datetime, float] = {}
        for row in rows.get(entity_id, []):
            if (mean := row.get("mean")) is None:
                continue
            hour = row["start"]
            if not isinstance(hour, datetime):
                hour = dt_util.utc_from_timestamp(hour)
            outdoor[hour] = mean
        return outdoor
