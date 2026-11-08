"""Sensors: ratios per mode and period, energy, cycling, diagnosis.

Ratio sensors have the state class measurement only so the frontend formats
them as numbers; their statistics are time means of a quotient, not a
balance. Energy sensors (total_increasing) feed the statistics instead.
Sensors are updated by the runtime at most once a minute and at events.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
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
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from . import WaermewachtConfigEntry, is_gas
from .binary_sensor import health_checks
from .charges import Charge, charge_ratio, is_disinfection
from .costs import CostComparison, compare_costs, compare_with_gas
from .degree_days import change_percent
from .energy import (
    SEASONAL_MODES,
    Kind,
    aux_share,
    combined_ratio,
    heat_pump_share,
    mode_ratio,
)
from .entity import HeatPumpEntity
from .gas_sensor import gas_sensors
from .health import STATUS_OPTIONS, status
from .heat_load import heat_load_as_dict
from .heating_curve import flow_curve_as_dict
from .model import (
    AUX_SIGNALS,
    BOILER_HEAT_SIGNALS,
    FUEL_SIGNALS,
    HEAT_SIGNALS,
    Mode,
    Signal,
    has_elec,
)
from .periods import RATIO_PERIODS, Period
from .prices import FIXED, price_source
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
    return HEAT_SIGNALS[mode] in runtime.entities and has_elec(runtime.entities, mode)


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


def _standby_attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
    found = runtime.findings["standby_rise"]
    return {"rising": found.problem, **found.as_attributes()}


ENERGY = [
    *(
        _energy_description(f"heat_{m}", Kind.HEAT, m, _has(HEAT_SIGNALS[m]))
        for m in Mode
    ),
    *(
        _energy_description(
            f"electricity_{m}", Kind.ELEC, m, lambda r, m=m: has_elec(r.entities, m)
        )
        for m in Mode
    ),
    # Boiler of a hybrid system: what it reports, never heat pump energy.
    *(
        _energy_description(f"boiler_heat_{m}", Kind.BOILER, m, _has(s))
        for m, s in BOILER_HEAT_SIGNALS.items()
    ),
    *(
        _energy_description(f"fuel_{m}", Kind.FUEL, m, _has(s))
        for m, s in FUEL_SIGNALS.items()
    ),
    HeatPumpSensorDescription(
        key="standby",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value=lambda r: round(r.totals.standby(), 1),
        needs=lambda r: r.standby_separable,
        attributes=_standby_attributes,
    ),
]


def _standby_power(runtime: HeatPumpRuntime) -> float | None:
    """Mean standby power of the last 7 days (W), from the daily analysis."""
    return runtime.findings["standby_rise"].evidence.get("mean_power_w_7d")


def _minutes(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 60, 1)


def _starts_total_attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
    return {"source": runtime.starts_total()[1]}


HAS_COMPRESSOR = _has(Signal.COMPRESSOR)


def _starts_season(runtime: HeatPumpRuntime) -> int | None:
    total, _ = runtime.starts_total()
    if total is None or runtime.starts_baseline is None:
        return None
    return max(total - runtime.starts_baseline[0], 0)


def _starts_season_attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
    if runtime.starts_baseline is None or (count := _starts_season(runtime)) is None:
        return {}
    since = runtime.starts_baseline[1]
    days = (dt_util.utcnow() - since).total_seconds() / 86400
    return {
        "since": since.isoformat(),
        "per_day": round(count / days, 1) if days >= 1 else None,
    }


CYCLING = [
    HeatPumpSensorDescription(
        key="starts_today",
        value=lambda r: r.cycles("today").starts,
        needs=HAS_COMPRESSOR,
        # Starts per day of the last 7 complete days and the projection to a
        # year against the Fraunhofer field test: an orientation only, the
        # binary sensor "cycling" does not use it.
        attributes=lambda r: r.starts_projection().as_attributes(),
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
        key="starts_season",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value=_starts_season,
        # The baseline comes with the daily analysis (outdoor temperature).
        needs=_has(Signal.STARTS_TOTAL, Signal.OUTDOOR_TEMP),
        attributes=_starts_season_attributes,
    ),
    HeatPumpSensorDescription(
        key="runtime_today",
        # Minutes like every duration here: the frontend shows hours as
        # "0h, 25 Min." and floors rounded values. Steps of 5 minutes: whole
        # minutes would write a state every minute while running (SD cards).
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value=lambda r: 5 * round(r.cycles("today").runtime_seconds / 300),
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
        needs=lambda r: r.has_activity,
        attributes=lambda r: {
            "minutes": _minutes(r.cycles("today").defrost_seconds),
            "yesterday": r.cycles("yesterday").defrosts,
            **({} if r.defrost_week is None else r.defrost_week.as_attributes()),
            "classes": r.defrost_classes,
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


def _aux_share_mode(period: Period, mode: Mode) -> Value:
    def value(runtime: HeatPumpRuntime) -> float | None:
        totals = runtime.energy(period)
        if totals is None:
            return None
        share = aux_share(totals, runtime.min_electricity, mode)
        return None if share is None else round(share, 2)

    return value


def _aux_share_attributes(
    period: Period,
) -> Callable[[HeatPumpRuntime], dict[str, Any]]:
    """Share within heating and within hot water: the total mixes both."""

    def attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
        totals = runtime.energy(period)
        result: dict[str, Any] = {}
        for mode in SEASONAL_MODES:
            share = (
                None
                if totals is None
                else aux_share(totals, runtime.min_electricity, mode)
            )
            result[mode.value] = None if share is None else round(share, 2)
        return result

    return attributes


def _boiler_incomplete(runtime: HeatPumpRuntime, period: Period) -> bool:
    """The boiler was mapped after the period began (Reconfigure): its share
    would compare the heat pump's whole period with part of the boiler's."""
    since = runtime.boiler_from
    start = runtime.marks.starts.get(period)
    return since is not None and (start is None or start < since)


def _share_value(period: Period) -> Value:
    def value(runtime: HeatPumpRuntime) -> float | None:
        totals = runtime.energy(period)
        if totals is None or _boiler_incomplete(runtime, period):
            return None
        share = heat_pump_share(
            totals, runtime.boiler_efficiency, runtime.fuel_modes, Mode.HEATING
        )
        return None if share is None else round(share, 1)

    return value


def _share_attributes(period: Period) -> Callable[[HeatPumpRuntime], dict[str, Any]]:
    """Heat of both and the share with hot water (the state: space heating,
    as most field studies of hybrid systems report it)."""

    def attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
        totals = runtime.energy(period)
        if totals is None:
            return {}
        efficiency, fuel = runtime.boiler_efficiency, runtime.fuel_modes
        both = heat_pump_share(totals, efficiency, fuel, Mode.HEATING, Mode.DHW)
        start = runtime.marks.starts.get(period)
        incomplete = _boiler_incomplete(runtime, period)
        return {
            "with_dhw": None if both is None or incomplete else round(both, 1),
            # Boiler mapped later: a share again for periods from then on.
            "boiler_from": runtime.boiler_from.isoformat() if incomplete else None,
            "heat_pump_heat_kwh": round(totals.heat(Mode.HEATING), 1),
            "boiler_heat_kwh": round(
                totals.boiler_heat(efficiency, fuel, Mode.HEATING), 1
            ),
            "heat_pump_heat_dhw_kwh": round(totals.heat(Mode.DHW), 1),
            "boiler_heat_dhw_kwh": round(
                totals.boiler_heat(efficiency, fuel, Mode.DHW), 1
            ),
            # Modes whose boiler heat is fuel x efficiency (no heat counter).
            "boiler_heat_from_fuel": sorted(m.value for m in fuel),
            "boiler_efficiency": efficiency if fuel else None,
            "period_start": start.isoformat() if start else None,
        }

    return attributes


HYBRID = [
    HeatPumpSensorDescription(
        key=f"heat_pump_share_{period}",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value=_share_value(period),
        needs=lambda r: (
            HEAT_SIGNALS[Mode.HEATING] in r.entities
            and any(
                s[Mode.HEATING] in r.entities
                for s in (BOILER_HEAT_SIGNALS, FUEL_SIGNALS)
            )
        ),
        attributes=_share_attributes(period),
    )
    for period in (Period.MONTH, Period.SEASON)
]


HAS_AUX: Needs = lambda r: any(  # noqa: E731
    s in r.entities for s in (*AUX_SIGNALS.values(), Signal.AUX_TOTAL)
)
DIAGNOSIS = (
    [
        HeatPumpSensorDescription(
            key=f"aux_share_{period}",
            native_unit_of_measurement=PERCENTAGE,
            suggested_display_precision=1,
            value=_aux_share(period),
            needs=HAS_AUX,
            attributes=_aux_share_attributes(period),
        )
        for period in (Period.MONTH, Period.SEASON)
    ]
    + [
        # The total mixes both modes; a heater that only helps with hot water
        # would look like a heater for space heating.
        HeatPumpSensorDescription(
            key=f"aux_share_{mode}_{period}",
            native_unit_of_measurement=PERCENTAGE,
            suggested_display_precision=1,
            value=_aux_share_mode(period, mode),
            needs=lambda r, mode=mode: HAS_AUX(r) and _mode_complete(r, mode),
        )
        for mode in SEASONAL_MODES
        for period in (Period.MONTH, Period.SEASON)
    ]
    + [
        HeatPumpSensorDescription(
            key="standby_power_7d",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPower.WATT,
            suggested_display_precision=0,
            value=_standby_power,
            needs=lambda r: r.standby_separable and HAS_OUTDOOR(r),
        ),
    ]
    + [
        HeatPumpSensorDescription(
            key="spread_today",
            native_unit_of_measurement=UnitOfTemperature.KELVIN,
            suggested_display_precision=1,
            value=lambda r: (
                None if r.spread.value is None else round(r.spread.value, 1)
            ),
            needs=lambda r: (
                r.has_activity and _has(Signal.FLOW_TEMP, Signal.RETURN_TEMP)(r)
            ),
        ),
        HeatPumpSensorDescription(
            key="flow_temp_today",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            suggested_display_precision=1,
            value=lambda r: None if r.flow.value is None else round(r.flow.value, 1),
            needs=lambda r: r.has_activity and _has(Signal.FLOW_TEMP)(r),
        ),
    ]
)


def _comparison(runtime: HeatPumpRuntime, period: Period) -> CostComparison | None:
    """Costs of the period: with the fixed price of the options, or hour by
    hour with the prices of the price sensor (price_feed.py)."""
    totals = runtime.energy(period)
    start = runtime.marks.starts.get(period)
    if totals is None or start is None:
        return None
    now = dt_util.utcnow()
    if runtime.prices is None:
        return compare_with_gas(
            {start: totals},
            start,
            now,
            runtime.tz,
            electricity_price=runtime.electricity_price,
            gas_price=runtime.gas_price,
            gas_base_price_per_year=runtime.gas_base_price,
            electricity_base_price_per_year=runtime.electricity_base_price,
        )
    priced = runtime.prices.period(start, totals, now)
    if priced is None:  # prices not read yet (shortly after the start)
        return None
    electricity, heat = priced
    return compare_costs(
        electricity,
        heat,
        start,
        now,
        runtime.tz,
        gas_price=runtime.gas_price,
        gas_base_price_per_year=runtime.gas_base_price,
        electricity_base_price_per_year=runtime.electricity_base_price,
    )


def _price_attributes(
    result: CostComparison | None, runtime: HeatPumpRuntime
) -> dict[str, Any]:
    """Where the prices came from: sensor, fixed or mixed (fixed price for
    hours without one of the sensor), and the hours without any price."""
    if runtime.prices is None:
        return {"price_source": FIXED}
    if result is None:
        return {"price_source": None, "price_entity": runtime.price_entity}
    electricity = result.electricity
    average = electricity.average_price
    return {
        "price_source": price_source(electricity),
        "price_entity": runtime.price_entity,
        "average_price_eur_per_kwh": None if average is None else round(average, 4),
        "hours_fixed_price": electricity.fallback_hours,
        "hours_without_price": electricity.missing_hours,
    }


def _money(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _cost(period: Period) -> Value:
    def value(runtime: HeatPumpRuntime) -> float | None:
        result = _comparison(runtime, period)
        if result is None or result.electricity.cost_eur is None:
            return None
        # Steps of 10 cents: each cent would be a state write (SD cards).
        return _money(result.electricity.cost_eur + result.electricity_base_cost_eur, 1)

    return value


def _period_attributes(period: Period) -> Callable[[HeatPumpRuntime], dict[str, Any]]:
    """Start of the period, as the ratio sensors have it."""

    def attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
        start = runtime.marks.starts.get(period)
        return {"period_start": start.isoformat() if start else None}

    return attributes


def _cost_attributes(period: Period) -> Callable[[HeatPumpRuntime], dict[str, Any]]:
    """Start of the period and where its prices came from."""

    def attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
        return {
            **_period_attributes(period)(runtime),
            **_price_attributes(_comparison(runtime, period), runtime),
        }

    return attributes


def _savings_attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
    result = _comparison(runtime, Period.SEASON)
    if result is None:
        return {}
    return {
        **_period_attributes(Period.SEASON)(runtime),
        **_price_attributes(result, runtime),
        "heat_kwh": round(result.heat_kwh, 1),
        "heat_pump_cost_eur": _money(result.heat_pump_cost_eur),
        "electricity_base_cost_eur": _money(result.electricity_base_cost_eur),
        "gas_kwh": round(result.gas_kwh, 1),
        "gas_cost_eur": _money(result.gas_cost_eur),
        "gas_base_cost_eur": _money(result.gas_base_cost_eur),
        "boiler_efficiency": result.boiler_efficiency,
    }


def _heating_or_dhw(runtime: HeatPumpRuntime) -> bool:
    return any(_mode_complete(runtime, m) for m in SEASONAL_MODES)


def _priced(runtime: HeatPumpRuntime) -> bool:
    """A fixed price or a price sensor is set."""
    return runtime.electricity_price is not None or runtime.price_entity is not None


HAS_PRICE: Needs = lambda r: _priced(r) and _heating_or_dhw(r)  # noqa: E731
# Electricity costs need no heat (ViCare: electricity and cycling only).
HAS_ELEC_PRICE: Needs = lambda r: (  # noqa: E731
    _priced(r) and any(has_elec(r.entities, m) for m in Mode)
)
EURO = "EUR"
COSTS = [
    *(
        HeatPumpSensorDescription(
            key=f"cost_{period}",
            device_class=SensorDeviceClass.MONETARY,
            native_unit_of_measurement=EURO,
            suggested_display_precision=2,
            value=_cost(period),
            needs=HAS_ELEC_PRICE,
            attributes=_cost_attributes(period),
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
        attributes=_cost_attributes(Period.SEASON),
    ),
    HeatPumpSensorDescription(
        key="gas_savings_season",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=EURO,
        suggested_display_precision=0,
        # Whole euros, as shown; cents would be a state write each.
        value=lambda r: _money(
            (c := _comparison(r, Period.SEASON)) and c.savings_eur, 0
        ),
        needs=lambda r: HAS_PRICE(r) and r.gas_price is not None,
        attributes=_savings_attributes,
    ),
]


def _curve_attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
    starts = runtime.curve_starts
    return {
        "current_start": starts["current"].isoformat() if "current" in starts else None,
        "previous_start": (
            starts["previous"].isoformat() if "previous" in starts else None
        ),
        "current": runtime.curves.get("current", []),
        "previous": runtime.curves.get("previous", []),
    }


def _heat_load_attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
    result = runtime.heat_load
    if result is None or runtime.heat_load_window is None:
        return {}
    start, end = runtime.heat_load_window
    return {
        "start": dt_util.as_local(start).isoformat(),
        "end": dt_util.as_local(end).isoformat(),
        # "previous" (last complete season) or "current" (so far, when the
        # previous one gives nothing usable; heat_load.choose_season).
        "season": runtime.heat_load_season,
        **heat_load_as_dict(result),
    }


def _watts_per_kelvin(runtime: HeatPumpRuntime) -> float | None:
    result = runtime.heat_load
    if result is None or not result.sufficient or result.slope_kw_per_k is None:
        return None
    return round(-result.slope_kw_per_k * 1000)


def _heating_limit(runtime: HeatPumpRuntime) -> float | None:
    result = runtime.heat_load
    if result is None or not result.sufficient or result.heating_limit is None:
        return None
    return round(result.heating_limit, 1)


def _design_load(runtime: HeatPumpRuntime) -> float | None:
    result = runtime.heat_load
    if result is None or not result.sufficient or result.standard_kw is None:
        return None
    return round(result.standard_kw, 2)


def _degree_days(runtime: HeatPumpRuntime) -> float | None:
    result = runtime.degree_days
    return None if result is None else round(result.degree_days, 1)


def _degree_days_attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
    result = runtime.degree_days
    if result is None:
        return {}
    return {
        "base": "G20/15",
        "days_counted": result.days_counted,
        "days_missing": result.days_missing,
        "days_without_heating": len(result.days_without_heating),
        "degree_days_heating": round(result.degree_days_heating, 1),
    }


def _per_degree_day(runtime: HeatPumpRuntime) -> float | None:
    result = runtime.degree_days
    return None if result is None else _round(result.kwh_per_degree_day)


def _per_degree_day_attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
    previous = runtime.degree_days_previous
    same = runtime.degree_days_same_period
    current = runtime.degree_days
    previous_same = None if same is None else _round(same.kwh_per_degree_day)
    return {
        "previous_season": None
        if previous is None
        else _round(previous.kwh_per_degree_day),
        # The previous season up to the same day (fair against a season so
        # far), its last day and the change of this season against it.
        "previous_same_period": previous_same,
        "previous_same_period_until": None
        if same is None or same.end <= same.start
        else (same.end - timedelta(days=1)).isoformat(),
        "change_percent": change_percent(
            None if current is None else current.kwh_per_degree_day,
            None if same is None else same.kwh_per_degree_day,
        ),
    }


def _flow_at_zero(runtime: HeatPumpRuntime) -> float | None:
    result = runtime.flow_curves.get("current")
    return None if result is None else _round(result.at_zero, 1)


def _flow_at_zero_attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
    if (result := runtime.flow_curves.get("current")) is None:
        return {}
    previous = runtime.flow_curves.get("previous")
    figures = flow_curve_as_dict(result)
    figures.pop("at_zero")
    return {
        **figures,
        "previous_season": None if previous is None else _round(previous.at_zero, 1),
        "previous_slope": None if previous is None else _round(previous.slope, 2),
    }


def _spread_7d(runtime: HeatPumpRuntime) -> float | None:
    figure = runtime.spread_7d
    return None if figure is None else _round(figure.value, 1)


def _oversize(runtime: HeatPumpRuntime) -> float | None:
    figure = runtime.oversize
    return None if figure is None else _round(figure.factor, 2)


HAS_OUTDOOR: Needs = lambda r: (  # noqa: E731
    Signal.OUTDOOR_TEMP in r.entities and _mode_complete(r, Mode.HEATING)
)
ANALYSIS = [
    HeatPumpSensorDescription(
        key="performance_curve_heating",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda r: r.analysed_at,
        needs=HAS_OUTDOOR,
        attributes=_curve_attributes,
    ),
    HeatPumpSensorDescription(
        key="spread_7d",
        native_unit_of_measurement=UnitOfTemperature.KELVIN,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value=_spread_7d,
        needs=lambda r: (
            HAS_OUTDOOR(r)
            and r.has_activity
            and _has(Signal.FLOW_TEMP, Signal.RETURN_TEMP)(r)
        ),
        attributes=lambda r: {} if r.spread_7d is None else r.spread_7d.as_attributes(),
    ),
    HeatPumpSensorDescription(
        key="oversize_factor",
        # Without a unit, the state class makes the frontend format the number.
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value=_oversize,
        needs=lambda r: HAS_OUTDOOR(r) and r.rated_power is not None,
        attributes=lambda r: {} if r.oversize is None else r.oversize.as_attributes(),
    ),
    HeatPumpSensorDescription(
        key="flow_at_zero",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value=_flow_at_zero,
        needs=lambda r: HAS_OUTDOOR(r) and Signal.FLOW_TEMP in r.entities,
        attributes=_flow_at_zero_attributes,
    ),
    HeatPumpSensorDescription(
        key="degree_days_season",
        native_unit_of_measurement="K·d",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value=_degree_days,
        needs=HAS_OUTDOOR,
        attributes=_degree_days_attributes,
    ),
    HeatPumpSensorDescription(
        key="heat_per_degree_day_season",
        native_unit_of_measurement="kWh/K·d",
        suggested_display_precision=2,
        value=_per_degree_day,
        needs=HAS_OUTDOOR,
        attributes=_per_degree_day_attributes,
    ),
    HeatPumpSensorDescription(
        key="heat_load_per_kelvin",
        native_unit_of_measurement="W/K",
        suggested_display_precision=0,
        value=_watts_per_kelvin,
        needs=HAS_OUTDOOR,
        attributes=_heat_load_attributes,
    ),
    HeatPumpSensorDescription(
        key="heating_limit",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value=_heating_limit,
        needs=HAS_OUTDOOR,
    ),
    HeatPumpSensorDescription(
        key="heat_load_design",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=1,
        value=_design_load,
        needs=lambda r: HAS_OUTDOOR(r) and r.design_temp is not None,
    ),
]


def _last_charge(runtime: HeatPumpRuntime) -> Charge | None:
    return runtime.charges[-1] if runtime.charges else None


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _last_charge_attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
    if (charge := _last_charge(runtime)) is None:
        return {}
    return {
        "start": charge.start.isoformat(),
        "minutes": round(charge.seconds(charge.end or charge.start) / 60),
        "heat_kwh": round(charge.heat_kwh, 2),
        "electricity_kwh": round(charge.electricity_kwh, 2),
        "aux_kwh": round(charge.aux_kwh, 2),
        "aux_kwh_defrost": round(charge.aux_defrost_kwh, 2),
        "start_temp": charge.start_dhw_temp,
        "max_temp": charge.max_dhw_temp,
        "disinfection": is_disinfection(charge, runtime.disinfection_temp),
        "uncertain": charge.uncertain,
    }


def _charges_attributes(runtime: HeatPumpRuntime) -> dict[str, Any]:
    split = runtime.charge_split(dt_util.utcnow())
    normal = split.normal
    return {
        "charges": normal.count,
        "uncertain": normal.uncertain,
        "mean_minutes": _round(normal.mean_minutes, 0),
        "mean_heat_kwh": _round(normal.mean_heat_kwh),
        "mean_lift": _round(normal.mean_lift, 1),
        "aux_share": _round(normal.aux_share, 1),
        "disinfections": split.disinfection.count,
    }


HAS_CHARGES: Needs = lambda r: r.has_charges  # noqa: E731
DHW = [
    HeatPumpSensorDescription(
        key="ratio_dhw_last_charge",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value=lambda r: _round(charge_ratio(c) if (c := _last_charge(r)) else None),
        needs=HAS_CHARGES,
        attributes=_last_charge_attributes,
    ),
    HeatPumpSensorDescription(
        key="ratio_dhw_charges_30d",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value=lambda r: _round(r.charge_split(dt_util.utcnow()).normal.ratio),
        needs=HAS_CHARGES,
        attributes=_charges_attributes,
    ),
    HeatPumpSensorDescription(
        key="last_disinfection",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda r: r.last_disinfection,
        needs=_has(Signal.DHW_TEMP),
    ),
]

DESCRIPTIONS: list[HeatPumpSensorDescription] = [
    *RATIOS,
    *ENERGY,
    *CYCLING,
    *DIAGNOSIS,
    *HYBRID,
    *DHW,
    *COSTS,
    *ANALYSIS,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaermewachtConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if is_gas(entry):
        async_add_entities(gas_sensors(entry))  # type: ignore[arg-type]
        return
    runtime = entry.runtime_data
    async_add_entities(
        HeatPumpSensor(entry, d) for d in DESCRIPTIONS if d.needs(runtime)
    )
    async_add_entities(HealthStatus(entry, check) for check in health_checks(runtime))


class HealthStatus(HeatPumpEntity, SensorEntity):
    """One check of the health check in words: fine, conspicuous or why there
    is no verdict yet. The problem sensor of the same check stays for
    automations and carries the figures."""

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, entry: WaermewachtConfigEntry, check: str) -> None:
        super().__init__(entry, f"{check}_status")
        self._check = check
        self._attr_options = list(STATUS_OPTIONS)

    @property
    def native_value(self) -> str | None:
        if self._check == "cycling_problem":
            return status(bool(self.runtime.cycling_problem()["problem"]), None)
        finding = self.runtime.findings[self._check]
        return status(finding.problem, finding.reason)


class HeatPumpSensor(HeatPumpEntity, SensorEntity):
    """A figure of the heat pump."""

    # Change with every counter reading while running; shown, not recorded.
    # Change with every counter reading, or large (curves, weeks): shown, not
    # recorded.
    _unrecorded_attributes = frozenset(
        {
            "heat_kwh",
            "electricity_kwh",
            "standby_kwh",
            "current",
            "previous",
            "weeks",
            "classes",
        }
    )

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
