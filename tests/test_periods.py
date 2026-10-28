"""Period marks: local boundaries, DST days, season, backfill."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.energy import Totals
from custom_components.waermewacht.periods import Period, PeriodMarks, period_start

BERLIN = ZoneInfo("Europe/Berlin")


def heat(kwh: float) -> Totals:
    return Totals({"heat_heating": kwh})


def value(marks: PeriodMarks, period: Period, now_totals: Totals) -> float | None:
    energy = marks.energy(period, now_totals)
    return None if energy is None else energy.values.get("heat_heating", 0.0)


def test_season_start() -> None:
    now = datetime(2026, 3, 10, 12, tzinfo=UTC)
    assert period_start(Period.SEASON, now, BERLIN, 7) == datetime(
        2025, 7, 1, tzinfo=BERLIN
    )
    later = datetime(2026, 7, 1, 0, 30, tzinfo=BERLIN)
    assert period_start(Period.SEASON, later, BERLIN, 7) == datetime(
        2026, 7, 1, tzinfo=BERLIN
    )
    assert period_start(Period.SEASON, now, BERLIN, 1) == datetime(
        2026, 1, 1, tzinfo=BERLIN
    )


@pytest.mark.parametrize(
    ("day", "hours"),
    [(date(2026, 10, 25), 25), (date(2027, 3, 28), 23)],
)
def test_dst_days(day: date, hours: int) -> None:
    """The day of a time change has 25 or 23 hours, each counted once."""
    noon = datetime.combine(day, time(12), tzinfo=BERLIN)
    start = period_start(Period.TODAY, noon, BERLIN, 7)
    next_day = period_start(Period.TODAY, noon + timedelta(days=1), BERLIN, 7)
    assert start and next_day
    assert (next_day - start).total_seconds() == hours * 3600


def test_rollover_moves_today_to_yesterday() -> None:
    marks = PeriodMarks(BERLIN, 7)
    marks.initialize(datetime(2026, 1, 15, 9, tzinfo=UTC), lambda start: Totals())
    assert value(marks, Period.TODAY, heat(4)) == 4
    # 23:00 UTC = midnight in Berlin (winter time).
    assert marks.rollover(datetime(2026, 1, 15, 23, 0, 5, tzinfo=UTC), heat(10))
    assert value(marks, Period.YESTERDAY, heat(11)) == 10
    assert value(marks, Period.TODAY, heat(11)) == 1
    assert value(marks, Period.MONTH, heat(11)) == 11
    assert not marks.rollover(datetime(2026, 1, 15, 23, 30, tzinfo=UTC), heat(12))


def test_rollover_after_a_day_offline_leaves_yesterday_unknown() -> None:
    marks = PeriodMarks(BERLIN, 7)
    marks.initialize(datetime(2026, 1, 15, 9, tzinfo=UTC), lambda start: Totals())
    marks.rollover(datetime(2026, 1, 17, 8, tzinfo=UTC), heat(30))
    assert value(marks, Period.YESTERDAY, heat(31)) is None
    assert value(marks, Period.TODAY, heat(31)) == 1


def test_month_and_season_roll_over() -> None:
    marks = PeriodMarks(BERLIN, 7)
    marks.initialize(datetime(2026, 6, 30, 9, tzinfo=UTC), lambda start: Totals())
    # 1 July 00:00 in Berlin is 22:00 UTC on 30 June (summer time).
    marks.rollover(datetime(2026, 6, 30, 22, 0, 1, tzinfo=UTC), heat(50))
    assert value(marks, Period.SEASON, heat(52)) == 2
    assert value(marks, Period.MONTH, heat(52)) == 2
    assert value(marks, Period.TOTAL, heat(52)) == 52


def test_backfill_before_setup() -> None:
    """Energy between each period start and the setup counts in the period."""
    setup = datetime(2026, 1, 15, 9, tzinfo=UTC)
    starts = {
        datetime(2026, 1, 14, 23, tzinfo=UTC): 8.0,  # today (Berlin midnight)
        datetime(2026, 1, 13, 23, tzinfo=UTC): 30.0,  # yesterday
        datetime(2025, 12, 31, 23, tzinfo=UTC): 300.0,  # month
        datetime(2025, 6, 30, 22, tzinfo=UTC): 3000.0,  # season
    }

    def energy_since(start: datetime | None) -> Totals:
        return heat(5000.0 if start is None else starts[start])

    marks = PeriodMarks(BERLIN, 7)
    marks.initialize(setup, energy_since)
    assert value(marks, Period.TODAY, heat(1)) == 9
    assert value(marks, Period.YESTERDAY, heat(1)) == 22
    assert value(marks, Period.MONTH, heat(1)) == 301
    assert value(marks, Period.SEASON, heat(1)) == 3001
    assert value(marks, Period.TOTAL, heat(1)) == 5001


def test_round_trip() -> None:
    marks = PeriodMarks(BERLIN, 7)
    marks.initialize(datetime(2026, 1, 15, 9, tzinfo=UTC), lambda start: heat(2))
    restored = PeriodMarks(BERLIN, 7)
    restored.restore(marks.as_dict())
    assert restored.marks == marks.marks
    assert restored.starts == marks.starts


def test_season_month_is_stored() -> None:
    """A changed season start is recognised after a restart (and recomputed)."""
    marks = PeriodMarks(BERLIN, 7)
    marks.initialize(datetime(2026, 1, 15, 9, tzinfo=UTC), lambda start: Totals())
    restored = PeriodMarks(BERLIN, 9)
    restored.restore(marks.as_dict())
    assert restored.stored_season_month == 7
    assert restored.season_month == 9


def test_cooling_season_is_the_calendar_year() -> None:
    """Cooling from March to October stays in one season, whatever the
    heating season start (July)."""
    for month in (3, 6, 7, 10):
        now = datetime(2026, month, 15, 12, tzinfo=UTC)
        assert period_start(Period.YEAR, now, BERLIN, 7) == datetime(
            2026, 1, 1, tzinfo=BERLIN
        )


def test_year_rolls_over_at_new_year() -> None:
    marks = PeriodMarks(BERLIN, 7)
    marks.initialize(datetime(2026, 10, 27, 12, tzinfo=UTC), lambda start: Totals())
    marks.rollover(datetime(2026, 12, 31, 12, tzinfo=UTC), heat(30))
    assert not marks.due(datetime(2026, 12, 31, 22, 59, tzinfo=UTC))
    # 23:00 UTC on 31 Dec = midnight in Berlin.
    new_year = datetime(2026, 12, 31, 23, 0, 5, tzinfo=UTC)
    assert marks.due(new_year)
    assert marks.rollover(new_year, heat(40))
    assert not marks.due(new_year)
    assert value(marks, Period.YEAR, heat(43)) == 3


def test_book_late_puts_an_hour_into_its_period() -> None:
    """Hourly statistics (Vaillant): the hour 23-24 of 31 January, booked at
    00:15 on 1 February, counts for yesterday and January, not for today or
    February."""
    marks = PeriodMarks(BERLIN, 7)
    totals = Totals()
    marks.rollover(datetime(2026, 1, 31, 12, tzinfo=UTC), totals)
    marks.rollover(datetime(2026, 2, 1, 0, 15, tzinfo=BERLIN), totals)
    hour = datetime(2026, 1, 31, 23, tzinfo=BERLIN)
    late = Totals({"heat_heating": 2.0})
    totals = totals + late
    marks.book_late(hour, late)
    assert marks.energy(Period.TODAY, totals).values.get("heat_heating", 0.0) == 0.0
    assert marks.energy(Period.MONTH, totals).values.get("heat_heating", 0.0) == 0.0
    assert marks.energy(Period.YESTERDAY, totals).values["heat_heating"] == 2.0
    assert marks.energy(Period.SEASON, totals).values["heat_heating"] == 2.0
