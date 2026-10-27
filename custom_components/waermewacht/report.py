"""Figures of the action "report" for any period. Pure Python, no HA imports.

The hours before the setup come from the source counters (standby estimated
per hour, see backfill.py); the hours after from Wärmewacht's own energy
sensors, which book standby from the compressor state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, tzinfo
from typing import Any

from .degree_days import MIN_DEGREE_DAYS, DayDegrees
from .energy import SEASONAL_MODES, Kind, Totals, combined_ratio, mode_ratio
from .model import Mode

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
    totals: Totals, min_electricity: float, modes: Iterable[Mode]
) -> dict[str, dict[str, Any]]:
    """Heat, electricity and ratio per scope whose modes are all configured."""
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
    degree day, which is None below MIN_DEGREE_DAYS."""
    chosen = list(days)
    total = sum(d.degree_days for d in chosen)
    heat = sum(d.heating_kwh for d in chosen)
    return {
        "degree_days": round(total, 1),
        "kwh_per_degree_day": round(heat / total, 2)
        if total >= MIN_DEGREE_DAYS
        else None,
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
)


def own_changes(totals: Totals) -> dict[str, float]:
    """Energy of the own sensors in `totals` (the inverse of own_hour)."""
    changes = {f"heat_{m}": totals.get(Kind.HEAT, m) for m in Mode}
    for mode in Mode:
        changes[f"electricity_{mode}"] = totals.get(Kind.ELEC, mode) + totals.get(
            Kind.AUX, mode
        )
    changes["standby"] = totals.standby()
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
    return totals
