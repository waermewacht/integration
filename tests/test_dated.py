"""Prices that change from a date on (dated.py) and where they are used."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.config_flow import apply_price_change
from custom_components.waermewacht.const import (
    CONF_ELECTRICITY_PRICE,
    CONF_GAS_BASE_PRICE,
    CONF_GAS_PRICE,
    CONF_PRICE_CHANGES,
)
from custom_components.waermewacht.costs import (
    compare_costs,
    dated_base_share,
    electricity_cost,
)
from custom_components.waermewacht.dated import Dated, dated, states, value_at
from custom_components.waermewacht.energy import Kind, Totals
from custom_components.waermewacht.model import Mode
from custom_components.waermewacht.prices import PricedDay, period_gas_price
from custom_components.waermewacht.summary import price_change_text

BERLIN = ZoneInfo("Europe/Berlin")
# 1 January 2027, 00:00 CET.
NEW_YEAR = datetime(2026, 12, 31, 23, tzinfo=UTC)
OPTIONS = {
    CONF_ELECTRICITY_PRICE: 30.0,
    CONF_GAS_PRICE: 12.0,
    CONF_GAS_BASE_PRICE: 120.0,
    CONF_PRICE_CHANGES: [
        {"from": "2027-03-01", CONF_GAS_BASE_PRICE: 240.0},
        {"from": "2027-01-01", CONF_GAS_PRICE: 14.0, CONF_ELECTRICITY_PRICE: 28.0},
    ],
}


def totals(**values: float) -> Totals:
    result = Totals()
    for key, value in values.items():
        kind, mode = key.split("_", 1)
        result.add(Kind(kind), Mode(mode), value)
    return result


def test_a_field_without_changes_stays_a_plain_price() -> None:
    assert (
        dated({CONF_GAS_PRICE: 12.0}, CONF_GAS_PRICE, CONF_PRICE_CHANGES, BERLIN)
        == 12.0
    )
    assert dated({}, CONF_GAS_PRICE, CONF_PRICE_CHANGES, BERLIN) is None


def test_changes_apply_from_local_midnight_in_date_order() -> None:
    gas = dated(OPTIONS, CONF_GAS_PRICE, CONF_PRICE_CHANGES, BERLIN, 0.01)
    assert isinstance(gas, Dated)
    assert gas.at(NEW_YEAR - timedelta(seconds=1)) == pytest.approx(0.12)
    assert gas.at(NEW_YEAR) == pytest.approx(0.14)
    # The base price changes on 1 March, the gas price stays.
    base = dated(OPTIONS, CONF_GAS_BASE_PRICE, CONF_PRICE_CHANGES, BERLIN)
    march = datetime(2027, 2, 28, 23, tzinfo=UTC)
    assert value_at(base, march - timedelta(hours=1)) == 120.0
    assert value_at(base, march) == 240.0
    assert value_at(gas, march) == pytest.approx(0.14)


def test_segments_cut_at_the_changes() -> None:
    price = Dated(1.0, ((NEW_YEAR, 2.0),))
    start, end = NEW_YEAR - timedelta(days=1), NEW_YEAR + timedelta(days=1)
    assert list(price.segments(start, end)) == [
        (start, NEW_YEAR, 1.0),
        (NEW_YEAR, end, 2.0),
    ]
    assert list(price.segments(end, start)) == []


def test_base_price_per_segment() -> None:
    # 365 €/a in 2026 (1 € a day), 730 €/a from 1 January (2 € a day).
    base = Dated(365.0, ((NEW_YEAR, 730.0),))
    start, end = NEW_YEAR - timedelta(days=2), NEW_YEAR + timedelta(days=3)
    assert dated_base_share(base, start, end, BERLIN) == pytest.approx(2 + 6)
    assert dated_base_share(365.0, start, end, BERLIN) == pytest.approx(5)
    assert dated_base_share(None, start, end, BERLIN) == 0.0


def test_electricity_hour_by_hour_with_the_price_of_its_time() -> None:
    before, after = NEW_YEAR - timedelta(hours=1), NEW_YEAR
    hours = {before: totals(elec_heating=10.0), after: totals(elec_heating=10.0)}
    result = electricity_cost(hours, price=Dated(0.30, ((NEW_YEAR, 0.20),)))
    assert result.cost_eur == pytest.approx(3.0 + 2.0)
    # A sensor price wins; the dated price fills the hours without one.
    mixed = electricity_cost(
        hours, price=Dated(0.30, ((NEW_YEAR, 0.20),)), hourly_prices={before: 0.5}
    )
    assert mixed.cost_eur == pytest.approx(5.0 + 2.0)
    assert (mixed.hourly_hours, mixed.fallback_hours) == (1, 1)


def test_gas_price_weighted_with_the_heat_of_each_day() -> None:
    gas = Dated(0.10, ((NEW_YEAR, 0.20),))
    day = timedelta(days=1)
    days = {
        NEW_YEAR - day: PricedDay(electricity_cost({}, price=None), 30.0),
        NEW_YEAR: PricedDay(electricity_cost({}, price=None), 10.0),
    }
    period = totals(heat_heating=50.0)  # 10 kWh not in the days yet
    price = period_gas_price(days, NEW_YEAR - day, period, gas, NEW_YEAR + day)
    assert price == pytest.approx((30 * 0.10 + 10 * 0.20 + 10 * 0.20) / 50)
    # A plain price stays as it is.
    assert period_gas_price(days, NEW_YEAR, period, 0.12, NEW_YEAR) == 0.12
    # Without heat: the price of the moment.
    assert period_gas_price({}, NEW_YEAR, Totals(), gas, NEW_YEAR) == 0.20


def test_compare_costs_with_dated_base_prices() -> None:
    start, end = NEW_YEAR - timedelta(days=2), NEW_YEAR + timedelta(days=3)
    electricity = electricity_cost({start: totals(elec_heating=10.0)}, price=0.30)
    result = compare_costs(
        electricity,
        87.0,
        start,
        end,
        BERLIN,
        gas_price=0.10,
        gas_base_price_per_year=Dated(365.0, ((NEW_YEAR, 730.0),)),
    )
    assert result.gas_base_cost_eur == pytest.approx(8.0)
    assert result.gas_cost_eur == pytest.approx(10.0 + 8.0)


def test_form_adds_and_removes_a_price_change() -> None:
    stored = list(OPTIONS[CONF_PRICE_CHANGES])
    added, error = apply_price_change(
        stored, {"change_from": "2027-06-01", "change_gas_price": 15.5}
    )
    assert error is None
    assert [c["from"] for c in added] == ["2027-01-01", "2027-03-01", "2027-06-01"]
    assert added[-1] == {"from": "2027-06-01", CONF_GAS_PRICE: 15.5}
    removed, error = apply_price_change(added, {"remove_change": "2027-03-01"})
    assert error is None and [c["from"] for c in removed] == [
        "2027-01-01",
        "2027-06-01",
    ]
    # Nothing entered: unchanged.
    assert apply_price_change(stored, {}) == (stored, None)
    assert apply_price_change(stored, None) == (stored, None)


def test_form_errors_of_a_price_change() -> None:
    stored = list(OPTIONS[CONF_PRICE_CHANGES])
    assert apply_price_change(stored, {"change_gas_price": 15.5})[1] == (
        "change_from_required"
    )
    assert (
        apply_price_change(stored, {"change_from": "2027-06-01"})[1] == "change_empty"
    )
    assert apply_price_change(
        stored, {"change_from": "2027-01-01", "change_gas_price": 15.5}
    )[1] == ("change_exists")
    # Replace in one go: remove the old one and add the new one.
    replaced, error = apply_price_change(
        stored,
        {
            "remove_change": "2027-01-01",
            "change_from": "2027-01-01",
            "change_gas_price": 15.5,
        },
    )
    assert error is None
    assert replaced[0] == {"from": "2027-01-01", CONF_GAS_PRICE: 15.5}


def test_overview_line_and_states() -> None:
    text = price_change_text(OPTIONS, 1)
    assert text == (
        "ab 01.01.2027: Strom 28 ct/kWh, Gas 14 ct/kWh; "
        "ab 01.03.2027: Gas-Grundpreis 240 €/a"
    )
    assert price_change_text({}, 1) is None
    found = states(OPTIONS, (CONF_GAS_PRICE, CONF_GAS_BASE_PRICE), CONF_PRICE_CHANGES)
    assert [values for _, values in found] == [
        {CONF_GAS_PRICE: 12.0, CONF_GAS_BASE_PRICE: 120.0},
        {CONF_GAS_PRICE: 14.0, CONF_GAS_BASE_PRICE: 120.0},
        {CONF_GAS_PRICE: 14.0, CONF_GAS_BASE_PRICE: 240.0},
    ]
