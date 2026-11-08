"""Figures of the action "report" for any period. Pure Python, no HA imports.

The hours before the setup come from the source counters (standby estimated
per hour, see backfill.py); the hours after from Wärmewacht's own energy
sensors, which book standby from the compressor state.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from datetime import datetime, tzinfo
from typing import Any

from .degree_days import DayDegrees, heat_per_degree_day
from .energy import SEASONAL_MODES, Kind, Totals, combined_ratio, mode_ratio
from .model import (
    AUX_SIGNALS,
    BOILER_HEAT_SIGNALS,
    ELEC_SIGNALS,
    FUEL_SIGNALS,
    HEAT_SIGNALS,
    Mode,
    Signal,
)

# Scope of the report -> modes; "heating_dhw" includes standby (seasonal ratio).
SCOPES: dict[str, tuple[Mode, ...]] = {
    "heating": (Mode.HEATING,),
    "dhw": (Mode.DHW,),
    "heating_dhw": SEASONAL_MODES,
    "cooling": (Mode.COOLING,),
}


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def figures(
    totals: Totals,
    min_electricity: float,
    modes: Iterable[Mode],
    electricity_modes: Iterable[Mode] = (),
) -> dict[str, dict[str, Any]]:
    """Heat, electricity and ratio per scope whose modes are all configured;
    `electricity_modes` without a heat counter get their electricity only."""
    configured = set(modes)
    result: dict[str, dict[str, Any]] = {}
    for scope, scope_modes in SCOPES.items():
        if not configured.intersection(scope_modes):
            continue
        row: dict[str, Any] = {
            "heat_kwh": round(totals.heat(*scope_modes), 3),
            "electricity_kwh": round(totals.electricity(*scope_modes), 3),
        }
        if scope == "heating_dhw":
            row["standby_kwh"] = round(totals.standby(), 3)
            row["ratio"] = _round(combined_ratio(totals, min_electricity), 2)
        else:
            row["ratio"] = _round(
                mode_ratio(totals, scope_modes[0], min_electricity), 2
            )
        result[scope] = row
    for mode in electricity_modes:
        if mode in configured or mode.value in result:
            continue
        result[mode.value] = {
            "heat_kwh": None,
            "electricity_kwh": round(totals.electricity(mode), 3),
            "ratio": None,
        }
    return result


def by_month(hours: Mapping[datetime, Totals], tz: tzinfo) -> dict[str, Totals]:
    """Sum hourly energy per local month ("YYYY-MM")."""
    months: dict[str, Totals] = {}
    for hour, totals in sorted(hours.items()):
        key = hour.astimezone(tz).strftime("%Y-%m")
        months[key] = months.get(key, Totals()) + totals
    return months


def degree_day_figures(days: Iterable[DayDegrees]) -> dict[str, Any]:
    """Degree days (G20/15) of the valid days and the heating heat per
    degree day over the heating days (degree_days.heat_per_degree_day)."""
    chosen = list(days)
    per_degree_day, _ = heat_per_degree_day(chosen)
    return {
        "degree_days": round(sum(d.degree_days for d in chosen), 1),
        "kwh_per_degree_day": None
        if per_degree_day is None
        else round(per_degree_day, 2),
        "days_counted": len(chosen),
    }


def degree_days_by_month(days: Iterable[DayDegrees]) -> dict[str, dict[str, Any]]:
    """degree_day_figures per local month ("YYYY-MM")."""
    months: dict[str, list[DayDegrees]] = {}
    for day in days:
        months.setdefault(day.day.strftime("%Y-%m"), []).append(day)
    return {month: degree_day_figures(chosen) for month, chosen in months.items()}


# Keys of Wärmewacht's own energy sensors.
OWN_KEYS = (
    *(f"heat_{m}" for m in Mode),
    *(f"electricity_{m}" for m in Mode),
    "standby",
    *(f"boiler_heat_{m}" for m in BOILER_HEAT_SIGNALS),
    *(f"fuel_{m}" for m in FUEL_SIGNALS),
)


def own_changes(totals: Totals) -> dict[str, float]:
    """Energy of the own sensors in `totals` (the inverse of own_hour)."""
    changes = {f"heat_{m}": totals.get(Kind.HEAT, m) for m in Mode}
    for mode in Mode:
        changes[f"electricity_{mode}"] = totals.get(Kind.ELEC, mode) + totals.get(
            Kind.AUX, mode
        )
    changes["standby"] = totals.standby()
    for mode in BOILER_HEAT_SIGNALS:
        changes[f"boiler_heat_{mode}"] = totals.get(Kind.BOILER, mode)
    for mode in FUEL_SIGNALS:
        changes[f"fuel_{mode}"] = totals.get(Kind.FUEL, mode)
    return changes


def statistics_rows(
    hours: Mapping[datetime, Totals],
) -> dict[str, list[tuple[datetime, float]]]:
    """Hourly sums of the own sensors for the hours before the setup.

    The sums end at 0 with the last hour: Home Assistant starts the sum of a
    new sensor at 0, so the imported past joins it without a step. Home
    Assistant takes the change of the earliest row against 0, though: once
    the sensor has short-term statistics, all rows are shifted up by the
    imported energy (own_totals), so the sum starts at 0. Hours without
    energy get no row.
    """
    changes: dict[str, list[tuple[datetime, float]]] = {}
    for hour in sorted(hours):
        for key, kwh in own_changes(hours[hour]).items():
            if kwh:
                changes.setdefault(key, []).append((hour, kwh))
    rows: dict[str, list[tuple[datetime, float]]] = {}
    for key, values in changes.items():
        remaining = sum(kwh for _, kwh in values)
        rows[key] = []
        for hour, kwh in values:
            remaining -= kwh
            rows[key].append((hour, round(-remaining, 3) + 0.0))
        rows[key][-1] = (rows[key][-1][0], 0.0)
    return rows


def late_import_signals(key: str, entities: Collection[Signal]) -> frozenset[Signal]:
    """The meters whose statistics alone make up the past of own sensor `key`
    when the sensor appears after the setup (a meter added under Reconfigure).

    Before it appeared, the other own sensors were already recorded: its past
    may only come from energy none of them counted. That holds for heat,
    boiler heat and fuel (their own meter), and for the electricity of a mode
    with its own meter (with that mode's backup heater; the heat only tells
    standby apart). Empty where the energy was in another sensor: standby
    (in the electricity of the modes) and the electricity of a mode split off
    a common meter (in the electricity of heating until the mode got its heat
    meter).
    """
    present = set(entities)
    for mode in Mode:
        heat, elec = HEAT_SIGNALS[mode], ELEC_SIGNALS[mode]
        if key == f"heat_{mode}" and heat in present:
            # The electricity only for sources that count it into the heat.
            return frozenset({heat, elec} & present)
        if (
            key == f"electricity_{mode}"
            and elec in present
            and Signal.ELEC_TOTAL not in present
        ):
            return frozenset({heat, elec, AUX_SIGNALS.get(mode, elec)} & present)
    for prefix, signals in (
        ("boiler_heat", BOILER_HEAT_SIGNALS),
        ("fuel", FUEL_SIGNALS),
    ):
        for mode, signal in signals.items():
            if key == f"{prefix}_{mode}" and signal in present:
                return frozenset({signal})
    return frozenset()


def own_totals(hours: Mapping[datetime, Totals]) -> dict[str, float]:
    """Energy of the own sensors over all `hours` (what an import adds)."""
    totals: dict[str, float] = {}
    for hour_totals in hours.values():
        for key, kwh in own_changes(hour_totals).items():
            totals[key] = totals.get(key, 0.0) + kwh
    return totals


def own_hour(changes: Mapping[str, float]) -> Totals:
    """One hour of Wärmewacht's own sensors: heat_<mode>, electricity_<mode>
    (running incl. backup heater) and standby (all modes)."""
    totals = Totals()
    for mode in Mode:
        totals.add(Kind.HEAT, mode, changes.get(f"heat_{mode}", 0.0))
        totals.add(Kind.ELEC, mode, changes.get(f"electricity_{mode}", 0.0))
    totals.add(Kind.STANDBY, Mode.HEATING, changes.get("standby", 0.0))
    for mode in BOILER_HEAT_SIGNALS:
        if heat := changes.get(f"boiler_heat_{mode}", 0.0):
            totals.add(Kind.BOILER, mode, heat)
    for mode in FUEL_SIGNALS:
        if fuel := changes.get(f"fuel_{mode}", 0.0):
            totals.add(Kind.FUEL, mode, fuel)
    return totals
