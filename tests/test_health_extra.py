"""Further health check rules: defrosts, spread, oversizing, standby, flow."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.averages import Mean
from custom_components.waermewacht.health import TOO_FEW_DAYS
from custom_components.waermewacht.health_extra import (
    HEAT_LOAD_INSUFFICIENT,
    NO_DESIGN_TEMP,
    NO_FLOW_RATE,
    NO_RATED_POWER,
    NO_STANDBY,
    SPREAD_TOO_SMALL,
    TOO_LITTLE_HEATING,
    ZeroFlow,
    compare_defrost_classes,
    day_hours,
    defrost_classes,
    defrost_figures,
    expected_flow,
    flow_plausibility,
    flow_plausibility_entry,
    oversizing,
    spread_figure,
    standby_day,
    standby_rise,
    to_lph,
)
from custom_components.waermewacht.heat_load import HeatLoad
from custom_components.waermewacht.runs import Defrost

BERLIN = ZoneInfo("Europe/Berlin")
TODAY = date(2026, 12, 15)
H = 3600


def entry(day: date, **values: Any) -> dict[str, Any]:
    """A diary entry in the format of runtime._write_diary (made-up values)."""
    return {
        "day": day.isoformat(),
        "outdoor": 0.0,
        "starts": 5,
        "run_seconds": 10 * H,
        "activity_seconds": {"heating": 9 * H, "dhw": H},
        "short_runs": 0,
        "defrosts": 4,
        "defrost_seconds": 800,
        "spread": {"weighted": 5.0 * 9 * H, "seconds": 9 * H},
        "flow": {"weighted": 35.0 * 9 * H, "seconds": 9 * H},
        "energy": {"heat_heating": 40.0, "elec_heating": 10.0, "standby_heating": 0.35},
        "charges": None,
        **values,
    }


def days_before(today: date, count: int) -> list[date]:
    return [today - timedelta(days=n) for n in range(count, 0, -1)]


# Day length and units.


def test_day_hours_follow_dst() -> None:
    assert day_hours(date(2026, 10, 25), BERLIN) == 25
    assert day_hours(date(2027, 3, 28), BERLIN) == 23
    assert day_hours(date(2026, 12, 1), BERLIN) == 24


def test_flow_units() -> None:
    assert to_lph(15, "L/min") == 900
    assert to_lph(900, "l/h") == 900
    assert to_lph(0.9, "m³/h") == pytest.approx(900)
    with pytest.raises(KeyError):
        to_lph(1, "kg/h")


# 4.3 Defrosts.


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 12, 10, hour, minute, tzinfo=UTC)


def test_defrost_figures() -> None:
    defrosts = [
        Defrost(at(1, 10), at(1, 14)),  # 4 min at 2 °C
        Defrost(at(13, 5), at(13, 25)),  # 20 min at 11 °C: warm
        Defrost(at(15, 50), None),  # running, at 10 °C: warm, no duration
        Defrost(at(20, 0), at(20, 3)),  # no outdoor value
        Defrost(at(1, 0) - timedelta(days=8), at(1, 5) - timedelta(days=8)),
    ]
    outdoor = {at(1): 2.0, at(13): 11.0, at(15): 10.0}
    result = defrost_figures(defrosts, outdoor, at(0) - timedelta(days=6), at(23))
    assert result.defrosts == 4
    assert result.warm_defrosts == 2
    assert result.unknown_outdoor == 1
    assert result.mean_minutes == pytest.approx(9.0)
    assert result.longest_minutes == pytest.approx(20.0)
    attrs = result.as_attributes()
    assert attrs["warm_defrosts_7d"] == 2 and attrs["warm_from"] == 10.0


def test_defrost_figures_without_defrosts() -> None:
    result = defrost_figures([], {}, at(0), at(23))
    assert result.defrosts == 0
    assert result.mean_minutes is None and result.longest_minutes is None


def test_defrost_classes_and_comparison() -> None:
    previous_days = days_before(date(2025, 12, 31), 20)
    current_days = days_before(TODAY, 20)
    previous = [entry(d, outdoor=1.0, defrosts=5) for d in previous_days[:10]] + [
        entry(d, outdoor=-3.0, defrosts=2) for d in previous_days[10:]
    ]
    current = [entry(d, outdoor=1.5, defrosts=10) for d in current_days[:10]] + [
        entry(d, outdoor=-2.5, defrosts=2)
        for d in current_days[10:16]  # sparse
    ]
    old = defrost_classes(previous, previous_days[0], previous_days[-1])
    new = defrost_classes(current, current_days[0], current_days[-1])
    assert [(c.lower, c.days) for c in new] == [(-4.0, 6), (0.0, 10)]
    assert new[0].per_run_hour is None  # fewer than 7 days
    assert new[1].per_run_hour == pytest.approx(1.0)  # 10 per 10 run hours
    rows = compare_defrost_classes(new, old)
    assert len(rows) == 1
    assert rows[0]["lower"] == 0.0 and rows[0]["factor"] == pytest.approx(2.0)


def test_defrost_classes_skip_days_without_run_or_outdoor() -> None:
    day = TODAY - timedelta(days=1)
    entries = [
        entry(day, outdoor=None),
        entry(day - timedelta(days=1), run_seconds=0),
    ]
    assert defrost_classes(entries, day - timedelta(days=5), day) == []


# 4.4 Spread.


def test_spread_of_cold_days() -> None:
    days = days_before(TODAY, 7)
    entries = [
        entry(d, outdoor=2.0, spread={"weighted": 6.0 * 4 * H, "seconds": 4 * H})
        for d in days[:4]
    ] + [
        entry(d, outdoor=8.0, spread={"weighted": 3.0 * 2 * H, "seconds": 2 * H})
        for d in days[4:]
    ]
    result = spread_figure(entries, TODAY)
    assert result.reason is None
    assert result.value == pytest.approx(6.0)
    assert result.days == 4 and result.hours == pytest.approx(16)
    assert result.all_days == pytest.approx((6 * 16 + 3 * 6) / 22)
    assert result.as_attributes()["field_reference"] == 6.8


def test_spread_needs_ten_hours_of_cold_heating() -> None:
    days = days_before(TODAY, 7)
    entries = [
        entry(d, outdoor=2.0, spread={"weighted": 6.0 * 3 * H, "seconds": 3 * H})
        for d in days[:3]
    ] + [entry(d, outdoor=9.0) for d in days[3:]]
    result = spread_figure(entries, TODAY)
    assert result.value is None and result.reason == TOO_LITTLE_HEATING
    assert result.all_days is not None


def test_spread_ignores_days_outside_the_window() -> None:
    old = [entry(d, outdoor=-5.0) for d in days_before(TODAY - timedelta(days=7), 7)]
    assert spread_figure(old, TODAY).reason == TOO_LITTLE_HEATING


# 4.7 Oversizing.


def load(design_temp: float | None = -12.0) -> HeatLoad:
    """Made-up signature: 2.4 kW at 0 °C, 0.16 kW/K, heating limit 15 °C."""
    a, b = 2.4, -0.16
    return HeatLoad(
        sufficient=True,
        intercept_kw=a,
        slope_kw_per_k=b,
        design_temp=design_temp,
        measured_kw=None if design_temp is None else a + b * design_temp,
        standard_kw=None if design_temp is None else b * (design_temp - 20),
    )


def test_oversizing_factor() -> None:
    result = oversizing(load(), 7.68, min_kw=2.0)
    assert result.reason is None
    assert result.heat_load_kw == pytest.approx(5.12)
    assert result.factor == pytest.approx(1.5)
    assert result.measured_factor == pytest.approx(7.68 / 4.32)
    assert result.load_mild_kw == pytest.approx(1.28)
    assert result.cycling_expected is True
    assert result.as_attributes()["field_mean"] == 1.5


def test_oversizing_reasons() -> None:
    assert oversizing(load(), None).reason == NO_RATED_POWER
    assert oversizing(None, 8.0).reason == HEAT_LOAD_INSUFFICIENT
    assert oversizing(HeatLoad(sufficient=False), 8.0).reason == HEAT_LOAD_INSUFFICIENT
    no_design = oversizing(load(None), 8.0, min_kw=1.0)
    assert no_design.reason == NO_DESIGN_TEMP and no_design.factor is None
    assert no_design.cycling_expected is False  # 1.28 kW at +7 °C >= 1 kW


def test_no_cycling_expected_above_the_heating_limit() -> None:
    warm = HeatLoad(sufficient=True, intercept_kw=0.8, slope_kw_per_k=-0.16)
    result = oversizing(warm, 8.0, min_kw=2.0)
    assert result.load_mild_kw == 0.0 and result.cycling_expected is False


# 4.8 Standby.


def standby_entries(recent_w: float, reference_w: float) -> list[dict[str, Any]]:
    """30 + 7 days with 10 run hours, 14 idle hours (24-hour December days)."""
    result = []
    for n, day in enumerate(days_before(TODAY, 37)):
        watts = reference_w if n < 30 else recent_w
        energy = {"heat_heating": 40.0, "standby_heating": watts * 14 / 1000}
        result.append(entry(day, energy=energy))
    return result


def test_standby_day() -> None:
    kwh, hours = standby_day(entry(TODAY), BERLIN) or (0, 0)
    assert kwh == pytest.approx(0.35) and hours == pytest.approx(14)
    assert standby_day(entry(TODAY, energy=None), BERLIN) is None
    assert standby_day(entry(TODAY, run_seconds=23 * H), BERLIN) is None


def test_constant_model_value_is_no_rise() -> None:
    result = standby_rise(standby_entries(25.0, 25.0), TODAY, BERLIN)
    assert result.problem is False
    assert result.evidence["mean_power_w_7d"] == pytest.approx(25.0)
    assert result.evidence["min_day_w"] == result.evidence["max_day_w"]


def test_standby_rise_needs_percent_and_watts() -> None:
    assert standby_rise(standby_entries(40.0, 25.0), TODAY, BERLIN).problem is True
    # +60 % but only +6 W.
    assert standby_rise(standby_entries(16.0, 10.0), TODAY, BERLIN).problem is False
    # +12 W but only +20 %.
    assert standby_rise(standby_entries(72.0, 60.0), TODAY, BERLIN).problem is False


def test_standby_unknown() -> None:
    no_standby = [
        entry(d, energy={"heat_heating": 40.0}) for d in days_before(TODAY, 37)
    ]
    assert standby_rise(no_standby, TODAY, BERLIN).reason == NO_STANDBY
    young = standby_entries(25.0, 25.0)[-10:]  # 3 reference days
    result = standby_rise(young, TODAY, BERLIN)
    assert result.problem is None and result.reason == TOO_FEW_DAYS
    assert result.evidence["mean_power_w_7d"] == pytest.approx(25.0)


# 4.10 e Flow.


def test_expected_flow() -> None:
    # 5 kW at 5 K: 5000 / (1.163 × 5) = 860 l/h.
    assert expected_flow(5.0, H, 5.0) == pytest.approx(859.8, abs=0.1)


def test_plausible_flow() -> None:
    spread = Mean(5.0 * 4 * H, 4 * H)
    flow = Mean(800.0 * 4 * H, 4 * H)
    result = flow_plausibility(20.0, spread, flow)
    assert result.problem is False
    assert result.evidence["expected_lph"] == 860
    assert result.evidence["ratio"] == pytest.approx(0.93, abs=0.01)


def test_unit_error_is_implausible() -> None:
    """l/h reported as L/min: converted to l/h, the flow is 60 times too high."""
    spread = Mean(5.0 * 4 * H, 4 * H)
    flow = Mean(to_lph(800, "L/min") * 4 * H, 4 * H)
    assert flow_plausibility(20.0, spread, flow).problem is True
    zero = Mean(0.0, 4 * H)
    assert flow_plausibility(20.0, spread, zero).problem is True


def test_flow_unknown() -> None:
    spread = Mean(5.0 * 4 * H, 4 * H)
    flow = Mean(800.0 * 4 * H, 4 * H)
    short = Mean(5.0 * 1800, 1800)
    assert flow_plausibility(20.0, short, flow).reason == TOO_LITTLE_HEATING
    assert flow_plausibility(0.5, spread, flow).reason == TOO_LITTLE_HEATING
    small = Mean(1.5 * 4 * H, 4 * H)
    assert flow_plausibility(20.0, small, flow).reason == SPREAD_TOO_SMALL
    assert flow_plausibility(20.0, spread, Mean()).reason == NO_FLOW_RATE


def test_flow_from_diary_entry() -> None:
    day = entry(TODAY, flow_rate={"weighted": 700.0 * 9 * H, "seconds": 9 * H})
    result = flow_plausibility_entry(day)
    assert result.problem is False and result.evidence["day"] == TODAY.isoformat()
    assert flow_plausibility_entry(entry(TODAY)).reason == NO_FLOW_RATE


def test_zero_flow() -> None:
    zero = ZeroFlow()
    for _ in range(14):
        zero.add(0.0, 60)
    assert not zero.problem
    zero.add(None, 60)  # unknown changes nothing
    assert zero.seconds == 840
    zero.add(0.0, 60)
    assert zero.problem
    zero.add(850.0, 60)
    assert not zero.problem and zero.seconds == 0
