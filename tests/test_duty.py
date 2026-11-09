"""Run time and cycling per outdoor class (health check 4.15), invented values."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.duty import (
    NEVER_CONTINUOUS,
    NO_SHORT_RUNS,
    TOO_FEW_HOURS,
    DutyFigures,
    choose,
    day_classes,
    duty_figures,
    expected_continuous_below,
    runtime_minutes,
    statistics_classes,
)
from custom_components.waermewacht.runs import Run

BERLIN = ZoneInfo("Europe/Berlin")
T0 = datetime(2026, 12, 1, 0, tzinfo=UTC)
H = timedelta(hours=1)


def run(start: datetime, minutes: float, **activity: float) -> Run:
    return Run(
        start=start,
        end=start + timedelta(minutes=minutes),
        activity_seconds=activity or {"heating": minutes * 60},
    )


def test_day_classes_per_hour() -> None:
    # Hour 0 at -1 °C fully heating, hour 1 at -1 °C: 30 min heating and
    # 30 min hot water in one run, hour 2 at 9 °C: two 10-minute starts.
    runs = [
        run(T0, 90, heating=4500, dhw=900),
        run(T0 + 2 * H, 10),
        run(T0 + 2 * H + timedelta(minutes=30), 10),
    ]
    outdoor = {T0: -1.0, T0 + H: -0.5, T0 + 2 * H: 9.0}
    classes = day_classes(runs, None, outdoor, T0 + 3 * H)
    # The first run is 5/6 heating: 60 + 30 minutes at 5/6.
    assert classes["-2"][0] == 2
    assert classes["-2"][1] == pytest.approx(90 * 60 * 5 / 6, abs=1)
    assert classes["-2"][2] == 1
    assert classes["8"] == [1, 1200, 2]


def test_day_classes_open_run_and_hot_water_start() -> None:
    runs = [run(T0, 20, dhw=1200)]  # a hot water run: no heating start
    open_run = Run(start=T0 + H + timedelta(minutes=30))
    classes = day_classes(runs, open_run, {T0: 5.0, T0 + H: 5.0}, T0 + 2 * H)
    assert classes["4"] == [2, 1800, 1]


def test_day_classes_skip_gaps() -> None:
    runs = [run(T0, 120)]
    gap = [(T0 + H + timedelta(minutes=5), T0 + H + timedelta(minutes=30))]
    classes = day_classes(runs, None, {T0: 0.0, T0 + H: 0.0}, T0 + 2 * H, gap)
    assert classes["0"] == [1, 3600, 1]


def test_statistics_classes() -> None:
    hours = {T0 + n * H: 30.0 for n in range(3)}
    starts = {T0: 1.0, T0 + H: 0.0, T0 + 2 * H: 1.0}
    outdoor = {T0: 1.0, T0 + H: 1.5, T0 + 2 * H: 3.0}
    days = statistics_classes(hours, starts, outdoor, BERLIN)
    (day,) = days.values()
    assert day["0"] == [2, 3600, 1]
    assert day["2"] == [1, 1800, 1]


def test_statistics_classes_skips_jumps_and_gaps() -> None:
    days = statistics_classes(
        {T0: 5000.0, T0 + H: -3.0, T0 + 2 * H: 10.0},
        {},
        {T0: 0.0, T0 + H: 0.0},
        BERLIN,
    )
    (day,) = days.values()
    assert day["0"] == [1, 3600, 0]  # capped at one hour, the drop skipped


def test_runtime_minutes() -> None:
    assert runtime_minutes(2.0, "h") == 120
    assert runtime_minutes(30.0, "min") == 30
    assert runtime_minutes(600.0, "s") == 10
    assert runtime_minutes(1.0, "kWh") is None
    assert runtime_minutes(None, "min") is None


def diary_day(day: date, classes: dict[str, list[float]]) -> dict:
    return {"day": day.isoformat(), "classes": classes}


def test_figures_continuous_and_short_runs() -> None:
    first = date(2026, 12, 1)
    # Per day: -6 class 24 h at 95 %, -2 class 24 h at 70 % (4 starts),
    # 10 class 24 h at 10 % with 18 starts (8 min each), 16 class 24 h at
    # 5 % with 9 starts (8 min each).
    classes = {
        "-6": [24, 0.95 * 24 * 3600, 1],
        "-2": [24, 0.70 * 24 * 3600, 4],
        "10": [24, 18 * 8 * 60, 18],
        "16": [24, 9 * 8 * 60, 9],
    }
    figures = duty_figures([diary_day(first, classes)], first, first, short_minutes=10)
    assert figures.continuous_below == -4.0  # upper bound of the -6 class
    assert figures.short_runs_from == 10.0
    rows = {c.lower: c for c in figures.classes}
    assert rows[-2.0].share == pytest.approx(0.7)
    assert rows[-2.0].starts_per_day == 4
    assert rows[10.0].minutes_per_start == pytest.approx(8)
    assert figures.days == 1


def test_figures_skip_cold_classes_where_the_heat_pump_is_off() -> None:
    # Hybrid, bivalent alternative: the boiler alone below -4 °C.
    first = date(2026, 12, 1)
    classes = {
        "-8": [24, 0, 0],
        "-6": [24, 0.02 * 24 * 3600, 1],
        "-2": [24, 0.95 * 24 * 3600, 1],
        "2": [24, 0.6 * 24 * 3600, 5],
    }
    figures = duty_figures([diary_day(first, classes)], first, first, short_minutes=10)
    assert figures.continuous_below == 0.0


def test_figures_reasons() -> None:
    first = date(2026, 12, 1)
    mild = {"4": [24, 0.5 * 24 * 3600, 4]}
    figures = duty_figures([diary_day(first, mild)], first, first, short_minutes=10)
    assert figures.continuous_reason == NEVER_CONTINUOUS
    assert figures.short_reason == NO_SHORT_RUNS
    few = {"4": [10, 3600, 2]}
    figures = duty_figures([diary_day(first, few)], first, first, short_minutes=10)
    assert figures.continuous_reason == TOO_FEW_HOURS
    assert not figures.usable


def test_figures_diary_wins_statistics_fill_in() -> None:
    first = date(2026, 12, 1)
    second = first + timedelta(days=1)
    diary = [diary_day(second, {"0": [24, 24 * 3600, 1]})]
    statistics = {
        first: {"0": [24.0, 24 * 3600.0, 1.0]},
        second: {"0": [24.0, 0.0, 0.0]},  # ignored: the diary has the day
    }
    figures = duty_figures(
        diary, first, second, short_minutes=10, statistics=statistics
    )
    assert figures.days == 2 and figures.days_from_statistics == 1
    assert figures.classes[0].share == pytest.approx(1.0)


def test_expected_continuous_below() -> None:
    # Heating limit 15 °C, 0.1 kW/K, smallest power 1.8 kW: -3 °C.
    assert expected_continuous_below(15.0, -0.1, 1.8) == -3.0
    assert expected_continuous_below(None, -0.1, 1.8) is None
    assert expected_continuous_below(15.0, -0.1, None) is None


def test_choose() -> None:
    empty = DutyFigures([], None, TOO_FEW_HOURS, None, TOO_FEW_HOURS)
    found = DutyFigures([], -4.0, None, None, NO_SHORT_RUNS)
    assert choose(found, empty) == "previous"
    assert choose(empty, found) == "current"
    assert choose(empty, empty) == "previous"
