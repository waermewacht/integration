"""Heating curve figure: flow at 0 °C from heating-only hours."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.energy import Kind, Totals
from custom_components.waermewacht.heating_curve import (
    CIRCUIT_MIN_FLOW,
    SPREAD_TOO_SMALL,
    TOO_FEW_DAYS,
    circuit_flow_curve,
    circuit_flow_days,
    flow_curve,
    flow_days,
)
from custom_components.waermewacht.model import Mode
from custom_components.waermewacht.periods import local_midnight

BERLIN = ZoneInfo("Europe/Berlin")


def heat(heating: float, dhw: float = 0.0) -> Totals:
    totals = Totals()
    totals.add(Kind.HEAT, Mode.HEATING, heating)
    totals.add(Kind.HEAT, Mode.DHW, dhw)
    return totals


def build(days: dict[date, float], curve=lambda t: 35.0 - 0.5 * t):
    """Each day: outdoor all day; heating every hour with the flow of the curve."""
    hours: dict[datetime, Totals] = {}
    flow: dict[datetime, float] = {}
    outdoor: dict[datetime, float] = {}
    for day, temp in days.items():
        start = local_midnight(day, BERLIN)
        for n in range(24):
            hour = start + timedelta(hours=n)
            outdoor[hour] = temp
            hours[hour] = heat(1.0)
            flow[hour] = curve(temp)
    return hours, flow, outdoor


def days(n: int, coldest: float, warmest: float) -> dict[date, float]:
    step = (warmest - coldest) / (n - 1)
    return {date(2026, 11, 1) + timedelta(days=i): coldest + i * step for i in range(n)}


def test_flow_at_zero_and_slope() -> None:
    result = flow_curve(*build(days(20, -4.0, 10.0)), BERLIN)
    assert result.reasons == ()
    assert result.at_zero == pytest.approx(35.0)
    assert result.slope == pytest.approx(-0.5)
    assert result.r_squared == pytest.approx(1.0)


def test_hot_water_hours_are_left_out() -> None:
    hours, flow, outdoor = build(days(20, -4.0, 10.0))
    for hour in list(hours)[::6]:  # a charge every six hours at 55 °C
        hours[hour] = heat(1.0, dhw=2.0)
        flow[hour] = 55.0
    assert flow_curve(hours, flow, outdoor, BERLIN).at_zero == pytest.approx(35.0)


def test_weak_hours_and_short_days_do_not_count() -> None:
    hours, flow, outdoor = build({date(2026, 11, 1): 5.0})
    for n, hour in enumerate(hours):
        hours[hour] = heat(0.1 if n else 1.0)  # one real heating hour only
    assert flow_days(hours, flow, outdoor, BERLIN) == []


def test_unknown_with_reasons() -> None:
    result = flow_curve(*build(days(10, 2.0, 4.0)), BERLIN)
    assert result.at_zero is None
    assert result.reasons == (TOO_FEW_DAYS, SPREAD_TOO_SMALL)


# A sensor in the heating circuit: hours by the running circuit, not by heat.


def test_circuit_hours_need_no_heat_and_weigh_the_same() -> None:
    _, flow, outdoor = build({date(2026, 11, 2): 5.0})
    hours = list(flow)
    for n, hour in enumerate(hours):
        # Circuit off at night (sensor at room level), two levels by day.
        flow[hour] = 20.0 if n < 6 else (30.0 if n % 2 else 40.0)
    (day,) = circuit_flow_days(flow, outdoor, BERLIN)
    assert day.flow == pytest.approx(35.0)


def test_circuit_leaves_out_days_above_the_heating_limit() -> None:
    """A circuit off in summer can read a warm boiler room above 25 °C."""
    _, flow, outdoor = build({date(2026, 7, 1): 15.0, date(2026, 7, 2): 14.9})
    for hour in flow:
        flow[hour] = 28.0
    assert [d.day for d in circuit_flow_days(flow, outdoor, BERLIN)] == [
        date(2026, 7, 2)
    ]


def test_circuit_curve_and_reasons() -> None:
    _, flow, outdoor = build(days(20, -4.0, 10.0))
    result = circuit_flow_curve(flow, outdoor, BERLIN)
    assert result.at_zero == pytest.approx(35.0)
    assert result.slope == pytest.approx(-0.5)
    _, flow, outdoor = build(days(10, 2.0, 4.0))
    assert circuit_flow_curve(flow, outdoor, BERLIN).reasons == (
        TOO_FEW_DAYS,
        SPREAD_TOO_SMALL,
    )
    # Below CIRCUIT_MIN_FLOW the circuit counts as off.
    _, flow, outdoor = build(days(20, -4.0, 10.0), curve=lambda t: CIRCUIT_MIN_FLOW - 1)
    assert circuit_flow_curve(flow, outdoor, BERLIN).days == ()
