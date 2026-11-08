"""Report figures: scopes, months, own sensors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.degree_days import DayDegrees
from custom_components.waermewacht.energy import Kind, Totals
from custom_components.waermewacht.model import Mode, Signal
from custom_components.waermewacht.report import (
    OWN_KEYS,
    by_month,
    degree_days_by_month,
    figures,
    late_import_signals,
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


def test_late_sensor_imports_only_its_own_meters() -> None:
    """A sensor that appears after the setup gets its past only from meters
    no other own sensor counted before it appeared."""
    entities = {
        Signal.HEAT_HEATING,
        Signal.ELEC_HEATING,
        Signal.HEAT_DHW,
        Signal.ELEC_DHW,
        Signal.AUX_DHW,
        Signal.ELEC_COOLING,
        Signal.BOILER_HEAT_HEATING,
        Signal.FUEL_DHW,
        Signal.COMPRESSOR,
    }
    assert late_import_signals("heat_dhw", entities) == {
        Signal.HEAT_DHW,
        Signal.ELEC_DHW,
    }
    # Electricity with its backup heater; the heat tells standby apart.
    assert late_import_signals("electricity_dhw", entities) == {
        Signal.HEAT_DHW,
        Signal.ELEC_DHW,
        Signal.AUX_DHW,
    }
    assert late_import_signals("electricity_cooling", entities) == {Signal.ELEC_COOLING}
    assert late_import_signals("boiler_heat_heating", entities) == {
        Signal.BOILER_HEAT_HEATING
    }
    assert late_import_signals("fuel_dhw", entities) == {Signal.FUEL_DHW}
    # Standby was in the electricity of the modes before.
    assert late_import_signals("standby", entities) == set()
    # Not mapped: nothing of its own.
    assert late_import_signals("heat_cooling", entities) == set()
    assert late_import_signals("fuel_heating", entities) == set()
    for key in OWN_KEYS:
        assert late_import_signals(key, set()) == set()


def test_late_sensor_split_off_a_common_meter_imports_nothing() -> None:
    """With one meter for all modes, the hot water's electricity was in
    heating's until the hot water got its heat meter."""
    entities = {
        Signal.HEAT_HEATING,
        Signal.HEAT_DHW,
        Signal.ELEC_TOTAL,
        Signal.ELEC_DHW,
    }
    assert late_import_signals("electricity_dhw", entities) == set()
    assert late_import_signals("electricity_heating", entities) == set()
    assert late_import_signals("heat_dhw", entities) == {
        Signal.HEAT_DHW,
        Signal.ELEC_DHW,
    }


def test_degree_days_per_month() -> None:
    def day(month: int, n: int, mean: float, heat: float) -> DayDegrees:
        return DayDegrees(
            day=datetime(2026, month, n, tzinfo=UTC).date(),
            hours=24,
            mean_outdoor=mean,
            degree_days=max(0.0, 20 - mean) if mean < 15 else 0.0,
            heating_kwh=heat,
        )

    days = [day(1, 30, 0.0, 40.0), day(1, 31, 2.0, 36.0), day(2, 1, 16.0, 2.0)]
    months = degree_days_by_month(days)
    assert months["2026-01"] == {
        "degree_days": 38.0,
        "kwh_per_degree_day": 2.0,
        "days_counted": 2,
    }
    # A mild month below the minimum degree days: no heat per degree day.
    assert months["2026-02"]["degree_days"] == 0.0
    assert months["2026-02"]["kwh_per_degree_day"] is None


def test_electricity_only_modes() -> None:
    totals = Totals({"elec_heating": 4.0, "elec_dhw": 1.5})
    rows = figures(totals, 0.5, [], electricity_modes=[Mode.HEATING, Mode.DHW])
    assert rows["heating"] == {"heat_kwh": None, "electricity_kwh": 4.0, "ratio": None}
    assert rows["dhw"]["electricity_kwh"] == 1.5
    assert "heating_dhw" not in rows
