"""Gas boiler with meter readings by hand: periods, signature, hot water, gas."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from custom_components.waermewacht.gas import NO_SUMMER_DAYS, SUMMER_BASE
from custom_components.waermewacht.readings import (
    NEGATIVE,
    NOT_RISING,
    TOO_FEW_PERIODS,
    Reading,
    add_reading,
    analyse_readings,
    check_reading,
    periods,
    to_kwh,
)

from .test_gas import DHW_PER_DAY, ETA, OUTDOOR, TOTAL, TZ, YEAR_START

END = YEAR_START + timedelta(days=365)


def meter_at(at: datetime) -> float:
    """The test house's gas meter (kWh) at `at` (hour precision)."""
    return 1000.0 + sum(kwh for hour, kwh in TOTAL.items() if hour < at)


def readings_every(
    days: int, *, first: date = YEAR_START
) -> list[tuple[datetime, float]]:
    """A reading every `days` days at 8:00 local time, over the year."""
    result = []
    day = first
    while day <= END:
        at = datetime.combine(day, time(8), tzinfo=TZ).astimezone(UTC)
        result.append((at, meter_at(at)))
        day += timedelta(days=days)
    return result


def test_weekly_readings_give_the_heat_load_of_the_house() -> None:
    result = analyse_readings(
        readings_every(7),
        OUTDOOR,
        TZ,
        YEAR_START,
        END,
        efficiency=ETA,
        design_temp=-12.0,
    )
    load = result.heat_load
    assert load.sufficient
    assert load.slope_kw_per_k == pytest.approx(-0.1, abs=0.003)
    assert load.heating_limit == pytest.approx(15.0, abs=0.5)
    assert load.standard_kw == pytest.approx(3.2, abs=0.1)
    assert result.split.method == SUMMER_BASE
    assert result.split.summer_base_kwh == pytest.approx(DHW_PER_DAY, rel=0.01)
    assert result.dhw_share is not None
    assert result.degree_days.kwh_per_degree_day is not None


def test_monthly_readings_still_find_the_slope() -> None:
    """Months weigh as much as their hours; their means vary less (spread)."""
    result = analyse_readings(
        readings_every(30), OUTDOOR, TZ, YEAR_START, END, efficiency=ETA
    )
    load = result.heat_load
    assert load.slope_kw_per_k == pytest.approx(-0.1, abs=0.005)
    assert len(load.weeks) >= 4


def test_too_few_periods() -> None:
    readings = readings_every(7, first=date(2026, 1, 5))[:4]
    result = analyse_readings(readings, OUTDOOR, TZ, YEAR_START, END, efficiency=ETA)
    assert not result.heat_load.sufficient
    assert TOO_FEW_PERIODS in result.heat_load.reasons
    # Readings only in winter: no summer days, nothing subtracted.
    assert result.split.method == NO_SUMMER_DAYS
    assert result.dhw_share is None


def test_gas_of_the_window_between_readings() -> None:
    """Readings around the window: its gas by linear interpolation; within
    a period the gas is linear in time, so take readings at the bounds."""
    readings = readings_every(7)
    result = analyse_readings(readings, OUTDOOR, TZ, YEAR_START, END, efficiency=ETA)
    first = readings[0][0]
    last = min(
        readings[-1][0], datetime.combine(END, time(0), tzinfo=TZ).astimezone(UTC)
    )
    expected = sum(kwh for hour, kwh in TOTAL.items() if first <= hour < last)
    assert result.gas_kwh == pytest.approx(expected, rel=1e-3)
    assert result.gas_days == 364


def test_periods_carry_the_weather() -> None:
    readings = readings_every(7)[:3]
    found = periods(readings, OUTDOOR, TZ)
    assert len(found) == 2
    assert found[0].days == pytest.approx(7.0)
    assert found[0].coverage == pytest.approx(1.0)
    assert found[0].degree_days > 0


def test_readings_must_rise() -> None:
    at = datetime(2026, 1, 5, 8, tzinfo=UTC)
    readings = [Reading(at, 100.0), Reading(at + timedelta(days=14), 120.0)]
    assert check_reading(readings, at + timedelta(days=7), 110.0) is None
    assert check_reading(readings, at + timedelta(days=7), 99.0) == NOT_RISING
    assert check_reading(readings, at + timedelta(days=7), 121.0) == NOT_RISING
    assert check_reading(readings, at, 90.0) is None  # replaces the first
    assert check_reading(readings, at, -1.0) == NEGATIVE
    added = add_reading(readings, Reading(at + timedelta(days=7), 110.0))
    assert [r.value for r in added] == [100.0, 110.0, 120.0]
    replaced = add_reading(added, Reading(at, 95.0))
    assert [r.value for r in replaced] == [95.0, 110.0, 120.0]


def test_volume_readings_in_kwh() -> None:
    at = datetime(2026, 1, 5, 8, tzinfo=UTC)
    readings = [Reading(at, 1000.0)]
    assert to_kwh(readings, volume=True, calorific_value=11.0, z_number=0.95) == [
        (at, pytest.approx(10450.0))
    ]
    assert to_kwh(readings, volume=False) == [(at, 1000.0)]
    with pytest.raises(ValueError):
        to_kwh(readings, volume=True)
