"""Cycling statistics: starts, short runs, pauses, defrosts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.cycling import (
    METHOD_7_DAYS,
    METHOD_12_MONTHS,
    METHOD_HEATING_DAYS,
    activity_seconds,
    cycle_stats,
    cycling_triggers,
    diary_starts,
    field_class,
    heating_days_per_year,
    max_starts_per_hour,
    prune,
    season_starts_baseline,
    starts_per_year,
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
    assert result.heating_by_day == (12,) * 7  # no activity: all heating
    assert result.window_hours == pytest.approx(168)
    assert result.as_attributes() == {
        "starts_per_day_7d": 12.0,
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


# Starts per year: counted over 12 months, with heating days, from 7 days.


def dhw_run(start: float) -> Run:
    return Run(start=at(start), end=at(start + 30), activity_seconds={"dhw": 1800.0})


def heating_week() -> list[Run]:
    """12 heating starts a day plus one hot water charge a day."""
    return [*every(120), *(dhw_run(d * 1440 + 605) for d in range(7))]


def test_heating_starts_per_day_of_the_week() -> None:
    result = projection(heating_week())
    assert result.starts == 7 * 13
    assert result.heating_by_day == (12,) * 7


def test_starts_per_year_counted_over_12_months() -> None:
    since = DAY - timedelta(days=358)
    result = starts_per_year(
        projection(heating_week()), last_12_months=(1250, since), heating_days=200
    )
    assert result.value == 1250
    assert result.method == METHOD_12_MONTHS
    assert result.field_class == "low_third"
    attributes = result.as_attributes()
    assert attributes["since"] == since.isoformat()
    assert attributes["method"] == METHOD_12_MONTHS
    assert attributes["starts_per_day_7d"] == 13.0


def test_starts_per_year_with_heating_days() -> None:
    """Five heating days in the week: 84 heating starts / 5 heating days x
    200 heating days + 1 other start a day x 365."""
    result = starts_per_year(
        projection(heating_week()),
        heating_days=200,
        heating_limit=15.0,
        week_outdoor=[2.0, 4.0, 16.0, 6.0, 17.0, 8.0, 10.0],
        split=True,
    )
    assert result.method == METHOD_HEATING_DAYS
    assert result.heating_per_day == pytest.approx(84 / 5)
    assert result.other_per_day == pytest.approx(1.0)
    assert result.value == round(84 / 5 * 200 + 365)
    assert result.week_heating_days == 5
    assert result.as_attributes()["heating_days_per_year"] == 200


def test_heating_days_scale_the_observed_hours() -> None:
    """A gap of 10 hours: the starts seen count for the whole week."""
    hour = timedelta(hours=1)
    week = projection(every(120), gaps=[(DAY + 2 * hour, DAY + 12 * hour)])
    result = starts_per_year(
        week,
        heating_days=100,
        heating_limit=15.0,
        week_outdoor=[0.0] * 7,
        split=True,
    )
    assert week.starts is not None
    assert result.heating_per_day == pytest.approx(week.starts * 168 / 158 / 7)
    assert result.other_per_day == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"split": False}, "runs without an activity"),
        ({"heating_days": None}, "no year of outdoor temperatures"),
        ({"heating_limit": None}, "no heat load"),
        ({"week_outdoor": [2.0] * 6 + [None]}, "a day without outdoor mean"),
        ({"week_outdoor": [2.0, 3.0] + [18.0] * 5}, "two heating days only"),
    ],
)
def test_starts_per_year_falls_back_to_7_days(kwargs: dict, why: str) -> None:
    args = {
        "heating_days": 200,
        "heating_limit": 15.0,
        "week_outdoor": [2.0] * 7,
        "split": True,
        **kwargs,
    }
    week = projection(heating_week())
    result = starts_per_year(week, **args)
    assert result.method == METHOD_7_DAYS, why
    assert result.value == week.per_year == 13 * 365


def test_starts_per_year_unknown_without_a_week() -> None:
    week = projection(every(60), observed_since=None)
    result = starts_per_year(week, heating_days=200, split=True)
    assert result.value is None and result.method is None
    assert result.field_class is None
    assert result.as_attributes()["starts_7d_reason"] == "too_few_days"


def test_heating_days_per_year() -> None:
    berlin = ZoneInfo("Europe/Berlin")
    first = date(2025, 11, 1)
    end = first + timedelta(days=365)
    outdoor = {}
    for k in range(365):
        midnight = local_midnight(first + timedelta(days=k), berlin)
        mean = 5.0 if k < 200 else 20.0
        for h in range(24):
            outdoor[midnight + timedelta(hours=h)] = mean
    assert heating_days_per_year(outdoor, berlin, first, end, 15.0) == 200

    # The first 20 days lose 5 hours each (too few): the rest scales to a year.
    def kept(hour: datetime) -> bool:
        local = hour.astimezone(berlin)
        return local.hour >= 5 or local.date() >= first + timedelta(days=20)

    thin = {h: v for h, v in outdoor.items() if kept(h)}
    assert heating_days_per_year(thin, berlin, first, end, 15.0) == round(
        180 * 365 / 345
    )
    # Too short a record: no heating days.
    cut = local_midnight(first + timedelta(days=300), berlin)
    short = {h: v for h, v in outdoor.items() if h < cut}
    assert heating_days_per_year(short, berlin, first, end, 15.0) is None


def test_diary_starts_over_a_year() -> None:
    first = date(2025, 11, 13)
    diary = [
        {"day": (first + timedelta(days=k)).isoformat(), "starts": 3}
        for k in range(365)
    ]
    last = first + timedelta(days=364)
    assert diary_starts(diary, first, last) == 3 * 365
    # A few days missing: scaled to the whole year.
    assert diary_starts(diary[:300] + diary[335:], first, last) == 3 * 365
    # Fewer than MIN_YEAR_DAYS: unknown.
    assert diary_starts(diary[:300], first, last) is None
