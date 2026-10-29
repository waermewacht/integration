"""Cycling statistics: starts, short runs, pauses, defrosts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.waermewacht.cycling import (
    cycle_stats,
    max_starts_per_hour,
    prune,
    season_starts_baseline,
)
from custom_components.waermewacht.runs import Defrost, Run

DAY = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
SHORT, CRITICAL = 600.0, 360.0


def at(minutes: float) -> datetime:
    return DAY + timedelta(minutes=minutes)


def run(start: float, end: float | None, **kwargs: bool) -> Run:
    return Run(start=at(start), end=at(end) if end is not None else None, **kwargs)


def stats(runs: list[Run], open_run: Run | None = None, now: float = 24 * 60):
    return cycle_stats(
        runs,
        open_run,
        [],
        None,
        DAY,
        DAY + timedelta(days=1),
        at(now),
        short_seconds=SHORT,
        critical_seconds=CRITICAL,
    )


def test_short_run_thresholds() -> None:
    """6 min is short and critical? No: critical is under 6 min. 11 min is neither."""
    result = stats([run(60, 66), run(120, 131), run(200, 205)])
    assert result.starts == 3
    assert result.short_runs == 2  # 6 and 5 minutes
    assert result.critical_runs == 1  # 5 minutes
    assert result.seconds_per_run == pytest.approx((6 + 11 + 5) * 60 / 3)


def test_shortest_pause() -> None:
    result = stats([run(60, 100), run(130, 170), run(175, 200)])
    assert result.shortest_pause_seconds == 5 * 60


def test_open_run_counts_as_start_and_runtime() -> None:
    result = stats([run(60, 100)], open_run=run(600, None), now=630)
    assert result.starts == 2
    assert result.runtime_seconds == (40 + 30) * 60
    assert result.finished_runs == 1
    assert result.shortest_pause_seconds == 500 * 60


def test_run_over_midnight_splits_runtime() -> None:
    result = stats([run(-30, 30)])
    assert result.starts == 0  # started yesterday
    assert result.runtime_seconds == 30 * 60
    assert result.finished_runs == 1  # ended today


def test_uncounted_and_uncertain_runs_are_left_out() -> None:
    result = stats(
        [run(60, 63, counted=False), run(120, 123, uncertain=True), run(200, 203)]
    )
    assert result.starts == 2  # the one already running when first seen is none
    assert result.short_runs == 1
    assert result.shortest_pause_seconds is None


def test_defrosts() -> None:
    result = cycle_stats(
        [],
        None,
        [Defrost(at(100), at(103.5))],
        Defrost(at(300), None),
        DAY,
        DAY + timedelta(days=1),
        at(302),
        short_seconds=SHORT,
        critical_seconds=CRITICAL,
    )
    assert result.defrosts == 2
    assert result.defrost_seconds == pytest.approx((3.5 + 2) * 60)


def test_max_starts_per_hour() -> None:
    runs = [run(m, m + 3) for m in (0, 10, 20, 50, 70, 200)]
    assert max_starts_per_hour(runs, None, DAY, DAY + timedelta(days=1)) == 4


def test_prune() -> None:
    runs = [run(0, 10), run(100, 110)]
    defrosts = [Defrost(at(5), at(8)), Defrost(at(105), None)]
    prune(runs, defrosts, at(50))
    assert [r.start for r in runs] == [at(100)]
    assert [d.start for d in defrosts] == [at(105)]


SEASON = datetime(2026, 7, 1, tzinfo=UTC)


def test_season_starts_from_the_statistics() -> None:
    """A counter with statistics: their value, the kept one stays as it is."""
    stats = (2000, SEASON)
    assert season_starts_baseline(stats, None, 2090, SEASON, DAY) == (stats, None)


def test_season_starts_without_statistics() -> None:
    """No statistics (P1P2MQTT, no state class): from the first value seen,
    kept until the next season starts."""
    first = datetime(2026, 10, 29, 11, 0, tzinfo=UTC)
    later = first + timedelta(days=3)
    baseline, seen = season_starts_baseline(None, None, 1806, SEASON, first)
    assert baseline == seen == (1806, first)
    assert season_starts_baseline(None, seen, 1812, SEASON, later) == (seen, seen)
    # Next season: the value then.
    nxt = datetime(2027, 7, 1, tzinfo=UTC)
    then = nxt + timedelta(hours=1)
    assert season_starts_baseline(None, seen, 2500, nxt, then) == (
        (2500, then),
        (2500, then),
    )
    # No value yet (unavailable): nothing.
    assert season_starts_baseline(None, None, None, SEASON, first) == (None, None)
