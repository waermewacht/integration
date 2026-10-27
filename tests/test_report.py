"""Report figures: scopes, months, own sensors."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.energy import Kind, Totals
from custom_components.waermewacht.model import Mode
from custom_components.waermewacht.report import by_month, figures, own_hour

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
