"""Measured heating power per outdoor temperature class (health check 4.17).

Pure Python, no Home Assistant imports. Design and decisions:
docs/GESUNDHEITSCHECK.md 4.17.

The run time per class (duty.py) says whether a heat pump cycles, not how
much it delivers: a modulating unit that runs all the time may run at a
third of its power. The heat of a full heating hour is its power in kW. Per
2-K class of the hourly outdoor mean this collects the heat of such hours
and derives, without a field and without a speed signal:

- per class the smallest (10th percentile), the median and the largest
  (95th percentile) heat per full heating hour, and the demand: the heating
  heat of the days whose outdoor mean falls in the class over their hours.
  Days, not hours: with a time program, a night setback or a blocking time
  the coldest hours (the night) take little or no heat and the warmer ones
  (the morning) catch up, so hourly demand would fall with the cold (a
  forum user's hybrid off from 23:00, 17.11.2026);
- "smallest measured power": the smallest class median among the classes
  in which the unit heats less than half of the time (own assumption: there
  it mostly runs at its lower limit);
- "largest measured power": the 95th percentile of the coldest class with
  enough full hours (own assumption), the demand of that class beside it.

Kennwerte only: no source says where these figures become a fault, so no
limits and no findings.

A full heating hour: the compressor ran at least 55 of its minutes in one
run (no stop and restart), no hot water and no cooling heat in the hour,
and, from the diary, no defrost and no hot water charge. Sources: per day
the diary's bit mask "full_hours" (written at midnight from the runs, exact
to the second), for days without it the hourly change of a run time counter
of heating (look-back; defrosts are not known there and stay in, which
lowers the 10th percentile, not the median). The heat per hour comes from
the hourly statistics the daily analysis reads anyway: no query of its own.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any

from .curve import class_lower
from .degree_days import MIN_DAY_HOURS, valid_outdoor
from .energy import Kind, Totals
from .model import Mode
from .runs import Run

HOUR = timedelta(hours=1)
FULL_HOUR_MINUTES = 55.0  # own assumption (trial 14.11.2026)
MIN_POWER_HOURS = 12  # full hours a class needs (own assumption)
# Days a class needs for its demand (own assumption, as the bands of
# heating_curve.py); a day counts with MIN_DAY_HOURS outdoor values.
MIN_DEMAND_DAYS = 3
PARTIAL_SHARE = 0.5  # heats less than half the time: at its lower limit
LOW_QUANTILE = 0.10
HIGH_QUANTILE = 0.95
# An hour with this much time without a known compressor state is left out
# (as duty.MAX_GAP_SECONDS).
MAX_GAP_SECONDS = 600.0
# A run time counter's hourly change above this is a jump, not an hour.
MAX_HOUR_MINUTES = 61.0

# Reasons without figures.
TOO_FEW_HOURS = "too_few_hours"
# No class heating less than half the time has enough full hours (a unit
# that cycles in mild weather has hardly any there).
NO_PARTIAL_LOAD = "no_partial_load_hours"
NO_RUN_TIME = "no_run_time"  # neither a compressor state nor a run time counter
NO_HOURLY_HEAT = "no_hourly_heat"  # heat only as day values of the day before
COARSE_HEAT = "coarse_heat"  # heat meter in whole kWh
NO_DHW_SPLIT = "no_dhw_split"  # one heat meter for all modes, no activity


def _overlap(start: datetime, end: datetime, lo: datetime, hi: datetime) -> float:
    return max((min(end, hi) - max(start, lo)).total_seconds(), 0.0)


def day_hours(day: date, tz: tzinfo) -> list[datetime]:
    """UTC starts of the hours of a local day (23, 24 or 25)."""
    hour = datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(UTC)
    nxt = day + timedelta(days=1)
    stop = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz).astimezone(UTC)
    hours = []
    while hour < stop:
        hours.append(hour)
        hour += HOUR
    return hours


def day_full_hours(
    runs: Sequence[Run],
    open_run: Run | None,
    hours: Sequence[datetime],
    now: datetime,
    *,
    blocked: Iterable[tuple[datetime, datetime | None]] = (),
    gaps: Sequence[tuple[datetime, datetime]] = (),
) -> int:
    """Bit mask of the full heating hours among `hours` (bit i: hours[i]).
    `blocked`: defrosts and hot water charges (start, end; None while
    open); an hour touching one is no full hour."""
    every = [*runs, *([open_run] if open_run else [])]
    spans = [(lo, hi or now) for lo, hi in blocked]
    mask = 0
    for index, hour in enumerate(hours):
        end = hour + HOUR
        if end > now:
            break
        inside = [
            seconds
            for r in every
            if (seconds := _overlap(r.start, r.end or now, hour, end)) > 0
        ]
        if len(inside) != 1 or inside[0] < FULL_HOUR_MINUTES * 60:
            continue
        if sum(_overlap(lo, hi, hour, end) for lo, hi in gaps) > MAX_GAP_SECONDS:
            continue
        if any(_overlap(lo, hi, hour, end) > 0 for lo, hi in spans):
            continue
        mask |= 1 << index
    return mask


def full_hours(
    entries: Iterable[Mapping[str, Any]],
    runtime_minutes: Mapping[datetime, float] | None,
    first: date,
    last: date,
    tz: tzinfo,
) -> tuple[set[datetime], int, int]:
    """Full heating hours of the days first … last: the diary's mask where a
    day has one, else the hours whose run time of heating is 55 minutes or
    more. Returns the hours, the days with a source, of them from the
    statistics."""
    diary = {
        day: entry["full_hours"]
        for entry in entries
        if entry.get("full_hours") is not None
        and first <= (day := date.fromisoformat(entry["day"])) <= last
    }
    by_day: dict[date, list[datetime]] = {}
    for hour, minutes in (runtime_minutes or {}).items():
        if minutes is not None and FULL_HOUR_MINUTES <= minutes <= MAX_HOUR_MINUTES:
            by_day.setdefault(hour.astimezone(tz).date(), []).append(hour)
    counted = set(runtime_minutes or {})
    found: set[datetime] = set()
    days = from_statistics = 0
    day = first
    while day <= last:
        if (mask := diary.get(day)) is not None:
            days += 1
            found.update(h for i, h in enumerate(day_hours(day, tz)) if mask >> i & 1)
        elif any(h in counted for h in day_hours(day, tz)):
            days += 1
            from_statistics += 1
            found.update(by_day.get(day, ()))
        day += timedelta(days=1)
    return found, days, from_statistics


def quantile(values: Sequence[float], q: float) -> float:
    """Linear between the closest ranks (as numpy's default)."""
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


@dataclass(frozen=True)
class PowerClass:
    """One outdoor class: heat per full heating hour and the demand (kW)."""

    lower: float
    full_hours: int
    min_kw: float | None  # 10th percentile
    median_kw: float | None
    max_kw: float | None  # 95th percentile
    hours: float  # hours of the days behind the demand
    demand_kw: float | None
    demand_days: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "full_hours": self.full_hours,
            "min_kw": _round(self.min_kw),
            "median_kw": _round(self.median_kw),
            "max_kw": _round(self.max_kw),
            "demand_kw": _round(self.demand_kw),
            "demand_days": self.demand_days,
        }


@dataclass(frozen=True)
class PowerFigures:
    """Classes of a period and the measured lower and upper power."""

    classes: list[PowerClass]
    min_kw: float | None
    min_class: float | None
    min_reason: str | None
    max_kw: float | None
    max_class: float | None
    demand_at_max_kw: float | None
    reason: str | None
    first: date
    last: date
    days: int = 0
    days_from_statistics: int = 0

    @property
    def full_hours(self) -> int:
        return sum(c.full_hours for c in self.classes)


def power_figures(
    hours: Mapping[datetime, Totals],
    building: Mapping[datetime, Totals],
    outdoor: Mapping[datetime, float],
    full: set[datetime],
    first: date,
    last: date,
    tz: tzinfo,
    *,
    shares: Mapping[float, float],
    lag: int = 0,
    days: int = 0,
    days_from_statistics: int = 0,
) -> PowerFigures:
    """Figures of the days first … last. `hours`: the heat pump's energy per
    hour; `building`: with a hybrid's boiler (the demand); `shares`: the
    heating run time share per class (duty.py). `lag` 1 for heat meters
    that report up to an hour late (day values): then the hour before must
    be full too and the hour after free of hot water."""
    lo = day_hours(first, tz)[0]
    hi = day_hours(last + timedelta(days=1), tz)[0]
    heat: dict[float, list[float]] = {}
    for hour in full:
        if not lo <= hour < hi or (temperature := outdoor.get(hour)) is None:
            continue
        if any(hour - k * HOUR not in full for k in range(1, lag + 1)):
            continue
        totals = hours.get(hour)
        if totals is None or (kwh := totals.get(Kind.HEAT, Mode.HEATING)) <= 0:
            continue  # no heat in a full hour: a stuck meter, never 0 kW
        if not all(
            (t := hours.get(hour + k * HOUR)) is not None
            and t.get(Kind.HEAT, Mode.DHW) <= 0
            and t.get(Kind.HEAT, Mode.COOLING) <= 0
            for k in range(lag + 1)
        ):
            continue
        heat.setdefault(class_lower(temperature), []).append(kwh)
    demand = daily_demand(building, outdoor, first, last, tz)
    classes = []
    for lower in sorted(heat.keys() | demand.keys()):
        values = heat.get(lower, [])
        enough = len(values) >= MIN_POWER_HOURS
        kwh, count, day_count = demand.get(lower, (0.0, 0.0, 0))
        classes.append(
            PowerClass(
                lower=lower,
                full_hours=len(values),
                min_kw=quantile(values, LOW_QUANTILE) if enough else None,
                median_kw=quantile(values, 0.5) if enough else None,
                max_kw=quantile(values, HIGH_QUANTILE) if enough else None,
                hours=count,
                demand_kw=max(kwh, 0.0) / count
                if day_count >= MIN_DEMAND_DAYS
                else None,
                demand_days=day_count,
            )
        )
    usable = [c for c in classes if c.median_kw is not None]
    partial = [
        c
        for c in usable
        if (share := shares.get(c.lower)) is not None and share < PARTIAL_SHARE
    ]
    coldest = usable[0] if usable else None
    smallest = min(partial, key=lambda c: c.median_kw or 0.0) if partial else None
    return PowerFigures(
        classes=classes,
        min_kw=None if smallest is None else smallest.median_kw,
        min_class=None if smallest is None else smallest.lower,
        min_reason=None
        if smallest is not None
        else (NO_PARTIAL_LOAD if usable else TOO_FEW_HOURS),
        max_kw=None if coldest is None else coldest.max_kw,
        max_class=None if coldest is None else coldest.lower,
        demand_at_max_kw=None if coldest is None else coldest.demand_kw,
        reason=None if usable else TOO_FEW_HOURS,
        first=first,
        last=last,
        days=days,
        days_from_statistics=days_from_statistics,
    )


def daily_demand(
    building: Mapping[datetime, Totals],
    outdoor: Mapping[datetime, float],
    first: date,
    last: date,
    tz: tzinfo,
) -> dict[float, tuple[float, float, int]]:
    """Per class of the daily outdoor mean: heating heat, hours and days of
    the days first … last. A day counts with MIN_DAY_HOURS valid outdoor
    values (degree_days.py) and energy statistics for the day."""
    result: dict[float, tuple[float, float, int]] = {}
    day = first
    while day <= last:
        hours = day_hours(day, tz)
        temps = [v for h in hours if valid_outdoor(v := outdoor.get(h))]
        known = [t for h in hours if (t := building.get(h)) is not None]
        if len(temps) >= MIN_DAY_HOURS and known:
            lower = class_lower(sum(temps) / len(temps))
            kwh, count, days = result.get(lower, (0.0, 0.0, 0))
            result[lower] = (
                kwh + sum(t.heat(Mode.HEATING) for t in known),
                count + len(hours),
                days + 1,
            )
        day += timedelta(days=1)
    return result


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def chosen(duty: Mapping[str, Any]) -> PowerFigures | None:
    """The power figures of the season the duty sensors show."""
    power = duty.get("power") or {}
    figures = power.get(duty.get("season", ""))
    return figures if isinstance(figures, PowerFigures) else None


def headline(duty: Mapping[str, Any]) -> dict[str, Any]:
    """The measured lower and upper power of the chosen season, with its
    period (seasons are never mixed) or the reason there is none."""
    figures = chosen(duty)
    power = duty.get("power") or {}
    if figures is None:
        return {"power_reason": power.get("reason")} if power else {}
    return {
        "measured_min_kw": _round(figures.min_kw),
        "measured_min_class": figures.min_class,
        "measured_max_kw": _round(figures.max_kw),
        "measured_max_class": figures.max_class,
        "demand_at_max_class_kw": _round(figures.demand_at_max_kw),
        "power_reason": figures.reason,
        "measured_min_reason": figures.min_reason,
        "power_first_day": figures.first.isoformat(),
        "power_last_day": figures.last.isoformat(),
        "power_days": figures.days,
        "power_days_from_statistics": figures.days_from_statistics,
        "full_hours": figures.full_hours,
        "full_hour_minutes": FULL_HOUR_MINUTES,
        "min_power_hours": MIN_POWER_HOURS,
    }


def with_power(
    attributes: dict[str, Any], duty: Mapping[str, Any], *, figures_too: bool
) -> dict[str, Any]:
    """The duty sensors' attributes (duty.duty_attributes) with the power per
    class in `classes`; `figures_too` adds the headline."""
    figures = chosen(duty)
    if figures is not None and attributes.get("classes"):
        by_lower = {c.lower: c.as_dict() for c in figures.classes}
        attributes["classes"] = [
            {**row, **by_lower.get(row["lower"], {})} for row in attributes["classes"]
        ]
    # The other season's power per class beside its run time shares.
    other_name = "current" if duty.get("season") == "previous" else "previous"
    other = (duty.get("power") or {}).get(other_name)
    if isinstance(other, PowerFigures) and attributes.get("other_classes"):
        by_lower = {c.lower: c.as_dict() for c in other.classes}
        attributes["other_classes"] = [
            {**row, **by_lower.get(row["lower"], {})}
            for row in attributes["other_classes"]
        ]
    if figures_too:
        attributes.update(headline(duty))
        attributes["expected_continuous_below_measured"] = duty.get(
            "expected_continuous_below_measured"
        )
    return attributes


def oversize_attributes(
    duty: Mapping[str, Any], load_at_7c_kw: float | None
) -> dict[str, Any]:
    """Measured power beside the data sheet's (health check 4.7), and whether
    the measured lower limit lies above the demand at +7 °C. No factor from
    the largest measured power: it is what the house took, not what the unit
    can, and an oversized unit would look too small."""
    figures = chosen(duty)
    result = headline(duty)
    if figures is None:
        return result
    bottom = figures.min_kw
    result["cycling_expected_measured"] = (
        None if bottom is None or load_at_7c_kw is None else 0 < load_at_7c_kw < bottom
    )
    return result


def shares(classes: Iterable[Any], min_hours: float) -> dict[float, float]:
    """Heating run time share per class (duty.DutyClass) with enough hours."""
    return {c.lower: c.share for c in classes if c.hours >= min_hours}
