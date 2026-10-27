"""Charges from the activity: start, defrost, late energy, gaps; and the
backup heater check on normal charges."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.waermewacht.charges import (
    LATE,
    Charge,
    ChargeTracker,
    disinfection_split,
)
from custom_components.waermewacht.energy import Kind
from custom_components.waermewacht.health import TOO_FEW_CHARGES, aux_dhw_charges
from custom_components.waermewacht.model import Activity

T0 = datetime(2026, 1, 15, 6, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_charge_with_defrost_and_late_energy() -> None:
    tracker = ChargeTracker()
    assert tracker.set_activity(Activity.HEATING, at(0), 42.0) is None
    tracker.add(Kind.HEAT, 1.0, at(1))  # no charge: not counted
    tracker.set_activity(Activity.DHW, at(10), 42.0)
    tracker.temperature(47.5)
    tracker.add(Kind.HEAT, 2.0, at(20))
    tracker.add(Kind.ELEC, 0.6, at(20))
    tracker.set_activity(Activity.DEFROST, at(25), None)  # does not end it
    tracker.set_activity(Activity.DHW, at(28), None)
    tracker.temperature(52.0)
    tracker.set_activity(Activity.HEATING, at(40), 41.0)
    tracker.add(Kind.HEAT, 0.5, at(42))  # the counter reports late
    tracker.add(Kind.AUX, 0.1, at(42))
    assert tracker.tick(at(44)) is None
    tracker.add(Kind.HEAT, 9.9, at(46))  # too late
    done = tracker.tick(at(46))
    assert done is not None
    assert (done.start, done.end) == (at(10), at(40))
    assert done.heat_kwh == pytest.approx(2.5)
    assert done.electricity_kwh == pytest.approx(0.6)
    assert done.aux_kwh == pytest.approx(0.1)
    assert (done.start_dhw_temp, done.max_dhw_temp) == (42.0, 52.0)
    assert done.lift == pytest.approx(10.0)
    assert not done.uncertain
    assert tracker.tick(at(50)) is None


def test_next_charge_hands_out_the_closing_one() -> None:
    tracker = ChargeTracker()
    tracker.set_activity(Activity.DHW, at(0), None)
    tracker.set_activity(Activity.OFF, at(10), None)
    done = tracker.set_activity(Activity.DHW, at(12), None)
    assert done is not None and done.end == at(10)
    assert tracker.open is not None and tracker.closing is None


def test_unknown_activity_and_restart_leave_a_gap() -> None:
    tracker = ChargeTracker()
    tracker.set_activity(Activity.DHW, at(0), None)
    tracker.set_activity(None, at(5), None)
    assert tracker.open is not None and tracker.open.uncertain

    other = ChargeTracker()
    other.set_activity(Activity.DHW, at(0), 40.0)
    data = other.as_dict()
    restored = ChargeTracker()
    restored.restore(data, saved_at=at(1), now=at(1) + LATE / 2)
    assert restored.open is not None and not restored.open.uncertain
    restored = ChargeTracker()
    restored.restore(data, saved_at=at(1), now=at(1) + 2 * LATE)
    assert restored.open is not None and restored.open.uncertain


def normal(start: float, aux: float, top: float = 50.0) -> Charge:
    return Charge(
        start=at(start),
        end=at(start + 30),
        heat_kwh=3.0,
        electricity_kwh=1.0,
        aux_kwh=aux,
        max_dhw_temp=top,
        start_dhw_temp=40.0,
    )


def test_backup_heater_in_normal_charges() -> None:
    disinfection = normal(0, 2.0, top=62.0)  # may use the heater
    charges = [disinfection] + [normal(60 * i, 0.0) for i in range(1, 11)]
    split = disinfection_split(charges, at(0), at(24 * 60))
    result = aux_dhw_charges(split)
    assert result.problem is False
    assert result.evidence["disinfections"] == 1
    assert result.evidence["aux_kwh_disinfections"] == 2.0

    charges = [normal(60 * i, 0.2) for i in range(10)]  # 0.2 of 1.2 kWh
    result = aux_dhw_charges(disinfection_split(charges, at(0), at(24 * 60)))
    assert result.problem is True
    assert result.evidence["aux_share"] == pytest.approx(16.7)

    result = aux_dhw_charges(disinfection_split(charges[:9], at(0), at(24 * 60)))
    assert result.problem is None and result.reason == TOO_FEW_CHARGES
