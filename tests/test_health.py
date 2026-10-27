"""Health check rules: efficiency drop, backup heater on mild days, outdoor sensor."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.waermewacht.curve import DaySample
from custom_components.waermewacht.energy import Kind, Totals
from custom_components.waermewacht.health import (
    NO_PREVIOUS,
    TOO_FEW_CLASSES,
    TOO_FEW_DAYS,
    TOO_LITTLE_ELECTRICITY,
    aux_mild_weather,
    efficiency_drop,
    outdoor_problem,
    window_days,
)
from custom_components.waermewacht.model import Mode


def row(lower: float, days: int, heat: float, ratio: float, **extra) -> dict:
    return {
        "lower": lower,
        "upper": lower + 2,
        "days": days,
        "heat_kwh": heat,
        "electricity_kwh": heat / ratio,
        "ratio": ratio,
        "sparse": False,
        **extra,
    }


def test_same_efficiency_is_no_problem() -> None:
    previous = [row(0, 10, 300, 3.0), row(2, 10, 250, 3.4)]
    current = [row(0, 8, 240, 3.0), row(2, 9, 220, 3.4)]
    result = efficiency_drop(current, previous)
    assert result.problem is False
    assert result.evidence["drop_percent"] == pytest.approx(0.0, abs=0.05)


def test_drop_compares_like_with_like() -> None:
    """Colder this season: the overall ratio falls, but not per class."""
    previous = [row(0, 10, 300, 3.0), row(6, 30, 600, 4.0)]
    current = [row(0, 30, 900, 3.0), row(6, 5, 100, 4.0)]
    assert efficiency_drop(current, previous).problem is False


def test_drop_of_twenty_percent_is_a_problem() -> None:
    previous = [row(0, 10, 300, 3.0), row(2, 10, 250, 3.5)]
    current = [row(0, 10, 300, 2.4), row(2, 10, 250, 2.8)]
    result = efficiency_drop(current, previous)
    assert result.problem is True
    assert result.evidence["drop_percent"] == pytest.approx(20.0, abs=0.1)
    assert result.evidence["ratio_previous_same_weather"] == pytest.approx(
        3.21, abs=0.01
    )


def test_hysteresis() -> None:
    previous = [row(0, 10, 300, 3.0), row(2, 10, 250, 3.0)]
    current = [row(0, 10, 300, 2.64), row(2, 10, 250, 2.64)]  # 12 % drop
    assert efficiency_drop(current, previous).problem is False
    assert efficiency_drop(current, previous, was_on=True).problem is True
    better = [row(0, 10, 300, 2.73), row(2, 10, 250, 2.73)]  # 9 % drop
    assert efficiency_drop(better, previous, was_on=True).problem is False


def test_only_common_classes_count() -> None:
    previous = [row(-8, 12, 300, 2.6, upper=-4), row(0, 10, 300, 3.0)]
    current = [row(-8, 12, 300, 2.0), row(0, 10, 300, 3.0)]  # bounds differ
    result = efficiency_drop(current, previous)
    assert result.problem is None and result.reason == TOO_FEW_CLASSES


def test_minimum_data() -> None:
    previous = [row(0, 10, 300, 3.0), row(2, 10, 250, 3.0)]
    assert (
        efficiency_drop([row(0, 6, 300, 3.0), row(2, 7, 250, 3.0)], previous).reason
        == TOO_FEW_DAYS
    )
    small = [row(0, 10, 15, 3.0), row(2, 10, 12, 3.0)]  # 9 kWh electricity
    assert efficiency_drop(small, previous).reason == TOO_LITTLE_ELECTRICITY
    assert efficiency_drop(small, []).reason == NO_PREVIOUS
    sparse = [
        row(0, 10, 300, 3.0),
        {**row(2, 10, 250, 3.0), "sparse": True, "ratio": None},
    ]
    assert efficiency_drop(sparse, previous).reason == TOO_FEW_CLASSES


def day(offset: int, mean: float, heat: float, aux: float) -> DaySample:
    totals = Totals()
    totals.add(Kind.HEAT, Mode.HEATING, heat)
    totals.add(Kind.AUX, Mode.HEATING, aux)
    totals.add(Kind.AUX, Mode.DHW, 3.0)  # disinfection: never counted
    return DaySample(date(2026, 11, 1) + timedelta(days=offset), 24, mean, totals)


def test_backup_heater_on_mild_days() -> None:
    days = [day(i, 6.0, 20.0, 0.5) for i in range(5)] + [day(5, 1.0, 40.0, 5.0)]
    result = aux_mild_weather(days)
    assert result.problem is True
    assert result.evidence["aux_kwh_7d"] == 2.5  # the cold day does not count
    assert result.evidence["mild_days_7d"] == 5


def test_backup_heater_only_on_cold_days_is_fine() -> None:
    days = [day(i, 6.0, 20.0, 0.0) for i in range(4)] + [day(4, -8.0, 60.0, 8.0)]
    assert aux_mild_weather(days).problem is False


def test_backup_heater_needs_mild_heating_days() -> None:
    days = [day(0, 6.0, 20.0, 0.0), day(1, 7.0, 0.0, 0.0), day(2, -2.0, 30.0, 0.0)]
    result = aux_mild_weather(days)
    assert result.problem is None and result.reason == TOO_FEW_DAYS
    # Three mild heating days from -5 °C on.
    days.append(day(3, 8.0, 10.0, 0.0))
    assert aux_mild_weather(days, mild_from=-5.0).problem is False


def test_window_days() -> None:
    assert window_days(date(2026, 11, 8)) == (date(2026, 11, 1), date(2026, 11, 7))


def hours(n: int, start: datetime) -> list[datetime]:
    return [start + timedelta(hours=i) for i in range(n)]


T0 = datetime(2026, 11, 1, tzinfo=UTC)


def test_outdoor_stuck_for_48_hours() -> None:
    stats = {h: (4.0, 4.0, 4.0) for h in hours(48, T0)}
    found = outdoor_problem(stats, [])
    assert found is not None and found.kind == "stuck"
    moving = {**stats, T0 + timedelta(hours=30): (4.1, 4.0, 4.2)}
    assert outdoor_problem(moving, []) is None
    assert outdoor_problem(dict(list(stats.items())[1:]), []) is None  # 47 hours


def test_outdoor_implausible_yesterday() -> None:
    day_hours = hours(24, T0)
    stats = {h: (5.0 + i % 3, 4.0, 7.0) for i, h in enumerate(day_hours)}
    for h in day_hours[10:14]:
        stats[h] = (50.0, 49.0, 51.0)
    found = outdoor_problem(stats, day_hours)
    assert found is not None and found.kind == "implausible" and found.hours == 4
    for h in day_hours[13:14]:
        stats[h] = (6.0, 5.0, 7.0)
    assert outdoor_problem(stats, day_hours) is None  # 3 hours are tolerated
