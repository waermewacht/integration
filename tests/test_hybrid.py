"""Hybrid systems: the boiler's heat and fuel next to the heat pump.

The boiler never becomes heat pump energy: ratios, standby and the backup
heater stay the heat pump's. Its heat enters the building's figures and the
heat pump's share; without a heat counter it is fuel times efficiency.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.waermewacht.backfill import hour_totals
from custom_components.waermewacht.energy import (
    MIN_SHARE_HEAT_KWH,
    Kind,
    Totals,
    building_hours,
    building_totals,
    combined_ratio,
    heat_pump_share,
    mode_ratio,
)
from custom_components.waermewacht.model import (
    ENERGY_SIGNALS,
    Mode,
    Signal,
    fuel_modes,
    has_boiler,
)
from custom_components.waermewacht.report import OWN_KEYS, own_changes, own_hour

H, W = Mode.HEATING, Mode.DHW


def totals(**values: float) -> Totals:
    result = Totals()
    for key, kwh in values.items():
        kind, mode = key.split("_", 1)
        result.add(Kind(kind), Mode(mode), kwh)
    return result


def test_boiler_signals_are_energy_but_never_complete_a_mode() -> None:
    boiler = {Signal.BOILER_HEAT_HEATING, Signal.FUEL_HEATING, Signal.FUEL_DHW}
    assert boiler <= ENERGY_SIGNALS
    assert has_boiler(boiler)
    assert not has_boiler({Signal.HEAT_HEATING, Signal.ELEC_HEATING})
    # Heat from the fuel only where the boiler reports no heat.
    assert fuel_modes(boiler) == {W}
    assert fuel_modes({Signal.FUEL_HEATING}) == {H}


def test_boiler_heat_from_counter_or_fuel() -> None:
    t = totals(boiler_heating=9.0, fuel_heating=10.0, fuel_dhw=2.0)
    # Heating has a heat counter: the boiler's own heat, not the fuel.
    assert t.boiler_heat(0.87, {W}, H) == 9.0
    assert t.boiler_heat(0.87, {W}, W) == pytest.approx(1.74)
    assert t.boiler_heat(0.87, {W}, H, W) == pytest.approx(10.74)


def test_building_heat_never_reaches_the_ratios() -> None:
    t = totals(heat_heating=30.0, elec_heating=10.0, heat_dhw=6.0, elec_dhw=3.0)
    t.add(Kind.BOILER, H, 20.0)
    t.add(Kind.FUEL, W, 4.0)
    building = building_totals(t, 0.87, {W})
    assert building.heat(H) == 50.0
    assert building.heat(W) == pytest.approx(6.0 + 0.87 * 4.0)
    # The heat pump's own figures are untouched.
    assert mode_ratio(t, H, 0.5) == pytest.approx(3.0)
    assert combined_ratio(t, 0.5) == pytest.approx(36.0 / 13.0)
    assert t.heat(H) == 30.0  # building_totals made a copy
    hour = datetime(2026, 1, 15, 6, tzinfo=UTC)
    assert building_hours({hour: t}, 0.87, {W})[hour].heat(H) == 50.0


def test_heat_pump_share_on_heat_basis() -> None:
    t = totals(heat_heating=30.0, boiler_heating=20.0, heat_dhw=5.0)
    t.add(Kind.FUEL, W, 10.0)
    assert heat_pump_share(t, 0.87, {W}, H) == pytest.approx(60.0)
    assert heat_pump_share(t, 0.87, {W}, H, W) == pytest.approx(
        100 * 35.0 / (35.0 + 20.0 + 8.7)
    )
    # Too little heat for a share; a pure heat pump period is 100 %.
    small = totals(heat_heating=MIN_SHARE_HEAT_KWH / 2)
    assert heat_pump_share(small, 0.87, set(), H) is None
    assert heat_pump_share(totals(heat_heating=5.0), 0.87, set(), H) == 100.0
    assert heat_pump_share(totals(boiler_heating=5.0), 0.87, set(), H) == 0.0


def test_boiler_heat_does_not_turn_standby_into_running() -> None:
    """An hour heated by the boiler alone: the heat pump's electricity is
    standby, the boiler is booked apart."""
    hour = hour_totals(
        {
            Signal.ELEC_HEATING: 0.03,
            Signal.BOILER_HEAT_HEATING: 4.0,
            Signal.FUEL_HEATING: 4.3,
            Signal.AUX_TOTAL: 0.0,
        }
    )
    assert hour.get(Kind.STANDBY, H) == pytest.approx(0.03)
    assert hour.get(Kind.ELEC, H) == 0.0
    assert hour.get(Kind.HEAT, H) == 0.0
    assert hour.get(Kind.BOILER, H) == 4.0
    assert hour.get(Kind.FUEL, H) == 4.3


def test_own_boiler_sensors_round_trip() -> None:
    t = totals(heat_heating=3.0, elec_heating=1.0, boiler_heating=2.0)
    t.add(Kind.FUEL, H, 2.2)
    t.add(Kind.FUEL, W, 0.4)
    changes = own_changes(t)
    assert set(changes) == set(OWN_KEYS)
    back = own_hour(changes)
    assert back.get(Kind.BOILER, H) == 2.0
    assert back.get(Kind.FUEL, H) == 2.2
    assert back.get(Kind.FUEL, W) == 0.4
    assert back.heat(H) == 3.0


def test_energy_signature_counts_the_boilers_heat() -> None:
    """Heat load from a cold week: with the boiler the building needs more
    than the heat pump alone delivered."""
    from zoneinfo import ZoneInfo

    from custom_components.waermewacht.heat_load import heat_load

    tz = ZoneInfo("Europe/Berlin")
    start = datetime(2026, 1, 5, 0, tzinfo=tz).astimezone(UTC)
    hours, outdoor = {}, {}
    for i in range(24 * 7 * 8):
        at = start + timedelta(hours=i)
        week = i // (24 * 7)
        temp = -4.0 + 2.0 * week  # eight weeks from -4 to +10 degC
        need = max(0.0, 0.1 * (15.0 - temp))  # 100 W/K, heating limit 15 degC
        t = Totals()
        pump = min(need, 1.2)  # the heat pump covers up to 1.2 kW
        t.add(Kind.HEAT, H, pump)
        t.add(Kind.ELEC, H, pump / 3)
        t.add(Kind.BOILER, H, need - pump)
        hours[at] = t
        outdoor[at] = temp
    alone = heat_load(hours, outdoor, tz, design_temp=-12.0)
    both = heat_load(building_hours(hours, 0.87, set()), outdoor, tz, design_temp=-12.0)
    assert both.slope_kw_per_k == pytest.approx(-0.1, rel=0.05)
    assert alone.slope_kw_per_k is None or alone.slope_kw_per_k > -0.09


def test_boiler_hours_and_replace_take_the_source() -> None:
    """The building's figures take the boiler from its own counters' hourly
    statistics: also for hours before it was mapped."""
    from custom_components.waermewacht.backfill import boiler_hours
    from custom_components.waermewacht.energy import replace_boiler

    h1 = datetime(2026, 1, 15, 6, tzinfo=UTC)
    h2 = h1 + timedelta(hours=1)
    source = boiler_hours(
        {
            Signal.BOILER_HEAT_HEATING: {h1: 4.0, h2: 0.0},
            Signal.FUEL_DHW: {h2: 1.0},
            Signal.HEAT_HEATING: {h1: 9.0},  # not the boiler's: left out
        }
    )
    assert set(source) == {h1, h2}
    assert source[h1].heat(H) == 0.0
    own = {h1: totals(heat_heating=3.0, boiler_heating=1.0)}  # own: too little
    merged = replace_boiler(own, source)
    assert merged[h1].get(Kind.BOILER, H) == 4.0
    assert merged[h1].heat(H) == 3.0  # the heat pump's own heat stays
    # No hour of the boiler alone: it would pass as a day with data.
    assert set(merged) == {h1}
    assert own[h1].get(Kind.BOILER, H) == 1.0  # input untouched
    own[h2] = Totals()  # the heat pump's hour exists (0 kWh): boiler joins
    assert replace_boiler(own, source)[h2].get(Kind.FUEL, W) == 1.0
