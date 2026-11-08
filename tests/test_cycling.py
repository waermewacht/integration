"""Cycling statistics: starts, short runs, pauses, defrosts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.cycling import (
    activity_seconds,
    cycle_stats,
    cycling_triggers,
    field_class,
    max_starts_per_hour,
    prune,
    season_starts_baseline,
    starts_projection,
    unobserved_seconds,
)
from custom_components.waermewacht.periods import local_midnight
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


def test_activity_seconds_split_at_midnight() -> None:
    """A run over midnight adds only its share inside the day (diary)."""
    over_midnight = run(-600, 600)  # 20 h, half of it yesterday
    over_midnight.activity_seconds = {"heating": 19 * 3600, "dhw": 3600}
    within = run(700, 760)
    within.activity_seconds = {"dhw": 3600}
    still_open = run(1380, None)  # 23:00, open at midnight
    still_open.activity_seconds = {"heating": 3600}
    result = activity_seconds(
        [over_midnight, within], still_open, DAY, DAY + timedelta(days=1), at(1500)
    )
    assert result["heating"] == pytest.approx(9.5 * 3600 + 3600 / 2)
    assert result["dhw"] == pytest.approx(1800 + 3600)
    assert sum(result.values()) <= 24 * 3600


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


# Starts per year projected from the last 7 complete days (Fraunhofer field).
MINUTE = timedelta(minutes=1)
BERLIN_DAYS = [DAY + timedelta(days=k) for k in range(7)]  # UTC midnights
END = DAY + timedelta(days=7)


def every(minutes: float, days: int = 7) -> list[Run]:
    """Runs of 10 minutes, one starting every `minutes` from DAY on."""
    count = int(days * 24 * 60 / minutes)
    return [run(i * minutes, i * minutes + 10) for i in range(count)]


def projection(runs: list[Run], **kwargs):
    args = {
        "open_run": None,
        "day_starts": BERLIN_DAYS,
        "end": END,
        "observed_since": DAY - timedelta(days=1),
        "gaps": [],
        **kwargs,
    }
    return starts_projection(runs, **args)


def test_projection_per_day_and_year() -> None:
    result = projection(every(120))  # 12 starts a day
    assert result.starts == 84
    assert result.per_day == pytest.approx(12)
    assert result.per_year == 4380
    assert result.field_class == "typical"
    assert result.reason is None
    assert result.as_attributes() == {
        "starts_per_day_7d": 12.0,
        "starts_per_year_projected": 4380,
        "starts_field_class": "typical",
        "starts_7d_days": 7,
        "starts_7d_observed_hours": 168.0,
        "starts_7d_reason": None,
    }


def test_projection_ignores_today_and_uncounted_runs() -> None:
    runs = [
        *every(24 * 60),  # one a day
        run(-60, -50),  # the day before the window
        run(7 * 24 * 60 + 5, 7 * 24 * 60 + 15),  # today
        Run(start=at(30), end=at(40), counted=False),  # first seen running
    ]
    open_run = Run(start=at(7 * 24 * 60 + 30))  # running now, today
    result = projection(runs, open_run=open_run)
    assert result.starts == 7
    assert result.per_year == 365
    assert result.field_class == "low_third"


@pytest.mark.parametrize(
    ("per_year", "expected"),
    [
        (2000, "low_third"),
        (2001, "typical"),
        (5500, "typical"),
        (5501, "top_10_percent"),
    ],
)
def test_field_classes(per_year: int, expected: str) -> None:
    assert field_class(per_year) == expected


def test_projection_needs_seven_observed_days() -> None:
    result = projection(every(60), observed_since=DAY + timedelta(days=3, hours=2))
    assert result.days == 3  # the days starting at or after the start
    assert result.per_year is None and result.field_class is None
    assert result.reason == "too_few_days"
    assert projection(every(60), observed_since=None).reason == "too_few_days"
    assert projection(every(60), observed_since=DAY).days == 7


def test_projection_without_a_gap() -> None:
    result = projection(every(60))
    assert result.observed_hours == pytest.approx(168)
    assert result.per_day == pytest.approx(24)


def test_projection_over_the_observed_hours() -> None:
    """A cloud outage of 10 hours: 31 starts in the 158 hours observed."""
    hour = timedelta(hours=1)
    runs = [run(i * 300, i * 300 + 10) for i in range(31)]  # every 5 hours
    gap = [(DAY + 155 * hour, DAY + 165 * hour)]  # after the last start
    result = projection(runs, gaps=gap)
    assert result.reason is None
    assert result.starts == 31
    assert result.observed_hours == pytest.approx(158)
    assert result.per_day == pytest.approx(31 / 158 * 24)
    assert result.per_year == 1719
    assert result.as_attributes()["starts_7d_observed_hours"] == 158.0


def test_projection_needs_six_observed_days() -> None:
    hour = timedelta(hours=1)
    result = projection(every(60), gaps=[(DAY + 50 * hour, DAY + 80 * hour)])
    assert result.reason == "too_few_hours"
    assert result.observed_hours == pytest.approx(138)
    assert result.days == 7 and result.per_year is None
    assert result.field_class is None
    # Exactly 6 days observed is enough.
    enough = projection(every(60), gaps=[(DAY + 50 * hour, DAY + 74 * hour)])
    assert enough.reason is None
    assert enough.observed_hours == pytest.approx(144)


def test_gap_across_a_day_boundary_and_the_window_edges() -> None:
    hour = timedelta(hours=1)
    # 20:00 to 04:00 the next day: 8 hours, both days lose a part.
    across = projection(every(60), gaps=[(DAY + 44 * hour, DAY + 52 * hour)])
    assert across.observed_hours == pytest.approx(160)
    # Gaps reaching beyond the window count only inside it, overlaps once.
    edges = projection(
        every(60),
        gaps=[
            (DAY - 5 * hour, DAY + 2 * hour),
            (DAY + hour, DAY + 3 * hour),
            (END - hour, END + 5 * hour),
        ],
    )
    assert edges.observed_hours == pytest.approx(164)
    assert unobserved_seconds(
        [(DAY, DAY + hour), (DAY + 30 * MINUTE, DAY + 90 * MINUTE)], DAY, END
    ) == pytest.approx(90 * 60)


def test_projection_over_a_dst_change() -> None:
    """A local day of 23 hours is still one day of the window; per day
    counts over the 167 hours observed."""
    berlin = ZoneInfo("Europe/Berlin")
    days = [
        local_midnight(date(2026, 3, 25) + timedelta(days=k), berlin) for k in range(7)
    ]
    end = local_midnight(date(2026, 4, 1), berlin)
    assert (end - days[0]) == timedelta(days=7, hours=-1)
    runs = [Run(start=d + timedelta(hours=1), end=d + timedelta(hours=2)) for d in days]
    result = starts_projection(runs, None, days, end, days[0], [])
    assert result.observed_hours == pytest.approx(167)
    assert result.per_day == pytest.approx(7 / 167 * 24)


def test_prune_drops_old_gaps() -> None:
    gaps = [(at(0), at(10)), (at(100), at(200))]
    prune([], [], at(50), gaps)
    assert gaps == [(at(100), at(200))]


def test_cycling_triggers() -> None:
    def triggers(per_hour: int, critical: int, starts: int, per_day=None):
        return cycling_triggers(
            per_hour,
            critical,
            starts,
            starts_per_hour=3,
            critical_per_day=3,
            starts_per_day=per_day,
        )

    assert triggers(3, 2, 30) == []  # no limit per day: 30 starts are fine
    assert triggers(4, 0, 4) == ["starts_per_hour"]
    assert triggers(1, 3, 5) == ["critical_runs"]
    # The limit per day, for an on/off heat pump: more than 4 starts in 24 h.
    assert triggers(1, 0, 4, per_day=4) == []
    assert triggers(1, 0, 5, per_day=4) == ["starts_per_day"]
    assert triggers(4, 3, 5, per_day=4) == [
        "starts_per_hour",
        "critical_runs",
        "starts_per_day",
    ]
