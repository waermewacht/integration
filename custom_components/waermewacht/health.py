"""Health check: rules that flag conspicuous behaviour. Pure Python.

Design, thresholds and sources: docs/GESUNDHEITSCHECK.md. A finding is
`problem` True/False, or None with a `reason` when the data do not allow a
decision. Thresholds marked "own assumption" there are options or constants
here, never hidden.

- Efficiency drop (4.1): heating ratio of the current season against the
  previous one at the same outdoor temperature, class by class of the
  performance curve; the previous season is weighted with the current heat
  per class. Where one season merged classes the other keeps apart (a young
  season has few days per class), the classes of the other are summed over
  the same range. On from a drop of 15 %, off below 10 % (hysteresis).
- Backup heater on mild days (4.2): heater energy for heating on days with a
  mean of at least 5 °C in the last 7 full days; on from 2 kWh. The rolling
  window is the hysteresis. Hot water does not count (disinfection may use
  the heater).
- Backup heater in hot water charges (4.9): share of the backup heater in
  the electricity of normal charges (without thermal disinfection) in the
  last 30 days; on above 10 % with at least 10 charges. Disinfection may use
  the heater, normal charges should not.
- Hot water efficiency against last year (4.9): ratio of normal charges in
  the last 30 full days against the same 30 days a year before, both from
  the diary (the cold water temperature follows the season); on from a drop
  of 15 % with at least 10 charges on each side. Rolling window, no
  hysteresis.
- Outdoor temperature unusable (4.10 c): an hourly minimum equal to the
  maximum for 48 hours in a row (the sensor stands still), or hourly means
  outside -35 … 45 °C in more than 3 hours of the previous day.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from .charges import MIN_CHARGE_ELECTRICITY_KWH, DisinfectionSplit
from .curve import OUTDOOR_MAX, OUTDOOR_MIN, DaySample
from .energy import Kind, ratio
from .model import Mode

# 4.1, own assumptions (docs/GESUNDHEITSCHECK.md): the class ratio scatters by
# about 0.14 at 7 days (3 % at a ratio of 4), so 15 % is well above noise.
DROP_PERCENT = 15.0
DROP_RELEASE_POINTS = 5.0  # off below threshold minus this
MIN_COMMON_SPAN = 4.0  # K of compared outdoor range, two classes
MIN_COMMON_DAYS = 14
MIN_COMPARED_KWH = 10.0
# 4.2, own assumptions.
MILD_FROM = 5.0  # °C day mean
AUX_KWH = 2.0  # in the window
WINDOW_DAYS = 7
MIN_MILD_DAYS = 3
# 4.9, own assumptions.
AUX_DHW_PERCENT = 10.0
MIN_CHARGES = 10
CHARGE_DAYS = 30
DHW_DROP_PERCENT = 15.0
# 4.10 c.
STUCK_HOURS = 48
MAX_IMPLAUSIBLE_HOURS = 3

NO_OUTDOOR = "no_outdoor_temp"
NO_AUX = "no_aux_counter"
NO_PREVIOUS = "no_previous_season"
NO_PREVIOUS_YEAR = "no_previous_year"
TOO_FEW_CLASSES = "too_few_classes"
TOO_FEW_DAYS = "too_few_days"
TOO_LITTLE_ELECTRICITY = "too_little_electricity"
TOO_FEW_CHARGES = "too_few_charges"
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


def _usable(rows: Sequence[Mapping[str, Any]]) -> bool:
    return all(not r.get("sparse") and r.get("ratio") for r in rows)


def _sum(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    return sum(r[key] for r in rows)


def common_ranges(
    current: Sequence[Mapping[str, Any]], previous: Sequence[Mapping[str, Any]]
) -> list[tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]]:
    """Smallest outdoor ranges bounded by class limits of both curves.

    Each pair holds the adjacent classes of either season that cover the
    same range. A range with a gap, a sparse class or a class without a
    ratio is left out.
    """
    cur = sorted(current, key=lambda r: r["lower"])
    prev = sorted(previous, key=lambda r: r["lower"])
    ranges = []
    i = j = 0
    while i < len(cur) and j < len(prev):
        if cur[i]["lower"] != prev[j]["lower"]:
            if cur[i]["lower"] < prev[j]["lower"]:
                i += 1
            else:
                j += 1
            continue
        a, b = [cur[i]], [prev[j]]
        i, j = i + 1, j + 1
        while a[-1]["upper"] != b[-1]["upper"]:
            if a[-1]["upper"] < b[-1]["upper"]:
                if i == len(cur) or cur[i]["lower"] != a[-1]["upper"]:
                    break
                a.append(cur[i])
                i += 1
            else:
                if j == len(prev) or prev[j]["lower"] != b[-1]["upper"]:
                    break
                b.append(prev[j])
                j += 1
        else:
            if _usable(a) and _usable(b):
                ranges.append((a, b))
    return ranges


def efficiency_drop(
    current: Sequence[Mapping[str, Any]],
    previous: Sequence[Mapping[str, Any]],
    *,
    threshold: float = DROP_PERCENT,
    was_on: bool = False,
) -> Finding:
    """Compare two performance curves (rows as from curve.curve_as_dicts).

    Only ranges covered by usable classes of both seasons take part
    (common_ranges). Reference ratio: the previous season with the current
    heat distribution, Σ heat_cur / Σ (heat_cur / ratio_prev); current
    ratio: Σ heat_cur / Σ electricity_cur over the same ranges.
    """
    if not previous:
        return Finding(None, NO_PREVIOUS)
    common = [
        (
            {
                "lower": a[0]["lower"],
                "upper": a[-1]["upper"],
                "days": _sum(a, "days"),
                "heat_kwh": _sum(a, "heat_kwh"),
                "electricity_kwh": _sum(a, "electricity_kwh"),
                "ratio": _sum(a, "heat_kwh") / _sum(a, "electricity_kwh"),
            },
            {
                "days": _sum(b, "days"),
                "ratio": _sum(b, "heat_kwh") / _sum(b, "electricity_kwh"),
            },
        )
        for a, b in common_ranges(current, previous)
    ]
    classes = [
        {
            "lower": cur["lower"],
            "upper": cur["upper"],
            "days_current": cur["days"],
            "days_previous": prev["days"],
            "ratio_current": round(cur["ratio"], 2),
            "ratio_previous": round(prev["ratio"], 2),
        }
        for cur, prev in common
    ]
    evidence: dict[str, Any] = {"threshold_percent": threshold, "classes": classes}
    if sum(cur["upper"] - cur["lower"] for cur, _ in common) < MIN_COMMON_SPAN:
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


def aux_dhw_charges(
    split: DisinfectionSplit, *, threshold: float = AUX_DHW_PERCENT
) -> Finding:
    """Backup heater share of normal hot water charges (`split` = the window)."""
    normal = split.normal
    share = normal.aux_share
    evidence: dict[str, Any] = {
        "charges": normal.count,
        "aux_share": None if share is None else round(share, 1),
        "aux_kwh": round(normal.aux_kwh, 2),
        "disinfections": split.disinfection.count,
        "aux_kwh_disinfections": round(split.disinfection.aux_kwh, 2),
        "threshold_percent": threshold,
    }
    if normal.count < MIN_CHARGES or share is None:
        return Finding(None, TOO_FEW_CHARGES, evidence)
    return Finding(share > threshold, None, evidence)


def year_earlier(day: date) -> date:
    """The same day a year before; 29 February becomes the 28th."""
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


@dataclass(frozen=True)
class DiaryCharges:
    """Normal hot water charges of some diary days."""

    count: int = 0
    heat_kwh: float = 0.0
    input_kwh: float = 0.0  # compressor and backup heater


def diary_charges(
    diary: Iterable[Mapping[str, Any]], first: date, last: date
) -> DiaryCharges:
    """Sum of the normal charges of the diary days first … last."""
    count, heat, used = 0, 0.0, 0.0
    lower, upper = first.isoformat(), last.isoformat()
    for entry in diary:
        if not lower <= entry.get("day", "") <= upper:
            continue
        if not (charges := entry.get("charges")):
            continue
        count += charges.get("count", 0)
        heat += charges.get("heat_kwh", 0.0)
        used += charges.get("input_kwh", 0.0)
    return DiaryCharges(count, heat, used)


def dhw_efficiency_drop(
    diary: Iterable[Mapping[str, Any]],
    today: date,
    *,
    length: int = CHARGE_DAYS,
    threshold: float = DHW_DROP_PERCENT,
    min_charges: int = MIN_CHARGES,
    min_electricity: float = MIN_CHARGE_ELECTRICITY_KWH,
) -> Finding:
    """Ratio of normal charges in the last `length` full days against the
    same days a year before."""
    diary = list(diary)
    first, last = window_days(today, length)
    before_first, before_last = year_earlier(first), year_earlier(last)
    now = diary_charges(diary, first, last)
    before = diary_charges(diary, before_first, before_last)
    current = ratio(now.heat_kwh, now.input_kwh, min_electricity)
    previous = ratio(before.heat_kwh, before.input_kwh, min_electricity)
    change = (
        None
        if current is None or previous is None
        else 100 * (current - previous) / previous
    )
    evidence: dict[str, Any] = {
        "from": first.isoformat(),
        "to": last.isoformat(),
        "charges": now.count,
        "ratio": None if current is None else round(current, 2),
        "previous_from": before_first.isoformat(),
        "previous_to": before_last.isoformat(),
        "previous_charges": before.count,
        "previous_ratio": None if previous is None else round(previous, 2),
        "change_percent": None if change is None else round(change, 1),
        "threshold_percent": threshold,
    }
    if now.count < min_charges or current is None:
        return Finding(None, TOO_FEW_CHARGES, evidence)
    if before.count < min_charges or previous is None or change is None:
        return Finding(None, NO_PREVIOUS_YEAR, evidence)
    return Finding(change <= -threshold, None, evidence)


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
