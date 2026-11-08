"""Heat pump electricity from the grid or from own PV and battery.

All energies and prices are made up.
"""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.allocation import (
    HEAT_PUMP_FIRST,
    PROPORTIONAL,
    Allocation,
    SplitSettings,
    allocate,
    grid_kwh,
    rule_for,
)
from custom_components.waermewacht.energy import Totals
from custom_components.waermewacht.periods import local_midnight
from custom_components.waermewacht.prices import (
    period_allocation,
    period_cost,
    price_days,
)
from custom_components.waermewacht.solar import (
    HourFlows,
    SolarSettings,
    detect_same_inverter,
)

BERLIN = ZoneInfo("Europe/Berlin")
DAY = local_midnight(date(2026, 1, 10), BERLIN)
HOUR = timedelta(hours=1)
AC = SolarSettings(same_inverter=False, feed_in_rate=0.08)
HYBRID = SolarSettings(same_inverter=True, feed_in_rate=0.08)


def h(n: int):
    return DAY + n * HOUR


def heating(kwh: float, **more: float) -> Totals:
    return Totals({"elec_heating": kwh, **more})


def split(rule: str, solar: SolarSettings = AC) -> SplitSettings:
    return SplitSettings(rule, 0.08, solar)


def test_rules() -> None:
    assert rule_for(pv=True, feed_in=True) == PROPORTIONAL
    assert rule_for(pv=False, feed_in=False) == HEAT_PUMP_FIRST
    assert rule_for(pv=True, feed_in=False) == HEAT_PUMP_FIRST


def test_example_of_both_rules() -> None:
    """Heat pump 2 kWh, house 3 kWh, from the grid 1 kWh."""
    flows = HourFlows(purchase=1.0, feed_in=0.5, pv=2.5)
    assert AC.consumption(flows) == pytest.approx(3.0)
    assert grid_kwh(2.0, flows, PROPORTIONAL, AC) == pytest.approx(2 / 3)
    assert grid_kwh(2.0, flows, HEAT_PUMP_FIRST, AC) == pytest.approx(1.0)


def test_grid_share_is_clamped() -> None:
    # More grid import than the house used (meters out of step): all grid.
    flows = HourFlows(purchase=4.0, feed_in=0.0, pv=0.0)
    assert grid_kwh(2.0, flows, PROPORTIONAL, AC) == pytest.approx(2.0)
    # Heat pump first never takes more than the heat pump used.
    assert grid_kwh(2.0, flows, HEAT_PUMP_FIRST, AC) == pytest.approx(2.0)
    # No consumption to share: as heat pump first.
    none = HourFlows(purchase=0.5, feed_in=1.0, pv=0.5)
    assert grid_kwh(2.0, none, PROPORTIONAL, AC) == pytest.approx(0.5)
    assert grid_kwh(0.0, flows, PROPORTIONAL, AC) == 0.0


def test_battery_with_its_own_inverter_and_behind_the_pv_inverter() -> None:
    # Evening: 1 kWh from the grid, 2 kWh from the battery, no PV.
    own = HourFlows(purchase=1.0, discharged=2.0)
    assert AC.consumption(own) == pytest.approx(3.0)
    assert grid_kwh(1.5, own, PROPORTIONAL, AC) == pytest.approx(0.5)
    # Hybrid inverter: its AC meter already holds the battery energy.
    hybrid = HourFlows(purchase=1.0, pv=1.9, discharged=2.0)
    assert HYBRID.consumption(hybrid) == pytest.approx(2.9)
    assert grid_kwh(1.5, hybrid, PROPORTIONAL, HYBRID) == pytest.approx(1.5 / 2.9)
    # Charging from PV is no consumption of the house.
    charging = HourFlows(purchase=0.0, pv=4.0, charged=3.0)
    assert AC.consumption(charging) == pytest.approx(1.0)
    assert grid_kwh(1.0, charging, PROPORTIONAL, AC) == 0.0


def test_allocate_with_a_missing_hour() -> None:
    hours = {
        h(0): heating(2.0, standby_heating=0.0),
        h(1): heating(1.0),  # no meter statistics: all grid
        h(2): Totals({"elec_cooling": 1.0}),
    }
    flows = {
        h(0): HourFlows(purchase=1.0, feed_in=0.5, pv=2.5),
        h(2): HourFlows(purchase=0.0, feed_in=1.0, pv=2.0),
    }
    found = allocate(hours, flows, {h(0): 0.30}, 0.25, split(PROPORTIONAL))
    assert found.hours_all_grid == 1
    assert found.kwh_grid == pytest.approx(2 / 3 + 1.0)
    assert found.kwh_own == pytest.approx(4 / 3 + 1.0)
    # Own kWh at the feed-in tariff instead of the grid price: hour 0 at the
    # sensor's 0.30, hour 2 at the fixed 0.25.
    assert found.saving_eur == pytest.approx(4 / 3 * 0.22 + 1.0 * 0.17)
    # Cooling is no heating or hot water.
    assert found.heat_saving_eur == pytest.approx(4 / 3 * 0.22)
    assert found.grid_share == pytest.approx((5 / 3) / 4)


def test_without_any_price_no_saving() -> None:
    found = allocate(
        {h(0): heating(2.0)},
        {h(0): HourFlows(purchase=0.0, pv=3.0, feed_in=1.0)},
        {},
        None,
        split(PROPORTIONAL),
    )
    assert found.kwh_own == pytest.approx(2.0)
    assert found.saving_eur == 0.0
    assert Allocation().grid_share is None


def test_period_cost_with_own_electricity() -> None:
    hours = {h(0): heating(2.0, heat_heating=8.0), h(1): heating(1.0)}
    flows = {
        h(0): HourFlows(purchase=1.0),
        h(1): HourFlows(purchase=1.0),
    }
    days = price_days(hours, {}, 0.30, BERLIN, flows, split(HEAT_PUMP_FIRST))
    # Heat pump first: hour 0 takes 1 kWh from the grid, 1 kWh own.
    allocation = period_allocation(days, DAY)
    assert allocation is not None
    assert allocation.kwh_own == pytest.approx(1.0)
    totals = hours[h(0)] + hours[h(1)] + heating(0.5)  # the running hour
    electricity, heat = period_cost(
        days, DAY, totals, current=None, fixed=0.30, at=h(2)
    )
    # 3.5 kWh at 0.30, then the own kWh at 0.08 instead.
    assert electricity.cost_eur == pytest.approx(3.5 * 0.30 - 1.0 * 0.22)
    assert electricity.heat_cost_eur == pytest.approx(3.5 * 0.30 - 0.22)
    assert heat == pytest.approx(8.0)
    # Without meters there is no allocation and the cost stays all grid.
    plain = price_days(hours, {}, 0.30, BERLIN)
    assert period_allocation(plain, DAY) is None
    cost, _ = period_cost(plain, DAY, totals, current=None, fixed=0.30, at=h(2))
    assert cost.cost_eur == pytest.approx(3.5 * 0.30)


def test_detect_same_inverter_copied_from_tarifwacht() -> None:
    nights = {h(i): HourFlows(pv=0.95, discharged=1.0) for i in range(12)}
    assert detect_same_inverter(nights) is True
    own = {h(i): HourFlows(pv=0.0, discharged=1.0) for i in range(12)}
    assert detect_same_inverter(own) is False
    assert detect_same_inverter({h(0): HourFlows(discharged=1.0)}) is None
