"""Counter increments: resets, dips (noise, defrost), jumps, daily values."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.counter import (
    Counter,
    CounterEvent,
    looks_like_day_counter,
    looks_like_lifetime_counter,
    to_kwh,
)

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


BERLIN = ZoneInfo("Europe/Berlin")


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=BERLIN)


def test_day_counter_books_the_new_day_value() -> None:
    """Bosch HomeCom: back to the hours of the new day at the first fetch."""
    counter = Counter(max_kw=50.0, day_tz=BERLIN)
    counter.update(6.69, local(26, 22, 30))
    assert counter.update(6.74, local(26, 23, 30)).delta == pytest.approx(0.05)
    update = counter.update(0.29, local(27, 0, 30))
    assert update.event is CounterEvent.RESET
    assert update.delta == pytest.approx(0.29)
    assert counter.update(1.29, local(27, 1, 30)).delta == pytest.approx(1.0)


def test_day_counter_new_day_above_the_last_value() -> None:
    """A pause over midnight: the new day's value exceeds yesterday's last
    one, yet all of it belongs to the new day."""
    counter = Counter(max_kw=50.0, day_tz=BERLIN)
    counter.update(0.4, local(26, 18))
    update = counter.update(2.1, local(27, 9))
    assert update.event is CounterEvent.RESET
    assert update.delta == pytest.approx(2.1)


def test_day_counter_step_back_within_the_day_is_a_dip() -> None:
    """Observed at the change from summer time: the doubled hour is
    overwritten and the day value drops mid-day, here by more than 1 kWh."""
    counter = Counter(max_kw=50.0, day_tz=BERLIN)
    counter.update(8.0, local(25, 3, 30))
    assert counter.update(6.5, local(25, 4, 30)).event is CounterEvent.DIP
    assert counter.update(7.9, local(25, 5, 30)).delta == 0
    assert counter.update(8.3, local(25, 6, 30)).delta == pytest.approx(0.3)


def test_day_counter_unchanged_value_keeps_its_day() -> None:
    """An attribute update after midnight repeats yesterday's value: no new day."""
    counter = Counter(max_kw=50.0, day_tz=BERLIN)
    counter.update(5.0, local(26, 23, 10))
    assert counter.update(5.0, local(27, 0, 5)).delta == 0
    update = counter.update(0.2, local(27, 0, 40))
    assert update.event is CounterEvent.RESET
    assert update.delta == pytest.approx(0.2)


def test_day_counter_implausible_value_keeps_the_baseline() -> None:
    counter = Counter(max_kw=20.0, day_tz=BERLIN)
    counter.update(5.0, local(26, 23))
    # 10 minutes after midnight at most 20 kW x 1.5 x 1/6 h + 1 kWh = 6 kWh.
    assert counter.update(90.0, local(27, 0, 10)).event is CounterEvent.JUMP
    update = counter.update(0.3, local(27, 0, 40))
    assert update.event is CounterEvent.RESET
    assert update.delta == pytest.approx(0.3)


def test_day_counter_catch_up_after_a_restart_is_no_jump() -> None:
    """After a restart two fetches come minutes apart, the second with
    two hours of heat: plausible for a day value at 10:02."""
    counter = Counter(max_kw=50.0, day_tz=BERLIN)
    counter.update(20.0, local(27, 9, 58))
    assert counter.update(28.0, local(27, 10, 2)).delta == pytest.approx(8.0)


def test_day_counter_stale_value_dated_by_its_change() -> None:
    """Restart after midnight: yesterday's last fetch (23:59:50) is read at
    00:01 with its own time, so it is yesterday's and not today's baseline."""
    counter = Counter(max_kw=50.0, day_tz=BERLIN)
    counter.update(7.5, local(26, 23, 10))
    assert counter.update(8.0, local(26, 23, 59)).delta == pytest.approx(0.5)
    update = counter.update(0.1, local(27, 0, 40))
    assert update.event is CounterEvent.RESET
    assert update.delta == pytest.approx(0.1)
    assert counter.update(5.0, local(27, 12)).delta == pytest.approx(4.9)


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


def test_previous_day_value_arrives_just_after_midnight() -> None:
    """MELCloud: a whole day of energy right after midnight is plausible."""
    counter = Counter(max_kw=20.0, day_tz=BERLIN, previous_day=True)
    counter.update(30.0, datetime(2026, 1, 14, 0, 20, tzinfo=BERLIN))
    update = counter.update(51.08, datetime(2026, 1, 15, 0, 21, tzinfo=BERLIN))
    assert update.event is CounterEvent.RESET
    assert update.delta == pytest.approx(51.08)
    # A plain day counter would reject it as a jump.
    plain = Counter(max_kw=20.0, day_tz=BERLIN)
    plain.update(30.0, datetime(2026, 1, 14, 0, 20, tzinfo=BERLIN))
    assert plain.update(51.08, datetime(2026, 1, 15, 0, 21, tzinfo=BERLIN)).event is (
        CounterEvent.JUMP
    )


def hourly(start: datetime, values: list[float]) -> list[tuple[datetime, float]]:
    return [(start + timedelta(hours=i), v) for i, v in enumerate(values)]


def test_day_counter_is_told_from_its_hourly_values() -> None:
    """Energy today restarts at the same local hour every day."""
    day = [0.2 * h for h in range(1, 25)]
    midnight = datetime(2026, 1, 12, 0, tzinfo=BERLIN)
    assert looks_like_day_counter(hourly(midnight, day * 3), BERLIN)
    assert not looks_like_day_counter(hourly(midnight, day * 2)[:30], BERLIN)
    # Small days (below 0.1 kWh) say nothing.
    small = [0.05, 0.0] * 24
    assert not looks_like_day_counter(hourly(midnight, small), BERLIN)


def test_day_counter_in_utc_over_the_clock_change() -> None:
    """ViCare-like day values restart at 0 UTC: 02:00 local in summer time,
    01:00 in winter time (change on 25 October 2026)."""
    start = datetime(2026, 10, 23, 0, tzinfo=UTC)
    rows = [(start + timedelta(hours=i), 0.5 * (i % 24 + 1)) for i in range(96)]
    assert looks_like_day_counter(rows, BERLIN)


def test_lifetime_counter_restarting_at_0_is_no_day_counter() -> None:
    """A device restart (ESPHome without restore, Shelly Gen1) at any hour,
    and a stuck spike, are no day counter; falls on the same day neither."""
    start = datetime(2026, 1, 12, 0, tzinfo=BERLIN)
    values = [100.0 + h for h in range(96)]
    values[10:] = [v - 110.0 for v in values[10:]]  # restart at 10:00, day 1
    values[63:] = [v - values[62] for v in values[63:]]  # 15:00, day 3
    values[92] = 99999.0  # spike at 20:00, day 4, back the hour after
    assert not looks_like_day_counter(hourly(start, values), BERLIN)
    same_day = [5.0, 0.0, 5.0, 0.0, 5.0, 0.0]
    assert not looks_like_day_counter(hourly(start, same_day), BERLIN)


def test_day_counter_without_day_tz_books_nothing_after_a_small_day() -> None:
    """Why the setup refuses such counters: the step back is a dip."""
    counter = Counter()
    counter.update(0.8, at(0))
    counter.update(0.1, at(60))  # next day, still below yesterday
    assert counter.update(0.7, at(120)).delta == 0.0


def test_lifetime_counter_in_a_day_value_place() -> None:
    """Rising on several days without a restart: a total counter."""
    start = datetime(2026, 1, 12, 0, tzinfo=BERLIN)
    lifetime = [5000.0 + 0.4 * h for h in range(72)]
    assert looks_like_lifetime_counter(hourly(start, lifetime), BERLIN)
    day = [0.4 * (h % 24 + 1) for h in range(72)]  # energy today
    assert not looks_like_lifetime_counter(hourly(start, day), BERLIN)
    idle = [909.0] * 72  # cooling in winter: says nothing
    assert not looks_like_lifetime_counter(hourly(start, idle), BERLIN)
    one_day = [5000.0] * 48 + [5000.0 + 0.5 * h for h in range(24)]
    assert not looks_like_lifetime_counter(hourly(start, one_day), BERLIN)


def test_previous_day_values_rising_from_day_to_day() -> None:
    """MELCloud: yesterday's total, changed once a day, here upwards; a total
    counter rises in many hours."""
    start = datetime(2026, 1, 12, 0, tzinfo=BERLIN)
    steps = [20.0] * 24 + [25.0] * 24 + [30.0] * 24 + [35.0] * 24
    assert looks_like_lifetime_counter(hourly(start, steps), BERLIN)
    assert not looks_like_lifetime_counter(
        hourly(start, steps), BERLIN, previous_day=True
    )
    lifetime = [5000.0 + 0.4 * h for h in range(72)]
    assert looks_like_lifetime_counter(
        hourly(start, lifetime), BERLIN, previous_day=True
    )
