"""Heat load: weekly energy signature, minimum data, measured and standard."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.energy import Kind, Totals
from custom_components.waermewacht.heat_load import (
    SLOPE_NOT_NEGATIVE,
    SPREAD_TOO_SMALL,
    TOO_FEW_FROST_DAYS,
    TOO_FEW_WEEKS,
    fit_line,
    heat_load,
    heat_load_as_dict,
)
from custom_components.waermewacht.model import Mode

BERLIN = ZoneInfo("Europe/Berlin")
START = date(2026, 10, 19)  # Monday; Sunday 25 October has 25 hours
A = 2.4  # kW at 0 °C (made up)
B = -0.16  # kW/K (made up): heating limit 15 °C
OFFSETS = (-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0)  # day temps around the week mean
# Ten weeks, mean outdoor 10 … -6 °C: spread 16 K, plenty of frost days.
WEEKS = (10.0, 8.0, 6.0, 4.0, 2.0, 0.0, -2.0, -4.0, -6.0, 3.0)


def day_hours(day: date) -> list[datetime]:
    """UTC hour starts of a local Berlin day (23, 24 or 25)."""
    start = datetime.combine(day, time(0), tzinfo=BERLIN).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=BERLIN)
    hours = []
    while start < end:
        hours.append(start)
        start += timedelta(hours=1)
    return hours


def build(
    week_means: Sequence[float],
    *,
    a: float = A,
    b: float = B,
    offsets: Sequence[float] = OFFSETS,
    noise: Sequence[float] = (),
) -> tuple[dict[datetime, Totals], dict[datetime, float]]:
    """Hourly heating power a + b·T of the day's temperature, plus hot water
    and standby that must not count."""
    hours: dict[datetime, Totals] = {}
    outdoor: dict[datetime, float] = {}
    for week, mean in enumerate(week_means):
        shift = noise[week] if noise else 0.0
        for n, offset in enumerate(offsets):
            temp = mean + offset
            for hour in day_hours(START + timedelta(days=7 * week + n)):
                totals = Totals()
                totals.add(Kind.HEAT, Mode.HEATING, a + b * temp + shift)
                totals.add(Kind.ELEC, Mode.HEATING, (a + b * temp) / 4)
                totals.add(Kind.STANDBY, Mode.HEATING, 0.025)
                totals.add(Kind.HEAT, Mode.DHW, 0.3)
                hours[hour] = totals
                outdoor[hour] = temp
    return hours, outdoor


def test_fit_line_recovers_exact_line() -> None:
    a, b, r2 = fit_line([(-5.0, 3.2), (0.0, 2.4), (5.0, 1.6)])
    assert a == pytest.approx(2.4)
    assert b == pytest.approx(-0.16)
    assert r2 == pytest.approx(1.0)


def test_clean_signature_recovers_line() -> None:
    hours, outdoor = build(WEEKS)
    result = heat_load(hours, outdoor, BERLIN, design_temp=-12.0)
    assert result.sufficient
    assert result.reasons == []
    assert len(result.weeks) == 10
    assert result.intercept_kw == pytest.approx(A)
    assert result.slope_kw_per_k == pytest.approx(B)
    assert result.r_squared == pytest.approx(1.0)
    assert result.heating_limit == pytest.approx(15.0)
    assert result.measured_kw == pytest.approx(A + B * -12.0)  # 4.32 kW
    # Standard: same slope, line through 0 at 20 °C.
    assert result.standard_kw == pytest.approx(-B * (20 - -12.0))  # 5.12 kW
    assert result.standard_kw > result.measured_kw


def test_noisy_signature_within_tolerance() -> None:
    noise = (0.05, -0.05, 0.03, -0.04, 0.05, -0.05, 0.02, -0.03, 0.04, -0.05)
    hours, outdoor = build(WEEKS, noise=noise)
    result = heat_load(hours, outdoor, BERLIN)
    assert result.sufficient
    assert result.intercept_kw == pytest.approx(A, abs=0.05)
    assert result.slope_kw_per_k == pytest.approx(B, abs=0.01)
    assert result.r_squared > 0.95
    assert result.measured_kw is None  # no design temperature given
    assert result.standard_kw is None


def test_dst_week_has_169_real_hours() -> None:
    hours, outdoor = build(WEEKS)
    week = heat_load(hours, outdoor, BERLIN).weeks[0]
    assert week.start == START
    assert week.days == 7
    assert week.hours == 169
    # Hour-weighted: the 25-hour Sunday (+3 K) pulls the mean up a little.
    assert week.mean_outdoor == pytest.approx(10.0 + 3.0 / 169)
    assert week.power_kw == pytest.approx(A + B * week.mean_outdoor)
    assert week.frost_days == 0


def test_weeks_start_monday_local() -> None:
    hours, outdoor = build(WEEKS)
    # Shift the data by one day: each Monday moves into the previous week.
    shifted_hours = {h + timedelta(days=1): t for h, t in hours.items()}
    shifted_outdoor = {h + timedelta(days=1): t for h, t in outdoor.items()}
    weeks = heat_load(shifted_hours, shifted_outdoor, BERLIN).weeks
    assert all(w.start.weekday() == 0 for w in weeks)
    assert weeks[0].start == START
    assert weeks[0].days == 6  # Tuesday to Sunday


def test_insufficient_data_names_all_reasons() -> None:
    hours, outdoor = build(WEEKS[:5])  # 10 … 2 °C
    result = heat_load(hours, outdoor, BERLIN, design_temp=-12.0)
    assert not result.sufficient
    assert result.reasons == [TOO_FEW_WEEKS, SPREAD_TOO_SMALL, TOO_FEW_FROST_DAYS]
    assert len(result.weeks) == 5
    assert result.spread == pytest.approx(8.0, abs=0.1)
    assert result.frost_days == 1  # 2 °C week, first day -1 °C
    assert result.slope_kw_per_k is None
    assert result.measured_kw is None
    assert result.standard_kw is None


def test_frost_days_alone_missing() -> None:
    means = (11.5, 10.0, 8.5, 7.0, 5.5, 4.0, 2.5, 1.0)
    hours, outdoor = build(means, offsets=(0.0,) * 7)
    result = heat_load(hours, outdoor, BERLIN)
    assert result.reasons == [TOO_FEW_FROST_DAYS]
    assert result.frost_days == 0


def test_no_data() -> None:
    result = heat_load({}, {}, BERLIN)
    assert not result.sufficient
    assert result.reasons == [TOO_FEW_WEEKS, SPREAD_TOO_SMALL, TOO_FEW_FROST_DAYS]
    assert result.spread is None


def test_warm_weeks_are_left_out() -> None:
    # Every day at the week mean: the warm weeks still have heating days.
    hours, outdoor = build((*WEEKS, 12.0, 14.0), offsets=(0.0,) * 7)
    result = heat_load(hours, outdoor, BERLIN)
    assert len(result.weeks) == 10
    assert result.slope_kw_per_k == pytest.approx(B)
    wider = heat_load(hours, outdoor, BERLIN, max_outdoor=15.0)
    assert len(wider.weeks) == 12


def test_week_mean_of_its_heating_days() -> None:
    """A 12 °C week with a day beyond the heating limit (15 °C): that day
    drops out, the six others enter at their mean of 11.5 °C, on the line."""
    hours, outdoor = build((*WEEKS, 12.0))
    week = heat_load(hours, outdoor, BERLIN).weeks[-1]
    assert (week.days, week.mean_outdoor) == (6, pytest.approx(11.5))
    assert week.power_kw == pytest.approx(A + B * 11.5)


def test_week_needs_six_full_days() -> None:
    hours, outdoor = build(WEEKS)
    second = START + timedelta(days=7)
    for day in (second, second + timedelta(days=1)):
        for hour in day_hours(day)[:5]:
            del outdoor[hour]  # 19 values: not a full day
    third = START + timedelta(days=14)
    for hour in day_hours(third)[:4]:
        del outdoor[hour]  # 20 values: still full
    weeks = {w.start: w for w in heat_load(hours, outdoor, BERLIN).weeks}
    assert second not in weeks
    assert weeks[third].days == 7
    assert weeks[third].hours == 7 * 24 - 4


def test_days_before_the_energy_data_do_not_count() -> None:
    """The meters were recorded later than the outdoor temperature: the
    weeks before have outdoor values but no energy and must not enter as
    0 kW."""
    hours, outdoor = build(WEEKS)
    full = heat_load(hours, outdoor, BERLIN, design_temp=-12.0)
    # Three frosty weeks before: outdoor values only.
    _, before = build((-1.0, -3.0, -5.0))
    before = {hour - timedelta(days=21): value for hour, value in before.items()}
    result = heat_load(hours, {**before, **outdoor}, BERLIN, design_temp=-12.0)
    assert len(result.weeks) == len(full.weeks)
    assert all(w.power_kw > 0 for w in result.weeks)
    assert result.slope_kw_per_k == pytest.approx(full.slope_kw_per_k)


def test_days_without_heating_do_not_count() -> None:
    """Summer mode held by hand in a cool autumn week: the heating was off,
    which says nothing about the building."""
    hours, outdoor = build(WEEKS)
    full = heat_load(hours, outdoor, BERLIN, design_temp=-12.0)
    # Two more cool weeks before, all days without heating heat.
    before, temps = build((9.0, 11.0))
    shift = timedelta(days=14)
    for totals in before.values():
        totals.values.pop(Totals.key(Kind.HEAT, Mode.HEATING))
    hours = {**{h - shift: t for h, t in before.items()}, **hours}
    outdoor = {**{h - shift: v for h, v in temps.items()}, **outdoor}
    result = heat_load(hours, outdoor, BERLIN, design_temp=-12.0)
    assert len(result.weeks) == len(full.weeks)
    assert result.slope_kw_per_k == pytest.approx(full.slope_kw_per_k)
    # One day off in a heating week: the week keeps its six heating days.
    for hour in day_hours(START + timedelta(days=7)):
        hours[hour].values.pop(Totals.key(Kind.HEAT, Mode.HEATING))
    weeks = {w.start: w for w in heat_load(hours, outdoor, BERLIN).weeks}
    assert weeks[START + timedelta(days=7)].days == 6


def test_day_with_cooling_does_not_count() -> None:
    hours, outdoor = build(WEEKS)
    for hour in day_hours(START + timedelta(days=9))[:1]:
        hours[hour].add(Kind.HEAT, Mode.COOLING, 0.5)
    weeks = heat_load(hours, outdoor, BERLIN).weeks
    assert weeks[1].days == 6


def test_rising_power_is_not_a_signature() -> None:
    hours, outdoor = build(WEEKS, a=1.0, b=0.05)
    result = heat_load(hours, outdoor, BERLIN, design_temp=-12.0)
    assert not result.sufficient
    assert result.reasons == [SLOPE_NOT_NEGATIVE]
    assert result.heating_limit is None
    assert result.measured_kw is None


def test_result_as_dict() -> None:
    hours, outdoor = build(WEEKS)
    data = heat_load_as_dict(heat_load(hours, outdoor, BERLIN, design_temp=-12.0))
    assert data["sufficient"] is True
    assert data["reasons"] == []
    assert data["week_count"] == 10
    assert data["slope_kw_per_k"] == -0.16
    assert data["intercept_kw"] == 2.4
    assert data["heating_limit"] == 15.0
    assert data["measured_kw"] == 4.32
    assert data["standard_kw"] == 5.12
    assert data["design_temp"] == -12.0
    assert data["weeks"][0] == {
        "start": "2026-10-19",
        "days": 7,
        "hours": 169,
        "mean_outdoor": 10.0,
        "power_kw": round(A + B * (10 + 3 / 169), 3),
    }
