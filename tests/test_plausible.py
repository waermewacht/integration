"""Implausible hours of a meter's long-term statistics (plausible.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.waermewacht.plausible import plausible_hours

H0 = datetime(2026, 11, 8, tzinfo=UTC)


def rows(states: list[float]) -> list[tuple[datetime, float, float]]:
    """Hourly rows as Home Assistant books a total_increasing meter: a fall
    by more than 10 % is a new cycle and adds the whole new reading."""
    result = []
    previous = 0.0
    for n, state in enumerate(states):
        change = state if state < previous * 0.9 else state - previous
        result.append((H0 + timedelta(hours=n), change, state))
        previous = state
    return result


def test_unit_glitch_and_its_fall_back_are_left_out() -> None:
    """A real meter: Wh reported as kWh for one reading (107 -> 109851.5),
    then back (110.131), which Home Assistant books as +110 kWh."""
    data = rows([107.0, 107.5, 109851.5, 110.131, 110.6])
    assert data[2][1] == pytest.approx(109744.0)
    assert data[3][1] == pytest.approx(110.131)
    kept, left_out = plausible_hours(data[1:], 150.0)
    assert left_out == [H0 + timedelta(hours=2), H0 + timedelta(hours=3)]
    assert sum(kept.values()) == pytest.approx(0.5 + 0.469)


def test_fall_back_under_the_bound_is_left_out_too() -> None:
    """A small reading (a new meter): the fall back adds only 7.9 kWh."""
    data = rows([7.0, 7.5, 7500.0, 7.9, 8.2])
    kept, left_out = plausible_hours(data[1:], 75.0)
    assert len(left_out) == 2
    assert sum(kept.values()) == pytest.approx(0.5 + 0.3)


def test_wrong_reading_lasting_hours() -> None:
    """The wrong reading stays for two hours: the fall back is still found."""
    data = rows([7.0, 7.5, 7500.0, 7500.2, 7.9, 8.2])
    kept, left_out = plausible_hours(data[1:], 75.0)
    assert left_out == [H0 + timedelta(hours=2), H0 + timedelta(hours=4)]
    assert sum(kept.values()) == pytest.approx(0.5 + 0.2 + 0.3)


def test_another_channel_and_negative_hours() -> None:
    data = [
        (H0, 1.0, 100.0),
        (H0 + timedelta(hours=1), 661683.0, 661784.0),
        (H0 + timedelta(hours=2), 2.0, 661786.0),  # stays up: no fall back
        (H0 + timedelta(hours=3), -5.0, None),  # sum restarted
    ]
    kept, left_out = plausible_hours(data, 150.0)
    assert kept == {H0: 1.0, H0 + timedelta(hours=2): 2.0}
    assert left_out == [H0 + timedelta(hours=1), H0 + timedelta(hours=3)]


def test_the_first_row_after_home_assistant_was_off_stays() -> None:
    """No rows while Home Assistant was off (48 hours): the first row
    afterwards holds the whole gap, the bound grows with the hours since the
    previous row. One hour later the bound is 75 kWh again."""
    data = [
        (H0, 0.5, 100.0),
        (H0 + timedelta(hours=48), 160.0, 260.0),
        (H0 + timedelta(hours=49), 80.0, 340.0),
        (H0 + timedelta(hours=50), -1.0, 339.0),
        (H0 + timedelta(hours=51), 0.4, 339.4),
    ]
    kept, left_out = plausible_hours(data, 75.0)
    assert left_out == [H0 + timedelta(hours=49), H0 + timedelta(hours=50)]
    assert kept == {
        H0: 0.5,
        H0 + timedelta(hours=48): 160.0,
        H0 + timedelta(hours=51): 0.4,
    }
    # The first row of the series counts as one hour.
    assert plausible_hours(data[1:2], 75.0)[1] == [H0 + timedelta(hours=48)]
    # The glitch and its fall back right after a gap are still left out.
    data = [
        (H0, 0.5, 107.0),
        (H0 + timedelta(hours=48), 109744.5, 109851.5),
        (H0 + timedelta(hours=49), 110.131, 110.131),
        (H0 + timedelta(hours=50), 0.4, 110.531),
    ]
    kept, left_out = plausible_hours(data, 150.0)
    assert left_out == [H0 + timedelta(hours=48), H0 + timedelta(hours=49)]
    assert kept == {H0: 0.5, H0 + timedelta(hours=50): 0.4}


def test_a_day_counter_reset_stays() -> None:
    """A day counter falls every midnight: without a jump before, it is no
    glitch (Home Assistant books the new day's first reading)."""
    data = rows([10.0, 11.0, 0.4, 1.4])
    kept, left_out = plausible_hours(data[1:], 75.0)
    assert left_out == []
    assert sum(kept.values()) == pytest.approx(1.0 + 0.4 + 1.0)
