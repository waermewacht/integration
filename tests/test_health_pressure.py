"""Check 4.16: system pressure dropped (health.pressure_drop)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.health import (
    MIN_PRESSURE_HOURS,
    PRESSURE_DROP_BAR,
    TOO_FEW_DAYS,
    pressure_days,
    pressure_drop,
)

BERLIN = ZoneInfo("Europe/Berlin")
TODAY = date(2026, 11, 14)


def days(values: dict[int, float]) -> dict[date, float]:
    """Day values by days before today (1 = yesterday)."""
    return {TODAY - timedelta(days=back): value for back, value in values.items()}


def steady(level: float, first: int = 97, last: int = 1) -> dict[int, float]:
    return dict.fromkeys(range(last, first + 1), level)


def test_steady_pressure_is_fine() -> None:
    found = pressure_drop(days(steady(1.85)), TODAY)
    assert found.problem is False
    assert found.reason is None
    assert found.evidence["current_bar"] == 1.85
    assert found.evidence["reference_bar"] == 1.85
    assert found.evidence["drop_bar"] == 0


def test_slow_leak_is_found() -> None:
    """0.4 bar lost over 60 days, never refilled."""
    values = steady(1.9, first=97, last=61)
    values |= {back: 1.5 + 0.4 * back / 60 for back in range(1, 61)}
    found = pressure_drop(days(values), TODAY)
    assert found.problem is True
    assert found.evidence["reference_bar"] == 1.9
    assert found.evidence["drop_bar"] >= PRESSURE_DROP_BAR


def test_seasonal_swing_is_no_leak() -> None:
    """Seen at one installation: weekly means 1.98 in summer, 1.80 in winter."""
    values = steady(1.98, first=97, last=40) | steady(1.81, first=39, last=1)
    found = pressure_drop(days(values), TODAY)
    assert found.problem is False
    assert found.evidence["drop_bar"] == pytest.approx(0.17)


def test_refill_after_a_loss_ends_the_finding() -> None:
    values = steady(1.9, first=97, last=40) | steady(1.5, first=39, last=8)
    values |= steady(1.9, first=7, last=1)
    assert pressure_drop(days(values), TODAY).problem is False


def test_refill_that_did_not_hold_counts_from_its_week() -> None:
    """Refilled to 1.90 for four days, back at 1.80 (observed in December):
    the 7-day median of that week stays below the threshold."""
    values = steady(1.80)
    values |= {60: 1.90, 59: 1.89, 58: 1.87, 57: 1.84}
    found = pressure_drop(days(values), TODAY)
    assert found.problem is False
    assert found.evidence["reference_bar"] < 1.9


def test_short_outliers_do_not_count() -> None:
    """Hourly outliers to 0.3 bar barely move a day's mean (hourly means)."""
    hours = {}
    start = datetime(2026, 8, 1, tzinfo=UTC)
    for h in range(24 * 105):
        at = start + timedelta(hours=h)
        hours[at] = 0.3 if h % 500 == 0 else 1.85
    found = pressure_drop(pressure_days(hours, BERLIN), TODAY)
    assert found.problem is False


def test_too_few_days() -> None:
    found = pressure_drop(days(steady(1.85, first=20)), TODAY)
    assert found.problem is None
    assert found.reason == TOO_FEW_DAYS
    found = pressure_drop(days(steady(1.85, first=97, last=10)), TODAY)
    assert found.reason == TOO_FEW_DAYS  # nothing in the last 7 days


def test_pressure_days_need_enough_hours() -> None:
    start = datetime(2026, 11, 1, 23, tzinfo=UTC)  # local midnight
    hours = {start + timedelta(hours=h): 1.8 for h in range(MIN_PRESSURE_HOURS)}
    hours |= {start + timedelta(days=1, hours=h): 1.9 for h in range(3)}
    assert pressure_days(hours, BERLIN) == {date(2026, 11, 2): 1.8}


def test_below_the_template_minimum() -> None:
    """EMS-ESP: below 1.05 bar (pre-pressure 0.75 + 0.3) the check is on even
    without a drop, and with too little history for the trend."""
    found = pressure_drop(days(steady(1.0)), TODAY, min_bar=1.05)
    assert found.problem is True
    assert found.evidence["triggers"] == ["minimum"]
    found = pressure_drop(days(steady(1.0, first=7)), TODAY, min_bar=1.05)
    assert found.problem is True
    assert found.reason is None
    assert pressure_drop(days(steady(1.85)), TODAY, min_bar=1.05).problem is False


def test_drop_and_minimum_together() -> None:
    values = steady(1.4, first=97, last=8) | steady(1.0, first=7, last=1)
    found = pressure_drop(days(values), TODAY, min_bar=1.05)
    assert found.evidence["triggers"] == ["drop", "minimum"]
