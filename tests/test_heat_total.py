"""One heat meter for heating and hot water (Signal.HEAT_TOTAL): which modes
it covers, its split before the setup, the past of sensors added later."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.waermewacht.backfill import (
    by_hour,
    hour_totals,
    near_heat_hours,
    split_heat_total,
)
from custom_components.waermewacht.energy import Kind
from custom_components.waermewacht.model import (
    ENERGY_SIGNALS,
    Mode,
    Signal,
    has_elec,
    has_heat,
    heat_signal,
    total_heat_modes,
)
from custom_components.waermewacht.report import late_import_signals

H0 = datetime(2026, 1, 15, 0, tzinfo=UTC)
HEAT_DHW_MODES = (Mode.HEATING, Mode.DHW)


def test_modes_of_the_common_heat_meter() -> None:
    assert Signal.HEAT_TOTAL in ENERGY_SIGNALS
    # Without an activity everything is heating: hot water cannot be told.
    alone = {Signal.HEAT_TOTAL, Signal.ELEC_TOTAL}
    assert total_heat_modes(alone) == (Mode.HEATING,)
    assert has_heat(alone, Mode.HEATING)
    assert not has_heat(alone, Mode.DHW)
    assert not has_elec(alone, Mode.DHW)
    # With an activity (entity or flags): heating and hot water, never cooling.
    for activity in (Signal.ACTIVITY, Signal.DHW_FLAG):
        entities = {Signal.HEAT_TOTAL, Signal.ELEC_TOTAL, activity}
        assert total_heat_modes(entities) == HEAT_DHW_MODES
        assert has_heat(entities, Mode.DHW)
        assert has_elec(entities, Mode.DHW)
        assert not has_heat(entities, Mode.COOLING)
        assert not has_elec(entities, Mode.COOLING)
        assert heat_signal(entities, Mode.DHW) is Signal.HEAT_TOTAL
    # A cooling meter of its own stays possible.
    cooling = {Signal.HEAT_TOTAL, Signal.ACTIVITY, Signal.HEAT_COOLING}
    assert has_heat(cooling, Mode.COOLING)
    assert heat_signal(cooling, Mode.COOLING) is Signal.HEAT_COOLING
    # Without the common meter nothing changes.
    assert total_heat_modes({Signal.HEAT_HEATING, Signal.ACTIVITY}) == ()
    assert heat_signal({Signal.HEAT_HEATING}, Mode.HEATING) is Signal.HEAT_HEATING


def test_split_by_the_electricity_per_mode() -> None:
    """Before the setup there is no activity per hour: the heat of an hour
    goes by the electricity per mode of that hour."""
    changes = {
        Signal.HEAT_TOTAL: 6.0,
        Signal.ELEC_HEATING: 1.0,
        Signal.ELEC_DHW: 0.5,
    }
    assert split_heat_total(changes, HEAT_DHW_MODES) == {
        Mode.HEATING: pytest.approx(4.0),
        Mode.DHW: pytest.approx(2.0),
    }
    totals = hour_totals(changes, HEAT_DHW_MODES)
    assert totals.get(Kind.HEAT, Mode.HEATING) == pytest.approx(4.0)
    assert totals.get(Kind.HEAT, Mode.DHW) == pytest.approx(2.0)
    assert totals.get(Kind.ELEC, Mode.DHW) == pytest.approx(0.5)
    assert totals.standby() == 0
    # A pure hot water hour: all of it is hot water, heating's few watts of
    # standby stay standby.
    pure = hour_totals(
        {Signal.HEAT_TOTAL: 3.0, Signal.ELEC_HEATING: 0.0, Signal.ELEC_DHW: 1.2},
        HEAT_DHW_MODES,
    )
    assert pure.get(Kind.HEAT, Mode.DHW) == pytest.approx(3.0)
    assert pure.get(Kind.HEAT, Mode.HEATING) == 0


def test_split_without_electricity_per_mode_is_heating() -> None:
    changes = {Signal.HEAT_TOTAL: 5.0, Signal.ELEC_TOTAL: 1.25}
    totals = hour_totals(changes, HEAT_DHW_MODES)
    assert totals.get(Kind.HEAT, Mode.HEATING) == pytest.approx(5.0)
    assert totals.get(Kind.ELEC, Mode.HEATING) == pytest.approx(1.25)
    assert totals.get(Kind.HEAT, Mode.DHW) == 0
    # Hot water not a mode (no activity): its electricity share stays out.
    assert split_heat_total(
        {Signal.HEAT_TOTAL: 2.0, Signal.ELEC_DHW: 1.0}, (Mode.HEATING,)
    ) == {Mode.HEATING: 2.0}


def test_hour_without_heat_is_standby() -> None:
    totals = hour_totals(
        {Signal.HEAT_TOTAL: 0.0, Signal.ELEC_HEATING: 0.03, Signal.ELEC_DHW: 0.0},
        HEAT_DHW_MODES,
    )
    assert totals.get(Kind.STANDBY, Mode.HEATING) == pytest.approx(0.03)
    assert totals.electricity(*Mode) == 0


def test_whole_kwh_heat_meter_keeps_runs_running() -> None:
    """A heat meter in whole kWh steps in one hour, the electricity in the
    next: the electricity near a step of the common meter is running."""
    hourly = {
        Signal.HEAT_TOTAL: {H0: 0.0, H0 + timedelta(hours=1): 3.0},
        Signal.ELEC_HEATING: {H0: 0.6, H0 + timedelta(hours=1): 0.0},
    }
    near = near_heat_hours(hourly, (Mode.HEATING,))
    assert H0 in near[Mode.HEATING]
    hours = by_hour(hourly, (Mode.HEATING,))
    assert hours[H0].get(Kind.ELEC, Mode.HEATING) == pytest.approx(0.6)
    assert hours[H0].standby() == 0


def test_late_sensors_with_the_common_heat_meter() -> None:
    """Heat split off the common meter was in heating's heat before hot water
    was told apart: nothing to import. Electricity of its own meter reads the
    common heat meter to tell standby."""
    entities = {
        Signal.HEAT_TOTAL,
        Signal.ELEC_HEATING,
        Signal.ELEC_DHW,
        Signal.ACTIVITY,
    }
    assert late_import_signals("heat_dhw", entities) == set()
    assert late_import_signals("heat_heating", entities) == set()
    assert late_import_signals("electricity_dhw", entities) == {
        Signal.HEAT_TOTAL,
        Signal.ELEC_HEATING,
        Signal.ELEC_DHW,
    }
