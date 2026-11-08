"""Cycling statistics over finished and open runs. Pure Python, no HA imports.

Definitions (docs/ENTWICKLUNG.md, section 3):
- A start is a counted run (its start was observed) beginning in the window.
- Short and critical runs, run time per start and pauses only use finished
  runs without observation gaps; a run counts for the window it ended in.
- Starts per year are projected from the last 7 complete local days (mean
  per day x 365) and placed in the field test of Fraunhofer ISE (WP-QS,
  measuring year 2024, 51 air/water heat pumps): a third at most 2,000
  starts a year, 90 % below 5,500 (docs/ENTWICKLUNG.md, section 3). An
  orientation, not a check: 7 days of autumn are no year.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

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
# Unobserved time (Home Assistant or the source down) the 7 days may hold:
# a restart misses no start worth speaking of, a day offline does (own
# assumption).
MAX_UNOBSERVED_SECONDS = 3600.0
TOO_FEW_DAYS = "too_few_days"
OBSERVATION_GAP = "observation_gap"


@dataclass(frozen=True)
class StartsProjection:
    """Starts per day of the last complete days and the yearly projection."""

    days: int  # complete local days observed (at most PROJECTION_DAYS)
    starts: int | None = None
    per_day: float | None = None
    per_year: int | None = None
    field_class: str | None = None  # one of FIELD_CLASSES
    reason: str | None = None  # why there is no projection

    def as_attributes(self) -> dict[str, float | int | str | None]:
        return {
            "starts_per_day_7d": None
            if self.per_day is None
            else round(self.per_day, 1),
            "starts_per_year_projected": self.per_year,
            "starts_field_class": self.field_class,
            "starts_7d_days": self.days,
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
    """Starts per day over the complete days [day_starts[0], end) and the
    projection to a year.

    `day_starts` are the starts (UTC) of the PROJECTION_DAYS local days
    before `end` (today's midnight), so days of 23 or 25 hours count as one
    day each. Unknown before the compressor was observed for all of them,
    or when more than MAX_UNOBSERVED_SECONDS of them are missing.
    """
    days = sum(1 for day in day_starts if observed_since and day >= observed_since)
    if observed_since is None or len(day_starts) < PROJECTION_DAYS:
        return StartsProjection(days=days, reason=TOO_FEW_DAYS)
    if days < len(day_starts):
        return StartsProjection(days=days, reason=TOO_FEW_DAYS)
    start = day_starts[0]
    if unobserved_seconds(gaps, start, end) > MAX_UNOBSERVED_SECONDS:
        return StartsProjection(days=days, reason=OBSERVATION_GAP)
    every = [*runs, *([open_run] if open_run else [])]
    starts = sum(1 for r in every if r.counted and start <= r.start < end)
    per_day = starts / len(day_starts)
    per_year = round(per_day * 365)
    return StartsProjection(
        days=days,
        starts=starts,
        per_day=per_day,
        per_year=per_year,
        field_class=field_class(per_year),
    )


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
