"""Degree days: G20/15, single base, local days with DST, missing days.

All values are made up.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.degree_days import (
    G20_15,
    DegreeDayBase,
    daily_degree_days,
    degree_days,
)
from custom_components.waermewacht.energy import Kind, Totals
from custom_components.waermewacht.model import Mode
from custom_components.waermewacht.periods import local_midnight

BERLIN = ZoneInfo("Europe/Berlin")


def _hours(day: date) -> list[datetime]:
    """UTC hour starts of a local Berlin day (23, 24 or 25)."""
    start = local_midnight(day, BERLIN)
    end = local_midnight(day + timedelta(days=1), BERLIN)
    count = int((end - start).total_seconds() // 3600)
    return [start + timedelta(hours=n) for n in range(count)]


def heating(kwh: float, *, dhw: float = 0.0) -> Totals:
    totals = Totals()
    totals.add(Kind.HEAT, Mode.HEATING, kwh)
    totals.add(Kind.HEAT, Mode.DHW, dhw)
    totals.add(Kind.STANDBY, Mode.HEATING, 0.02)
    return totals


def build(
    days: dict[date, tuple[float, float]],
) -> tuple[dict[datetime, Totals], dict[datetime, float]]:
    """Day → (outdoor °C every hour, heating kWh every hour)."""
    hours: dict[datetime, Totals] = {}
    outdoor: dict[datetime, float] = {}
    for day, (temp, kwh) in days.items():
        for hour in _hours(day):
            outdoor[hour] = temp
            hours[hour] = heating(kwh)
    return hours, outdoor


def test_base_values() -> None:
    assert G20_15.day_value(5.0) == 15.0
    assert G20_15.day_value(14.9) == pytest.approx(5.1)
    assert G20_15.day_value(15.0) == 0.0  # not below the limit
    single = DegreeDayBase.single(15.0)
    assert single.day_value(10.0) == 5.0
    assert single.day_value(15.0) == 0.0
    with pytest.raises(ValueError):
        DegreeDayBase(15.0, 20.0)


def test_period_sum_and_heat_per_degree_day() -> None:
    hours, outdoor = build(
        {
            date(2026, 1, 10): (5.0, 1.0),
            date(2026, 1, 11): (16.0, 0.5),  # above the limit: 0 Kd, heat counts
            date(2026, 1, 12): (0.0, 1.0),
        }
    )
    result = degree_days(hours, outdoor, BERLIN, date(2026, 1, 10), date(2026, 1, 13))
    assert result.degree_days == pytest.approx(15 + 0 + 20)
    assert result.days_counted == 3
    assert result.days_missing == 0
    assert result.days_without_heating == ()
    assert result.heating_kwh == pytest.approx(24 + 12 + 24)
    assert result.kwh_per_degree_day == pytest.approx(60 / 35)


def test_single_base() -> None:
    hours, outdoor = build({date(2026, 1, 10): (5.0, 1.0)})
    base = DegreeDayBase.single(15.0)
    result = degree_days(
        hours, outdoor, BERLIN, date(2026, 1, 10), date(2026, 1, 11), base
    )
    assert result.degree_days == pytest.approx(10.0)
    assert result.base == base
    assert result.kwh_per_degree_day == pytest.approx(2.4)


@pytest.mark.parametrize(
    ("day", "count"),
    [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25), (date(2026, 10, 26), 24)],
)
def test_dst_days_use_real_hours(day: date, count: int) -> None:
    hours, outdoor = build({day: (4.0, 1.0)})
    valid, missing, _ = daily_degree_days(
        hours, outdoor, BERLIN, day, day + timedelta(days=1)
    )
    assert missing == []
    assert len(valid) == 1
    assert valid[0].hours == count
    assert valid[0].heating_kwh == pytest.approx(count)
    assert valid[0].degree_days == pytest.approx(16.0)


def test_hour_belongs_to_local_day() -> None:
    # 2026-10-24 22:00 UTC is midnight of 25 October in Berlin (CEST).
    first = datetime(2026, 10, 24, 22, tzinfo=UTC)
    assert _hours(date(2026, 10, 25))[0] == first
    hours, outdoor = build({date(2026, 10, 25): (10.0, 0.0)})
    outdoor[first] = -10.0  # 25 values: mean (24 × 10 − 10) / 25 = 9.2
    result = degree_days(hours, outdoor, BERLIN, date(2026, 10, 25), date(2026, 10, 26))
    assert result.degree_days == pytest.approx(20 - 9.2)


def test_missing_hours_and_implausible_values() -> None:
    day1, day2, day3 = date(2026, 2, 1), date(2026, 2, 2), date(2026, 2, 3)
    hours, outdoor = build({day1: (2.0, 1.0), day2: (2.0, 1.0), day3: (2.0, 1.0)})
    # Day 1: only 19 hourly values left -> missing.
    for hour in _hours(day1)[:5]:
        del outdoor[hour]
    # Day 2: exactly 20 valid values; four implausible ones are discarded.
    for hour, bad in zip(
        _hours(day2)[:4], (-40.0, 50.0, float("nan"), float("inf")), strict=True
    ):
        outdoor[hour] = bad
    # Day 3: implausible values do not shift the mean either.
    outdoor[_hours(day3)[0]] = 44.0  # still plausible (sun on the sensor)

    result = degree_days(hours, outdoor, BERLIN, day1, date(2026, 2, 5))
    assert result.missing_days == (day1, date(2026, 2, 4))  # 4 Feb has no data
    assert result.days_missing == 2
    assert result.days_counted == 2
    mean3 = (23 * 2.0 + 44.0) / 24
    assert result.degree_days == pytest.approx(18.0 + (20 - mean3))
    assert result.heating_kwh == pytest.approx(48.0)
    assert result.heating_kwh_missing_days == pytest.approx(24.0)


def test_days_with_degree_days_but_no_heating() -> None:
    day1, day2, day3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)
    hours, outdoor = build({day1: (12.0, 0.0), day2: (12.0, 0.5), day3: (18.0, 0.0)})
    # Hot water only on day 1: still no heating.
    hours[_hours(day1)[7]] = heating(0.0, dhw=3.0)
    result = degree_days(hours, outdoor, BERLIN, day1, date(2026, 10, 4))
    assert result.days_without_heating == (day1,)  # day 3 has no degree days
    assert result.degree_days == pytest.approx(16.0)
    assert result.heating_kwh == pytest.approx(12.0)
    # 16 Kd is above the minimum.
    assert result.kwh_per_degree_day == pytest.approx(12 / 16)


def test_heat_per_degree_day_unknown_below_minimum() -> None:
    warm = date(2026, 7, 1)
    hours, outdoor = build({warm: (22.0, 0.0)})
    result = degree_days(hours, outdoor, BERLIN, warm, date(2026, 7, 2))
    assert result.degree_days == 0.0
    assert result.kwh_per_degree_day is None

    mild = date(2026, 9, 20)
    hours, outdoor = build({mild: (14.0, 0.2)})  # 6 Kd < 10
    result = degree_days(hours, outdoor, BERLIN, mild, date(2026, 9, 21))
    assert result.degree_days == pytest.approx(6.0)
    assert result.kwh_per_degree_day is None
    result = degree_days(
        hours, outdoor, BERLIN, mild, date(2026, 9, 21), min_degree_days=5.0
    )
    assert result.kwh_per_degree_day == pytest.approx(4.8 / 6)


def test_hours_outside_the_period_are_ignored() -> None:
    hours, outdoor = build(
        {date(2026, 1, 9): (-5.0, 2.0), date(2026, 1, 10): (5.0, 1.0)}
    )
    result = degree_days(hours, outdoor, BERLIN, date(2026, 1, 10), date(2026, 1, 11))
    assert result.days_counted == 1
    assert result.degree_days == pytest.approx(15.0)
    assert result.heating_kwh == pytest.approx(24.0)
