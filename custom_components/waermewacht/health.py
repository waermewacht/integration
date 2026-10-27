"""Health check: rules that flag conspicuous behaviour. Pure Python.

Design, thresholds and sources: docs/GESUNDHEITSCHECK.md. A finding is
`problem` True/False, or None with a `reason` when the data do not allow a
decision. Thresholds marked "own assumption" there are options or constants
here, never hidden.

- Efficiency drop (4.1): heating ratio of the current season against the
  previous one at the same outdoor temperature, class by class of the
  performance curve; the previous season is weighted with the current heat
  per class. On from a drop of 15 %, off below 10 % (hysteresis).
- Backup heater on mild days (4.2): heater energy for heating on days with a
  mean of at least 5 °C in the last 7 full days; on from 2 kWh. The rolling
  window is the hysteresis. Hot water does not count (disinfection may use
  the heater).
- Outdoor temperature unusable (4.10 c): an hourly minimum equal to the
  maximum for 48 hours in a row (the sensor stands still), or hourly means
  outside -35 … 45 °C in more than 3 hours of the previous day.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from .curve import OUTDOOR_MAX, OUTDOOR_MIN, DaySample
from .energy import Kind
from .model import Mode

# 4.1, own assumptions (docs/GESUNDHEITSCHECK.md): the class ratio scatters by
# about 0.14 at 7 days (3 % at a ratio of 4), so 15 % is well above noise.
DROP_PERCENT = 15.0
DROP_RELEASE_POINTS = 5.0  # off below threshold minus this
MIN_COMMON_CLASSES = 2
MIN_COMMON_DAYS = 14
MIN_COMPARED_KWH = 10.0
# 4.2, own assumptions.
MILD_FROM = 5.0  # °C day mean
AUX_KWH = 2.0  # in the window
WINDOW_DAYS = 7
MIN_MILD_DAYS = 3
# 4.10 c.
STUCK_HOURS = 48
MAX_IMPLAUSIBLE_HOURS = 3

NO_OUTDOOR = "no_outdoor_temp"
NO_AUX = "no_aux_counter"
NO_PREVIOUS = "no_previous_season"
TOO_FEW_CLASSES = "too_few_classes"
TOO_FEW_DAYS = "too_few_days"
TOO_LITTLE_ELECTRICITY = "too_little_electricity"
NOT_ANALYSED = "not_analysed_yet"
RESTARTED = "comparison_restarted"


@dataclass
class Finding:
    """Result of one check: problem True/False/None, reason, evidence."""

    problem: bool | None
    reason: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_attributes(self) -> dict[str, Any]:
        return {"reason": self.reason, **self.evidence}


def _key(row: Mapping[str, Any]) -> tuple[float, float]:
    return (row["lower"], row["upper"])


def efficiency_drop(
    current: Sequence[Mapping[str, Any]],
    previous: Sequence[Mapping[str, Any]],
    *,
    threshold: float = DROP_PERCENT,
    was_on: bool = False,
) -> Finding:
    """Compare two performance curves (rows as from curve.curve_as_dicts).

    Only classes with the same bounds, not sparse and with a ratio in both
    take part. Reference ratio: the previous season with the current heat
    distribution, Σ heat_cur / Σ (heat_cur / ratio_prev); current ratio:
    Σ heat_cur / Σ electricity_cur over the same classes.
    """
    if not previous:
        return Finding(None, NO_PREVIOUS)
    usable = {_key(r): r for r in previous if not r.get("sparse") and r.get("ratio")}
    common = [
        (row, usable[_key(row)])
        for row in current
        if not row.get("sparse") and row.get("ratio") and _key(row) in usable
    ]
    classes = [
        {
            "lower": cur["lower"],
            "upper": cur["upper"],
            "days_current": cur["days"],
            "days_previous": prev["days"],
            "ratio_current": cur["ratio"],
            "ratio_previous": prev["ratio"],
        }
        for cur, prev in common
    ]
    evidence: dict[str, Any] = {"threshold_percent": threshold, "classes": classes}
    if len(common) < MIN_COMMON_CLASSES:
        return Finding(None, TOO_FEW_CLASSES, evidence)
    if sum(cur["days"] for cur, _ in common) < MIN_COMMON_DAYS:
        return Finding(None, TOO_FEW_DAYS, evidence)
    heat = sum(cur["heat_kwh"] for cur, _ in common)
    electricity = sum(cur["electricity_kwh"] for cur, _ in common)
    if electricity < MIN_COMPARED_KWH:
        return Finding(None, TOO_LITTLE_ELECTRICITY, evidence)
    reference_electricity = sum(cur["heat_kwh"] / prev["ratio"] for cur, prev in common)
    ratio = heat / electricity
    reference = heat / reference_electricity
    drop = (1 - ratio / reference) * 100
    on = drop >= (threshold - DROP_RELEASE_POINTS if was_on else threshold)
    evidence.update(
        ratio_current=round(ratio, 2),
        ratio_previous_same_weather=round(reference, 2),
        drop_percent=round(drop, 1),
    )
    return Finding(on, None, evidence)


def aux_mild_weather(
    days: Iterable[DaySample],
    *,
    mild_from: float = MILD_FROM,
    threshold_kwh: float = AUX_KWH,
) -> Finding:
    """Backup heater energy for heating on mild days (`days` = the window)."""
    mild = [d for d in days if d.mean_outdoor >= mild_from]
    heating_days = [d for d in mild if d.totals.get(Kind.HEAT, Mode.HEATING) > 0]
    aux = sum(d.totals.get(Kind.AUX, Mode.HEATING) for d in mild)
    evidence: dict[str, Any] = {
        "aux_kwh_7d": round(aux, 1),
        "mild_days_7d": len(mild),
        "min_outdoor_temp": mild_from,
        "threshold_kwh": threshold_kwh,
        "days": [
            {
                "day": d.day.isoformat(),
                "mean_outdoor": round(d.mean_outdoor, 1),
                "aux_kwh": round(d.totals.get(Kind.AUX, Mode.HEATING), 2),
            }
            for d in mild
        ],
    }
    if aux >= threshold_kwh:
        return Finding(True, None, evidence)
    if len(heating_days) < MIN_MILD_DAYS:
        return Finding(None, TOO_FEW_DAYS, evidence)
    return Finding(False, None, evidence)


def window_days(today: date, length: int = WINDOW_DAYS) -> tuple[date, date]:
    """First and last day of the `length` full days before `today`."""
    return today - timedelta(days=length), today - timedelta(days=1)


@dataclass(frozen=True)
class OutdoorProblem:
    """What is wrong with the outdoor temperature (None: nothing)."""

    kind: str  # "stuck" or "implausible"
    hours: int


def outdoor_problem(
    min_max: Mapping[datetime, tuple[float | None, float | None, float | None]],
    yesterday: Iterable[datetime],
) -> OutdoorProblem | None:
    """Check hourly statistics (UTC hour -> mean, min, max), newest last.

    Stuck: the latest STUCK_HOURS hours all have min == max and the same
    value. Implausible: more than MAX_IMPLAUSIBLE_HOURS hourly means of
    `yesterday` (its UTC hour starts) outside the plausible range.
    """
    hours = sorted(min_max)
    tail = hours[-STUCK_HOURS:]
    if len(tail) == STUCK_HOURS and tail[-1] - tail[0] == timedelta(
        hours=STUCK_HOURS - 1
    ):
        values = [min_max[h] for h in tail]
        lows = {v[1] for v in values}
        highs = {v[2] for v in values}
        if len(lows) == 1 and lows == highs and None not in lows:
            return OutdoorProblem("stuck", STUCK_HOURS)
    implausible = sum(
        1
        for h in yesterday
        if (v := min_max.get(h)) is not None
        and v[0] is not None
        and not OUTDOOR_MIN <= v[0] <= OUTDOOR_MAX
    )
    if implausible > MAX_IMPLAUSIBLE_HOURS:
        return OutdoorProblem("implausible", implausible)
    return None
