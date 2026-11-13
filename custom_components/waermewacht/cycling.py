"""Cycling statistics over finished and open runs. Pure Python, no HA imports.

Definitions (docs/ENTWICKLUNG.md, section 3):
- A start is a counted run (its start was observed) beginning in the window.
- Short and critical runs, run time per start and pauses only use finished
  runs without observation gaps; a run counts for the window it ended in.
- Starts per year (`starts_per_year`): counted over the last 12 months
  where the start counter's statistics or the diary reach back that far;
  else projected from the last 7 complete local days, over the hours the
  compressor state was known in them, with the heating days of the last
  12 months when the week had heating days (heating starts per heating day
  x heating days + other starts per day x 365), else starts per day x 365.
  Placed in the field test of Fraunhofer ISE (WP-QS, measuring year 2024,
  51 air/water heat pumps): a third at most 2,000 starts a year, 90 %
  below 5,500 (docs/ENTWICKLUNG.md, section 3). An orientation, not a
  check.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from itertools import pairwise

from .degree_days import MIN_DAY_HOURS, valid_outdoor
from .duty import heating_start
from .periods import local_midnight
from .runs import Defrost, Run


@dataclass(frozen=True)
class CycleStats:
    """Cycling figures for one time window."""

    starts: int
    runtime_seconds: float
    finished_runs: int  # counted, certain runs that ended in the window
    finished_seconds: float  # their total duration
    short_runs: int
    critical_runs: int
    shortest_pause_seconds: float | None
    defrosts: int
    defrost_seconds: float

    @property
    def seconds_per_run(self) -> float | None:
        """Average duration of the runs that ended in the window."""
        if not self.finished_runs:
            return None
        return self.finished_seconds / self.finished_runs


def _overlap(start: datetime, end: datetime, lo: datetime, hi: datetime) -> float:
    seconds = (min(end, hi) - max(start, lo)).total_seconds()
    return max(seconds, 0.0)


def cycle_stats(
    runs: Sequence[Run],
    open_run: Run | None,
    defrosts: Iterable[Defrost],
    open_defrost: Defrost | None,
    start: datetime,
    end: datetime,
    now: datetime,
    *,
    short_seconds: float,
    critical_seconds: float,
) -> CycleStats:
    """Figures for the window [start, end), counted up to `now`."""
    hi = min(end, now)
    every = [*runs, *([open_run] if open_run else [])]
    starts = sum(1 for r in every if r.counted and start <= r.start < end)
    runtime = sum(_overlap(r.start, r.end or now, start, hi) for r in every)

    certain = [r for r in runs if r.end and r.counted and not r.uncertain]
    ended = [r for r in certain if r.end and start <= r.end < end]
    durations = [r.seconds(now) for r in ended]

    pauses: list[float] = []
    for before, after in pairwise(sorted(every, key=lambda r: r.start)):
        if before.end is None or before.uncertain or after.uncertain:
            continue
        if not after.counted or not start <= after.start < end:
            continue
        pauses.append((after.start - before.end).total_seconds())

    every_defrost = [*defrosts, *([open_defrost] if open_defrost else [])]
    return CycleStats(
        starts=starts,
        runtime_seconds=runtime,
        finished_runs=len(ended),
        finished_seconds=sum(durations),
        short_runs=sum(1 for d in durations if d < short_seconds),
        critical_runs=sum(1 for d in durations if d < critical_seconds),
        shortest_pause_seconds=min(pauses) if pauses else None,
        defrosts=sum(1 for d in every_defrost if start <= d.start < end),
        defrost_seconds=sum(
            _overlap(d.start, d.end or now, start, hi) for d in every_defrost
        ),
    )


def activity_seconds(
    runs: Sequence[Run],
    open_run: Run | None,
    start: datetime,
    end: datetime,
    now: datetime,
) -> dict[str, float]:
    """Running seconds per activity within the window [start, end).

    A run only keeps its total per activity, so a run reaching into the window
    (over midnight, or still open) adds its share of the time inside it.
    """
    hi = min(end, now)
    result: dict[str, float] = {}
    for run in [*runs, *([open_run] if open_run else [])]:
        duration = run.seconds(now)
        inside = _overlap(run.start, run.end or now, start, hi)
        if duration <= 0 or inside <= 0:
            continue
        share = min(inside / duration, 1.0)
        for activity, seconds in run.activity_seconds.items():
            result[activity] = result.get(activity, 0.0) + seconds * share
    return result


def max_starts_per_hour(
    runs: Sequence[Run], open_run: Run | None, start: datetime, end: datetime
) -> int:
    """Most counted starts within any 60 minutes beginning in [start, end)."""
    times = sorted(
        r.start
        for r in [*runs, *([open_run] if open_run else [])]
        if r.counted and start <= r.start < end
    )
    best, first = 0, 0
    for last, at in enumerate(times):
        while at - times[first] >= timedelta(hours=1):
            first += 1
        best = max(best, last - first + 1)
    return best


# Starts per year in the field test of Fraunhofer ISE (WP-QS, 2024, 51
# air/water heat pumps): a third at most LOW_THIRD, 90 % below TOP_TENTH.
FIELD_LOW_THIRD = 2000
FIELD_TOP_TENTH = 5500
FIELD_CLASSES = ("low_third", "typical", "top_10_percent")
PROJECTION_DAYS = 7
# Hours of the 7 days with a known compressor state the projection needs:
# a cloud source may be gone for hours, the rest of the week still tells
# (own assumption: 6 of 7 days).
MIN_OBSERVED_HOURS = 144.0
TOO_FEW_DAYS = "too_few_days"
TOO_FEW_HOURS = "too_few_hours"
# How the starts per year came about (attribute `method`).
METHOD_12_MONTHS = "last_12_months"
METHOD_HEATING_DAYS = "heating_days"
METHOD_7_DAYS = "last_7_days"
# Own assumptions: the days with an outdoor mean a year needs (most of it,
# a few days without data are fine) and the heating days of the 7 a week
# needs for heating starts per heating day.
MIN_YEAR_DAYS = 330
MIN_WEEK_HEATING_DAYS = 3


@dataclass(frozen=True)
class StartsProjection:
    """Starts per day of the last complete days and the yearly projection."""

    days: int  # complete local days observed (at most PROJECTION_DAYS)
    observed_hours: float | None = None  # with a known compressor state
    starts: int | None = None
    per_day: float | None = None
    per_year: int | None = None
    field_class: str | None = None  # one of FIELD_CLASSES
    reason: str | None = None  # why there is no projection
    window_hours: float = 0.0  # hours of the days (DST: 167 or 169)
    heating_by_day: tuple[int, ...] = ()  # heating starts per day

    def as_attributes(self) -> dict[str, float | int | str | None]:
        return {
            "starts_per_day_7d": None
            if self.per_day is None
            else round(self.per_day, 1),
            "starts_7d_days": self.days,
            "starts_7d_observed_hours": None
            if self.observed_hours is None
            else round(self.observed_hours, 1),
            "starts_7d_reason": self.reason,
        }


def field_class(per_year: float) -> str:
    """Place a number of starts per year in the Fraunhofer field test."""
    if per_year <= FIELD_LOW_THIRD:
        return "low_third"
    if per_year <= FIELD_TOP_TENTH:
        return "typical"
    return "top_10_percent"


def unobserved_seconds(
    gaps: Iterable[tuple[datetime, datetime]], start: datetime, end: datetime
) -> float:
    """Seconds of [start, end) inside the gaps (overlaps counted once)."""
    total = 0.0
    reached = start
    for lo, hi in sorted(gaps):
        lo, hi = max(lo, reached), min(hi, end)
        if hi > lo:
            total += (hi - lo).total_seconds()
            reached = hi
    return total


def starts_projection(
    runs: Sequence[Run],
    open_run: Run | None,
    day_starts: Sequence[datetime],
    end: datetime,
    observed_since: datetime | None,
    gaps: Iterable[tuple[datetime, datetime]],
) -> StartsProjection:
    """Starts per observed day over the complete days [day_starts[0], end)
    and the projection to a year.

    `day_starts` are the starts (UTC) of the PROJECTION_DAYS local days
    before `end` (today's midnight). The time without a known compressor
    state (`gaps`: source unavailable, Home Assistant down) is left out:
    starts per observed hour x 24 (per day) and x 24 x 365 (per year). A run
    first seen running after a gap is no start (RunTracker). Unknown before
    the compressor was observed since the first of the days, or with less
    than MIN_OBSERVED_HOURS observed.
    """
    days = sum(1 for day in day_starts if observed_since and day >= observed_since)
    if observed_since is None or len(day_starts) < PROJECTION_DAYS:
        return StartsProjection(days=days, reason=TOO_FEW_DAYS)
    if days < len(day_starts):
        return StartsProjection(days=days, reason=TOO_FEW_DAYS)
    start = day_starts[0]
    observed = (
        (end - start).total_seconds() - unobserved_seconds(gaps, start, end)
    ) / 3600
    if observed < MIN_OBSERVED_HOURS:
        return StartsProjection(
            days=days, observed_hours=observed, reason=TOO_FEW_HOURS
        )
    every = [*runs, *([open_run] if open_run else [])]
    starts = sum(1 for r in every if r.counted and start <= r.start < end)
    bounds = [*day_starts, end]
    heating_by_day = tuple(
        sum(1 for r in every if lo <= r.start < hi and heating_start(r))
        for lo, hi in pairwise(bounds)
    )
    per_day = starts / observed * 24
    per_year = round(per_day * 365)
    return StartsProjection(
        days=days,
        observed_hours=observed,
        starts=starts,
        per_day=per_day,
        per_year=per_year,
        field_class=field_class(per_year),
        window_hours=(end - start).total_seconds() / 3600,
        heating_by_day=heating_by_day,
    )


@dataclass(frozen=True)
class StartsYear:
    """Starts per year: counted over the last 12 months where the counter or
    the diary reaches back that far, else projected from the last 7 days
    (with the heating days of a year when the week had heating days)."""

    value: int | None
    method: str | None  # one of the METHOD_* constants
    week: StartsProjection
    since: datetime | None = None  # METHOD_12_MONTHS: start of the count
    heating_per_day: float | None = None  # METHOD_HEATING_DAYS
    other_per_day: float | None = None
    heating_days: int | None = None  # heating days in the last 12 months
    week_heating_days: int | None = None  # of the 7 days

    @property
    def field_class(self) -> str | None:
        return None if self.value is None else field_class(self.value)

    def as_attributes(self) -> dict[str, float | int | str | None]:
        def one(value: float | None) -> float | None:
            return None if value is None else round(value, 1)

        return {
            "method": self.method,
            "field_class": self.field_class,
            "since": None if self.since is None else self.since.isoformat(),
            "heating_starts_per_heating_day": one(self.heating_per_day),
            "other_starts_per_day": one(self.other_per_day),
            "heating_days_per_year": self.heating_days,
            "heating_days_7d": self.week_heating_days,
            **self.week.as_attributes(),
        }


def heating_days_per_year(
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
    first: date,
    end: date,
    limit: float,
) -> int | None:
    """Days of [first, end) whose outdoor mean lies below the heating limit,
    scaled to 365 days; None with fewer than MIN_YEAR_DAYS days that have
    MIN_DAY_HOURS valid hourly values (`outdoor` keyed by UTC hour starts)."""
    temps: dict[date, list[float]] = {}
    lo, hi = local_midnight(first, tz), local_midnight(end, tz)
    for hour, value in outdoor.items():
        if lo <= hour < hi and valid_outdoor(value):
            temps.setdefault(hour.astimezone(tz).date(), []).append(value)
    means = [sum(v) / len(v) for v in temps.values() if len(v) >= MIN_DAY_HOURS]
    if len(means) < MIN_YEAR_DAYS:
        return None
    below = sum(1 for mean in means if mean < limit)
    return round(below * 365 / len(means))


def starts_per_year(
    week: StartsProjection,
    *,
    last_12_months: Baseline | None = None,
    heating_days: int | None = None,
    week_outdoor: Sequence[float | None] = (),
    heating_limit: float | None = None,
    split: bool = False,
) -> StartsYear:
    """Starts per year, in this order:

    1. `last_12_months` (starts, since): counted, no projection.
    2. With the heating days of the last 12 months, the heating limit, the
       outdoor mean of each of the 7 days and runs that know their activity
       (`split`): heating starts per heating day of the week x heating days
       + other starts (hot water, cooling) per day x 365. Needs
       MIN_WEEK_HEATING_DAYS heating days in the week.
    3. Starts per day of the last 7 days x 365 (too high in winter, too low
       in summer).
    """
    if last_12_months is not None:
        count, since = last_12_months
        return StartsYear(count, METHOD_12_MONTHS, week, since=since)
    if week.per_year is None or week.starts is None or not week.observed_hours:
        return StartsYear(None, None, week)
    known = [t for t in week_outdoor if t is not None]
    if (
        split
        and heating_days is not None
        and heating_limit is not None
        and len(week.heating_by_day) == len(week_outdoor) == len(known)
    ):
        flags = [t < heating_limit for t in known]
        count = sum(flags)
        if count >= MIN_WEEK_HEATING_DAYS:
            # Gaps: scale the observed starts up to the whole window.
            factor = week.window_hours / week.observed_hours
            heating = sum(week.heating_by_day)
            per_heating_day = heating * factor / count
            other = (week.starts - heating) * factor / len(flags)
            return StartsYear(
                round(per_heating_day * heating_days + other * 365),
                METHOD_HEATING_DAYS,
                week,
                heating_per_day=per_heating_day,
                other_per_day=other,
                heating_days=heating_days,
                week_heating_days=count,
            )
    return StartsYear(week.per_year, METHOD_7_DAYS, week)


def diary_starts(
    diary: Sequence[Mapping[str, object]], first: date, last: date
) -> int | None:
    """Starts of the diary days first … last (both included), when the diary
    has at least MIN_YEAR_DAYS of them (Wärmewacht counted the starts)."""
    lo, hi = first.isoformat(), last.isoformat()
    counts = [
        e["starts"]
        for e in diary
        if lo <= str(e.get("day")) <= hi and isinstance(e.get("starts"), int)
    ]
    if len(counts) < MIN_YEAR_DAYS:
        return None
    days = (last - first).days + 1
    return round(sum(counts) * days / len(counts))


# Why cycling counts as conspicuous (attribute triggers).
TRIGGER_PER_HOUR = "starts_per_hour"
TRIGGER_CRITICAL = "critical_runs"
TRIGGER_PER_DAY = "starts_per_day"


def cycling_triggers(
    max_per_hour: int,
    critical_runs: int,
    starts_24h: int,
    *,
    starts_per_hour: float,
    critical_per_day: int,
    starts_per_day: float | None,
) -> list[str]:
    """What makes the last 24 hours conspicuous: more starts within one hour
    than `starts_per_hour`, at least `critical_per_day` critical runs, or
    (only when set) more starts in 24 hours than `starts_per_day`."""
    triggers = []
    if max_per_hour > starts_per_hour:
        triggers.append(TRIGGER_PER_HOUR)
    if critical_runs >= critical_per_day:
        triggers.append(TRIGGER_CRITICAL)
    if starts_per_day is not None and starts_24h > starts_per_day:
        triggers.append(TRIGGER_PER_DAY)
    return triggers


type Baseline = tuple[int, datetime]


def season_starts_baseline(
    from_statistics: Baseline | None,
    seen: Baseline | None,
    current: int | None,
    season_start: datetime,
    now: datetime,
) -> tuple[Baseline | None, Baseline | None]:
    """Start counter at the start of the season, and the value to keep.

    From the statistics where the counter has some; else (no state class,
    P1P2MQTT) the first value seen in this season, kept across restarts.
    Returns (baseline, seen value to keep).
    """
    if from_statistics is not None:
        return from_statistics, seen
    if seen is None or seen[1] < season_start:
        seen = (current, now) if current is not None else None
    return seen, seen


def prune(
    runs: list[Run],
    defrosts: list[Defrost],
    keep_from: datetime,
    gaps: list[tuple[datetime, datetime]] | None = None,
) -> None:
    """Drop runs, defrosts and gaps that ended before `keep_from` (in place)."""
    runs[:] = [r for r in runs if r.end is None or r.end >= keep_from]
    defrosts[:] = [d for d in defrosts if d.end is None or d.end >= keep_from]
    if gaps is not None:
        gaps[:] = [g for g in gaps if g[1] >= keep_from]
