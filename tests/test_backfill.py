"""Backfill from hourly statistics: standby rule and backup heater."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.backfill import (
    balance_groups,
    by_hour,
    coarse,
    common_hours,
    compare_on_source,
    drop_together,
    energy_between,
    hour_totals,
)
from custom_components.waermewacht.curve import daily_samples
from custom_components.waermewacht.energy import Kind, Totals
from custom_components.waermewacht.health import (
    BASIS_OUTDOOR,
    baseline_drop,
    outdoor_days,
)
from custom_components.waermewacht.model import Mode, Signal, has_elec
from custom_components.waermewacht.plausible import plausible_hours

H0 = datetime(2026, 7, 15, 0, tzinfo=UTC)


def hour(n: int) -> datetime:
    return H0 + timedelta(hours=n)


def test_electricity_without_heat_is_standby() -> None:
    """Summer: the heating counter grows by ~25 W while nothing heats."""
    t = hour_totals({Signal.HEAT_HEATING: 0.0, Signal.ELEC_HEATING: 0.03})
    assert t.get(Kind.STANDBY, Mode.HEATING) == pytest.approx(0.03)
    assert t.get(Kind.ELEC, Mode.HEATING) == 0


def test_electricity_with_heat_is_running() -> None:
    t = hour_totals({Signal.HEAT_DHW: 3.0, Signal.ELEC_DHW: 0.8})
    assert t.get(Kind.ELEC, Mode.DHW) == pytest.approx(0.8)
    assert t.get(Kind.HEAT, Mode.DHW) == pytest.approx(3.0)


def test_aux_total_goes_to_mode_with_most_heat() -> None:
    t = hour_totals(
        {Signal.HEAT_DHW: 2.0, Signal.HEAT_HEATING: 0.5, Signal.AUX_TOTAL: 1.5}
    )
    assert t.get(Kind.AUX, Mode.DHW) == pytest.approx(1.5)
    t = hour_totals({Signal.AUX_TOTAL: 1.0})
    assert t.get(Kind.AUX, Mode.HEATING) == pytest.approx(1.0)


def test_elec_total_split_by_heat() -> None:
    """One compressor meter for all modes (Waterkotte): split by the heat."""
    t = hour_totals(
        {Signal.HEAT_HEATING: 3.0, Signal.HEAT_DHW: 1.0, Signal.ELEC_TOTAL: 1.2}
    )
    assert t.get(Kind.ELEC, Mode.HEATING) == pytest.approx(0.9)
    assert t.get(Kind.ELEC, Mode.DHW) == pytest.approx(0.3)
    assert t.standby() == 0
    t = hour_totals({Signal.HEAT_HEATING: 0.0, Signal.ELEC_TOTAL: 0.03})
    assert t.get(Kind.STANDBY, Mode.HEATING) == pytest.approx(0.03)
    assert t.electricity(*Mode) == 0


def test_has_elec() -> None:
    entities = {Signal.HEAT_HEATING, Signal.HEAT_DHW, Signal.ELEC_TOTAL}
    assert has_elec(entities, Mode.HEATING)
    assert has_elec(entities, Mode.DHW)
    assert not has_elec(entities, Mode.COOLING)
    assert has_elec({Signal.ELEC_TOTAL}, Mode.HEATING)
    assert has_elec({Signal.ELEC_COOLING}, Mode.COOLING)
    assert not has_elec({Signal.HEAT_COOLING}, Mode.COOLING)


def test_energy_between() -> None:
    hourly = {
        Signal.HEAT_HEATING: {hour(0): 0.0, hour(1): 2.01, hour(2): 0.99},
        Signal.ELEC_HEATING: {hour(0): 0.02, hour(1): 0.6, hour(2): 0.3},
    }
    t = energy_between(hourly, hour(1), hour(3))
    assert t.get(Kind.HEAT, Mode.HEATING) == pytest.approx(3.0)
    assert t.get(Kind.ELEC, Mode.HEATING) == pytest.approx(0.9)
    assert t.get(Kind.STANDBY, Mode.HEATING) == 0
    everything = energy_between(hourly, None, hour(3))
    assert everything.get(Kind.STANDBY, Mode.HEATING) == pytest.approx(0.02)


def test_electricity_without_heat_counter_is_running() -> None:
    """ViCare: no heat counter, so no standby can be told."""
    t = hour_totals({Signal.ELEC_HEATING: 1.2}, heat_modes=())
    assert t.get(Kind.ELEC, Mode.HEATING) == pytest.approx(1.2)
    assert t.get(Kind.STANDBY, Mode.HEATING) == 0


def test_defrost_and_standby_counted_apart() -> None:
    """Lambda/iDM: defrost electricity to the mode that ran, standby apart."""
    t = hour_totals(
        {
            Signal.HEAT_HEATING: 3.0,
            Signal.ELEC_HEATING: 0.9,
            Signal.ELEC_DEFROST: 0.1,
            Signal.ELEC_STANDBY: 0.02,
        }
    )
    assert t.get(Kind.ELEC, Mode.HEATING) == pytest.approx(1.0)
    assert t.get(Kind.STANDBY, Mode.HEATING) == pytest.approx(0.02)


def test_whole_kwh_electricity_next_to_heat_is_running() -> None:
    """Daikin over P1P2MQTT: whole kWh, the electricity of a hot water charge
    steps an hour after its heat. Same hour only, it was standby (a real
    month: 10 of 23 kWh, hot water ratio 5.8 instead of 3.3)."""
    hourly = {
        Signal.HEAT_DHW: {hour(6): 2.0, hour(7): 1.0},
        Signal.ELEC_DHW: {hour(8): 1.0},
        Signal.HEAT_HEATING: {hour(h): 2.0 for h in range(0, 6)},
        Signal.ELEC_HEATING: {hour(5): 1.0, hour(20): 1.0},
    }
    total = energy_between(hourly, None, hour(24))
    assert total.get(Kind.ELEC, Mode.DHW) == 1.0
    assert total.get(Kind.STANDBY, Mode.DHW) == 0
    # Far from any heat: still standby (about one step a day at ~30 W).
    assert total.get(Kind.STANDBY, Mode.HEATING) == 1.0
    assert total.get(Kind.ELEC, Mode.HEATING) == 1.0


def test_fine_counters_keep_the_same_hour_rule() -> None:
    """Counters in 0.01 kWh (EMS-ESP): standby next to a run stays standby."""
    hourly = {
        Signal.HEAT_HEATING: {hour(6): 2.31},
        Signal.ELEC_HEATING: {hour(6): 0.74, hour(7): 0.03},
    }
    booked = by_hour(hourly)
    assert booked[hour(7)].get(Kind.STANDBY, Mode.HEATING) == pytest.approx(0.03)
    assert booked[hour(6)].get(Kind.ELEC, Mode.HEATING) == pytest.approx(0.74)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({hour(0): 1.0, hour(1): 0.0, hour(2): 2.0}, True),
        ({hour(0): 1.0, hour(1): 0.03}, False),
        ({hour(0): 0.0}, False),
        ({}, False),
    ],
)
def test_coarse(values: dict, expected: bool) -> None:
    assert coarse(values) is expected


# --- comparing two seasons with one method -------------------------------------

SWITCH = datetime(2026, 1, 29, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("start", "end", "previous_day", "expected"),
    [
        (SWITCH - timedelta(days=60), SWITCH + timedelta(days=30), False, True),
        (SWITCH + timedelta(days=1), SWITCH + timedelta(days=30), False, False),
        (SWITCH - timedelta(days=60), SWITCH, False, False),
        (SWITCH - timedelta(days=60), SWITCH + timedelta(days=30), True, False),
    ],
)
def test_compare_on_source(
    start: datetime, end: datetime, previous_day: bool, expected: bool
) -> None:
    assert compare_on_source(start, end, SWITCH, previous_day) is expected


def test_cycling_unit_compared_with_one_method() -> None:
    """A unit with heat in every hour: before the switch the source counters
    book its standby (20 Wh an hour) as running, after it the own sensors
    tell it apart. A real drop of 20 % then hides behind the lower previous
    season; on the source counters alone it shows."""
    tz = ZoneInfo("Europe/Berlin")
    start = SWITCH - timedelta(days=32)
    source: dict[Signal, dict[datetime, float]] = {
        Signal.HEAT_HEATING: {},
        Signal.ELEC_HEATING: {},
    }
    own: dict[datetime, Totals] = {}
    outdoor: dict[datetime, float] = {}
    for n in range(60 * 24):
        at = start + timedelta(hours=n)
        day = n // 24
        outdoor[at] = 4.0 if day % 2 else 9.0  # 5 K apart
        running = 0.15 if at < SWITCH else 0.1875  # ratio 4.0, then 3.2
        source[Signal.HEAT_HEATING][at] = 0.6
        source[Signal.ELEC_HEATING][at] = running + 0.02
        exact = Totals()
        exact.add(Kind.HEAT, Mode.HEATING, 0.6)
        exact.add(Kind.ELEC, Mode.HEATING, running)
        exact.add(Kind.STANDBY, Mode.HEATING, 0.02)
        own[at] = exact

    def drop(hours: dict[datetime, Totals]):
        days = outdoor_days(daily_samples(hours, outdoor, tz))
        switch = SWITCH.astimezone(tz).date()
        return baseline_drop(
            [d for d in days if d.day >= switch],
            [d for d in days if d.day < switch],
            basis=BASIS_OUTDOOR,
        )

    booked = by_hour(source)
    mixed = {h: booked[h] if h < SWITCH else own[h] for h in booked}
    hidden = drop(mixed)
    assert hidden.problem is False
    assert hidden.evidence["drop_percent"] == pytest.approx(9.3, abs=0.2)
    shown = drop(booked)
    assert shown.problem is True
    assert shown.evidence["drop_percent"] == pytest.approx(18.1, abs=0.2)


def test_look_back_starts_where_heat_and_electricity_have_statistics() -> None:
    """A meter for all modes with long statistics next to heat meters added
    later: the hours before the heat meters are no standby (simon42 forum,
    2026-11-11: heating+hot water with standby 0.02)."""
    configured = {Signal.ELEC_TOTAL, Signal.HEAT_HEATING, Signal.HEAT_DHW}
    hourly = {
        Signal.ELEC_TOTAL: {hour(n): 0.5 for n in range(48)},
        # Not whole kWh: no neighbouring hours count as running (COARSE_WINDOW).
        Signal.HEAT_HEATING: {hour(n): 2.05 for n in range(24, 48)},
        Signal.HEAT_DHW: {hour(n): 0.0 for n in range(30, 48)},
    }
    common = common_hours(hourly, configured)
    assert min(common[Signal.ELEC_TOTAL]) == hour(30)
    assert min(common[Signal.HEAT_HEATING]) == hour(30)
    total = energy_between(common, None, hour(48))
    assert total.standby() == 0
    assert total.get(Kind.ELEC, Mode.HEATING) == pytest.approx(9.0)
    # Before the fix: 12 kWh of standby from the hours without heat rows.
    assert energy_between(hourly, None, hour(48)).standby() == pytest.approx(12.0)
    # A configured heat meter without any statistics: no look-back at all.
    assert common_hours({**hourly, Signal.HEAT_DHW: {}}, configured) == {}
    # Cooling and the backup heater do not cut the look-back.
    late = {
        **hourly,
        Signal.HEAT_COOLING: {hour(47): 0.0},
        Signal.AUX_HEATING: {hour(40): 0.0},
    }
    both = {*configured, Signal.HEAT_COOLING, Signal.AUX_HEATING}
    assert min(common_hours(late, both)[Signal.ELEC_TOTAL]) == hour(30)
    # Nothing of it configured: unchanged.
    assert common_hours(hourly, set()) is hourly


def test_look_back_per_mode_pair() -> None:
    """Counters per mode: a hot water pair with shorter statistics (EMS-ESP
    after a change of its id format) cuts only hot water, not heating."""
    configured = {
        Signal.HEAT_HEATING,
        Signal.ELEC_HEATING,
        Signal.HEAT_DHW,
        Signal.ELEC_DHW,
        Signal.HEAT_COOLING,
    }
    hourly = {
        Signal.HEAT_HEATING: {hour(n): 2.05 for n in range(48)},
        Signal.ELEC_HEATING: {hour(n): 0.55 for n in range(48)},
        Signal.HEAT_DHW: {hour(n): 1.05 for n in range(40, 48)},
        Signal.ELEC_DHW: {hour(n): 0.35 for n in range(20, 48)},
        Signal.HEAT_COOLING: {hour(n): 0.0 for n in range(48)},
    }
    assert sorted(map(sorted, balance_groups(configured))) == [
        sorted({Signal.HEAT_DHW, Signal.ELEC_DHW}),
        sorted({Signal.HEAT_HEATING, Signal.ELEC_HEATING}),
    ]
    common = common_hours(hourly, configured)
    assert min(common[Signal.HEAT_HEATING]) == hour(0)
    assert min(common[Signal.ELEC_DHW]) == hour(40)
    assert min(common[Signal.HEAT_COOLING]) == hour(0)
    assert energy_between(common, None, hour(48)).standby() == 0
    # Without the rule the hot water electricity of hours 20-39 is standby.
    assert energy_between(hourly, None, hour(48)).standby() == pytest.approx(7.0)
    # A common electricity meter joins every heat meter into one group.
    assert balance_groups(
        {Signal.ELEC_TOTAL, Signal.HEAT_HEATING, Signal.HEAT_DHW}
    ) == [{Signal.ELEC_TOTAL, Signal.HEAT_HEATING, Signal.HEAT_DHW}]


def test_heat_hour_left_out_takes_its_electricity_along() -> None:
    """A glitch of the heat counter (jump, fall back) leaves out two hours;
    their electricity is dropped too instead of becoming standby (simon42
    PN, 2026-11-12: 32 kWh standby in a week at some 4 W live)."""
    h = timedelta(hours=1)
    heat_rows = [
        (H0, 2.5, 100.0),
        (H0 + h, 9000.0, 9102.5),
        (H0 + 2 * h, -8997.5, 105.0),
    ]
    elec_rows = [(H0 + i * h, 0.9, 40.0 + 0.9 * i) for i in range(3)]
    heat, left_out = plausible_hours(heat_rows, 30.0)
    elec, _ = plausible_hours(elec_rows, 30.0)
    hourly = {Signal.HEAT_HEATING: heat, Signal.ELEC_HEATING: elec}
    # Before: the electricity of both hours was standby.
    before = by_hour(hourly, (Mode.HEATING,))
    assert sum(t.get(Kind.STANDBY, Mode.HEATING) for t in before.values()) == 1.8

    kept = drop_together(hourly, {Signal.HEAT_HEATING: left_out}, set(hourly))
    after = by_hour(kept, (Mode.HEATING,))
    assert list(after) == [H0]
    assert after[H0].get(Kind.HEAT, Mode.HEATING) == 2.5
    assert after[H0].get(Kind.ELEC, Mode.HEATING) == 0.9
    assert sum(t.get(Kind.STANDBY, Mode.HEATING) for t in after.values()) == 0


def test_left_out_hours_stay_within_their_group() -> None:
    """Hot water loses its hour, heating and the boiler keep theirs."""
    hourly = {
        Signal.HEAT_HEATING: {H0: 2.0},
        Signal.ELEC_HEATING: {H0: 0.7},
        Signal.ELEC_DHW: {H0: 0.5},
        Signal.BOILER_HEAT_HEATING: {H0: 1.0},
    }
    left_out = {Signal.HEAT_DHW: [H0]}
    kept = drop_together(hourly, left_out, {*hourly, Signal.HEAT_DHW})
    assert Signal.ELEC_DHW not in kept
    assert kept[Signal.HEAT_HEATING] == {H0: 2.0}
    assert kept[Signal.ELEC_HEATING] == {H0: 0.7}
    assert kept[Signal.BOILER_HEAT_HEATING] == {H0: 1.0}
    # Nothing left out: unchanged.
    assert drop_together(hourly, {}, set(hourly)) is hourly
