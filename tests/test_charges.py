"""DHW charges: statistics, ratio, disinfection detection, backup heater split."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.waermewacht.charges import (
    Charge,
    charge_ratio,
    charge_stats,
    days_since,
    disinfection_split,
    disinfections,
    is_disinfection,
    last_disinfection,
    open_charge,
    prune,
)

DAY = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
WEEK_END = DAY + timedelta(days=7)


def at(hours: float) -> datetime:
    return DAY + timedelta(hours=hours)


def charge(
    start: float,
    minutes: float | None,
    heat: float = 3.0,
    elec: float = 1.0,
    aux: float = 0.0,
    *,
    top: float | None = 50.0,
    begin: float | None = 40.0,
    uncertain: bool = False,
) -> Charge:
    return Charge(
        start=at(start),
        end=at(start) + timedelta(minutes=minutes) if minutes is not None else None,
        heat_kwh=heat,
        electricity_kwh=elec,
        aux_kwh=aux,
        max_dhw_temp=top,
        start_dhw_temp=begin,
        uncertain=uncertain,
    )


# Made-up week: daily normal charges, one weekly disinfection with backup heater.
NORMAL = [charge(6 + 24 * d, 40) for d in range(5)]
DISINFECTION = charge(24 * 5 + 2, 90, heat=5.0, elec=1.2, aux=1.8, top=62.0)
GAP = charge(24 * 6 + 6, 30, heat=2.0, elec=1.0, uncertain=True)
WEEK = [*NORMAL, DISINFECTION, GAP]


def test_charge_ratio_and_minimum() -> None:
    assert charge_ratio(charge(0, 30, heat=3.0, elec=1.0)) == pytest.approx(3.0)
    # Backup heater counts as electricity.
    assert charge_ratio(DISINFECTION) == pytest.approx(5.0 / 3.0)
    # Below the minimum electricity or without heat: unknown, never 0.
    assert charge_ratio(charge(0, 5, heat=0.5, elec=0.1)) is None
    assert charge_ratio(charge(0, 5, heat=0.5, elec=0.1), min_electricity=0.05) == 5.0
    assert charge_ratio(charge(0, 5, heat=0.0, elec=1.0)) is None
    assert charge_ratio(charge(0, 5, heat=0.0, elec=0.0)) is None


def test_week_stats() -> None:
    stats = charge_stats(WEEK, DAY, WEEK_END)
    assert stats.count == 7
    assert stats.uncertain == 1
    assert stats.uncertain_share == pytest.approx(100 / 7)
    assert stats.heat_kwh == pytest.approx(5 * 3.0 + 5.0 + 2.0)
    assert stats.electricity_kwh == pytest.approx(5 * 1.0 + 1.2 + 1.0)
    assert stats.aux_kwh == pytest.approx(1.8)
    assert stats.ratio == pytest.approx(22.0 / 9.0)
    assert stats.aux_share == pytest.approx(100 * 1.8 / 9.0)
    # Means leave out the uncertain charge.
    assert stats.mean_minutes == pytest.approx((5 * 40 + 90) / 6)
    assert stats.mean_heat_kwh == pytest.approx((5 * 3.0 + 5.0) / 6)
    assert stats.lift_count == 6
    assert stats.mean_lift == pytest.approx((5 * 10.0 + 22.0) / 6)


def test_window_counts_charges_by_end() -> None:
    # Starts before midnight, ends after it: belongs to the next day.
    late = charge(-0.25, 30)
    assert charge_stats([late], DAY - timedelta(days=1), DAY).count == 0
    assert charge_stats([late], DAY, DAY + timedelta(days=1)).count == 1
    # The end of the window is exclusive.
    edge = Charge(start=at(23), end=at(24), heat_kwh=1.0, electricity_kwh=0.5)
    assert charge_stats([edge], DAY, at(24)).count == 0


def test_empty_window_is_unknown_not_zero() -> None:
    stats = charge_stats([], DAY, WEEK_END)
    assert stats.count == 0
    assert stats.heat_kwh == 0.0
    assert stats.ratio is None
    assert stats.aux_share is None
    assert stats.mean_minutes is None
    assert stats.mean_heat_kwh is None
    assert stats.mean_lift is None
    assert stats.uncertain_share is None


def test_small_window_below_minimum() -> None:
    small = charge(1, 4, heat=0.4, elec=0.1)
    stats = charge_stats([small], DAY, WEEK_END)
    assert stats.count == 1
    assert stats.ratio is None
    assert stats.aux_share is None
    assert stats.mean_heat_kwh == pytest.approx(0.4)


def test_running_charge_only_with_as_of() -> None:
    running = charge(30, None, heat=1.0, elec=0.4, top=48.0, begin=42.0)
    every = [*WEEK, running]
    assert charge_stats(every, DAY, WEEK_END).count == 7
    assert open_charge(every) is running
    assert open_charge(WEEK) is None

    now = at(30.5)
    current = charge_stats([running], at(30), at(31), as_of=now)
    assert current.count == 1
    assert current.mean_minutes == pytest.approx(30.0)
    assert current.ratio == pytest.approx(2.5)
    assert current.mean_lift == pytest.approx(6.0)
    # `as_of` outside the window leaves the running charge out.
    assert charge_stats([running], DAY, at(30), as_of=now).count == 0


def test_missing_temperatures() -> None:
    no_start = charge(1, 30, begin=None)
    no_top = charge(3, 30, top=None)
    both = charge(5, 30, top=55.0, begin=45.0)
    stats = charge_stats([no_start, no_top, both], DAY, WEEK_END)
    assert stats.count == 3
    assert stats.lift_count == 1
    assert stats.mean_lift == pytest.approx(10.0)
    assert no_start.lift is None
    assert not is_disinfection(no_top)
    assert charge_stats([no_start], DAY, WEEK_END).mean_lift is None


def test_disinfection_detection() -> None:
    assert disinfections(WEEK) == [DISINFECTION]
    # Exactly the threshold counts.
    exact = charge(24 * 7 + 2, 60, top=60.0)
    assert is_disinfection(exact)
    assert not is_disinfection(charge(0, 30, top=59.9))
    # A lower threshold for a storage sensor that reads below the outlet.
    assert len(disinfections([*WEEK, charge(0, 30, top=58.5)], threshold=58.0)) == 2
    assert last_disinfection([exact, *WEEK]) is exact
    assert last_disinfection(NORMAL) is None


def test_days_since() -> None:
    ended = DISINFECTION.end
    assert ended is not None
    assert days_since(WEEK, ended + timedelta(days=2, hours=12)) == pytest.approx(2.5)
    assert days_since(NORMAL, WEEK_END) is None
    # A disinfection still running: 0 days.
    running = charge(24 * 8, None, top=61.0)
    assert days_since([*WEEK, running], at(24 * 8 + 1)) == 0.0


def test_disinfection_split_shows_where_backup_heater_goes() -> None:
    extra = charge(24 * 4 + 18, 40, heat=3.0, elec=0.9, aux=0.2)
    split = disinfection_split([*WEEK, extra], DAY, WEEK_END)
    assert split.disinfection.count == 1
    assert split.normal.count == 7
    assert split.disinfection.aux_share == pytest.approx(100 * 1.8 / 3.0)
    assert split.normal.aux_share == pytest.approx(100 * 0.2 / (5 + 1.0 + 0.9 + 0.2))
    assert split.aux_in_disinfection == pytest.approx(90.0)
    assert split.disinfection.ratio == pytest.approx(5.0 / 3.0)


def test_split_without_backup_heater() -> None:
    split = disinfection_split(NORMAL, DAY, WEEK_END)
    assert split.disinfection.count == 0
    assert split.disinfection.ratio is None
    assert split.aux_in_disinfection is None


def test_round_trip() -> None:
    for item in [*WEEK, charge(1, None, top=None, begin=None)]:
        assert Charge.from_dict(item.as_dict()) == item
    # Older or partial data falls back to defaults.
    minimal = Charge.from_dict({"start": DAY.isoformat()})
    assert minimal == Charge(start=DAY)


def test_prune() -> None:
    running = charge(24 * 6 + 20, None)
    kept = [*WEEK, running]
    prune(kept, at(24 * 5))
    assert kept == [DISINFECTION, GAP, running]
