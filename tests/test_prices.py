"""Electricity prices from a sensor: units, hourly means, priced days and
the cost of a period. All prices and energies are made up."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.costs import (
    NO_ELECTRICITY,
    compare_costs,
    compare_with_gas,
    electricity_cost,
)
from custom_components.waermewacht.energy import Totals
from custom_components.waermewacht.periods import local_midnight
from custom_components.waermewacht.prices import (
    FIXED,
    MIXED,
    SENSOR,
    day_mean_prices,
    hourly_means,
    hours_before,
    hours_between,
    period_cost,
    price_days,
    price_factor,
    price_source,
    priced_from,
    to_eur_per_kwh,
)

BERLIN = ZoneInfo("Europe/Berlin")
# 10.01.2026 00:00 local = 09.01. 23:00 UTC.
DAY = local_midnight(date(2026, 1, 10), BERLIN)
HOUR = timedelta(hours=1)


def h(n: float) -> datetime:
    return DAY + n * HOUR


def totals(**kwh: float) -> Totals:
    return Totals(dict(kwh))


@pytest.mark.parametrize(
    ("unit", "factor"),
    [
        ("ct/kWh", 0.01),
        ("Cent/kWh", 0.01),
        ("EUR/kWh", 1.0),
        ("€/kWh", 1.0),
        (" eur / kwh ", 1.0),
        ("EUR/MWh", 0.001),
        ("€/MWh", 0.001),
        ("EUR", None),
        ("kWh", None),
        ("SEK/kWh", None),
        ("", None),
        (None, None),
    ],
)
def test_price_units(unit: str | None, factor: float | None) -> None:
    assert price_factor(unit) == factor


def test_to_eur_per_kwh() -> None:
    assert to_eur_per_kwh(30.0, "ct/kWh") == pytest.approx(0.30)
    assert to_eur_per_kwh(120.0, "EUR/MWh") == pytest.approx(0.12)
    assert to_eur_per_kwh(0.25, "€/kWh") == pytest.approx(0.25)
    assert to_eur_per_kwh(-5.0, "ct/kWh") == pytest.approx(-0.05)  # negative prices
    assert to_eur_per_kwh(float("nan"), "ct/kWh") is None
    assert to_eur_per_kwh(None, "ct/kWh") is None
    assert to_eur_per_kwh(30.0, "EUR") is None


def test_hours_between() -> None:
    assert hours_between(h(0), h(3)) == [h(0), h(1), h(2)]
    assert hours_between(h(3), h(3)) == []


def test_hourly_means_are_time_weighted() -> None:
    samples = [
        (h(-2), 0.10),  # before the window: holds into it
        (h(0.5), 0.20),
        (h(1.25), None),  # unavailable: holds nothing
        (h(1.75), 0.30),
    ]
    means = hourly_means(samples, h(0), h(3))
    assert means[h(0)] == pytest.approx(0.15)
    # 15 min at 0.20, 15 min unknown, 15 min at 0.30: the mean of the known.
    assert means[h(1)] == pytest.approx(0.25)
    assert means[h(2)] == pytest.approx(0.30)
    assert set(means) == {h(0), h(1), h(2)}


def test_hourly_means_without_known_time() -> None:
    assert hourly_means([(h(0), None)], h(0), h(2)) == {}
    assert hourly_means([], h(0), h(2)) == {}
    # Unsorted input, a value starting after the window.
    means = hourly_means([(h(5), 0.4), (h(0), 0.1)], h(0), h(2))
    assert means == {h(0): pytest.approx(0.1), h(1): pytest.approx(0.1)}


def test_day_mean_prices_for_day_values() -> None:
    """Day values book a day in one hour: it gets the day's mean price."""
    prices = {h(i): 0.10 + 0.01 * i for i in range(24)}  # 0.10 ... 0.33
    prices[h(24)] = 0.50  # next day
    found = day_mean_prices(prices, [h(0), h(24), h(48)], BERLIN)
    assert found[h(0)] == pytest.approx(0.215)
    assert found[h(24)] == pytest.approx(0.50)
    assert h(48) not in found  # no price that day


def test_priced_days_and_period_cost() -> None:
    hours = {
        h(0): totals(elec_heating=1.0, heat_heating=3.0),
        h(1): totals(elec_dhw=2.0, heat_dhw=5.0),
        h(25): totals(standby_heating=0.5),  # next local day
        h(26): totals(elec_cooling=1.0, heat_cooling=3.0),
    }
    prices = {h(0): 0.20, h(1): 0.30, h(25): 0.40}  # h(26) without
    days = price_days(hours, prices, 0.25, BERLIN)
    assert set(days) == {DAY, local_midnight(date(2026, 1, 11), BERLIN)}
    first = days[DAY]
    assert first.electricity.cost_eur == pytest.approx(0.2 + 0.6)
    assert first.electricity.hourly_hours == 2
    assert first.heat_kwh == pytest.approx(8.0)
    second = days[DAY + 24 * HOUR]
    assert second.electricity.fallback_hours == 1  # cooling at the fixed price
    assert second.electricity.heat_cost_eur == pytest.approx(0.2)

    # The period holds 1.5 kWh more than the statistics: the running hour,
    # priced at the current price.
    period = sum(hours.values(), Totals()) + totals(elec_heating=1.5, heat_heating=4.0)
    electricity, heat = period_cost(
        days, DAY, period, current=0.50, fixed=0.25, at=h(27)
    )
    assert electricity.electricity_kwh == pytest.approx(6.0)
    assert electricity.cost_eur == pytest.approx(0.2 + 0.6 + 0.2 + 0.25 + 0.75)
    assert electricity.heat_cost_eur == pytest.approx(0.2 + 0.6 + 0.2 + 0.75)
    assert electricity.hourly_hours == 4
    assert electricity.fallback_hours == 1
    assert heat == pytest.approx(12.0)  # heating + hot water, no cooling
    assert price_source(electricity) == MIXED

    # A month starting on the second day takes that day only.
    second_start = DAY + 24 * HOUR
    month = hours[h(25)] + hours[h(26)]
    only, _ = period_cost(days, second_start, month, current=0.5, fixed=0.25, at=h(27))
    assert only.cost_eur == pytest.approx(0.2 + 0.25)


def test_period_cost_without_any_price_is_unknown() -> None:
    hours = {h(0): totals(elec_heating=1.0)}
    days = price_days(hours, {}, None, BERLIN)
    electricity, _ = period_cost(
        days, DAY, hours[h(0)], current=None, fixed=None, at=h(1)
    )
    assert electricity.cost_eur is None
    assert electricity.missing_hours == 1
    assert electricity.missing_kwh == pytest.approx(1.0)


def test_prices_starting_within_the_period_count_from_the_next_day() -> None:
    # Day 1 without any price, day 2 priced from 12:00 on, day 3 priced: the
    # sensor's prices begin on day 2 (no state class, states kept ~10 days).
    hours = {
        h(10): totals(elec_heating=1.0, heat_heating=3.0),
        h(34): totals(elec_heating=1.0, heat_heating=3.0),  # day 2, 10:00
        h(36): totals(elec_heating=2.0, heat_heating=7.0),  # day 2, 12:00
        h(58): totals(elec_heating=2.0, heat_heating=8.0),  # day 3, 10:00
    }
    days = price_days(hours, {h(36): 0.3, h(58): 0.25}, None, BERLIN)
    third = DAY + 48 * HOUR
    assert priced_from(days, DAY, BERLIN, h(60)) == third
    assert hours_before(days, DAY, third) == 2
    period = sum(hours.values(), Totals())
    electricity, heat = period_cost(
        days, DAY, period, current=0.4, fixed=None, at=h(60), priced_from=third
    )
    assert electricity.cost_eur == pytest.approx(2 * 0.25)
    assert electricity.electricity_kwh == pytest.approx(2.0)
    assert electricity.missing_hours == 0
    assert heat == pytest.approx(8.0)  # the heat of the priced days only
    # Without it the cost stays unknown, as before.
    unknown, _ = period_cost(days, DAY, period, current=0.4, fixed=None, at=h(60))
    assert unknown.cost_eur is None


def test_the_running_hour_counts_after_priced_from() -> None:
    hours = {h(10): totals(elec_heating=1.0), h(34): totals(elec_heating=1.0)}
    days = price_days(hours, {h(34): 0.3}, None, BERLIN)
    second = DAY + 24 * HOUR
    # Day 1 is the only day with a gap, day 2 fully priced.
    begin = priced_from(days, DAY, BERLIN, h(40))
    assert begin == second
    period = sum(hours.values(), Totals()) + totals(elec_heating=0.5)
    electricity, _ = period_cost(
        days, DAY, period, current=0.4, fixed=None, at=h(40), priced_from=begin
    )
    # Day 2 at 0.30 plus the running hour at the current 0.40; day 1 left out.
    assert electricity.cost_eur == pytest.approx(0.3 + 0.5 * 0.4)


def test_a_gap_after_priced_days_keeps_the_cost_unknown() -> None:
    # Day 1 priced, day 2 without a price (the sensor was down): no new start.
    hours = {h(10): totals(elec_heating=1.0), h(34): totals(elec_heating=1.0)}
    days = price_days(hours, {h(10): 0.3}, None, BERLIN)
    assert priced_from(days, DAY, BERLIN, h(60)) is None


def test_no_priced_from_while_today_has_no_price() -> None:
    hours = {h(10): totals(elec_heating=1.0)}
    days = price_days(hours, {}, None, BERLIN)
    # The day after the gap has not begun yet.
    assert priced_from(days, DAY, BERLIN, h(12)) is None
    # All priced: nothing to leave out.
    assert (
        priced_from(price_days(hours, {h(10): 0.3}, None, BERLIN), DAY, BERLIN, h(12))
        is None
    )
    assert hours_before(days, DAY, None) == 0


def test_rest_without_current_price_uses_the_fixed_one() -> None:
    days = price_days({h(0): totals(elec_heating=1.0)}, {h(0): 0.2}, 0.3, BERLIN)
    period = totals(elec_heating=2.0)
    electricity, _ = period_cost(days, DAY, period, current=None, fixed=0.3, at=h(1))
    assert electricity.cost_eur == pytest.approx(0.2 + 0.3)
    assert price_source(electricity) == MIXED
    # Rounding noise of the difference needs no price.
    exact, _ = period_cost(
        days, DAY, totals(elec_heating=1.0 + 1e-12), current=None, fixed=None, at=h(1)
    )
    assert exact.cost_eur == pytest.approx(0.2)
    assert price_source(exact) == SENSOR


def test_price_sources() -> None:
    hours = {h(0): totals(elec_heating=1.0)}
    assert price_source(electricity_cost(hours, price=0.3, hourly_prices={})) == FIXED
    assert (
        price_source(electricity_cost(hours, price=None, hourly_prices={h(0): 0.2}))
        == SENSOR
    )
    assert price_source(NO_ELECTRICITY) == SENSOR


def test_electricity_cost_sum() -> None:
    a = electricity_cost({h(0): totals(elec_heating=1.0)}, price=0.3)
    b = electricity_cost({h(1): totals(elec_cooling=1.0)}, price=None)
    both = a + b
    assert both.electricity_kwh == pytest.approx(2.0)
    assert both.heat_electricity_kwh == pytest.approx(1.0)
    assert both.cost_eur is None  # one part without a price
    assert both.heat_cost_eur == pytest.approx(0.3)
    assert both.missing_hours == 1
    assert (a + NO_ELECTRICITY) == a


def test_compare_costs_matches_compare_with_gas() -> None:
    hours = {
        h(0): totals(elec_heating=1.0, heat_heating=4.0),
        h(1): totals(elec_dhw=1.0, heat_dhw=3.0, standby_heating=0.2),
    }
    prices = {h(0): 0.2, h(1): 0.4}
    start, end = DAY, h(2)
    whole = compare_with_gas(
        hours,
        start,
        end,
        BERLIN,
        electricity_price=0.3,
        gas_price=0.1,
        hourly_prices=prices,
        gas_base_price_per_year=200.0,
        electricity_base_price_per_year=100.0,
    )
    parts = compare_costs(
        electricity_cost(hours, price=0.3, hourly_prices=prices),
        7.0,
        start,
        end,
        BERLIN,
        gas_price=0.1,
        gas_base_price_per_year=200.0,
        electricity_base_price_per_year=100.0,
    )
    assert parts == whole
    assert whole.electricity.hourly_hours == 2


def test_hour_keys_are_utc() -> None:
    """Day boundaries are local: the first hour of 10.01. is 23:00 UTC."""
    assert datetime(2026, 1, 9, 23, tzinfo=UTC) == DAY
    days = price_days({h(0): totals(elec_heating=1.0)}, {h(0): 0.2}, None, BERLIN)
    assert list(days) == [DAY]
