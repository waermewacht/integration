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


def test_day_counter_rest_of_the_previous_day_after_midnight() -> None:
    """Bosch HomeCom since 1.6.2 (2026-11-09): the previous day's last hour
    arrives at 00:41, today's values from 00:42. Only the rise is booked,
    and the new day starts with the step back."""
    counter = Counter(max_kw=50.0, day_tz=BERLIN)
    counter.update(4.95, local(26, 23, 16))
    late = counter.update(5.25, local(27, 0, 41))
    assert late.event is CounterEvent.LATE
    assert late.delta == pytest.approx(0.30)
    reset = counter.update(0.0, local(27, 0, 42))
    assert reset.event is CounterEvent.RESET
    assert reset.delta == 0
    assert counter.update(0.3, local(27, 1, 43)).delta == pytest.approx(0.3)
    assert counter.update(2.06, local(27, 9)).delta == pytest.approx(1.76)


def test_day_counter_rest_of_the_day_survives_a_restart() -> None:
    counter = Counter(max_kw=50.0, day_tz=BERLIN)
    counter.update(4.95, local(26, 23, 16))
    counter.update(5.25, local(27, 0, 41))
    restored = Counter(max_kw=50.0, day_tz=BERLIN)
    restored.restore(counter.as_dict())
    assert restored.value_day == counter.value_day
    reset = restored.update(0.1, local(27, 0, 50))
    assert reset.event is CounterEvent.RESET
    assert reset.delta == pytest.approx(0.1)


def test_day_counter_rising_after_midnight_books_every_rise_once() -> None:
    """No step back after the late value (a day without energy before, the
    source's first value of today above it): each rise is booked once."""
    counter = Counter(max_kw=50.0, day_tz=BERLIN)
    counter.update(0.0, local(26, 23, 30))
    booked = sum(
        counter.update(value, moment).delta
        for value, moment in (
            (0.2, local(27, 0, 41)),
            (0.5, local(27, 1, 41)),
            (0.9, local(27, 2, 41)),
            (1.4, local(27, 4, 41)),
        )
    )
    assert booked == pytest.approx(1.4)
    # The next day starts anew with its first lower value.
    reset = counter.update(0.2, local(28, 0, 30))
    assert reset.event is CounterEvent.RESET
    assert reset.delta == pytest.approx(0.2)


def test_day_counter_baseline_from_the_wrong_day_heals() -> None:
    """Updated during a day that started wrongly (before 0.4.10): the
    baseline holds yesterday's 5.25, today's values stay below it. That day
    is booked whole the next night; the first day above the day before
    heals it (its rest after midnight is told, the step back starts anew)."""
    counter = Counter(max_kw=50.0, day_tz=BERLIN)
    counter.restore(
        {"last_value": 5.25, "last_time": local(27, 10).isoformat(), "rose_time": None}
    )
    assert counter.update(2.4, local(27, 11)).event is CounterEvent.DIP
    assert counter.update(4.3, local(27, 23, 16)).event is CounterEvent.DIP
    assert counter.update(4.5, local(28, 0, 41)).delta == pytest.approx(4.5)
    assert counter.update(0.0, local(28, 0, 42)).event is CounterEvent.DIP
    assert counter.update(6.0, local(28, 23, 16)).delta == pytest.approx(1.5)
    late = counter.update(6.2, local(29, 0, 41))
    assert late.event is CounterEvent.LATE
    assert counter.update(0.0, local(29, 0, 42)).event is CounterEvent.RESET
    assert counter.update(0.4, local(29, 1, 42)).delta == pytest.approx(0.4)


def test_day_counter_last_reading_follows_dips_and_survives_a_restart() -> None:
    """The stuck check compares with the value read, not the held baseline."""
    counter = Counter(max_kw=50.0, day_tz=BERLIN)
    counter.update(5.25, local(27, 10))
    counter.update(4.3, local(27, 23, 16))
    assert counter.last_value == pytest.approx(5.25)
    assert counter.last_reading == pytest.approx(4.3)
    restored = Counter(max_kw=50.0, day_tz=BERLIN)
    restored.restore(counter.as_dict())
    assert restored.last_reading == pytest.approx(4.3)


def test_previous_day_values_are_never_the_rest_of_a_day() -> None:
    """MELCloud: the new previous-day value after midnight is a whole day."""
    counter = Counter(max_kw=20.0, day_tz=BERLIN, previous_day=True)
    counter.update(10.0, local(26, 23))
    update = counter.update(12.0, local(27, 0, 30))
    assert update.event is CounterEvent.RESET
    assert update.delta == pytest.approx(12.0)


@pytest.mark.parametrize("month", [1, 7])
def test_utc_days_with_a_reset_at_local_midnight(month: int) -> None:
    """ViCare Vitocal 151-A starts its day values at local midnight, the
    template counts UTC days: the values until midnight UTC are dips, the
    first one after it books everything since the reset (one hour late, two
    in summer). Over two days exactly the energy used is booked."""
    zurich = ZoneInfo("Europe/Zurich")
    counter = Counter(max_kw=50.0, day_tz=UTC)
    booked = 0.0
    used = 0.0
    value = 0.0
    start = datetime(2026, month, 14, 12, tzinfo=zurich)
    counter.update(value, start)
    # 1 kWh every 30 minutes, the day value restarting at local midnight.
    for step in range(1, 96):
        moment = start + timedelta(minutes=30 * step)
        if moment.astimezone(zurich).time() == datetime.min.time():
            value = 0.0
        else:
            value += 1.0
            used += 1.0
        booked += counter.update(value, moment).delta
    assert booked == pytest.approx(used)


def test_implausible_jump_is_not_booked() -> None:
    counter = Counter(max_kw=20.0)
    counter.update(100.0, at(0))
    # 1 minute at 20 kW is 0.33 kWh; 50 kWh is a glitch.
    update = counter.update(150.0, at(1))
    assert update.event is CounterEvent.JUMP
    assert update.delta == 0
    assert counter.update(150.1, at(2)).delta == pytest.approx(0.1)


def test_glitch_falling_back_books_the_real_increase() -> None:
    """Observed in Tarifwacht: one reading in Wh as kWh, 107 -> 109851.5 ->
    110.131. The 3.131 kWh across the glitch are real and booked when the
    counter falls back, not lost as jump plus reset."""
    counter = Counter(max_kw=50.0)
    counter.update(107.0, at(0))
    assert counter.update(109851.5, at(1)).event is CounterEvent.JUMP
    update = counter.update(110.131, at(10))
    assert update.event is CounterEvent.RECOVERED
    assert update.delta == pytest.approx(3.131)
    assert counter.jump is None
    assert counter.update(110.2, at(11)).delta == pytest.approx(0.069)


def test_glitch_over_several_readings() -> None:
    """The wrong value stays for some readings and even rises: what was
    booked at the glitch level counts towards the real increase."""
    counter = Counter(max_kw=50.0)
    counter.update(107.0, at(0))
    assert counter.update(109851.5, at(1)).event is CounterEvent.JUMP
    assert counter.update(109851.5, at(5)).delta == 0
    assert counter.update(109852.0, at(20)).delta == pytest.approx(0.5)
    # A second jump keeps the value before the first.
    assert counter.update(209852.0, at(25)).event is CounterEvent.JUMP
    update = counter.update(110.131, at(40))
    assert update.event is CounterEvent.RECOVERED
    assert update.delta == pytest.approx(2.631)  # 3.131 in all


def test_fall_back_below_the_value_before_the_jump_is_a_reset() -> None:
    """A real reset or a new meter: as before, nothing booked."""
    counter = Counter(max_kw=50.0)
    counter.update(107.0, at(0))
    counter.update(109851.5, at(1))
    update = counter.update(5.0, at(10))
    assert update.event is CounterEvent.RESET
    assert update.delta == 0
    assert counter.jump is None


def test_implausible_increase_across_the_glitch_is_a_reset() -> None:
    """More than the heat pump can do since the value before the jump."""
    counter = Counter(max_kw=20.0)
    counter.update(107.0, at(0))
    counter.update(109851.5, at(1))
    update = counter.update(150.0, at(10))  # 43 kWh in 10 minutes
    assert update.event is CounterEvent.RESET
    assert update.delta == 0


def test_dip_after_a_real_jump_is_no_fall_back() -> None:
    """A defrost dip at the new level is a dip, not the glitch ending."""
    counter = Counter(max_kw=20.0)
    counter.update(100.0, at(0))
    assert counter.update(150.0, at(1)).event is CounterEvent.JUMP
    update = counter.update(149.7, at(180))
    assert update.event is CounterEvent.DIP
    assert update.delta == 0
    assert counter.update(150.2, at(181)).delta == pytest.approx(0.2)


def test_pending_jump_survives_a_restart_and_expires() -> None:
    counter = Counter(max_kw=50.0)
    counter.update(107.0, at(0))
    counter.update(109851.5, at(1))
    restored = Counter(max_kw=50.0)
    restored.restore(counter.as_dict())
    update = restored.update(110.131, at(10))
    assert update.event is CounterEvent.RECOVERED
    assert update.delta == pytest.approx(3.131)
    # After a day the jump stands: the fall back is a reset again.
    late = Counter(max_kw=50.0)
    late.restore(counter.as_dict())
    assert late.update(110.131, at(60 * 25)).event is CounterEvent.RESET


def seconds(minutes: float, secs: float) -> datetime:
    return at(minutes) + timedelta(seconds=secs)


# Observed (waermewacht#6): a template adding two Shelly phases (53.48 and
# 39.96 kWh) falls to 0 or to one phase when the Shelly reconnects and climbs
# back in steps within half a second.
DROPOUTS = {
    "to zero": [0.0, 53.48, 93.44],
    "to one phase, then zero": [39.96, 0.0, 53.48, 93.44],
    "to one phase": [53.48, 93.44],
}


@pytest.mark.parametrize("steps", DROPOUTS.values(), ids=DROPOUTS.keys())
def test_dropout_and_climb_back_books_nothing(steps: list[float]) -> None:
    counter = Counter(max_kw=50.0)
    counter.update(93.44, at(0))
    booked = 0.0
    for day in range(3):  # once a day, as observed
        minutes = 60 * 12 * (day + 1)
        for i, value in enumerate(steps):
            booked += counter.update(value, seconds(minutes, 0.1 * i)).delta
        assert counter.jump is None
        assert counter.drop is None
    assert booked == 0
    assert counter.update(93.45, at(60 * 40)).delta == pytest.approx(0.01)


def test_climb_back_books_the_increase_above_the_old_value() -> None:
    """Energy that came in while the source was away is booked once."""
    counter = Counter(max_kw=50.0)
    counter.update(93.44, at(0))
    assert counter.update(0.0, at(10)).event is CounterEvent.RESET
    assert counter.update(53.48, seconds(10, 0.4)).event is CounterEvent.JUMP
    update = counter.update(93.64, seconds(10, 0.5))
    assert update.event is CounterEvent.RETURNED
    assert update.delta == pytest.approx(0.2)
    assert counter.update(93.70, at(12)).delta == pytest.approx(0.06)


def test_climb_back_survives_a_restart() -> None:
    counter = Counter(max_kw=50.0)
    counter.update(93.44, at(0))
    counter.update(0.0, at(10))
    restored = Counter(max_kw=50.0)
    restored.restore(counter.as_dict())
    update = restored.update(93.44, at(11))
    assert update.event is CounterEvent.RETURNED
    assert update.delta == 0


def test_new_meter_rises_from_zero_as_before() -> None:
    """A real reset: rises from 0 are booked, also past the old value."""
    counter = Counter(max_kw=20.0)
    counter.update(30.0, at(0))
    assert counter.update(0.0, at(1)).event is CounterEvent.RESET
    assert counter.update(0.5, at(30)).delta == pytest.approx(0.5)
    assert counter.update(10.0, at(60 * 12)).delta == pytest.approx(9.5)
    update = counter.update(31.0, at(60 * 20))
    assert update.event is None
    assert update.delta == pytest.approx(21.0)
    assert counter.drop is None


def test_climb_back_too_fast_for_the_time_since_is_a_jump() -> None:
    """Far above the old value in seconds: not booked, as any jump."""
    counter = Counter(max_kw=20.0)
    counter.update(93.44, at(0))
    counter.update(0.0, at(1))
    update = counter.update(150.0, seconds(1, 0.4))
    assert update.event is CounterEvent.JUMP
    assert update.delta == 0


def test_whole_kwh_step_is_not_a_jump() -> None:
    counter = Counter(max_kw=20.0)
    counter.update(2104.0, at(0))
    assert counter.update(2105.0, at(0.5)).delta == 1.0


def test_catch_up_after_repeated_value_is_no_jump() -> None:
    """Observed (P1P2MQTT): the source drops out, repeats its old value when
    it comes back and 38 seconds later catches up with the 2 kWh of the 36
    minutes since its last rise."""
    counter = Counter(max_kw=50.0)
    counter.update(50554.0, at(0))
    counter.update(50555.0, at(16))
    assert counter.update(50555.0, at(51.3)).delta == 0
    assert counter.update(50557.0, at(52)).delta == pytest.approx(2.0)


def test_catch_up_counts_at_most_an_hour_back() -> None:
    """A counter idle for weeks (cooling in winter) still rejects a glitch."""
    counter = Counter(max_kw=50.0)
    counter.update(10.0, at(0))
    counter.update(10.0, at(60 * 24 * 30))
    # One hour back allows 50 kW x 1.5 x 1 h + 1 kWh = 76 kWh.
    assert counter.update(100.0, at(60 * 24 * 30 + 1)).event is CounterEvent.JUMP


def test_catch_up_time_survives_a_restart() -> None:
    counter = Counter(max_kw=50.0)
    counter.update(50627.0, at(0))
    restored = Counter(max_kw=50.0)
    restored.restore(counter.as_dict())
    restored.update(50627.0, at(51))
    assert restored.update(50630.0, at(52)).delta == pytest.approx(3.0)


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
