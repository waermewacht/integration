"""Report figures: scopes, months, own sensors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.energy import Kind, Totals
from custom_components.waermewacht.model import Mode
from custom_components.waermewacht.report import (
    by_month,
    figures,
    own_hour,
    statistics_rows,
)

BERLIN = ZoneInfo("Europe/Berlin")


def test_figures_per_scope() -> None:
    totals = Totals(
        {
            "heat_heating": 30.0,
            "elec_heating": 10.0,
            "standby_heating": 2.0,
            "heat_dhw": 10.0,
            "elec_dhw": 4.0,
            "aux_dhw": 1.0,
        }
    )
    result = figures(totals, 0.5, [Mode.HEATING, Mode.DHW])
    assert set(result) == {"heating", "dhw", "heating_dhw"}  # no cooling configured
    assert result["heating"]["ratio"] == 3.0
    assert result["dhw"]["ratio"] == 2.0
    assert result["heating_dhw"]["standby_kwh"] == 2.0
    assert result["heating_dhw"]["ratio"] == pytest.approx(round(40 / 17, 2))


def test_unknown_ratio_is_none() -> None:
    result = figures(Totals({"standby_heating": 3.0}), 0.5, [Mode.HEATING])
    assert result["heating"]["ratio"] is None


def test_months_follow_local_time() -> None:
    """31 Jan 23:30 UTC is already February in Berlin."""
    hours = {
        datetime(2026, 1, 31, 22, tzinfo=UTC): Totals({"heat_heating": 1.0}),
        datetime(2026, 1, 31, 23, tzinfo=UTC): Totals({"heat_heating": 2.0}),
    }
    months = by_month(hours, BERLIN)
    assert months["2026-01"].get(Kind.HEAT, Mode.HEATING) == 1.0
    assert months["2026-02"].get(Kind.HEAT, Mode.HEATING) == 2.0


def test_own_sensors_hour() -> None:
    totals = own_hour({"heat_dhw": 3.0, "electricity_dhw": 1.0, "standby": 0.02})
    assert totals.get(Kind.HEAT, Mode.DHW) == 3.0
    assert totals.get(Kind.ELEC, Mode.DHW) == 1.0
    assert totals.standby() == pytest.approx(0.02)


def test_statistics_rows_end_at_zero() -> None:
    """Imported past hours join the sum Home Assistant starts at 0."""
    h0 = datetime(2026, 10, 1, 10, tzinfo=UTC)
    hours = {}
    for offset, (heat, elec, standby, aux) in enumerate(
        [(3.0, 0.8, 0.0, 0.0), (0.0, 0.0, 0.03, 0.0), (2.0, 0.5, 0.0, 0.2)]
    ):
        totals = Totals()
        totals.add(Kind.HEAT, Mode.HEATING, heat)
        totals.add(Kind.ELEC, Mode.HEATING, elec)
        totals.add(Kind.STANDBY, Mode.HEATING, standby)
        totals.add(Kind.AUX, Mode.HEATING, aux)
        hours[h0 + timedelta(hours=offset)] = totals
    rows = statistics_rows(hours)
    assert rows["heat_heating"] == [(h0, -2.0), (h0 + timedelta(hours=2), 0.0)]
    # Electricity of a mode includes its backup heater, as the sensor does.
    assert rows["electricity_heating"] == [(h0, -0.7), (h0 + timedelta(hours=2), 0.0)]
    assert rows["standby"] == [(h0 + timedelta(hours=1), 0.0)]
    assert "heat_dhw" not in rows  # no energy, no rows
