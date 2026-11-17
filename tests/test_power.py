"""Measured heating power per outdoor class (health check 4.17), invented values."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.energy import Kind, Totals
from custom_components.waermewacht.model import Mode
from custom_components.waermewacht.power import (
    MIN_DEMAND_DAYS,
    MIN_POWER_HOURS,
    NO_PARTIAL_LOAD,
    TOO_FEW_HOURS,
    PowerFigures,
    daily_demand,
    day_full_hours,
    day_hours,
    full_hours,
    headline,
    oversize_attributes,
    power_figures,
    quantile,
    with_power,
)
from custom_components.waermewacht.runs import Run

BERLIN = ZoneInfo("Europe/Berlin")
H = timedelta(hours=1)
M = timedelta(minutes=1)
DAY = date(2026, 12, 1)
T0 = datetime(2026, 11, 30, 23, tzinfo=UTC)  # local midnight of DAY


def run(start: datetime, minutes: float) -> Run:
    return Run(start=start, end=start + minutes * M)


def hour_totals(heat: float, dhw: float = 0.0, cooling: float = 0.0) -> Totals:
    totals = Totals()
    totals.add(Kind.HEAT, Mode.HEATING, heat)
    totals.add(Kind.ELEC, Mode.HEATING, heat / 4)
    if dhw:
        totals.add(Kind.HEAT, Mode.DHW, dhw)
    if cooling:
        totals.add(Kind.HEAT, Mode.COOLING, cooling)
    return totals


def test_day_hours_change_of_time() -> None:
    assert len(day_hours(DAY, BERLIN)) == 24
    assert day_hours(DAY, BERLIN)[0] == T0
    assert len(day_hours(date(2026, 10, 25), BERLIN)) == 25
    assert len(day_hours(date(2027, 3, 28), BERLIN)) == 23


def test_day_full_hours() -> None:
    hours = day_hours(DAY, BERLIN)
    runs = [
        run(T0, 3 * 60 + 2),  # hours 0, 1, 2 full; 3 has 2 minutes
        run(T0 + 4 * H + 3 * M, 57),  # hour 4: one run, 57 min
        run(T0 + 5 * H, 30),  # hour 5: stop and restart
        run(T0 + 5 * H + 31 * M, 29),
        run(T0 + 6 * H, 50),  # hour 6: too short
        run(T0 + 7 * H, 120),  # hours 7, 8: a defrost in 8
        run(T0 + 9 * H, 60),  # hour 9: hot water charge
    ]
    defrost = (T0 + 8 * H + 20 * M, T0 + 8 * H + 24 * M)
    charge = (T0 + 9 * H + 50 * M, None)  # still open
    mask = day_full_hours(runs, None, hours, T0 + 10 * H, blocked=[defrost, charge])
    assert [i for i in range(24) if mask >> i & 1] == [0, 1, 2, 4, 7]


def test_day_full_hours_open_run_gap_and_now() -> None:
    hours = day_hours(DAY, BERLIN)
    open_run = Run(start=T0 + 20 * H)
    gaps = [(T0 + 21 * H + 10 * M, T0 + 21 * H + 25 * M)]  # 15 min unknown
    mask = day_full_hours([], open_run, hours, T0 + 23 * H + 30 * M, gaps=gaps)
    # 20 and 22 full, 21 has the gap, 23 is not over yet.
    assert [i for i in range(24) if mask >> i & 1] == [20, 22]


def test_full_hours_diary_before_statistics() -> None:
    day2 = DAY + timedelta(days=1)
    t1 = day_hours(day2, BERLIN)[0]
    entries = [{"day": DAY.isoformat(), "full_hours": 0b101}]
    minutes = {
        T0: 60.0,  # ignored: the diary has the day
        T0 + 5 * H: 60.0,
        t1: 58.0,
        t1 + H: 40.0,
        t1 + 2 * H: 300.0,  # a jump, no hour
    }
    found, days, from_statistics = full_hours(entries, minutes, DAY, day2, BERLIN)
    assert found == {T0, T0 + 2 * H, t1}
    assert (days, from_statistics) == (2, 1)


def test_full_hours_without_sources() -> None:
    found, days, from_statistics = full_hours(
        [{"day": DAY.isoformat(), "full_hours": None}], None, DAY, DAY, BERLIN
    )
    assert (found, days, from_statistics) == (set(), 0, 0)


def test_quantile() -> None:
    assert quantile([3.0, 1.0, 2.0], 0.5) == 2.0
    assert quantile([1.0, 2.0], 0.25) == pytest.approx(1.25)
    assert quantile([4.0], 0.95) == 4.0


def _season(
    cold: list[float], mild: list[float], *, extra: dict | None = None
) -> tuple[dict, dict, set]:
    """Hours at -7 °C (`cold` kWh each) and +7 °C (`mild`), all full."""
    hours: dict[datetime, Totals] = {}
    outdoor: dict[datetime, float] = {}
    hour = T0
    for temperature, values in ((-7.0, cold), (7.0, mild)):
        for kwh in values:
            hours[hour] = hour_totals(kwh)
            outdoor[hour] = temperature
            hour += H
    hours.update(extra or {})
    return hours, outdoor, set(hours)


def test_power_figures() -> None:
    cold = [3.0 + 0.05 * i for i in range(24)]  # 3.0 … 4.15
    mild = [1.5 + 0.02 * i for i in range(20)]
    hours, outdoor, full = _season(cold, mild)
    # Not full but in the classes' demand: an idle hour at +7 °C.
    idle = T0 + 50 * H
    hours[idle], outdoor[idle] = hour_totals(0.0), 7.5
    # A hot water hour and an hour without heat are no full hours.
    dhw, stuck = T0 + 51 * H, T0 + 52 * H
    hours[dhw], outdoor[dhw] = hour_totals(9.0, dhw=1.0), -7.0
    hours[stuck], outdoor[stuck] = hour_totals(0.0), -7.0
    full |= {dhw, stuck}
    figures = power_figures(
        hours,
        hours,
        outdoor,
        full,
        DAY,
        DAY + timedelta(days=2),
        BERLIN,
        shares={-8.0: 0.95, 6.0: 0.3},
        days=3,
    )
    cold_class, mild_class = figures.classes
    assert cold_class.lower == -8.0 and cold_class.full_hours == 24
    assert cold_class.max_kw == pytest.approx(quantile(cold, 0.95))
    assert cold_class.min_kw == pytest.approx(quantile(cold, 0.10))
    assert mild_class.median_kw == pytest.approx(quantile(mild, 0.5))
    # Demand from days: one day per class is too few, the third day has
    # only 3 outdoor values.
    assert cold_class.demand_kw is None and cold_class.demand_days == 1
    assert mild_class.demand_kw is None and mild_class.demand_days == 1
    assert cold_class.hours == 24
    assert figures.min_kw == pytest.approx(quantile(mild, 0.5))
    assert figures.min_class == 6.0
    assert figures.max_kw == cold_class.max_kw
    assert figures.max_class == -8.0
    assert figures.reason is None and figures.min_reason is None
    assert figures.full_hours == 44


def test_demand_from_days_with_a_night_setback() -> None:
    """Heat pump off at night (a forum user's hybrid, 17.11.2026): the cold
    night hours take no heat, the day catches up. By hour the demand would
    fall with the cold; by day it is the day's heat over its hours, in the
    class of the day's mean."""
    hours: dict[datetime, Totals] = {}
    outdoor: dict[datetime, float] = {}
    days = [DAY + timedelta(days=n) for n in range(MIN_DEMAND_DAYS + 2)]
    for n, day in enumerate(days):
        for i, hour in enumerate(day_hours(day, BERLIN)):
            night = i < 6
            outdoor[hour] = 0.0 if night else 4.0
            if n < MIN_DEMAND_DAYS + 1:  # the last day has no statistics
                hours[hour] = hour_totals(0.0 if night else 2.0)
    # One day with too few outdoor values does not count.
    for hour in day_hours(days[MIN_DEMAND_DAYS], BERLIN)[:5]:
        del outdoor[hour]
    demand = daily_demand(hours, outdoor, days[0], days[-1], BERLIN)
    # Day mean (6 x 0 + 18 x 4) / 24 = 3 °C: class 2.
    assert demand == {2.0: (pytest.approx(36.0 * MIN_DEMAND_DAYS), 72.0, 3)}
    figures = power_figures(
        hours, hours, outdoor, set(), days[0], days[-1], BERLIN, shares={}
    )
    (row,) = figures.classes
    assert row.lower == 2.0 and row.demand_kw == pytest.approx(1.5)
    assert row.as_dict()["demand_days"] == MIN_DEMAND_DAYS


def test_power_figures_without_partial_load_or_hours() -> None:
    hours, outdoor, full = _season([3.0] * MIN_POWER_HOURS, [1.5] * 3)
    args = (hours, hours, outdoor, full, DAY, DAY + timedelta(days=1), BERLIN)
    figures = power_figures(*args, shares={-8.0: 0.95, 6.0: 0.6})
    assert figures.max_kw == 3.0
    assert figures.min_kw is None and figures.min_reason == NO_PARTIAL_LOAD
    assert figures.classes[1].median_kw is None  # 3 full hours only
    empty = power_figures(*args[:3], set(), *args[4:], shares={})
    assert empty.reason == TOO_FEW_HOURS and empty.max_kw is None


def test_power_figures_late_heat_meter() -> None:
    """Day values (lag 1): the hour before must be full as well, the hour
    after free of hot water."""
    hours, outdoor, full = _season([3.0] * 14, [])
    hours[T0 + 5 * H] = hour_totals(3.0, dhw=0.5)
    args = (hours, hours, outdoor, full, DAY, DAY, BERLIN)
    lagged = power_figures(*args, shares={}, lag=1)
    # Hour 0 lacks its hour before, 4 and 5 see the hot water of 5, the
    # last one has no hour after it yet.
    assert lagged.classes[0].full_hours == 10
    assert power_figures(*args, shares={}).classes[0].full_hours == 13


def _duty(figures: PowerFigures) -> dict:
    return {"season": "previous", "power": {"previous": figures}}


def test_attributes() -> None:
    hours, outdoor, full = _season([3.0 + 0.1 * i for i in range(20)], [1.6] * 20)
    figures = power_figures(
        hours, hours, outdoor, full, DAY, DAY + timedelta(days=1), BERLIN,
        shares={6.0: 0.4},
    )  # fmt: skip
    duty = _duty(figures)
    duty["expected_continuous_below_measured"] = -1.0
    top = headline(duty)
    assert top["measured_min_kw"] == 1.6 and top["measured_min_class"] == 6.0
    assert top["measured_max_class"] == -8.0
    assert top["power_first_day"] == "2026-12-01"
    assert top["power_last_day"] == "2026-12-02"
    classes = [{"lower": -8.0, "hours": 20.0}, {"lower": 6.0, "hours": 20.0}]
    merged = with_power({"classes": classes}, duty, figures_too=True)
    assert merged["classes"][1]["median_kw"] == 1.6
    assert merged["classes"][0]["full_hours"] == 20
    assert merged["expected_continuous_below_measured"] == -1.0
    plain = with_power({"classes": classes}, duty, figures_too=False)
    assert "measured_min_kw" not in plain
    over = oversize_attributes(duty, 1.2)
    assert over["cycling_expected_measured"] is True
    assert over["measured_max_kw"] == top["measured_max_kw"]
    assert oversize_attributes(duty, None)["cycling_expected_measured"] is None


def test_attributes_with_a_reason() -> None:
    duty = {"season": "current", "power": {"reason": "no_run_time"}}
    assert headline(duty) == {"power_reason": "no_run_time"}
    assert oversize_attributes(duty, 1.0) == {"power_reason": "no_run_time"}
    assert headline({}) == {}
