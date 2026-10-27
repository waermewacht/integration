"""Figures of the action "report" for any period. Pure Python, no HA imports.

The hours before the setup come from the source counters (standby estimated
per hour, see backfill.py); the hours after from Wärmewacht's own energy
sensors, which book standby from the compressor state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, tzinfo
from typing import Any

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


def own_hour(changes: Mapping[str, float]) -> Totals:
    """One hour of Wärmewacht's own sensors: heat_<mode>, electricity_<mode>
    (running incl. backup heater) and standby (all modes)."""
    totals = Totals()
    for mode in Mode:
        totals.add(Kind.HEAT, mode, changes.get(f"heat_{mode}", 0.0))
        totals.add(Kind.ELEC, mode, changes.get(f"electricity_{mode}", 0.0))
    totals.add(Kind.STANDBY, Mode.HEATING, changes.get("standby", 0.0))
    return totals
