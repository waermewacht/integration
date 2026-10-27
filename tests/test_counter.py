"""Counter increments: resets, dips (noise, defrost), jumps, daily values."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.waermewacht.counter import Counter, CounterEvent, to_kwh

T0 = datetime(2026, 1, 15, 6, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_first_reading_is_baseline() -> None:
    counter = Counter()
    update = counter.update(1000.0, at(0))
    assert update.event is CounterEvent.FIRST
    assert update.delta == 0
    assert counter.update(1000.25, at(10)).delta == pytest.approx(0.25)


def test_small_step_back_is_a_dip_and_not_booked_twice() -> None:
    """Observed: a heat counter went back by 0.02 kWh and up again."""
    counter = Counter()
    counter.update(500.00, at(0))
    assert counter.update(499.98, at(1)).event is CounterEvent.DIP
    assert counter.update(500.00, at(2)).delta == 0
    assert counter.update(500.05, at(3)).delta == pytest.approx(0.05)


def test_defrost_dip_books_net_heat() -> None:
    """Observed pattern: during a defrost the heat counter falls by ~0.3 kWh in
    steps of 0.04-0.06 every 30 s, then rises again. Only heat above the old
    maximum is new: the dip and its recovery cancel out (net heat)."""
    counter = Counter()
    counter.update(1000.00, at(0))
    value, booked = 1000.00, 0.0
    for _ in range(6):  # -0.30 in total
        value = round(value - 0.05, 2)
        update = counter.update(value, at(1))
        assert update.event is CounterEvent.DIP
        booked += update.delta
    for step in (0.10, 0.10, 0.10, 0.10, 0.10):  # back to 1000.20
        value = round(value + step, 2)
        booked += counter.update(value, at(5)).delta
    assert booked == pytest.approx(0.20)


def test_reset_to_zero_books_nothing() -> None:
    counter = Counter()
    counter.update(2104.0, at(0))
    update = counter.update(0.0, at(1))
    assert update.event is CounterEvent.RESET
    assert update.delta == 0
    assert counter.update(0.4, at(10)).delta == pytest.approx(0.4)


def test_daily_counter_books_the_new_day_value() -> None:
    """Day values reset at midnight; the first value of the new day is energy."""
    counter = Counter(daily_reset=True)
    counter.update(6.69, at(0))
    assert counter.update(6.74, at(60)).delta == pytest.approx(0.05)
    update = counter.update(0.29, at(120))
    assert update.event is CounterEvent.RESET
    assert update.delta == pytest.approx(0.29)


def test_implausible_jump_is_not_booked() -> None:
    counter = Counter(max_kw=20.0)
    counter.update(100.0, at(0))
    # 1 minute at 20 kW is 0.33 kWh; 50 kWh is a glitch.
    update = counter.update(150.0, at(1))
    assert update.event is CounterEvent.JUMP
    assert update.delta == 0
    assert counter.update(150.1, at(2)).delta == pytest.approx(0.1)


def test_whole_kwh_step_is_not_a_jump() -> None:
    counter = Counter(max_kw=20.0)
    counter.update(2104.0, at(0))
    assert counter.update(2105.0, at(0.5)).delta == 1.0


def test_long_gap_allows_large_increase() -> None:
    """Home Assistant off for 10 h: the energy of that time arrives at once."""
    counter = Counter(max_kw=20.0)
    counter.update(100.0, at(0))
    assert counter.update(160.0, at(600)).delta == pytest.approx(60.0)


def test_out_of_order_reading_is_ignored() -> None:
    counter = Counter()
    counter.update(10.0, at(5))
    assert counter.update(9.0, at(4)).delta == 0
    assert counter.last_value == 10.0


def test_round_trip() -> None:
    counter = Counter()
    counter.update(12.5, at(0))
    restored = Counter()
    restored.restore(counter.as_dict())
    assert restored.update(13.0, at(1)).delta == pytest.approx(0.5)


def test_units() -> None:
    assert to_kwh(1500, "Wh") == 1.5
    assert to_kwh(1.5, "MWh") == 1500
    with pytest.raises(KeyError):
        to_kwh(1, "J")
