"""Electricity cost, heat cost and the gas boiler comparison.

All prices and energies are made up.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.costs import (
    BOILER_EFFICIENCY_HS,
    DIRECT,
    WITH_UPSTREAM,
    base_price_share,
    compare_with_gas,
    electricity_cost,
    gas_for_heat,
    heat_cost_per_kwh,
)
from custom_components.waermewacht.energy import Totals
from custom_components.waermewacht.periods import local_midnight

BERLIN = ZoneInfo("Europe/Berlin")
T0 = datetime(2026, 1, 10, 0, tzinfo=UTC)


def h(n: int) -> datetime:
    return T0 + timedelta(hours=n)


def totals(**kwh: float) -> Totals:
    """Keys like heat_heating, elec_dhw, standby_heating, aux_heating."""
    return Totals(dict(kwh))


def test_electricity_includes_all_modes_standby_and_aux() -> None:
    hours = {
        h(0): totals(elec_heating=2.0, aux_heating=0.5, heat_heating=7.0),
        h(1): totals(elec_dhw=1.0, standby_heating=0.03, heat_dhw=3.0),
        h(2): totals(elec_cooling=1.5, standby_cooling=0.02, heat_cooling=5.0),
    }
    result = electricity_cost(hours, price=0.30)
    assert result.electricity_kwh == pytest.approx(5.05)
    # Heating side: heating + hot water + standby of every mode, no cooling.
    assert result.heat_electricity_kwh == pytest.approx(3.55)
    assert result.cost_eur == pytest.approx(5.05 * 0.30)
    assert result.heat_cost_eur == pytest.approx(3.55 * 0.30)
    assert result.average_price == pytest.approx(0.30)
    assert result.fallback_hours == result.missing_hours == 0


def test_hourly_prices_with_fixed_fallback() -> None:
    hours = {
        h(0): totals(elec_heating=1.0),
        h(1): totals(elec_heating=2.0),
        h(2): totals(elec_heating=1.0),
        h(3): totals(),  # no electricity, no price: not missing
    }
    prices = {h(0): 0.20, h(1): -0.05, h(2): float("nan")}
    result = electricity_cost(hours, price=0.30, hourly_prices=prices)
    assert result.cost_eur == pytest.approx(0.20 - 0.10 + 0.30)
    assert result.fallback_hours == 1  # h(2): NaN counts as no price
    assert result.missing_hours == 0


def test_hourly_prices_without_fallback_report_missing() -> None:
    hours = {
        h(0): totals(elec_heating=1.0),
        h(1): totals(elec_cooling=2.0),
        h(2): totals(elec_dhw=0.5),
    }
    result = electricity_cost(hours, price=None, hourly_prices={h(0): 0.25, h(2): 0.30})
    # Cooling electricity has no price: total unknown, heating side known.
    assert result.cost_eur is None
    assert result.average_price is None
    assert result.missing_hours == 1
    assert result.missing_kwh == pytest.approx(2.0)
    assert result.heat_missing_kwh == 0.0
    assert result.heat_cost_eur == pytest.approx(0.25 + 0.15)

    result = electricity_cost(hours, price=None, hourly_prices={h(1): 0.25})
    assert result.heat_cost_eur is None
    assert result.missing_hours == 2


def test_no_price_at_all() -> None:
    result = electricity_cost({h(0): totals(elec_heating=1.0)}, price=None)
    assert result.cost_eur is None
    assert result.heat_cost_eur is None
    assert result.missing_hours == 1


def test_heat_cost_per_kwh() -> None:
    assert heat_cost_per_kwh(3.0, 10.0) == pytest.approx(0.3)
    assert heat_cost_per_kwh(None, 10.0) is None
    assert heat_cost_per_kwh(0.01, 0.0) is None
    assert heat_cost_per_kwh(0.01, 0.2) is None  # below the minimum heat


def test_gas_for_heat() -> None:
    assert BOILER_EFFICIENCY_HS == 0.87
    assert gas_for_heat(87.0) == pytest.approx(100.0)
    assert gas_for_heat(90.0, 0.9) == pytest.approx(100.0)
    with pytest.raises(ValueError):
        gas_for_heat(10.0, 0.0)
    with pytest.raises(ValueError):
        gas_for_heat(10.0, 1.1)


def test_base_price_share() -> None:
    year = (
        local_midnight(date(2026, 1, 1), BERLIN),
        local_midnight(date(2027, 1, 1), BERLIN),
    )
    assert base_price_share(120.0, *year, BERLIN) == pytest.approx(120.0)
    february = (
        local_midnight(date(2026, 2, 1), BERLIN),
        local_midnight(date(2026, 3, 1), BERLIN),
    )
    assert base_price_share(365.0, *february, BERLIN) == pytest.approx(28.0)
    leap_day = (
        local_midnight(date(2028, 2, 29), BERLIN),
        local_midnight(date(2028, 3, 1), BERLIN),
    )
    assert base_price_share(366.0, *leap_day, BERLIN) == pytest.approx(1.0)
    assert base_price_share(365.0, year[1], year[0], BERLIN) == 0.0


def test_base_price_share_dst_and_partial_days() -> None:
    # 25 October 2026 has 25 hours: a full day is still one day.
    start = local_midnight(date(2026, 10, 25), BERLIN)
    end = local_midnight(date(2026, 10, 26), BERLIN)
    assert end - start == timedelta(hours=25)
    assert base_price_share(365.0, start, end, BERLIN) == pytest.approx(1.0)
    # Half of its real hours is half a day.
    half = start + timedelta(hours=12.5)
    assert base_price_share(365.0, start, half, BERLIN) == pytest.approx(0.5)
    # 29 March has 23 hours; from noon of the 28th: half a day plus one day.
    start = local_midnight(date(2026, 3, 28), BERLIN) + timedelta(hours=12)
    end = local_midnight(date(2026, 3, 30), BERLIN)
    assert base_price_share(365.0, start, end, BERLIN) == pytest.approx(1.5)


def two_days() -> tuple[dict[datetime, Totals], datetime, datetime]:
    start = local_midnight(date(2026, 1, 10), BERLIN)
    end = local_midnight(date(2026, 1, 12), BERLIN)
    hours = {
        start: totals(heat_heating=60.0, elec_heating=16.0, aux_heating=1.0),
        start + timedelta(hours=5): totals(heat_dhw=27.0, elec_dhw=7.5),
        start + timedelta(hours=9): totals(standby_heating=0.3, standby_cooling=0.2),
        start + timedelta(hours=30): totals(heat_cooling=8.0, elec_cooling=2.0),
        # Outside the period.
        end: totals(heat_heating=100.0, elec_heating=30.0),
        start - timedelta(hours=1): totals(heat_heating=100.0, elec_heating=30.0),
    }
    return hours, start, end


def test_compare_with_gas() -> None:
    hours, start, end = two_days()
    result = compare_with_gas(
        hours,
        start,
        end,
        BERLIN,
        electricity_price=0.30,
        gas_price=0.10,
        gas_base_price_per_year=365.0,
    )
    assert result.heat_kwh == pytest.approx(87.0)  # cooling heat left out
    assert result.electricity.electricity_kwh == pytest.approx(27.0)
    assert result.electricity.heat_electricity_kwh == pytest.approx(25.0)
    assert result.electricity.cost_eur == pytest.approx(8.1)
    assert result.heat_pump_cost_eur == pytest.approx(7.5)
    assert result.heat_cost_per_kwh == pytest.approx(7.5 / 87)
    assert result.boiler_efficiency == 0.87
    assert result.gas_kwh == pytest.approx(100.0)
    assert result.gas_energy_cost_eur == pytest.approx(10.0)
    assert result.gas_base_cost_eur == pytest.approx(2.0)
    assert result.gas_cost_eur == pytest.approx(12.0)
    assert result.gas_cost_per_kwh == pytest.approx(12 / 87)
    assert result.savings_eur == pytest.approx(4.5)
    # CO₂ with upstream chains: 406 g/kWh electricity, 240 g/kWh_Hi gas.
    assert result.factors == WITH_UPSTREAM
    assert result.heat_pump_co2_kg == pytest.approx(25 * 0.406)
    assert result.gas_co2_kg == pytest.approx(100 * 0.906 * 0.240)
    assert result.savings_co2_kg == pytest.approx(21.744 - 10.15)


def test_compare_with_gas_direct_factors_and_efficiency() -> None:
    hours, start, end = two_days()
    result = compare_with_gas(
        hours,
        start,
        end,
        BERLIN,
        electricity_price=0.30,
        gas_price=0.10,
        boiler_efficiency=0.9,
        factors=DIRECT,
    )
    assert result.gas_kwh == pytest.approx(87 / 0.9)
    assert result.gas_base_cost_eur == 0.0
    assert result.heat_pump_co2_kg == pytest.approx(25 * 0.344)
    assert result.gas_co2_kg == pytest.approx(87 / 0.9 * 0.906 * 0.201)


def test_compare_with_gas_missing_prices() -> None:
    hours, start, end = two_days()
    result = compare_with_gas(
        hours, start, end, BERLIN, electricity_price=0.30, gas_price=None
    )
    assert result.gas_energy_cost_eur is None
    assert result.gas_cost_eur is None
    assert result.gas_cost_per_kwh is None
    assert result.savings_eur is None
    assert result.heat_pump_cost_eur == pytest.approx(7.5)
    assert result.savings_co2_kg == pytest.approx(21.744 - 10.15)

    result = compare_with_gas(
        hours, start, end, BERLIN, electricity_price=None, gas_price=0.10
    )
    assert result.heat_pump_cost_eur is None
    assert result.heat_cost_per_kwh is None
    assert result.gas_cost_eur == pytest.approx(10.0)
    assert result.savings_eur is None


def test_compare_with_gas_hourly_prices() -> None:
    hours, start, end = two_days()
    prices = {start: 0.20, start + timedelta(hours=5): 0.40}
    result = compare_with_gas(
        hours,
        start,
        end,
        BERLIN,
        electricity_price=0.30,
        gas_price=0.10,
        hourly_prices=prices,
    )
    # Heating 17 × 0.20, hot water 7.5 × 0.40, standby 0.5 × 0.30 (fallback).
    assert result.heat_pump_cost_eur == pytest.approx(3.4 + 3.0 + 0.15)
    assert result.electricity.fallback_hours == 2  # standby hour and cooling hour
