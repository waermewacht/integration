"""Gas boiler before the switch: hot water split, heat load, degree days, costs."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.gas import (
    COUNTER,
    FLOW_BY_CIRCUIT,
    FLOW_BY_HEAT,
    FLOW_NEEDS_DHW_COUNTER,
    HEATING_ONLY,
    NO_SUMMER_DAYS,
    SUMMER_BASE,
    analyse,
    split_dhw,
    summer_base,
    volume_to_kwh,
    window,
)
from custom_components.waermewacht.periods import local_midnight

TZ = ZoneInfo("Europe/Berlin")
ETA = 0.87
LOSS_KW_PER_K = 0.1  # 100 W/K
LIMIT = 15.0  # °C
DHW_PER_DAY = 6.0  # kWh gas


def day_mean(day: date) -> float:
    """-4 … 22 °C over the year, coldest in mid January."""
    angle = 2 * math.pi * (day - date(2026, 1, 15)).days / 365
    return 9.0 - 13.0 * math.cos(angle)


def house(first: date, days: int) -> tuple[dict, dict, dict]:
    """Hourly outdoor means, total gas and hot water gas of a test house."""
    outdoor: dict[datetime, float] = {}
    total: dict[datetime, float] = {}
    water: dict[datetime, float] = {}
    for n in range(days):
        day = first + timedelta(days=n)
        start, end = local_midnight(day, TZ), local_midnight(day + timedelta(1), TZ)
        hours = int((end - start) / timedelta(hours=1))
        mean = day_mean(day)
        heating_kw = max(0.0, LOSS_KW_PER_K * (LIMIT - mean))
        for h in range(hours):
            hour = start + timedelta(hours=h)
            outdoor[hour] = mean
            water[hour] = DHW_PER_DAY / hours
            total[hour] = heating_kw / ETA + water[hour]
    return outdoor, total, water


YEAR_START = date(2025, 10, 30)
OUTDOOR, TOTAL, WATER = house(YEAR_START, 365)
END = YEAR_START + timedelta(days=365)


def test_summer_base_is_the_hot_water_of_warm_days() -> None:
    base, count = summer_base(TOTAL, OUTDOOR, TZ)
    assert base == pytest.approx(DHW_PER_DAY)
    assert count > 60


def test_a_total_counter_loses_the_summer_base_every_day() -> None:
    split = split_dhw(TOTAL, OUTDOOR, TZ, includes_dhw=True)
    assert split.method == SUMMER_BASE
    assert split.summer_base_kwh == pytest.approx(DHW_PER_DAY)
    assert sum(split.dhw.values()) == pytest.approx(DHW_PER_DAY * 365)
    assert sum(split.heating.values()) == pytest.approx(
        sum(TOTAL.values()) - DHW_PER_DAY * 365
    )


def test_without_summer_days_nothing_is_subtracted() -> None:
    winter = {h: v for h, v in TOTAL.items() if h < datetime(2026, 3, 1, tzinfo=UTC)}
    split = split_dhw(winter, OUTDOOR, TZ, includes_dhw=True)
    assert split.method == NO_SUMMER_DAYS
    assert split.dhw == {}
    assert split.heating == winter
    assert not split.dhw_known


def test_hot_water_counter_and_heating_counter() -> None:
    from_total = split_dhw(TOTAL, OUTDOOR, TZ, includes_dhw=True, dhw=WATER)
    assert from_total.method == COUNTER
    heating = {h: TOTAL[h] - WATER[h] for h in TOTAL}
    assert from_total.heating == pytest.approx(heating)
    # A heating counter next to a hot water counter (ViCare) stays as it is.
    beside = split_dhw(heating, OUTDOOR, TZ, includes_dhw=False, dhw=WATER)
    assert beside.heating == heating
    only = split_dhw(heating, OUTDOOR, TZ, includes_dhw=False)
    assert (only.method, only.dhw) == (HEATING_ONLY, {})


def test_heat_load_of_the_test_house() -> None:
    result = analyse(
        TOTAL, OUTDOOR, TZ, YEAR_START, END, includes_dhw=True, design_temp=-12.0
    )
    load = result.heat_load
    assert load.sufficient
    assert load.slope_kw_per_k == pytest.approx(-LOSS_KW_PER_K, rel=1e-6)
    assert load.heating_limit == pytest.approx(LIMIT, abs=0.01)
    assert load.standard_kw == pytest.approx(LOSS_KW_PER_K * 32, rel=1e-6)
    assert result.dhw_share == pytest.approx(
        100 * DHW_PER_DAY * 365 / sum(TOTAL.values())
    )
    assert result.gas_days == 365
    assert result.reasons == []


def test_hot_water_left_in_moves_the_heating_limit_not_the_heat_load() -> None:
    result = analyse(
        TOTAL, OUTDOOR, TZ, YEAR_START, END, includes_dhw=False, design_temp=-12.0
    )
    load = result.heat_load
    # The hot water base spreads over 23 or 25 hours in DST weeks: tiny noise.
    assert load.slope_kw_per_k == pytest.approx(-LOSS_KW_PER_K, rel=1e-3)
    assert load.standard_kw == pytest.approx(LOSS_KW_PER_K * 32, rel=1e-3)
    assert load.heating_limit > LIMIT + 1
    assert result.dhw_share is None


def test_efficiency_scales_the_heat_load() -> None:
    result = analyse(
        TOTAL, OUTDOOR, TZ, YEAR_START, END, includes_dhw=True, efficiency=ETA / 2
    )
    assert result.heat_load.slope_kw_per_k == pytest.approx(-LOSS_KW_PER_K / 2)
    assert result.heat_kwh == pytest.approx(sum(TOTAL.values()) * ETA / 2)


def test_heat_per_degree_day_uses_the_heating_heat() -> None:
    result = analyse(TOTAL, OUTDOOR, TZ, YEAR_START, END, includes_dhw=True)
    days = result.degree_days
    # G20/15: heat per K·d of a house with 0.1 kW/K and a limit of 15 °C is
    # 2.4 kWh per K below 15 °C, spread over 20 - T.
    assert days.kwh_per_degree_day is not None
    assert 1.0 < days.kwh_per_degree_day < 2.4
    assert days.heating_kwh == pytest.approx(
        sum(
            LOSS_KW_PER_K * max(0.0, LIMIT - day_mean(YEAR_START + timedelta(n))) * 24
            for n in range(365)
        ),
        rel=0.01,
    )


def test_only_hours_of_the_window_count_and_costs() -> None:
    start, end = date(2026, 1, 1), date(2026, 1, 8)
    result = analyse(
        TOTAL,
        OUTDOOR,
        TZ,
        start,
        end,
        includes_dhw=True,
        gas_price=0.12,
        gas_base_price=365.0,
    )
    first, last = local_midnight(start, TZ), local_midnight(end, TZ)
    gas = sum(v for h, v in TOTAL.items() if first <= h < last)
    assert result.gas_kwh == pytest.approx(gas)
    assert result.gas_days == 7
    assert result.base_cost_eur == pytest.approx(7.0)
    assert result.cost_eur == pytest.approx(gas * 0.12 + 7.0)
    # Too few days for the heat load; no summer days in a January week.
    assert not result.heat_load.sufficient
    assert result.reasons == [NO_SUMMER_DAYS]


def test_volume_to_kwh() -> None:
    hour = datetime(2026, 1, 1, tzinfo=UTC)
    assert volume_to_kwh({hour: 2.0}, 11.2, 0.95)[hour] == pytest.approx(21.28)
    with pytest.raises(ValueError):
        volume_to_kwh({hour: 2.0}, 0.0, 0.95)


def test_window_is_the_last_365_full_days() -> None:
    now = datetime(2026, 10, 30, 2, 30, tzinfo=UTC)  # 03:30 local
    assert window(now, TZ) == (date(2025, 10, 30), date(2026, 10, 30))


def flow_line(outdoor: dict[datetime, float]) -> dict[datetime, float]:
    """A heating curve: 35 °C flow at 0 °C, 0.8 K more per K colder."""
    return {hour: 35.0 - 0.8 * mean for hour, mean in outdoor.items()}


FLOW = flow_line(OUTDOOR)
HEATING = {hour: TOTAL[hour] - WATER[hour] for hour in TOTAL}


def test_flow_at_zero_and_at_design_temperature() -> None:
    result = analyse(
        HEATING,
        OUTDOOR,
        TZ,
        YEAR_START,
        END,
        includes_dhw=False,
        design_temp=-12.0,
        flow=FLOW,
    )
    assert result.flow is not None
    assert result.flow_reason is None
    assert result.flow_selection == FLOW_BY_HEAT
    assert result.flow.at_zero == pytest.approx(35.0, abs=0.01)
    assert result.flow.slope == pytest.approx(-0.8, abs=0.001)
    assert result.flow_at_design == pytest.approx(44.6, abs=0.01)


def test_flow_leaves_out_the_hours_of_hot_water_charges() -> None:
    """One charge a day lifts the flow to 65 °C; the hot water counter shows
    the hour, so it does not count."""
    charge = {
        hour: DHW_PER_DAY if hour.astimezone(TZ).hour == 6 else 0.0 for hour in TOTAL
    }
    total = {hour: HEATING[hour] + charge[hour] for hour in TOTAL}
    flow = {hour: 65.0 if charge[hour] else value for hour, value in FLOW.items()}
    result = analyse(
        total, OUTDOOR, TZ, YEAR_START, END, includes_dhw=True, dhw=charge, flow=flow
    )
    assert result.flow is not None
    assert result.flow.at_zero == pytest.approx(35.0, abs=0.01)
    # Without a design temperature only the value at 0 °C.
    assert result.flow_at_design is None


def test_flow_needs_the_hot_water_hours() -> None:
    """With the summer base every hour has a hot water share: no flow."""
    result = analyse(TOTAL, OUTDOOR, TZ, YEAR_START, END, includes_dhw=True, flow=FLOW)
    assert result.flow is None
    assert result.flow_reason == FLOW_NEEDS_DHW_COUNTER
    assert result.flow_selection == FLOW_BY_HEAT
    # Without a flow entity: nothing, and no reason.
    plain = analyse(TOTAL, OUTDOOR, TZ, YEAR_START, END, includes_dhw=True)
    assert plain.flow is None
    assert plain.flow_reason is None
    assert plain.flow_selection is None
    # The box alone (without a flow entity) changes nothing.
    ticked = analyse(
        TOTAL, OUTDOOR, TZ, YEAR_START, END, includes_dhw=True, flow_in_circuit=True
    )
    assert ticked.flow is None
    assert ticked.flow_selection is None


def buffer_system() -> tuple[dict[datetime, float], dict[datetime, float]]:
    """Gas boiler and solar thermal charge a buffer; the radiator circuit
    runs from it through a mixing valve, the sensor sits after the mixer.

    The burner fires only from 0 to 3 o'clock (buffer charge, hot water on
    top), on every third day not at all (solar). The circuit runs from 6 to
    22 o'clock on the heating curve (35 °C at 0 °C, 0.8 K per K), at night it
    is off and the sensor at room level (20 °C); in summer it is off, and the
    warm boiler room keeps the sensor at 27 °C. Hot water charges never
    reach it."""
    gas: dict[datetime, float] = {}
    flow: dict[datetime, float] = {}
    for hour, mean in OUTDOOR.items():
        local = hour.astimezone(TZ)
        solar = local.date().toordinal() % 3 == 0
        gas[hour] = 0.0 if solar or local.hour >= 3 else 8.0
        if mean >= LIMIT:
            flow[hour] = 27.0
        elif 6 <= local.hour < 22:
            flow[hour] = 35.0 - 0.8 * mean
        else:
            flow[hour] = 20.0
    return gas, flow


def test_flow_sensor_in_the_heating_circuit() -> None:
    """With the box the running circuit chooses the hours: no hot water
    counter needed, burner hours and solar days do not matter."""
    gas, flow = buffer_system()
    old = analyse(gas, OUTDOOR, TZ, YEAR_START, END, includes_dhw=True, flow=flow)
    assert old.flow is None
    assert old.flow_reason == FLOW_NEEDS_DHW_COUNTER
    result = analyse(
        gas,
        OUTDOOR,
        TZ,
        YEAR_START,
        END,
        includes_dhw=True,
        design_temp=-12.0,
        flow=flow,
        flow_in_circuit=True,
    )
    assert result.flow_reason is None
    assert result.flow_selection == FLOW_BY_CIRCUIT
    assert result.flow is not None
    assert result.flow.reasons == ()
    assert result.flow.at_zero == pytest.approx(35.0, abs=0.01)
    assert result.flow.slope == pytest.approx(-0.8, abs=0.001)
    assert result.flow_at_design == pytest.approx(44.6, abs=0.01)
    # Summer (warm boiler room) and the hours below 25 °C are left out.
    assert max(d.mean_outdoor for d in result.flow.days) < LIMIT
    # Solar days count as well (no gas that day).
    solar = {d.day for d in result.flow.days if d.day.toordinal() % 3 == 0}
    assert solar
    # By the burner hours instead (a heating counter): the night flow of a
    # circuit at rest, a wrong line.
    by_gas = analyse(gas, OUTDOOR, TZ, YEAR_START, END, includes_dhw=False, flow=flow)
    assert by_gas.flow is not None
    assert by_gas.flow.at_zero != pytest.approx(35.0, abs=1.0)


def test_flow_in_the_circuit_with_too_few_days() -> None:
    gas, flow = buffer_system()
    first = date(2026, 1, 10)
    short = {
        h: v
        for h, v in flow.items()
        if local_midnight(first, TZ) <= h < local_midnight(first + timedelta(10), TZ)
    }
    result = analyse(
        gas,
        OUTDOOR,
        TZ,
        YEAR_START,
        END,
        includes_dhw=True,
        flow=short,
        flow_in_circuit=True,
    )
    assert result.flow is not None
    assert result.flow.at_zero is None
    assert result.flow.reasons[0] == "too_few_days"
    assert result.flow_reason is None
