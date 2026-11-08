"""Heat load from the energy signature. Pure Python, no HA imports.

Energy signature as in the EAV method (Fraunhofer ISE, WP-QS final report
p. 93-94): mean heating power per local week (Monday 00:00) over the week's
mean outdoor temperature, fitted with a least-squares line P = a + b·T. Only
heat for space heating counts (hot water is separated), only cold weeks
(mean < 12 °C), and only weeks with at least 6 full days. A full day is a
heating day (at least degree_days.MIN_HEATING_DAY_KWH of heating heat): a
cool day with the heating off (summer mode held by hand, a gas boiler not
switched on yet in autumn) says nothing about the building and would steepen
the line. The slope -b is the building's heat loss in kW/K, -a/b the heating
limit where P reaches 0.

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
With 8 weeks but too small a spread or too few frost days (data only from
mild weeks, e.g. a gas meter recorded since late winter) the line is kept
as preliminary: slope, intercept, R² and heating limit, but no heat load at
the design temperature - that is the far extrapolation the rules guard.

A heat pump's sensors show the last complete season; without a usable one
(statistics only since this autumn) the current season so far, see
`choose_season`. The two are never mixed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from .curve import MIN_DAY_HOURS, DaySample, daily_samples
from .degree_days import MIN_HEATING_DAY_KWH
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
    """Energy signature fit; values are None unless `sufficient`, except the
    line itself when `preliminary`."""

    sufficient: bool
    preliminary: bool = False  # line from mild weeks only, no design value
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
    `daily_samples`), as many hours with energy data, no cooling, and heating.

    Without energy data (a meter recorded later than the outdoor temperature)
    the day would enter with no heat at all: weeks of 0 kW in frost. Without
    heating (switched off by hand) likewise.
    """
    return (
        sample.energy_hours >= MIN_DAY_HOURS
        and sample.totals.heat(Mode.COOLING) <= 0
        and sample.totals.heat(Mode.HEATING) >= MIN_HEATING_DAY_KWH
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


def fit_line(
    points: list[tuple[float, float]], weights: list[float] | None = None
) -> tuple[float, float, float]:
    """Least-squares line y = a + b·x; returns (a, b, R²).

    Needs at least two distinct x values. R² is 0 when y does not vary.
    `weights` (one per point, positive) weight the squares, e.g. by the hours
    behind a point of uneven length; without them all points count alike.
    """
    w = weights if weights is not None else [1.0] * len(points)
    n = sum(w)
    mx = sum(wi * x for wi, (x, _) in zip(w, points, strict=True)) / n
    my = sum(wi * y for wi, (_, y) in zip(w, points, strict=True)) / n
    sxx = sum(wi * (x - mx) ** 2 for wi, (x, _) in zip(w, points, strict=True))
    sxy = sum(wi * (x - mx) * (y - my) for wi, (x, y) in zip(w, points, strict=True))
    b = sxy / sxx
    a = my - b * mx
    ss_tot = sum(wi * (y - my) ** 2 for wi, (_, y) in zip(w, points, strict=True))
    ss_res = sum(
        wi * (y - a - b * x) ** 2 for wi, (x, y) in zip(w, points, strict=True)
    )
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
    return fit_signature(
        weeks,
        enough=len(weeks) >= MIN_WEEKS,
        too_few=TOO_FEW_WEEKS,
        design_temp=design_temp,
    )


def fit_signature(
    weeks: list[WeekPoint],
    *,
    enough: bool,
    too_few: str,
    design_temp: float | None = None,
    weighted: bool = False,
) -> HeatLoad:
    """The line through valid points (weeks, or the periods between manual
    meter readings); `enough` tells whether there are enough of them, else
    the reason `too_few`. Spread and frost days as for weeks. `weighted`
    weights each point with its hours (points of uneven length)."""
    temps = [w.mean_outdoor for w in weeks]
    spread = max(temps) - min(temps) if temps else None
    frost_days = sum(w.frost_days for w in weeks)
    reasons = []
    if not enough:
        reasons.append(too_few)
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
    if too_few in reasons:
        return result
    a, b, r2 = fit_line(
        [(w.mean_outdoor, w.power_kw) for w in weeks],
        [float(w.hours) for w in weeks] if weighted else None,
    )
    if b >= 0:
        result.reasons.append(SLOPE_NOT_NEGATIVE)
        return result
    result.intercept_kw = a
    result.slope_kw_per_k = b
    result.r_squared = r2
    result.heating_limit = -a / b
    if reasons:
        result.preliminary = True
        return result
    result.sufficient = True
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


PREVIOUS_SEASON = "previous"
CURRENT_SEASON = "current"


def choose_season(previous: HeatLoad, current: HeatLoad) -> str:
    """Which season's signature the sensors show: PREVIOUS_SEASON (the last
    complete one) or CURRENT_SEASON (so far).

    The last complete season wins whenever it is sufficient. Otherwise the
    better of the two: sufficient before preliminary before neither, then
    more valid weeks; a tie keeps the previous season. So a statistic that
    starts this autumn shows this winter's weeks as they come and the values
    once they suffice, and the result does not swing back and forth: the
    previous season stays fixed, the current one only gains weeks.
    """
    if previous.sufficient:
        return PREVIOUS_SEASON

    def rank(result: HeatLoad) -> tuple[bool, bool, int]:
        return result.sufficient, result.preliminary, len(result.weeks)

    return CURRENT_SEASON if rank(current) > rank(previous) else PREVIOUS_SEASON


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def heat_load_as_dict(result: HeatLoad) -> dict[str, Any]:
    """Result as a plain dict for an action response."""
    return {
        "sufficient": result.sufficient,
        "preliminary": result.preliminary,
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
