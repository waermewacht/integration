"""Performance curve: local days, 2-K classes, edge merging, unknown ratio."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.waermewacht.curve import (
    class_lower,
    curve_as_dicts,
    daily_samples,
    performance_curve,
)
from custom_components.waermewacht.energy import Kind, Totals
from custom_components.waermewacht.model import Mode

BERLIN = ZoneInfo("Europe/Berlin")
START = date(2026, 11, 2)  # no DST change in the following weeks


def day_hours(day: date) -> list[datetime]:
    """UTC hour starts of a local Berlin day (23, 24 or 25)."""
    start = datetime.combine(day, time(0), tzinfo=BERLIN).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=BERLIN)
    hours = []
    while start < end:
        hours.append(start)
        start += timedelta(hours=1)
    return hours


def hour_totals(
    heat: float = 0.0,
    elec: float = 0.0,
    *,
    standby: float = 0.0,
    aux: float = 0.0,
    dhw_heat: float = 0.0,
    dhw_elec: float = 0.0,
) -> Totals:
    totals = Totals()
    totals.add(Kind.HEAT, Mode.HEATING, heat)
    totals.add(Kind.ELEC, Mode.HEATING, elec)
    totals.add(Kind.STANDBY, Mode.HEATING, standby)
    totals.add(Kind.AUX, Mode.HEATING, aux)
    totals.add(Kind.HEAT, Mode.DHW, dhw_heat)
    totals.add(Kind.ELEC, Mode.DHW, dhw_elec)
    return totals


class Data:
    """Hourly energy and outdoor temperature, built day by day."""

    def __init__(self) -> None:
        self.hours: dict[datetime, Totals] = {}
        self.outdoor: dict[datetime, float] = {}
        self.next_day = START

    def add_days(self, count: int, temp: float, **energy: float) -> None:
        for _ in range(count):
            self.add_day(self.next_day, temp, **energy)
            self.next_day += timedelta(days=1)

    def add_day(self, day: date, temp: float, **energy: float) -> None:
        for hour in day_hours(day):
            self.hours[hour] = hour_totals(**energy)
            self.outdoor[hour] = temp

    def curve(self, scope: str = "heating", **kwargs: float):
        return performance_curve(self.hours, self.outdoor, BERLIN, scope, **kwargs)


def test_class_bounds() -> None:
    assert class_lower(-0.5) == -2.0
    assert class_lower(-2.0) == -2.0
    assert class_lower(1.99) == 0.0
    zero = class_lower(-0.0)
    assert zero == 0.0
    assert math.copysign(1, zero) == 1  # never -0.0


def test_ratio_per_class_without_standby() -> None:
    data = Data()
    data.add_days(7, 1.0, heat=1.0, elec=0.25, standby=0.025)
    data.add_days(7, 5.0, heat=1.0, elec=1 / 3, standby=0.025)
    rows = data.curve()
    assert [(r.lower, r.upper, r.days) for r in rows] == [
        (0.0, 2.0, 7),
        (4.0, 6.0, 7),
    ]
    assert rows[0].ratio == pytest.approx(4.0)
    assert rows[1].ratio == pytest.approx(3.0)
    assert rows[0].heat_kwh == pytest.approx(7 * 24)
    assert rows[0].electricity_kwh == pytest.approx(7 * 24 * 0.25)
    assert rows[0].mean_outdoor == pytest.approx(1.0)
    assert not any(r.sparse for r in rows)


def test_backup_heater_counts_as_electricity() -> None:
    data = Data()
    data.add_days(7, 1.0, heat=1.0, elec=0.2, aux=0.05)
    assert data.curve()[0].ratio == pytest.approx(4.0)


def test_combined_scope_includes_hot_water() -> None:
    data = Data()
    data.add_days(7, 1.0, heat=1.0, elec=0.25, dhw_heat=0.5, dhw_elec=0.25)
    assert data.curve("heating")[0].ratio == pytest.approx(4.0)
    assert data.curve("combined")[0].ratio == pytest.approx(3.0)


def test_day_without_heat_in_scope_does_not_count() -> None:
    data = Data()
    data.add_days(7, 1.0, heat=1.0, elec=0.25)
    data.add_days(3, 1.0, dhw_heat=0.5, dhw_elec=0.25, standby=0.025)
    assert data.curve("heating")[0].days == 7
    assert data.curve("combined")[0].days == 10


def test_sparse_edge_classes_are_merged_inwards() -> None:
    data = Data()
    data.add_days(2, -11.0, heat=2.0, elec=1.0)  # [-12, -10): 2 days
    data.add_days(3, -7.0, heat=2.0, elec=1.0)  # [-8, -6): 3 days
    data.add_days(7, -3.0, heat=2.0, elec=0.5)  # [-4, -2)
    data.add_days(7, 1.0, heat=1.0, elec=0.25)  # [0, 2)
    data.add_days(2, 15.0, heat=1.0, elec=0.5)  # [14, 16): 2 days
    rows = data.curve()
    assert [(r.lower, r.upper, r.days) for r in rows] == [
        (-12.0, -2.0, 12),  # 2 + 3 days merged in two steps
        (0.0, 16.0, 9),
    ]
    assert rows[0].ratio == pytest.approx(24 * (2 * 5 + 2 * 7) / (24 * (5 + 0.5 * 7)))
    assert rows[0].mean_outdoor == pytest.approx((2 * -11 + 3 * -7 + 7 * -3) / 12)
    assert rows[1].ratio == pytest.approx((7 + 2) / (7 * 0.25 + 2 * 0.5))
    assert not any(r.sparse for r in rows)


def test_sparse_inner_class_is_flagged_without_ratio() -> None:
    data = Data()
    data.add_days(7, -3.0, heat=2.0, elec=0.5)
    data.add_days(3, 1.0, heat=1.0, elec=0.25)
    data.add_days(7, 5.0, heat=1.0, elec=0.25)
    rows = data.curve()
    assert [(r.lower, r.days, r.sparse) for r in rows] == [
        (-4.0, 7, False),
        (0.0, 3, True),
        (4.0, 7, False),
    ]
    assert rows[1].ratio is None
    assert rows[1].heat_kwh == pytest.approx(3 * 24)


def test_too_few_days_overall_is_one_sparse_row() -> None:
    data = Data()
    data.add_days(2, -3.0, heat=2.0, elec=0.5)
    data.add_days(2, 5.0, heat=1.0, elec=0.25)
    rows = data.curve()
    assert len(rows) == 1
    assert (rows[0].lower, rows[0].upper, rows[0].days) == (-4.0, 6.0, 4)
    assert rows[0].sparse
    assert rows[0].ratio is None


def test_ratio_unknown_below_minimum_electricity() -> None:
    data = Data()
    data.add_days(7, 9.0, heat=0.01, elec=0.002)  # 0.336 kWh in the class
    row = data.curve()[0]
    assert row.electricity_kwh == pytest.approx(0.336)
    assert row.ratio is None  # unknown, never 0
    assert data.curve(min_electricity=0.3)[0].ratio == pytest.approx(5.0)


def test_no_data_no_rows() -> None:
    assert performance_curve({}, {}, BERLIN) == []


def test_day_needs_twenty_valid_values() -> None:
    data = Data()
    short, outliers, ok = date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)
    for day in (short, outliers, ok):
        data.add_day(day, 4.0, heat=1.0, elec=0.25)
    for hour in day_hours(short)[:5]:
        del data.outdoor[hour]  # 19 values left
    for hour in day_hours(outliers)[:5]:
        data.outdoor[hour] = 50.0  # discarded: 19 valid values
    for hour in day_hours(ok)[:4]:
        data.outdoor[hour] = -40.0  # discarded: 20 valid values remain
    data.outdoor[day_hours(ok)[4]] = math.nan
    samples = daily_samples(data.hours, data.outdoor, BERLIN, min_hours=19)
    assert [(s.day, s.hours) for s in samples] == [
        (short, 19),
        (outliers, 19),
        (ok, 19),
    ]
    samples = daily_samples(data.hours, data.outdoor, BERLIN)
    assert samples == []
    data.outdoor[day_hours(ok)[4]] = 4.0
    samples = daily_samples(data.hours, data.outdoor, BERLIN)
    assert [(s.day, s.hours, s.mean_outdoor) for s in samples] == [(ok, 20, 4.0)]


def test_hours_without_outdoor_value_are_skipped() -> None:
    data = Data()
    day = date(2026, 11, 2)
    data.add_day(day, 4.0, heat=1.0, elec=0.25)
    for hour in day_hours(day)[:2]:
        del data.outdoor[hour]
    (sample,) = daily_samples(data.hours, data.outdoor, BERLIN)
    assert sample.totals.heat(Mode.HEATING) == pytest.approx(22.0)


def test_hour_without_energy_books_nothing() -> None:
    data = Data()
    day = date(2026, 11, 2)
    data.add_day(day, 4.0, heat=1.0, elec=0.25)
    del data.hours[day_hours(day)[0]]
    (sample,) = daily_samples(data.hours, data.outdoor, BERLIN)
    assert sample.hours == 24
    assert sample.totals.heat(Mode.HEATING) == pytest.approx(23.0)


def test_local_days_at_dst_changes() -> None:
    data = Data()
    autumn, spring = date(2026, 10, 25), date(2026, 3, 29)
    data.add_day(autumn, 6.0, heat=1.0, elec=0.25)
    data.add_day(spring, 3.0, heat=1.0, elec=0.25)
    # The day before the autumn change ends at 22:00 UTC, the day itself at 23:00.
    assert day_hours(autumn)[0] == datetime(2026, 10, 24, 22, tzinfo=UTC)
    samples = {s.day: s for s in daily_samples(data.hours, data.outdoor, BERLIN)}
    assert samples[autumn].hours == 25
    assert samples[autumn].totals.heat(Mode.HEATING) == pytest.approx(25.0)
    assert samples[spring].hours == 23
    assert samples[spring].totals.heat(Mode.HEATING) == pytest.approx(23.0)


def test_rows_as_dicts() -> None:
    data = Data()
    data.add_days(7, 1.04, heat=1.0, elec=0.3)
    data.add_days(7, 9.0, heat=0.01, elec=0.002)
    assert curve_as_dicts(data.curve()) == [
        {
            "lower": 0.0,
            "upper": 2.0,
            "days": 7,
            "mean_outdoor": 1.0,
            "heat_kwh": 168.0,
            "electricity_kwh": 50.4,
            "ratio": 3.33,
            "sparse": False,
        },
        {
            "lower": 8.0,
            "upper": 10.0,
            "days": 7,
            "mean_outdoor": 9.0,
            "heat_kwh": 1.68,
            "electricity_kwh": 0.336,
            "ratio": None,
            "sparse": False,
        },
    ]
