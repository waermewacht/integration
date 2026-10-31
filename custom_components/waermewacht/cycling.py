"""Cycling statistics over finished and open runs. Pure Python, no HA imports.

Definitions (docs/ENTWICKLUNG.md, section 3):
- A start is a counted run (its start was observed) beginning in the window.
- Short and critical runs, run time per start and pauses only use finished
  runs without observation gaps; a run counts for the window it ended in.
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


def prune(runs: list[Run], defrosts: list[Defrost], keep_from: datetime) -> None:
    """Drop runs and defrosts that ended before `keep_from` (in place)."""
    runs[:] = [r for r in runs if r.end is None or r.end >= keep_from]
    defrosts[:] = [d for d in defrosts if d.end is None or d.end >= keep_from]
