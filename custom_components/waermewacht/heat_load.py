"""Heat load from the energy signature. Pure Python, no HA imports.

Energy signature as in the EAV method (Fraunhofer ISE, WP-QS final report
p. 93-94): mean heating power per local week (Monday 00:00) over the week's
mean outdoor temperature, fitted with a least-squares line P = a + b·T. Only
heat for space heating counts (hot water is separated), only cold weeks
(mean < 12 °C), and only weeks with at least 6 full days. The slope -b is the
building's heat loss in kW/K, -a/b the heating limit where P reaches 0.

Two readings at the design outdoor temperature (DIN/TS 12831-1, per postcode,
an option without default):
- measured: a + b·T_design, the line as fitted, i.e. with internal and solar
  gains that lower the heat demand;
- standard: the line moved parallel until it reaches 0 at 20 °C indoor
  reference (EAV sample report), P_std(T) = b·(T - 20) = -b·(20 - T). Only
  the slope is used; the gains, which make the measured line reach 0 below
  20 °C, are left out as a standard heat load calculation does.

Shown only with enough data (feasibility study, docs/ENTWICKLUNG.md
"Machbarkeit mit echten Daten"): at least 8 valid weeks, a spread of the weekly means of
at least 10 K and at least 5 frost days (day mean < 0 °C) in those weeks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from .curve import MIN_DAY_HOURS, DaySample, daily_samples
from .energy import Totals
from .model import Mode

INDOOR_REFERENCE = 20.0  # °C, where the standard line reaches 0 (EAV)
MAX_WEEK_OUTDOOR = 12.0  # °C, only weeks colder than this
MIN_WEEK_DAYS = 6  # full days a week needs
MIN_WEEKS = 8
MIN_SPREAD = 10.0  # K between the coldest and warmest valid week
MIN_FROST_DAYS = 5  # days with a mean below FROST in the valid weeks
FROST = 0.0  # °C

# Reasons for an insufficient result.
TOO_FEW_WEEKS = "too_few_weeks"
SPREAD_TOO_SMALL = "spread_too_small"
TOO_FEW_FROST_DAYS = "too_few_frost_days"
SLOPE_NOT_NEGATIVE = "slope_not_negative"


@dataclass(frozen=True)
class WeekPoint:
    """One valid week of the signature."""

    start: date  # local Monday
    days: int  # full days that entered
    hours: int  # hours of those days with an outdoor value (real hours)
    mean_outdoor: float  # °C, hour-weighted
    power_kw: float  # heating heat / hours
    frost_days: int


@dataclass
class HeatLoad:
    """Energy signature fit; values are None unless `sufficient`."""

    sufficient: bool
    reasons: list[str] = field(default_factory=list)
    weeks: list[WeekPoint] = field(default_factory=list)
    spread: float | None = None  # K
    frost_days: int = 0
    intercept_kw: float | None = None  # a
    slope_kw_per_k: float | None = None  # b, negative
    r_squared: float | None = None
    heating_limit: float | None = None  # °C where the measured line is 0
    design_temp: float | None = None
    measured_kw: float | None = None  # at design_temp, with gains
    standard_kw: float | None = None  # at design_temp, line through 0 at 20 °C


def full_day(sample: DaySample) -> bool:
    """A day that may enter the signature: enough outdoor values (checked by
    `daily_samples`), as many hours with energy data, and no cooling.

    Without energy data (a meter recorded later than the outdoor temperature)
    the day would enter with no heat at all: weeks of 0 kW in frost.
    """
    return (
        sample.energy_hours >= MIN_DAY_HOURS and sample.totals.heat(Mode.COOLING) <= 0
    )


def weekly_points(
    days: list[DaySample],
    *,
    max_outdoor: float = MAX_WEEK_OUTDOOR,
    min_days: int = MIN_WEEK_DAYS,
) -> list[WeekPoint]:
    """Valid weeks from day samples (full local days with enough values).

    Power is the heating heat of the week's full days over their hours with an
    outdoor value. Each such hour is one real hour, so a DST week has 167 or
    169 hours, and missing hours neither count as zero heat nor as time.
    """
    by_week: dict[date, list[DaySample]] = {}
    for sample in days:
        if full_day(sample):
            monday = sample.day - timedelta(days=sample.day.weekday())
            by_week.setdefault(monday, []).append(sample)
    points = []
    for monday, samples in sorted(by_week.items()):
        if len(samples) < min_days:
            continue
        hours = sum(s.hours for s in samples)
        mean = sum(s.mean_outdoor * s.hours for s in samples) / hours
        if mean >= max_outdoor:
            continue
        heat = sum(s.totals.heat(Mode.HEATING) for s in samples)
        points.append(
            WeekPoint(
                start=monday,
                days=len(samples),
                hours=hours,
                mean_outdoor=mean,
                power_kw=heat / hours,
                frost_days=sum(1 for s in samples if s.mean_outdoor < FROST),
            )
        )
    return points


def fit_line(points: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Least-squares line y = a + b·x; returns (a, b, R²).

    Needs at least two distinct x values. R² is 0 when y does not vary.
    """
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    sxy = sum((x - mx) * (y - my) for x, y in points)
    b = sxy / sxx
    a = my - b * mx
    ss_tot = sum((y - my) ** 2 for _, y in points)
    ss_res = sum((y - a - b * x) ** 2 for x, y in points)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return a, b, r2


def signature(
    days: list[DaySample],
    *,
    design_temp: float | None = None,
    max_outdoor: float = MAX_WEEK_OUTDOOR,
) -> HeatLoad:
    """Heat load from day samples; see `heat_load`."""
    weeks = weekly_points(days, max_outdoor=max_outdoor)
    temps = [w.mean_outdoor for w in weeks]
    spread = max(temps) - min(temps) if temps else None
    frost_days = sum(w.frost_days for w in weeks)
    reasons = []
    if len(weeks) < MIN_WEEKS:
        reasons.append(TOO_FEW_WEEKS)
    if spread is None or spread < MIN_SPREAD:
        reasons.append(SPREAD_TOO_SMALL)
    if frost_days < MIN_FROST_DAYS:
        reasons.append(TOO_FEW_FROST_DAYS)
    result = HeatLoad(
        sufficient=False,
        reasons=reasons,
        weeks=weeks,
        spread=spread,
        frost_days=frost_days,
        design_temp=design_temp,
    )
    if reasons:
        return result
    a, b, r2 = fit_line([(w.mean_outdoor, w.power_kw) for w in weeks])
    if b >= 0:
        result.reasons.append(SLOPE_NOT_NEGATIVE)
        return result
    result.sufficient = True
    result.intercept_kw = a
    result.slope_kw_per_k = b
    result.r_squared = r2
    result.heating_limit = -a / b
    if design_temp is not None:
        result.measured_kw = a + b * design_temp
        result.standard_kw = b * (design_temp - INDOOR_REFERENCE)
    return result


def heat_load(
    hours: Mapping[datetime, Totals],
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
    *,
    design_temp: float | None = None,
    max_outdoor: float = MAX_WEEK_OUTDOOR,
) -> HeatLoad:
    """Energy signature of space heating from hourly energy and outdoor means.

    Keys are UTC hour starts; weeks start on Monday 00:00 in `tz`. Without
    `design_temp` the heat load at the design temperature is not computed.
    """
    return signature(
        daily_samples(hours, outdoor, tz),
        design_temp=design_temp,
        max_outdoor=max_outdoor,
    )


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def heat_load_as_dict(result: HeatLoad) -> dict[str, Any]:
    """Result as a plain dict for an action response."""
    return {
        "sufficient": result.sufficient,
        "reasons": list(result.reasons),
        "week_count": len(result.weeks),
        "spread": _round(result.spread, 1),
        "frost_days": result.frost_days,
        "intercept_kw": _round(result.intercept_kw, 3),
        "slope_kw_per_k": _round(result.slope_kw_per_k, 4),
        "r_squared": _round(result.r_squared, 3),
        "heating_limit": _round(result.heating_limit, 1),
        "design_temp": result.design_temp,
        "measured_kw": _round(result.measured_kw, 2),
        "standard_kw": _round(result.standard_kw, 2),
        "weeks": [
            {
                "start": week.start.isoformat(),
                "days": week.days,
                "hours": week.hours,
                "mean_outdoor": round(week.mean_outdoor, 1),
                "power_kw": round(week.power_kw, 3),
            }
            for week in result.weeks
        ],
    }
