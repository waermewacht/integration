"""Ratios: unknown instead of 0, standby, backup heater, cooling."""

from __future__ import annotations

import pytest

from custom_components.waermewacht.energy import (
    Kind,
    Totals,
    aux_share,
    combined_ratio,
    mode_ratio,
    ratio,
)
from custom_components.waermewacht.model import Mode

MIN = 0.5


def totals(**values: float) -> Totals:
    return Totals(dict(values))


def test_no_heat_or_no_electricity_is_unknown() -> None:
    assert ratio(0.0, 0.0, MIN) is None
    assert ratio(5.0, 0.0, MIN) is None
    assert ratio(0.0, 2.0, MIN) is None  # standby only, e.g. a summer day
    assert ratio(1.0, 0.3, MIN) is None  # below the minimum electricity
    assert ratio(12.0, 4.0, MIN) == 3.0


def test_period_ratio_is_sum_over_sum() -> None:
    """Two days 10/2 and 30/15: 40/17, not the mean of 5 and 2."""
    day1 = totals(heat_heating=10, elec_heating=2)
    day2 = totals(heat_heating=30, elec_heating=15)
    assert mode_ratio(day1 + day2, Mode.HEATING, MIN) == pytest.approx(40 / 17)


def test_mode_ratio_leaves_standby_out_and_aux_in() -> None:
    t = totals(heat_heating=30, elec_heating=9, standby_heating=0.6, aux_heating=1)
    assert mode_ratio(t, Mode.HEATING, MIN) == pytest.approx(3.0)


def test_combined_ratio_includes_standby_not_cooling() -> None:
    t = totals(
        heat_heating=30,
        elec_heating=9,
        standby_heating=1,
        heat_dhw=10,
        elec_dhw=4,
        aux_dhw=1,
        heat_cooling=40,
        elec_cooling=10,
    )
    assert combined_ratio(t, MIN) == pytest.approx(40 / 15)
    assert combined_ratio(t, MIN, with_standby=False) == pytest.approx(40 / 14)
    assert mode_ratio(t, Mode.COOLING, MIN) == pytest.approx(4.0)


def test_aux_share() -> None:
    t = totals(elec_heating=18, aux_dhw=1, standby_heating=1)
    assert aux_share(t, MIN) == pytest.approx(5.0)
    assert aux_share(Totals(), MIN) is None


def test_aux_share_per_mode() -> None:
    """The total mixes both modes; per mode the heater shows where it ran."""
    t = totals(elec_heating=87, elec_dhw=68, aux_dhw=29, standby_dhw=1)
    assert aux_share(t, MIN) == pytest.approx(100 * 29 / 185)
    assert aux_share(t, MIN, Mode.HEATING) == pytest.approx(0.0)
    assert aux_share(t, MIN, Mode.DHW) == pytest.approx(100 * 29 / 98)
    assert aux_share(totals(elec_heating=10), MIN, Mode.DHW) is None


def test_arithmetic_and_round_trip() -> None:
    t = Totals()
    t.add(Kind.HEAT, Mode.HEATING, 2.5)
    t.add(Kind.HEAT, Mode.HEATING, 0.5)
    assert t.get(Kind.HEAT, Mode.HEATING) == 3.0
    assert (-t).get(Kind.HEAT, Mode.HEATING) == -3.0
    assert (t - t).get(Kind.HEAT, Mode.HEATING) == 0.0
    assert Totals.from_dict(t.as_dict()) == t
