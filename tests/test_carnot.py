"""Carnot efficiency factor (health check 4.14), invented values."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.carnot import (
    SKIP_AUX,
    SKIP_LITTLE_HEATING,
    SKIP_NO_ENERGY,
    SKIP_NO_OUTDOOR,
    SKIP_SMALL_LIFT,
    TOO_FEW_DAYS,
    TOO_LITTLE_ELECTRICITY,
    FactorDay,
    carnot_cop,
    efficiency_factor,
    factor_attributes,
    factor_day,
    factor_spans,
    field_reference,
    statistics_days,
    winter_span,
)
from custom_components.waermewacht.energy import Totals

H = 3600.0
DAY = date(2026, 12, 1)


def mean(value: float, hours: float) -> dict[str, float]:
    return {"weighted": value * hours * H, "seconds": hours * H}


def entry(
    day: date = DAY,
    *,
    heat: float = 40.0,
    elec: float = 10.0,
    aux: float = 0.0,
    flow: float | None = 35.0,
    spread: float | None = 5.0,
    outdoor_heating: float | None = 0.0,
    outdoor: float | None = 2.0,
    hours: float = 12.0,
) -> dict[str, Any]:
    energy = {"heat_heating": heat, "elec_heating": elec}
    if aux:
        energy["aux_heating"] = aux
    return {
        "day": day.isoformat(),
        "outdoor": outdoor,
        "energy": energy,
        "flow": mean(flow, hours) if flow is not None else {},
        "spread": mean(spread, hours) if spread is not None else {},
        "outdoor_heating": mean(outdoor_heating, hours)
        if outdoor_heating is not None
        else {},
    }


def test_carnot_cop() -> None:
    # Sink 32.5 °C (flow 35, spread 5), source 0 °C: 305.65 K / 32.5 K.
    assert carnot_cop(32.5, 0.0) == pytest.approx(9.405, abs=1e-3)
    assert carnot_cop(35.0, 0.0) == pytest.approx(8.804, abs=1e-3)
    assert carnot_cop(20.0, 12.0) is None  # lift below 10 K


def test_day_uses_mean_of_flow_and_return_and_outdoor_while_heating() -> None:
    day = factor_day(entry())
    assert not isinstance(day, str)
    assert day.sink == pytest.approx(32.5)
    assert day.source == 0.0
    assert not day.flow_only and not day.day_mean_source
    assert day.cop == pytest.approx(9.405, abs=1e-3)


def test_day_fallbacks() -> None:
    no_return = factor_day(entry(spread=None))
    assert not isinstance(no_return, str)
    assert no_return.flow_only and no_return.sink == 35.0
    swapped = factor_day(entry(spread=-4.0))
    assert not isinstance(swapped, str) and swapped.flow_only
    old = factor_day(entry(outdoor_heating=None))
    assert not isinstance(old, str)
    assert old.day_mean_source and old.source == 2.0


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"heat": 0.0}, SKIP_NO_ENERGY),
        ({"elec": 0.0}, SKIP_NO_ENERGY),
        ({"hours": 1.5}, SKIP_LITTLE_HEATING),
        ({"flow": None}, SKIP_LITTLE_HEATING),
        ({"aux": 2.0}, SKIP_AUX),
        ({"outdoor_heating": None, "outdoor": None}, SKIP_NO_OUTDOOR),
        ({"flow": 25.0, "spread": 4.0, "outdoor_heating": 14.0}, SKIP_SMALL_LIFT),
    ],
)
def test_day_skipped(kwargs: dict[str, Any], reason: str) -> None:
    assert factor_day(entry(**kwargs)) == reason


def test_day_without_energy_key() -> None:
    assert factor_day({"day": DAY.isoformat(), "energy": None}) == SKIP_NO_ENERGY


def test_factor_is_ideal_over_real_electricity() -> None:
    # COP 4 at a Carnot COP of 9.405: factor 0.425.
    days = [entry(DAY + timedelta(days=i)) for i in range(14)]
    result = efficiency_factor(days, DAY, DAY + timedelta(days=13), min_days=14)
    assert result.reason is None and result.days == 14
    assert result.value == pytest.approx(4.0 / 9.405, abs=1e-3)
    assert result.carnot_cop == pytest.approx(9.405, abs=1e-3)
    attributes = result.as_attributes()
    assert attributes["sink"] == "mean_flow_return"
    assert attributes["source"] == "while_heating"
    assert attributes["sink_temp"] == 32.5 and attributes["source_temp"] == 0.0


def test_factor_is_heat_weighted() -> None:
    # A cold day with much heat and a mild day with little: the cold one
    # dominates. Same factor 0.4 on both days gives 0.4 overall.
    cold_cop = carnot_cop(40.0 - 2.5, -5.0)
    mild_cop = carnot_cop(30.0 - 2.5, 12.0)
    assert cold_cop and mild_cop
    cold = entry(
        heat=60.0, elec=60.0 / (0.4 * cold_cop), flow=40.0, outdoor_heating=-5.0
    )
    mild = entry(
        DAY + timedelta(days=1),
        heat=5.0,
        elec=5.0 / (0.4 * mild_cop),
        flow=30.0,
        outdoor_heating=12.0,
    )
    result = efficiency_factor([cold, mild], DAY, DAY + timedelta(days=1), min_days=2)
    assert result.value == pytest.approx(0.4)
    assert result.source == pytest.approx((60 * -5.0 + 5 * 12.0) / 65)


def test_factor_window_and_reasons() -> None:
    days = [entry(DAY + timedelta(days=i)) for i in range(10)]
    days.append(entry(DAY + timedelta(days=10), aux=3.0))
    inside = efficiency_factor(days, DAY, DAY + timedelta(days=4), min_days=7)
    assert inside.value is None and inside.reason == TOO_FEW_DAYS
    assert inside.days == 5
    every = efficiency_factor(days, DAY, DAY + timedelta(days=10), min_days=7)
    assert every.days == 10 and every.skipped == {SKIP_AUX: 1}
    little = efficiency_factor(
        days, DAY, DAY + timedelta(days=9), min_days=7, min_electricity=500.0
    )
    assert little.value is None and little.reason == TOO_LITTLE_ELECTRICITY


def test_flow_only_is_marked() -> None:
    days = [entry(DAY + timedelta(days=i), spread=None) for i in range(7)]
    result = efficiency_factor(days, DAY, DAY + timedelta(days=6), min_days=7)
    assert result.flow_only_days == 7
    assert result.as_attributes()["sink"] == "flow_only"
    # The Carnot COP of the flow alone is smaller: the factor comes out higher.
    assert result.value == pytest.approx(4.0 / 8.804, abs=1e-3)


def test_field_reference() -> None:
    reference = field_reference()
    assert reference["mean"] == 0.39
    assert (reference["min"], reference["max"]) == (0.32, 0.44)


# Look-back from the hourly statistics.

BERLIN = ZoneInfo("Europe/Berlin")


def hourly(
    day: date,
    hours: int,
    *,
    heat: float = 1.0,
    elec: float = 0.25,
    aux: float = 0.0,
    dhw: float = 0.0,
    flow: float = 35.0,
    ret: float | None = 30.0,
    outdoor: float = 0.0,
) -> tuple[dict, dict, dict, dict]:
    """`hours` heating hours from 06:00 local of `day`."""
    totals, flows, rets, outs = {}, {}, {}, {}
    first = datetime.combine(day, time(6), tzinfo=BERLIN).astimezone(UTC)
    for n in range(hours):
        hour = first + timedelta(hours=n)
        values = {"heat_heating": heat, "elec_heating": elec}
        if aux:
            values["aux_heating"] = aux
        if dhw:
            values["heat_dhw"] = dhw
        totals[hour] = Totals(values)
        flows[hour] = flow
        if ret is not None:
            rets[hour] = ret
        outs[hour] = outdoor
    return totals, flows, rets, outs


def test_statistics_day() -> None:
    days = statistics_days(*hourly(DAY, 10), BERLIN)
    found = days[DAY]
    assert isinstance(found, FactorDay) and found.from_statistics
    assert found.heat == pytest.approx(10.0) and found.electricity == pytest.approx(2.5)
    assert found.sink == pytest.approx(32.5) and found.source == 0.0
    assert found.cop == pytest.approx(9.405, abs=1e-3)
    assert not found.flow_only


def test_statistics_day_reasons() -> None:
    assert statistics_days(*hourly(DAY, 1), BERLIN)[DAY] == SKIP_LITTLE_HEATING
    assert statistics_days(*hourly(DAY, 5, aux=1.0), BERLIN)[DAY] == SKIP_AUX
    # Hot water in every hour: no heating-only hour.
    assert statistics_days(*hourly(DAY, 5, dhw=0.5), BERLIN)[DAY] == SKIP_LITTLE_HEATING
    # Too little heat per hour (0.3 kWh is the limit).
    assert (
        statistics_days(*hourly(DAY, 5, heat=0.2), BERLIN)[DAY] == SKIP_LITTLE_HEATING
    )
    without_return = statistics_days(*hourly(DAY, 5, ret=None), BERLIN)[DAY]
    assert isinstance(without_return, FactorDay) and without_return.flow_only


def test_diary_while_heating_wins_statistics_fill_in() -> None:
    # Days 1-7 only in the statistics (before the setup), days 8-14 in the
    # diary with the outdoor mean while heating: all 14 count.
    totals, flows, rets, outs = {}, {}, {}, {}
    for n in range(14):
        parts = hourly(DAY + timedelta(days=n), 10)
        for target, part in zip((totals, flows, rets, outs), parts, strict=True):
            target.update(part)
    statistics = statistics_days(totals, flows, rets, outs, BERLIN)
    diary = [entry(DAY + timedelta(days=n)) for n in range(7, 14)]
    result = efficiency_factor(
        diary, DAY, DAY + timedelta(days=13), min_days=14, statistics=statistics
    )
    assert result.days == 14 and result.statistics_days == 7
    assert result.value == pytest.approx(4.0 / 9.405, abs=1e-3)
    assert result.as_attributes()["days_from_statistics"] == 7


def test_old_diary_day_prefers_statistics() -> None:
    # A diary day from before the update (day mean outdoor 8 °C, no mean
    # while heating) loses against the statistics day (0 °C while heating).
    old = entry(outdoor_heating=None, outdoor=8.0)
    statistics = statistics_days(*hourly(DAY, 10), BERLIN)
    result = efficiency_factor([old], DAY, DAY, min_days=1, statistics=statistics)
    assert result.statistics_days == 1 and result.day_mean_days == 0
    assert result.source == 0.0
    # Without a statistics day the old diary day counts with its day mean.
    alone = efficiency_factor([old], DAY, DAY, min_days=1)
    assert alone.day_mean_days == 1 and alone.source == 8.0


# Winter (November to March), the field test's period.


def test_winter_span() -> None:
    # Season from 1 July: the winter of that season, clipped to yesterday.
    assert winter_span(date(2026, 7, 1), date(2026, 10, 31)) is None
    assert winter_span(date(2026, 7, 1), date(2026, 12, 9)) == (
        date(2026, 11, 1),
        date(2026, 12, 9),
    )
    assert winter_span(date(2025, 7, 1), date(2026, 6, 30)) == (
        date(2025, 11, 1),
        date(2026, 3, 31),
    )
    # Season from 1 January: November and December of that year only.
    assert winter_span(date(2026, 1, 1), date(2026, 12, 31)) == (
        date(2026, 11, 1),
        date(2026, 12, 31),
    )


def test_factor_spans() -> None:
    spans = factor_spans(
        date(2026, 7, 1), date(2025, 7, 1), date(2026, 12, 1), date(2026, 12, 9)
    )
    assert spans["season"] == (date(2026, 7, 1), date(2026, 12, 9), 14)
    assert spans["month"] == (date(2026, 12, 1), date(2026, 12, 9), 7)
    assert spans["previous_season"] == (date(2025, 7, 1), date(2026, 6, 30), 14)
    assert spans["winter"] == (date(2026, 11, 1), date(2026, 12, 9), 14)
    assert spans["previous_winter"] == (date(2025, 11, 1), date(2026, 3, 31), 14)
    before = factor_spans(
        date(2026, 7, 1), date(2025, 7, 1), date(2026, 10, 1), date(2026, 10, 9)
    )
    assert "winter" not in before


def test_factor_attributes() -> None:
    days = [entry(DAY + timedelta(days=i)) for i in range(14)]
    season = efficiency_factor(days, DAY, DAY + timedelta(days=13), min_days=14)
    attributes = factor_attributes({"season": season, "winter": season})
    assert attributes["winter"]["value"] == pytest.approx(0.43)
    assert attributes["previous_winter"] is None
    assert attributes["field_reference"]["period"] == "November to March"
    assert factor_attributes({}) == {}
