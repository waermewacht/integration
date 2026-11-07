"""Oil boiler in the gas mode (oil.py): conversion, efficiency, tank levels."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.waermewacht.oil import (
    BOILER_TYPES,
    CONDENSING,
    CONSTANT_TEMPERATURE,
    CUSTOM,
    KWH_PER_LITRE_HS,
    LOW_TEMPERATURE,
    REFILL_NOT_POSITIVE,
    TANK_RISING,
    TANK_TOLERANCE_LITRES,
    check_tank,
    consumed,
    efficiency,
    price_per_kwh,
)
from custom_components.waermewacht.readings import NEGATIVE, Reading

T0 = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)


def at(days: float) -> datetime:
    return T0 + timedelta(days=days)


def test_litre_on_hs() -> None:
    # 10 kWh/l on Hi (HeizkostenV) / 0.938 (BAFA) = 10.66 kWh/l on Hs.
    assert KWH_PER_LITRE_HS == 10.66


def test_price_per_100_litres() -> None:
    # 106.60 €/100 l = 1.066 €/l = 0.10 €/kWh Hs.
    assert price_per_kwh(106.6, 10.66) == pytest.approx(0.10)
    assert price_per_kwh(None, 10.66) is None
    with pytest.raises(ValueError):
        price_per_kwh(100, 0)


def test_efficiency_by_boiler_type() -> None:
    assert efficiency(CONDENSING, None) == 0.87
    assert efficiency(LOW_TEMPERATURE, 0.95) == 0.79  # own value only for CUSTOM
    assert efficiency(CONSTANT_TEMPERATURE, None) == 0.70
    assert efficiency(CUSTOM, 0.82) == 0.82
    assert efficiency(CUSTOM, None) is None
    assert set(BOILER_TYPES) == {CONDENSING, LOW_TEMPERATURE, CONSTANT_TEMPERATURE}


def test_consumed_without_refill() -> None:
    levels = [Reading(at(0), 3000), Reading(at(7), 2860), Reading(at(14), 2700)]
    used = consumed(levels, [])
    assert [r.value for r in used] == [0, 140, 300]
    assert [r.at for r in used] == [r.at for r in levels]


def test_consumed_with_refill_between() -> None:
    # 1000 l on day 0, 800 l on day 7; refill of 2000 l on day 9; 2700 l on day 14.
    levels = [Reading(at(0), 1000), Reading(at(7), 800), Reading(at(14), 2700)]
    refills = [Reading(at(9), 2000)]
    used = consumed(levels, refills)
    # Day 7 -> 14: 800 - 2700 + 2000 = 100 l.
    assert [r.value for r in used] == [0, 200, 300]
    assert check_tank(levels, refills) is None


def test_refill_at_the_minute_of_a_level_counts_before_it() -> None:
    levels = [Reading(at(0), 500), Reading(at(7), 2400)]
    assert consumed(levels, [Reading(at(7), 2000)])[-1].value == 100
    # A refill at the first level is before the counter starts.
    assert consumed(levels, [Reading(at(0), 2000)])[-1].value == 0
    assert check_tank(levels, [Reading(at(0), 2000)]) == TANK_RISING


def test_refills_before_the_first_or_after_the_last_level_do_not_count() -> None:
    levels = [Reading(at(0), 1000), Reading(at(7), 900)]
    refills = [Reading(at(-3), 500), Reading(at(8), 2000)]
    assert [r.value for r in consumed(levels, refills)] == [0, 100]


def test_small_rise_is_netted() -> None:
    # Summer: 2000 l, read 2030 l a week later (gauge), then 1990 l.
    levels = [Reading(at(0), 2000), Reading(at(7), 2030), Reading(at(14), 1990)]
    assert check_tank(levels, []) is None
    # The counter stays at 0 and counts only beyond the rise: 10 l in all.
    assert [r.value for r in consumed(levels, [])] == [0, 0, 10]


def test_rises_add_up_against_the_highest_count() -> None:
    # 60 l up, then another 60 l up: 120 l above the counter so far.
    levels = [Reading(at(0), 2000), Reading(at(7), 2060), Reading(at(14), 2120)]
    assert check_tank(levels, []) == TANK_RISING
    # After a drop the counter so far is higher: 150 l used, then 80 l up.
    levels = [Reading(at(0), 2000), Reading(at(7), 1850), Reading(at(14), 1930)]
    assert check_tank(levels, []) is None
    assert [r.value for r in consumed(levels, [])] == [0, 150, 150]


def test_small_rise_after_a_refill_is_netted() -> None:
    # 800 l + 2000 l refilled = 2800 l expected, read 2850 l, then 2780 l.
    levels = [
        Reading(at(0), 1000),
        Reading(at(7), 800),
        Reading(at(14), 2850),
        Reading(at(21), 2780),
    ]
    refills = [Reading(at(9), 2000)]
    assert check_tank(levels, refills) is None
    assert [r.value for r in consumed(levels, refills)] == [0, 200, 200, 220]


def test_removing_a_small_refill_is_accepted() -> None:
    # Without the 80 l refill the level lies only 50 l above: netted.
    levels = [Reading(at(0), 1000), Reading(at(7), 1050)]
    assert check_tank(levels, [Reading(at(3), 80)]) is None
    assert check_tank(levels, []) is None
    assert [r.value for r in consumed(levels, [])] == [0, 0]


def test_check_tank() -> None:
    limit = TANK_TOLERANCE_LITRES
    assert limit == 100
    rise = [Reading(at(0), 1000), Reading(at(7), 1000 + limit)]
    assert check_tank(rise, []) is None
    levels = [Reading(at(0), 1000), Reading(at(7), 1101)]
    assert check_tank(levels, []) == TANK_RISING
    assert check_tank(levels, [Reading(at(3), 150)]) is None
    assert check_tank(levels, [Reading(at(3), 0)]) == REFILL_NOT_POSITIVE
    assert check_tank([Reading(at(0), -1)], []) == NEGATIVE
    # Float sums: no false alarm on an exact refill.
    levels = [Reading(at(0), 1000.3), Reading(at(7), 1500.1)]
    assert check_tank(levels, [Reading(at(3), 499.8)]) is None
    assert check_tank([], []) is None
