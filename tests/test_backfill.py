"""Backfill from hourly statistics: standby rule and backup heater."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.waermewacht.backfill import energy_between, hour_totals
from custom_components.waermewacht.energy import Kind
from custom_components.waermewacht.model import Mode, Signal, has_elec

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
        Signal.HEAT_HEATING: {hour(0): 0.0, hour(1): 2.0, hour(2): 1.0},
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
