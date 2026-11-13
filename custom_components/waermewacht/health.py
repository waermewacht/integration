"""Health check: rules that flag conspicuous behaviour. Pure Python.

Design, thresholds and sources: docs/GESUNDHEITSCHECK.md. A finding is
`problem` True/False, or None with a `reason` when the data do not allow a
decision. Thresholds marked "own assumption" there are options or constants
here, never hidden.

- Efficiency drop (4.1, 4.1a): a baseline model of the previous season,
  1/ratio = a + b * x, fitted per day with the heat as weight, x the lift
  (sink minus outdoor while heating) or, without a flow temperature, the
  outdoor day mean. The current season's days within the previous range
  give the expected electricity; the drop is the electricity used above it.
  The heating curve and the weather fall out, no restart is needed after a
  deliberate change. On from a drop of 15 %, off below 10 % (hysteresis).
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
- System pressure dropped (4.16): the median of the daily means of the last
  7 full days against the highest such 7-day median in the 90 days before;
  on from a drop of 0.3 bar. Daily means of hourly means, never minima
  (short outliers). Refilling raises the pressure again; the rolling window
  is the hysteresis.
- Outdoor temperature unusable (4.10 c): an hourly minimum equal to the
  maximum for 48 hours in a row (the sensor stands still), or hourly means
  outside -35 … 45 °C in more than 3 hours of the previous day.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from statistics import median
from typing import Any

from .carnot import FactorDay
from .charges import MIN_CHARGE_ELECTRICITY_KWH, DisinfectionSplit
from .curve import CLASS_WIDTH, OUTDOOR_MAX, OUTDOOR_MIN, DaySample, class_lower
from .energy import Kind, ratio
from .model import Mode

# 4.1, own assumptions (docs/GESUNDHEITSCHECK.md): the class ratio scatters by
# about 0.14 at 7 days (3 % at a ratio of 4), so 15 % is well above noise.
DROP_PERCENT = 15.0
DROP_RELEASE_POINTS = 5.0  # off below threshold minus this
# 4.1a, own assumptions checked on one heat pump (two seasons, 31 windows of
# 28 days against the rest of the season: scatter about 2 %).
MIN_PREVIOUS_DAYS = 30  # days of the previous season for the model
MIN_SPAN_K = 4.0  # spread of x in the previous season, else b is guesswork
MIN_COMPARED_DAYS = 14  # current days within the previous range
MIN_COMPARED_KWH = 10.0
RANGE_MARGIN_K = 1.0  # x beyond the previous range still predicted
BASIS_LIFT = "lift"
BASIS_OUTDOOR = "outdoor"
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
# 4.16, own assumptions checked on one heat pump (EMS-ESP syspress, 0.1 bar
# steps, 17 months): weekly means swing by up to 0.17 bar without a leak
# (not explained by the water temperature), a refill adds about 0.1 bar.
PRESSURE_DROP_BAR = 0.3
PRESSURE_DAYS = 7
PRESSURE_REFERENCE_DAYS = 90
MIN_PRESSURE_HOURS = 12  # hourly means for a day value
MIN_PRESSURE_WEEK_DAYS = 5  # day values for a 7-day median
MIN_PRESSURE_REFERENCE_DAYS = 21
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
OUTSIDE_RANGE = "outside_previous_range"


@dataclass
class Finding:
    """Result of one check: problem True/False/None, reason, evidence."""

    problem: bool | None
    reason: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_attributes(self) -> dict[str, Any]:
        return {"reason": self.reason, **self.evidence}


# State of the status sensor of a check ("Befund …"): fine, conspicuous or
# the reason why there is no verdict yet. Home Assistant translates these, so
# cards need no table of reasons.
STATUS_OK = "ok"
STATUS_PROBLEM = "problem"
STATUS_REASONS = (
    NOT_ANALYSED,
    NO_PREVIOUS,
    NO_PREVIOUS_YEAR,
    TOO_FEW_CLASSES,
    TOO_FEW_DAYS,
    TOO_LITTLE_ELECTRICITY,
    TOO_FEW_CHARGES,
    OUTSIDE_RANGE,
    NO_AUX,
    NO_OUTDOOR,
)
STATUS_OPTIONS = (STATUS_OK, STATUS_PROBLEM, *STATUS_REASONS)


def status(problem: bool | None, reason: str | None) -> str | None:
    """The status of a check; None (unknown) for a reason it does not know."""
    if reason is not None:
        return reason if reason in STATUS_REASONS else None
    if problem is None:
        return None
    return STATUS_PROBLEM if problem else STATUS_OK


@dataclass(frozen=True)
class BaselineDay:
    """One day of the efficiency comparison: heating heat, its electricity
    (running and backup heater, no standby), the model's x (lift or outdoor
    temperature) and the outdoor day mean for the table by class."""

    day: date
    heat: float
    electricity: float
    x: float
    outdoor: float


def fit_baseline(days: Sequence[BaselineDay]) -> tuple[float, float] | None:
    """a, b of 1/ratio = a + b * x by least squares, each day weighted with
    its heat; None without spread in x."""
    w = sum(d.heat for d in days)
    if w <= 0:
        return None
    mx = sum(d.heat * d.x for d in days) / w
    my = sum(d.electricity for d in days) / w  # heat-weighted mean of 1/ratio
    sxx = sum(d.heat * (d.x - mx) ** 2 for d in days)
    if sxx <= 0:
        return None
    sxy = sum(d.heat * (d.x - mx) * (d.electricity / d.heat - my) for d in days)
    b = sxy / sxx
    return my - b * mx, b


def baseline_drop(
    current: Sequence[BaselineDay],
    previous: Sequence[BaselineDay],
    *,
    basis: str,
    threshold: float = DROP_PERCENT,
    was_on: bool = False,
) -> Finding:
    """Electricity of the current days against what the previous season's
    model expects for them (docs/GESUNDHEITSCHECK.md 4.1a)."""
    previous = [d for d in previous if d.heat > 0 and d.electricity > 0]
    current = [d for d in current if d.heat > 0 and d.electricity > 0]
    evidence: dict[str, Any] = {
        "basis": basis,
        "threshold_percent": threshold,
        "days_current": len(current),
        "days_previous": len(previous),
    }
    if not previous:
        return Finding(None, NO_PREVIOUS, evidence)
    if len(previous) < MIN_PREVIOUS_DAYS:
        return Finding(None, TOO_FEW_DAYS, evidence)
    low, high = min(d.x for d in previous), max(d.x for d in previous)
    evidence["x_range"] = [round(low, 1), round(high, 1)]
    model = fit_baseline(previous)
    if high - low < MIN_SPAN_K or model is None:
        return Finding(None, TOO_FEW_CLASSES, evidence)
    a, b = model
    evidence["model"] = {"a": round(a, 4), "b": round(b, 5)}
    compared = [
        (d, expected)
        for d in current
        if low - RANGE_MARGIN_K <= d.x <= high + RANGE_MARGIN_K
        and (expected := a + b * d.x) > 0
    ]
    evidence["days_compared"] = len(compared)
    if len(current) < MIN_COMPARED_DAYS:
        return Finding(None, TOO_FEW_DAYS, evidence)
    if len(compared) < MIN_COMPARED_DAYS:
        return Finding(None, OUTSIDE_RANGE, evidence)
    heat = sum(d.heat for d, _ in compared)
    electricity = sum(d.electricity for d, _ in compared)
    if electricity < MIN_COMPARED_KWH:
        return Finding(None, TOO_LITTLE_ELECTRICITY, evidence)
    expected = sum(d.heat * e for d, e in compared)
    drop = (1 - expected / electricity) * 100
    on = drop >= (threshold - DROP_RELEASE_POINTS if was_on else threshold)
    by_class: dict[float, list[float]] = {}
    for d, e in compared:
        row = by_class.setdefault(class_lower(d.outdoor), [0, 0.0, 0.0, 0.0])
        row[0] += 1
        row[1] += d.heat
        row[2] += d.electricity
        row[3] += d.heat * e
    evidence.update(
        ratio_current=round(heat / electricity, 2),
        ratio_expected=round(heat / expected, 2),
        drop_percent=round(drop, 1),
        by_outdoor=[
            {
                "lower": lower,
                "upper": lower + CLASS_WIDTH,
                "days": int(n),
                "ratio_current": round(h / e, 2),
                "ratio_expected": round(h / x, 2),
            }
            for lower, (n, h, e, x) in sorted(by_class.items())
        ],
    )
    return Finding(on, None, evidence)


def lift_days(
    days: Mapping[date, FactorDay | str], samples: Iterable[DaySample] = ()
) -> list[tuple[BaselineDay, float]]:
    """Days of the comparison with a flow temperature (carnot.statistics_days
    with the backup heater): x is the lift, each with its share of heat
    counted without a return. The outdoor day mean (for the table) from
    `samples` where there, else the outdoor while heating."""
    means = {s.day: s.mean_outdoor for s in samples}
    return [
        (
            BaselineDay(
                day,
                found.heat,
                found.electricity,
                found.sink - found.source,
                means.get(day, found.source),
            ),
            found.flow_only_share,
        )
        for day, found in sorted(days.items())
        if isinstance(found, FactorDay)
    ]


def flow_only_share(days: Sequence[tuple[BaselineDay, float]]) -> float:
    """Share of the heat counted without a return temperature."""
    heat = sum(d.heat for d, _ in days)
    return sum(d.heat * share for d, share in days) / heat if heat > 0 else 0.0


def outdoor_days(samples: Iterable[DaySample]) -> list[BaselineDay]:
    """Days of the comparison without a flow temperature: x is the outdoor
    day mean (curve.daily_samples), energy of heating without standby."""
    return [
        BaselineDay(
            s.day,
            s.totals.heat(Mode.HEATING),
            s.totals.electricity(Mode.HEATING),
            s.mean_outdoor,
            s.mean_outdoor,
        )
        for s in samples
        if s.totals.heat(Mode.HEATING) > 0
    ]


def aux_mild_weather(
    days: Iterable[DaySample],
    *,
    mild_from: float = MILD_FROM,
    threshold_kwh: float = AUX_KWH,
    defrost_aux: Mapping[date, float] | None = None,
) -> Finding:
    """Backup heater energy for heating on mild days (`days` = the window).

    `defrost_aux`: heating backup heater energy during defrosts per day
    (`runs.defrost_aux_by_day`); it is left out of the check and shown apart.
    """
    defrost_aux = defrost_aux or {}
    mild = [d for d in days if d.mean_outdoor >= mild_from]
    heating_days = [d for d in mild if d.totals.get(Kind.HEAT, Mode.HEATING) > 0]

    def split(d: DaySample) -> tuple[float, float]:
        total = d.totals.get(Kind.AUX, Mode.HEATING)
        defrost = min(defrost_aux.get(d.day, 0.0), total)
        return total - defrost, defrost

    parts = {d.day: split(d) for d in mild}
    aux = sum(normal for normal, _ in parts.values())
    evidence: dict[str, Any] = {
        "aux_kwh_7d": round(aux, 1),
        "aux_kwh_defrost_7d": round(sum((d for _, d in parts.values()), 0.0), 1),
        "mild_days_7d": len(mild),
        "min_outdoor_temp": mild_from,
        "threshold_kwh": threshold_kwh,
        "days": [
            {
                "day": d.day.isoformat(),
                "mean_outdoor": round(d.mean_outdoor, 1),
                "aux_kwh": round(parts[d.day][0], 2),
                **(
                    {"aux_kwh_defrost": round(parts[d.day][1], 2)}
                    if parts[d.day][1] > 0
                    else {}
                ),
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
    """Backup heater share of normal hot water charges (`split` = the window).

    Backup heater energy during defrosts is left out of the share and shown
    apart (`aux_kwh_defrost`, all charges): it says nothing about hot water.
    """
    normal = split.normal
    hot = split.disinfection
    share = normal.aux_share
    evidence: dict[str, Any] = {
        "charges": normal.count,
        "aux_share": None if share is None else round(share, 1),
        "aux_kwh": round(normal.aux_kwh, 2),
        "aux_kwh_defrost": round(normal.aux_defrost_kwh + hot.aux_defrost_kwh, 2),
        "defrost_aux_charges": normal.defrost_aux_charges + hot.defrost_aux_charges,
        "disinfections": hot.count,
        "aux_kwh_disinfections": round(hot.aux_kwh, 2),
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


def pressure_days(hours: Mapping[datetime, float], tz: tzinfo) -> dict[date, float]:
    """Daily means (local days) of hourly mean pressures, days with at
    least MIN_PRESSURE_HOURS hours."""
    by_day: dict[date, list[float]] = {}
    for hour, value in hours.items():
        by_day.setdefault(hour.astimezone(tz).date(), []).append(value)
    return {
        day: sum(values) / len(values)
        for day, values in by_day.items()
        if len(values) >= MIN_PRESSURE_HOURS
    }


def _week_median(days: Mapping[date, float], first: date) -> float | None:
    values = [
        v
        for i in range(PRESSURE_DAYS)
        if (v := days.get(first + timedelta(days=i))) is not None
    ]
    return median(values) if len(values) >= MIN_PRESSURE_WEEK_DAYS else None


def pressure_drop(
    days: Mapping[date, float],
    today: date,
    *,
    threshold_bar: float = PRESSURE_DROP_BAR,
) -> Finding:
    """System pressure of the last 7 full days against the highest 7-day
    median of the 90 days before (`days`: pressure_days)."""
    first, _ = window_days(today, PRESSURE_DAYS)
    reference_from = first - timedelta(days=PRESSURE_REFERENCE_DAYS)
    current = _week_median(days, first)
    reference_days = sum(1 for d in days if reference_from <= d < first)
    best: tuple[float, date] | None = None
    for offset in range(PRESSURE_REFERENCE_DAYS - PRESSURE_DAYS + 1):
        start = reference_from + timedelta(days=offset)
        value = _week_median(days, start)
        if value is not None and (best is None or value > best[0]):
            best = (value, start)
    evidence: dict[str, Any] = {
        "current_bar": None if current is None else round(current, 2),
        "reference_bar": None if best is None else round(best[0], 2),
        "reference_week": None if best is None else best[1].isoformat(),
        "drop_bar": None,
        "threshold_bar": threshold_bar,
        "days": sum(1 for d in days if first <= d < today),
        "reference_days": reference_days,
    }
    if current is None or best is None or reference_days < MIN_PRESSURE_REFERENCE_DAYS:
        return Finding(None, TOO_FEW_DAYS, evidence)
    drop = best[0] - current
    evidence["drop_bar"] = round(drop, 2)
    return Finding(drop >= threshold_bar - 1e-9, None, evidence)


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
