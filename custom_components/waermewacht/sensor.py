"""Sensors: ratios per mode and period, energy, cycling, diagnosis.

Ratio sensors have no state class: the long-term statistics would average
quotients. Energy sensors (total_increasing) feed the statistics instead.
Sensors are updated by the runtime at most once a minute and at events.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from . import WaermewachtConfigEntry
from .costs import CostComparison, compare_with_gas
from .energy import SEASONAL_MODES, Kind, aux_share, combined_ratio, mode_ratio
from .entity import HeatPumpEntity
from .model import AUX_SIGNALS, ELEC_SIGNALS, HEAT_SIGNALS, Mode, Signal
from .periods import RATIO_PERIODS, Period
from .runtime import HeatPumpRuntime

type Value = Callable[[HeatPumpRuntime], StateType]
type Needs = Callable[[HeatPumpRuntime], bool]


@dataclass(frozen=True, kw_only=True)
class HeatPumpSensorDescription(SensorEntityDescription):
    """A sensor computed from the runtime."""

    value: Value
    needs: Needs = lambda runtime: True
    attributes: Callable[[HeatPumpRuntime], dict[str, Any]] | None = None


def _has(*signals: Signal) -> Needs:
    return lambda runtime: all(s in runtime.entities for s in signals)


def _mode_complete(runtime: HeatPumpRuntime, mode: Mode) -> bool:
    return (
        HEAT_SIGNALS[mode] in runtime.entities
        and ELEC_SIGNALS[mode] in runtime.entities
    )


# Ratios: scope -> (modes, function).
SCOPES: dict[str, tuple[tuple[Mode, ...], Callable[..., float | None]]] = {
    "heating": ((Mode.HEATING,), lambda t, m: mode_ratio(t, Mode.HEATING, m)),
    "dhw": ((Mode.DHW,), lambda t, m: mode_ratio(t, Mode.DHW, m)),
    "combined": ((Mode.HEATING, Mode.DHW), lambda t, m: combined_ratio(t, m)),
    "cooling": ((Mode.COOLING,), lambda t, m: mode_ratio(t, Mode.COOLING, m)),
}
# Ratios of today and yesterday swing a lot; created, but disabled.
QUIET_PERIODS = (Period.TODAY, Period.YESTERDAY)


def _ratio_description(scope: str, period: Period) -> HeatPumpSensorDescription:
    modes, compute = SCOPES[scope]
    # Cooling runs from spring to autumn: its season is the calendar year.
    window = Period.YEAR if scope == "cooling" and period is Period.SEASON else period

    def value(runtime: HeatPumpRuntime) -> float | None:
        totals = runtime.energy(window)
        if totals is None:
            return None
        # Rounded to what is shown: the recorder writes a row on every change.
        ratio = compute(totals, runtime.min_electricity)
        return None if ratio is None else round(ratio, 2)

    def attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
        totals = runtime.energy(window)
        if totals is None:
            return {}
        result = {
            "heat_kwh": round(totals.heat(*modes), 3),
            "electricity_kwh": round(totals.electricity(*modes), 3),
        }
        if scope == "combined":
            result["standby_kwh"] = round(totals.standby(), 3)
        start = runtime.marks.starts.get(window)
        result["period_start"] = start.isoformat() if start else None
        # Counters in whole kWh make short periods uncertain (1 kWh of 5 = 20 %).
        result["counter_step_kwh"] = runtime.resolution(*modes)
        result["reliable"] = runtime.reliable(totals, *modes)
        return result

    return HeatPumpSensorDescription(
        key=f"ratio_{scope}_{period}",
        # The frontend formats a value as a number (locale, precision) only
        # with a unit or a state class. Its statistics are time means of the
        # sensor, not a balance: the balance is in the energy sensors.
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=period not in QUIET_PERIODS,
        value=value,
        needs=lambda runtime: any(_mode_complete(runtime, m) for m in modes),
        attributes=attributes,
    )


RATIOS = [_ratio_description(s, p) for s in SCOPES for p in RATIO_PERIODS]


def _energy_description(
    key: str, kind: Kind, mode: Mode, needs: Needs
) -> HeatPumpSensorDescription:
    def value(runtime: HeatPumpRuntime) -> float:
        total = runtime.totals.get(kind, mode)
        if kind is Kind.ELEC:
            total += runtime.totals.get(Kind.AUX, mode)
        return round(total, 1)  # 0.1 kWh: fewer recorder rows, enough for statistics

    return HeatPumpSensorDescription(
        key=key,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value=value,
        needs=needs,
    )


ENERGY = [
    *(
        _energy_description(f"heat_{m}", Kind.HEAT, m, _has(HEAT_SIGNALS[m]))
        for m in Mode
    ),
    *(
        _energy_description(f"electricity_{m}", Kind.ELEC, m, _has(ELEC_SIGNALS[m]))
        for m in Mode
    ),
    HeatPumpSensorDescription(
        key="standby",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value=lambda r: round(r.totals.standby(), 1),
        needs=lambda r: any(s in r.entities for s in ELEC_SIGNALS.values()),
    ),
]


def _minutes(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 60, 1)


def _starts_total_attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
    return {"source": runtime.starts_total()[1]}


HAS_COMPRESSOR = _has(Signal.COMPRESSOR)
CYCLING = [
    HeatPumpSensorDescription(
        key="starts_today",
        value=lambda r: r.cycles("today").starts,
        needs=HAS_COMPRESSOR,
    ),
    HeatPumpSensorDescription(
        key="starts_yesterday",
        value=lambda r: r.cycles("yesterday").starts,
        needs=HAS_COMPRESSOR,
    ),
    HeatPumpSensorDescription(
        key="starts_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value=lambda r: r.starts_total()[0],
        needs=lambda r: (
            Signal.COMPRESSOR in r.entities or Signal.STARTS_TOTAL in r.entities
        ),
        attributes=_starts_total_attributes,
    ),
    HeatPumpSensorDescription(
        key="runtime_today",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value=lambda r: round(r.cycles("today").runtime_seconds / 3600, 1),
        needs=HAS_COMPRESSOR,
    ),
    *(
        HeatPumpSensorDescription(
            key=f"run_minutes_{window}",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            suggested_display_precision=0,
            value=lambda r, w=window: _minutes(r.cycles(w).seconds_per_run),
            needs=HAS_COMPRESSOR,
        )
        for window in ("today", "week", "month")
    ),
    HeatPumpSensorDescription(
        key="short_runs_today",
        value=lambda r: r.cycles("today").short_runs,
        needs=HAS_COMPRESSOR,
        attributes=lambda r: {
            "threshold_minutes": r.short_seconds / 60,
            "critical_runs": r.cycles("today").critical_runs,
            "critical_threshold_minutes": r.critical_seconds / 60,
        },
    ),
    HeatPumpSensorDescription(
        key="shortest_pause_today",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value=lambda r: _minutes(r.cycles("today").shortest_pause_seconds),
        needs=HAS_COMPRESSOR,
    ),
    HeatPumpSensorDescription(
        key="defrosts_today",
        value=lambda r: r.cycles("today").defrosts,
        needs=_has(Signal.ACTIVITY),
        attributes=lambda r: {
            "minutes": _minutes(r.cycles("today").defrost_seconds),
            "yesterday": r.cycles("yesterday").defrosts,
        },
    ),
]


def _aux_share(period: Period) -> Value:
    def value(runtime: HeatPumpRuntime) -> float | None:
        totals = runtime.energy(period)
        if totals is None:
            return None
        share = aux_share(totals, runtime.min_electricity)
        return None if share is None else round(share, 2)

    return value


HAS_AUX: Needs = lambda r: any(  # noqa: E731
    s in r.entities for s in (*AUX_SIGNALS.values(), Signal.AUX_TOTAL)
)
DIAGNOSIS = [
    HeatPumpSensorDescription(
        key=f"aux_share_{period}",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value=_aux_share(period),
        needs=HAS_AUX,
    )
    for period in (Period.MONTH, Period.SEASON)
] + [
    HeatPumpSensorDescription(
        key="spread_today",
        native_unit_of_measurement=UnitOfTemperature.KELVIN,
        suggested_display_precision=1,
        value=lambda r: None if r.spread.value is None else round(r.spread.value, 1),
        needs=_has(Signal.FLOW_TEMP, Signal.RETURN_TEMP, Signal.ACTIVITY),
    ),
    HeatPumpSensorDescription(
        key="flow_temp_today",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value=lambda r: None if r.flow.value is None else round(r.flow.value, 1),
        needs=_has(Signal.FLOW_TEMP, Signal.ACTIVITY),
    ),
]


def _comparison(runtime: HeatPumpRuntime, period: Period) -> CostComparison | None:
    """Costs of the period with the fixed prices of the options."""
    totals = runtime.energy(period)
    start = runtime.marks.starts.get(period)
    if totals is None or start is None:
        return None
    return compare_with_gas(
        {start: totals},
        start,
        dt_util.utcnow(),
        runtime.tz,
        electricity_price=runtime.electricity_price,
        gas_price=runtime.gas_price,
        gas_base_price_per_year=runtime.gas_base_price,
    )


def _money(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _cost(period: Period) -> Value:
    def value(runtime: HeatPumpRuntime) -> float | None:
        result = _comparison(runtime, period)
        return None if result is None else _money(result.electricity.cost_eur)

    return value


def _savings_attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
    result = _comparison(runtime, Period.SEASON)
    if result is None:
        return {}
    return {
        "heat_kwh": round(result.heat_kwh, 1),
        "heat_pump_cost_eur": _money(result.heat_pump_cost_eur),
        "gas_kwh": round(result.gas_kwh, 1),
        "gas_cost_eur": _money(result.gas_cost_eur),
        "gas_base_cost_eur": _money(result.gas_base_cost_eur),
        "boiler_efficiency": result.boiler_efficiency,
    }


def _heating_or_dhw(runtime: HeatPumpRuntime) -> bool:
    return any(_mode_complete(runtime, m) for m in SEASONAL_MODES)


HAS_PRICE: Needs = lambda r: r.electricity_price is not None and _heating_or_dhw(r)  # noqa: E731
EURO = "EUR"
COSTS = [
    *(
        HeatPumpSensorDescription(
            key=f"cost_{period}",
            device_class=SensorDeviceClass.MONETARY,
            native_unit_of_measurement=EURO,
            suggested_display_precision=2,
            value=_cost(period),
            needs=HAS_PRICE,
        )
        for period in (Period.MONTH, Period.SEASON)
    ),
    HeatPumpSensorDescription(
        key="heat_cost_season",
        native_unit_of_measurement=f"{EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=3,
        value=lambda r: _money(
            (c := _comparison(r, Period.SEASON)) and c.heat_cost_per_kwh, 3
        ),
        needs=HAS_PRICE,
    ),
    HeatPumpSensorDescription(
        key="gas_savings_season",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=EURO,
        suggested_display_precision=0,
        value=lambda r: _money((c := _comparison(r, Period.SEASON)) and c.savings_eur),
        needs=lambda r: HAS_PRICE(r) and r.gas_price is not None,
        attributes=_savings_attributes,
    ),
]

DESCRIPTIONS: list[HeatPumpSensorDescription] = [
    *RATIOS,
    *ENERGY,
    *CYCLING,
    *DIAGNOSIS,
    *COSTS,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaermewachtConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        HeatPumpSensor(entry, d) for d in DESCRIPTIONS if d.needs(runtime)
    )


class HeatPumpSensor(HeatPumpEntity, SensorEntity):
    """A figure of the heat pump."""

    # Change with every counter reading while running; shown, not recorded.
    _unrecorded_attributes = frozenset({"heat_kwh", "electricity_kwh", "standby_kwh"})

    entity_description: HeatPumpSensorDescription

    def __init__(
        self, entry: WaermewachtConfigEntry, description: HeatPumpSensorDescription
    ) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value(self.runtime)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes is None:
            return None
        return self.entity_description.attributes(self.runtime)
