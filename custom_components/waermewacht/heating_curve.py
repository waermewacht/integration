"""Heating curve as a figure: flow temperature at 0 °C outdoors. Pure Python.

docs/GESUNDHEITSCHECK.md 4.5. The flow temperature decides the ratio more
than any other setting; a steep heating curve is the most common avoidable
loss. This is a figure for comparison (with the previous season, after a
change of the curve), not a finding: there is no sourced limit.

From the long-term statistics, hour by hour:
- An hour counts when it brought heating heat (at least MIN_HOUR_KWH) and no
  hot water or cooling heat: a hot water charge raises the flow to 50 °C and
  more, so hours with one are left out entirely.
- Per local day: the mean of the counted hours' flow temperature, weighted
  with their heating heat, against the day's mean outdoor temperature (as in
  curve.daily_samples, at least 20 valid hourly values). A day needs at least
  MIN_DAY_HOURS counted hours.
- A least-squares line through the days; its value at 0 °C is the figure,
  its slope the steepness of the curve (K flow per K outdoor, negative). At
  least MIN_DAYS days spanning MIN_SPREAD K, otherwise unknown with reasons.

The hourly flow mean includes the pauses of a run within the hour, so the
figure is a little below the set curve; it compares like with like between
seasons of the same installation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from typing import Any

from .curve import daily_samples
from .energy import Kind, Totals
from .heat_load import fit_line
from .model import Mode

MIN_HOUR_KWH = 0.3  # heating heat an hour needs to count
MIN_HOURS_PER_DAY = 2  # counted hours a day needs
MIN_DAYS = 14
MIN_SPREAD = 6.0  # K between the coldest and warmest counted day
AT_OUTDOOR = 0.0  # °C, where the figure is read off the line
FLOW_MIN = 10.0  # °C, plausible hourly flow means
FLOW_MAX = 80.0

TOO_FEW_DAYS = "too_few_days"
SPREAD_TOO_SMALL = "spread_too_small"


@dataclass(frozen=True)
class FlowDay:
    day: date
    mean_outdoor: float
    flow: float  # heat-weighted mean flow of the counted hours


@dataclass(frozen=True)
class FlowCurve:
    """Flow temperature over outdoor temperature of one period."""

    days: tuple[FlowDay, ...]
    at_zero: float | None  # °C flow at AT_OUTDOOR, None with reasons
    slope: float | None  # K flow per K outdoor
    r_squared: float | None
    spread: float | None  # K between the coldest and warmest day
    reasons: tuple[str, ...] = field(default=())


def _counts(totals: Totals) -> bool:
    return (
        totals.get(Kind.HEAT, Mode.HEATING) >= MIN_HOUR_KWH
        and totals.get(Kind.HEAT, Mode.DHW) <= 0
        and totals.get(Kind.HEAT, Mode.COOLING) <= 0
    )


def flow_days(
    hours: Mapping[datetime, Totals],
    flow: Mapping[datetime, float],
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
) -> list[FlowDay]:
    """Days with enough heating-only hours, with their outdoor mean."""
    weighted: dict[date, list[tuple[float, float]]] = {}
    for hour, totals in hours.items():
        value = flow.get(hour)
        if value is None or not FLOW_MIN <= value <= FLOW_MAX or not _counts(totals):
            continue
        heat = totals.get(Kind.HEAT, Mode.HEATING)
        weighted.setdefault(hour.astimezone(tz).date(), []).append((value, heat))
    result = []
    for sample in daily_samples({}, outdoor, tz):
        rows = weighted.get(sample.day, [])
        if len(rows) < MIN_HOURS_PER_DAY:
            continue
        heat = sum(h for _, h in rows)
        result.append(
            FlowDay(
                day=sample.day,
                mean_outdoor=sample.mean_outdoor,
                flow=sum(v * h for v, h in rows) / heat,
            )
        )
    return result


def flow_curve(
    hours: Mapping[datetime, Totals],
    flow: Mapping[datetime, float],
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
) -> FlowCurve:
    days = flow_days(hours, flow, outdoor, tz)
    temps = [d.mean_outdoor for d in days]
    spread = max(temps) - min(temps) if temps else None
    reasons = []
    if len(days) < MIN_DAYS:
        reasons.append(TOO_FEW_DAYS)
    if spread is None or spread < MIN_SPREAD:
        reasons.append(SPREAD_TOO_SMALL)
    if reasons:
        return FlowCurve(tuple(days), None, None, None, spread, tuple(reasons))
    a, b, r2 = fit_line([(d.mean_outdoor, d.flow) for d in days])
    return FlowCurve(tuple(days), a + b * AT_OUTDOOR, b, r2, spread)


def flow_curve_as_dict(result: FlowCurve) -> dict[str, Any]:
    def r(value: float | None, digits: int) -> float | None:
        return None if value is None else round(value, digits)

    return {
        "at_zero": r(result.at_zero, 1),
        "slope": r(result.slope, 2),
        "r_squared": r(result.r_squared, 2),
        "days": len(result.days),
        "spread": r(result.spread, 1),
        "reasons": list(result.reasons),
    }
