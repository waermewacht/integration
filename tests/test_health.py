"""Health check rules: efficiency drop, backup heater on mild days, outdoor sensor."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.waermewacht.curve import DaySample
from custom_components.waermewacht.energy import Kind, Totals
from custom_components.waermewacht.health import (
    BASIS_LIFT,
    NO_PREVIOUS,
    NO_PREVIOUS_YEAR,
    OUTSIDE_RANGE,
    TOO_FEW_CHARGES,
    TOO_FEW_CLASSES,
    TOO_FEW_DAYS,
    TOO_LITTLE_ELECTRICITY,
    BaselineDay,
    aux_mild_weather,
    baseline_drop,
    dhw_efficiency_drop,
    outdoor_days,
    outdoor_problem,
    window_days,
    year_earlier,
)
from custom_components.waermewacht.model import Mode

D0 = date(2025, 10, 1)


def lifted(
    n: int, lift: float, *, cop_at_20: float = 4.0, loss: float = 0.0, start: int = 0
) -> list[BaselineDay]:
    """n days at one lift; 1/COP = 0.1 + 0.0075 * lift (4.0 at 20 K), times
    (1 + loss) for a real loss (more electricity for the same heat)."""
    days = []
    for i in range(n):
        x = lift + (i % 5) - 2  # spread of 4 K around the lift
        inverse = (0.1 + 0.0075 * x) * (4.0 / cop_at_20) * (1 + loss)
        heat = 30.0 + (i % 3)
        days.append(
            BaselineDay(D0 + timedelta(days=start + i), heat, heat * inverse, x, 5.0)
        )
    return days


def test_baseline_unchanged_is_fine_and_a_loss_is_found() -> None:
    previous = lifted(60, 20.0) + lifted(60, 26.0, start=60)
    same = baseline_drop(lifted(20, 22.0, start=200), previous, basis=BASIS_LIFT)
    assert same.problem is False
    assert same.evidence["drop_percent"] == pytest.approx(0.0, abs=0.1)
    assert same.evidence["days_compared"] == 20
    lost = baseline_drop(
        lifted(20, 22.0, start=200, loss=0.25), previous, basis=BASIS_LIFT
    )
    assert lost.problem is True
    assert lost.evidence["drop_percent"] == pytest.approx(20.0, abs=0.1)
    assert lost.evidence["ratio_expected"] > lost.evidence["ratio_current"]
    assert lost.evidence["by_outdoor"][0]["days"] == 20


def test_baseline_a_lower_heating_curve_is_no_alarm() -> None:
    """The lift falls by 6 K: the ratio rises, the model expects exactly that
    (no alarm, no restart needed); a loss at the same time still shows. The
    previous season had a few mild days at the lower lift too."""
    previous = lifted(30, 20.0) + lifted(90, 26.0, start=30)
    lower = baseline_drop(lifted(20, 20.0, start=200), previous, basis=BASIS_LIFT)
    assert lower.problem is False
    assert lower.evidence["drop_percent"] == pytest.approx(0.0, abs=0.1)
    both = baseline_drop(
        lifted(20, 20.0, start=200, loss=0.2), previous, basis=BASIS_LIFT
    )
    assert both.problem is True


def test_baseline_hysteresis() -> None:
    previous = lifted(60, 20.0) + lifted(60, 26.0, start=60)
    slight = lifted(20, 24.0, start=200, loss=0.12)  # 10.7 % more electricity
    assert baseline_drop(slight, previous, basis=BASIS_LIFT).problem is False
    assert (
        baseline_drop(slight, previous, basis=BASIS_LIFT, was_on=True).problem is True
    )
    better = lifted(20, 24.0, start=200, loss=0.05)
    assert (
        baseline_drop(better, previous, basis=BASIS_LIFT, was_on=True).problem is False
    )


def test_baseline_reasons() -> None:
    previous = lifted(120, 24.0)
    assert baseline_drop(lifted(20, 24.0), [], basis=BASIS_LIFT).reason == NO_PREVIOUS
    assert (
        baseline_drop(lifted(20, 24.0), lifted(20, 24.0), basis=BASIS_LIFT).reason
        == TOO_FEW_DAYS
    )
    flat = [BaselineDay(d.day, d.heat, d.electricity, 24.0, 5.0) for d in previous]
    assert baseline_drop(lifted(20, 24.0), flat, basis=BASIS_LIFT).reason == (
        TOO_FEW_CLASSES
    )
    assert baseline_drop(lifted(10, 24.0), previous, basis=BASIS_LIFT).reason == (
        TOO_FEW_DAYS
    )
    # A lift far below what the previous season knew: no extrapolation.
    far = baseline_drop(lifted(20, 12.0, start=200), previous, basis=BASIS_LIFT)
    assert far.reason == OUTSIDE_RANGE
    assert far.evidence["x_range"] == [22.0, 26.0]
    tiny = [BaselineDay(d.day, 1.0, 0.25, d.x, 5.0) for d in lifted(20, 24.0)]
    assert baseline_drop(tiny, previous, basis=BASIS_LIFT).reason == (
        TOO_LITTLE_ELECTRICITY
    )


def test_outdoor_days_without_flow() -> None:
    samples = [
        day(0, 4.0, 40.0, 0.0),
        day(1, 6.0, 0.0, 0.0),  # no heating heat: not a day of the comparison
    ]
    found = outdoor_days(samples)
    assert [(d.x, d.heat) for d in found] == [(4.0, 40.0)]


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


def charge_days(first: date, days: int, ratio: float, per_day: int = 1) -> list[dict]:
    """Diary days with `per_day` normal charges of 3 kWh heat each."""
    return [
        {
            "day": (first + timedelta(days=i)).isoformat(),
            "charges": {
                "count": per_day,
                "heat_kwh": 3.0 * per_day,
                "input_kwh": 3.0 * per_day / ratio,
                "disinfections": 0,
            },
        }
        for i in range(days)
    ]


TODAY = date(2027, 11, 1)  # window 2.10. - 31.10.2027


def test_dhw_ratio_against_the_same_days_last_year() -> None:
    diary = charge_days(date(2026, 10, 2), 30, 3.0) + charge_days(
        date(2027, 10, 2), 30, 2.4
    )
    result = dhw_efficiency_drop(diary, TODAY)
    assert result.problem is True
    assert result.evidence["ratio"] == 2.4
    assert result.evidence["previous_ratio"] == 3.0
    assert result.evidence["change_percent"] == -20.0
    assert result.evidence["charges"] == 30
    assert result.evidence["previous_from"] == "2026-10-02"
    assert result.evidence["previous_to"] == "2026-10-31"


def test_dhw_small_drop_is_no_problem() -> None:
    diary = charge_days(date(2026, 10, 2), 30, 3.0) + charge_days(
        date(2027, 10, 2), 30, 2.7
    )
    assert dhw_efficiency_drop(diary, TODAY).problem is False


def test_dhw_days_outside_the_windows_do_not_count() -> None:
    """A bad September last year and a better day today change nothing."""
    diary = (
        charge_days(date(2026, 9, 1), 31, 1.0)
        + charge_days(date(2026, 10, 2), 30, 3.0)
        + charge_days(date(2027, 10, 2), 30, 3.0)
        + charge_days(TODAY, 1, 9.0)
    )
    result = dhw_efficiency_drop(diary, TODAY)
    assert result.problem is False
    assert result.evidence["change_percent"] == 0.0


def test_dhw_needs_ten_charges_on_each_side() -> None:
    only_now = charge_days(date(2027, 10, 2), 30, 2.0)
    result = dhw_efficiency_drop(only_now, TODAY)
    assert result.problem is None
    assert result.reason == NO_PREVIOUS_YEAR
    assert result.evidence["previous_ratio"] is None

    few_now = charge_days(date(2026, 10, 2), 30, 3.0) + charge_days(
        date(2027, 10, 22), 9, 2.0
    )
    result = dhw_efficiency_drop(few_now, TODAY)
    assert (result.problem, result.reason) == (None, TOO_FEW_CHARGES)

    # Days without charges (no hot water counter, late source) are skipped.
    empty = [{"day": "2027-10-10", "charges": None}]
    assert dhw_efficiency_drop(empty, TODAY).reason == TOO_FEW_CHARGES


def test_year_earlier_leap_day() -> None:
    assert year_earlier(date(2028, 2, 29)) == date(2027, 2, 28)
    assert year_earlier(date(2027, 3, 1)) == date(2026, 3, 1)


def test_backup_heater_during_defrosts_is_left_out_on_mild_days() -> None:
    days = [day(i, 6.0, 20.0, 0.5) for i in range(5)]
    defrost = {d.day: 0.4 for d in days}
    defrost[days[0].day] = 9.0  # never more than booked that day
    result = aux_mild_weather(days, defrost_aux=defrost)
    assert result.problem is False
    assert result.evidence["aux_kwh_7d"] == 0.4
    assert result.evidence["aux_kwh_defrost_7d"] == 2.1
    first = result.evidence["days"][0]
    assert (first["aux_kwh"], first["aux_kwh_defrost"]) == (0.0, 0.5)


def test_status_of_a_check() -> None:
    from custom_components.waermewacht.health import (
        NOT_ANALYSED,
        STATUS_OPTIONS,
        status,
    )

    assert status(True, None) == "problem"
    assert status(False, None) == "ok"
    assert status(None, NOT_ANALYSED) == NOT_ANALYSED
    assert status(None, None) is None
    assert status(None, "something_new") is None  # not an option: unknown
    assert len(set(STATUS_OPTIONS)) == len(STATUS_OPTIONS)


def test_status_states_are_translated() -> None:
    """Every status sensor names every state in both languages."""
    import json
    from pathlib import Path

    from custom_components.waermewacht.health import STATUS_OPTIONS

    root = Path(__file__).parent.parent / "custom_components" / "waermewacht"
    checks = (
        "cycling_problem",
        "efficiency_drop",
        "aux_mild_weather",
        "aux_dhw_charges",
        "dhw_efficiency_drop",
        "status_messages",
    )
    for name in ("strings.json", "translations/en.json", "translations/de.json"):
        sensors = json.loads((root / name).read_text(encoding="utf-8"))["entity"][
            "sensor"
        ]
        for check in checks:
            assert set(sensors[f"{check}_status"]["state"]) == set(STATUS_OPTIONS)
