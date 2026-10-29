"""Performance curve: ratio over outdoor temperature. Pure Python, no HA imports.

Days are grouped by their local date and sorted into classes of 2 K by the
day's mean outdoor temperature. The ratio of a class is Σ heat / Σ electricity
of its days, never a mean of daily ratios, and without standby: standby is
nearly constant per day, so on mild days with little heat it would bend the
curve down artificially. A class needs at least 7 days (spread of the class
ratio about 0.14 at n = 7 in the feasibility study, docs/ENTWICKLUNG.md
"Machbarkeit mit echten Daten"). Sparse classes at the cold and warm ends are
merged into their inner neighbour; sparse classes in between keep their row
but are flagged and get no ratio.

Outdoor values outside -35 … +45 °C are discarded (sun or exhaust air on the
sensor reached 44 °C in summer). Hours without an outdoor value are skipped
together with their energy; a day counts with at least 20 hourly values.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Any

from .energy import SEASONAL_MODES, Totals, ratio
from .model import Mode

OUTDOOR_MIN = -35.0  # °C, plausible range of an hourly outdoor mean
OUTDOOR_MAX = 45.0
MIN_DAY_HOURS = 20  # hourly outdoor values a day needs to count
CLASS_WIDTH = 2.0  # K
MIN_DAYS = 7  # days a class needs for a ratio
MIN_ELECTRICITY = 0.5  # kWh, below that the ratio is unknown

# Scope of the curve -> modes (always without standby).
CURVE_SCOPES: dict[str, tuple[Mode, ...]] = {
    "heating": (Mode.HEATING,),
    "combined": SEASONAL_MODES,
}


@dataclass(frozen=True)
class DaySample:
    """One local day: its mean outdoor temperature and booked energy.

    `hours` counts the hours with a valid outdoor value; only their energy is
    in `totals`. Each is one real hour, so DST days have at most 23 or 25.
    `energy_hours` counts those of them with an energy row at all: a day
    before the meters were recorded has outdoor values but no energy.
    """

    day: date
    hours: int
    mean_outdoor: float
    totals: Totals
    energy_hours: int = 0


@dataclass(frozen=True)
class CurveRow:
    """One temperature class [lower, upper) of the curve."""

    lower: float  # °C, inclusive
    upper: float  # °C, exclusive
    days: int
    heat_kwh: float
    electricity_kwh: float
    ratio: float | None  # None: below the minimum electricity or sparse
    mean_outdoor: float  # mean of the day means in this class
    sparse: bool = False  # inner class with fewer than the minimum days


def valid_outdoor(value: float | None) -> bool:
    """An hourly outdoor mean inside the plausible range."""
    return (
        value is not None
        and math.isfinite(value)
        and OUTDOOR_MIN <= value <= OUTDOOR_MAX
    )


def daily_samples(
    hours: Mapping[datetime, Totals],
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
    *,
    min_hours: int = MIN_DAY_HOURS,
) -> list[DaySample]:
    """Local days with at least `min_hours` valid outdoor values, by date.

    `hours` and `outdoor` are keyed by UTC hour starts. An hour belongs to the
    local day its start falls in. An hour in `outdoor` but not in `hours`
    booked no energy.
    """
    temps: dict[date, list[float]] = {}
    energy: dict[date, Totals] = {}
    energy_hours: dict[date, int] = {}
    for hour, value in outdoor.items():
        if not valid_outdoor(value):
            continue
        day = hour.astimezone(tz).date()
        temps.setdefault(day, []).append(value)
        if (totals := hours.get(hour)) is not None:
            energy[day] = energy.get(day, Totals()) + totals
            energy_hours[day] = energy_hours.get(day, 0) + 1
    return [
        DaySample(
            day=day,
            hours=len(values),
            mean_outdoor=sum(values) / len(values),
            totals=energy.get(day, Totals()),
            energy_hours=energy_hours.get(day, 0),
        )
        for day, values in sorted(temps.items())
        if len(values) >= min_hours
    ]


def class_lower(temperature: float, width: float = CLASS_WIDTH) -> float:
    """Lower bound of the class holding `temperature` (e.g. -0.5 -> -2.0)."""
    return math.floor(temperature / width) * width + 0.0  # no -0.0


@dataclass
class _Group:
    lower: float
    upper: float
    days: list[DaySample]

    def merged(self, other: _Group) -> _Group:
        return _Group(
            min(self.lower, other.lower),
            max(self.upper, other.upper),
            self.days + other.days,
        )


def curve_from_days(
    days: list[DaySample],
    scope: str = "heating",
    *,
    min_electricity: float = MIN_ELECTRICITY,
    min_days: int = MIN_DAYS,
    width: float = CLASS_WIDTH,
) -> list[CurveRow]:
    """Curve rows from day samples; see `performance_curve`."""
    modes = CURVE_SCOPES[scope]
    by_class: dict[float, list[DaySample]] = {}
    for sample in days:
        if sample.totals.heat(*modes) <= 0:
            continue  # no heat in this scope: not a day of the curve
        by_class.setdefault(class_lower(sample.mean_outdoor, width), []).append(sample)
    groups = [
        _Group(lower, lower + width, samples)
        for lower, samples in sorted(by_class.items())
    ]
    # Merge sparse edge classes into their inner neighbour.
    while len(groups) > 1 and len(groups[0].days) < min_days:
        groups[1] = groups[0].merged(groups[1])
        del groups[0]
    while len(groups) > 1 and len(groups[-1].days) < min_days:
        groups[-2] = groups[-2].merged(groups[-1])
        del groups[-1]
    rows = []
    for group in groups:
        heat = sum(d.totals.heat(*modes) for d in group.days)
        electricity = sum(d.totals.electricity(*modes) for d in group.days)
        sparse = len(group.days) < min_days
        rows.append(
            CurveRow(
                lower=group.lower,
                upper=group.upper,
                days=len(group.days),
                heat_kwh=heat,
                electricity_kwh=electricity,
                ratio=None if sparse else ratio(heat, electricity, min_electricity),
                mean_outdoor=sum(d.mean_outdoor for d in group.days) / len(group.days),
                sparse=sparse,
            )
        )
    return rows


def performance_curve(
    hours: Mapping[datetime, Totals],
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
    scope: str = "heating",
    *,
    min_electricity: float = MIN_ELECTRICITY,
    min_days: int = MIN_DAYS,
    width: float = CLASS_WIDTH,
) -> list[CurveRow]:
    """Ratio per outdoor temperature class, coldest class first.

    `scope` is "heating" or "combined" (heating and hot water). A day enters
    a scope's curve only when it delivered heat in that scope. Electricity is
    running plus backup heater of the scope's modes, without standby. A
    single remaining class below `min_days` is returned flagged as sparse.
    """
    return curve_from_days(
        daily_samples(hours, outdoor, tz),
        scope,
        min_electricity=min_electricity,
        min_days=min_days,
        width=width,
    )


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def curve_as_dicts(rows: list[CurveRow]) -> list[dict[str, Any]]:
    """Rows as plain dicts for an action response."""
    return [
        {
            "lower": row.lower,
            "upper": row.upper,
            "days": row.days,
            "mean_outdoor": round(row.mean_outdoor, 1),
            "heat_kwh": round(row.heat_kwh, 3),
            "electricity_kwh": round(row.electricity_kwh, 3),
            "ratio": _round(row.ratio, 2),
            "sparse": row.sparse,
        }
        for row in rows
    ]
