"""Run time and cycling per outdoor temperature class, health check 4.15.

Pure Python, no Home Assistant imports. Design and decisions:
docs/GESUNDHEITSCHECK.md 4.15.

Whether a heat pump cycles depends mostly on the outdoor temperature: below
the heat demand of its smallest power it has to switch on and off. Per 2-K
class of the hourly outdoor mean this collects the hours, the compressor
seconds while heating and the heating starts, and derives:

- the share of the time the compressor heats, starts per day, minutes per
  start;
- "runs continuously below": the upper bound of the warmest class whose
  heating share is at least 90 % (own assumption: hot water and defrosts
  take a few percent even at full demand);
- "short runs from": the lower bound of the classes, from the warmest one
  with starts down, whose minutes per start lie below the short-run limit.

A modulating heat pump at 100 % run time only does not cycle; it may run at
a fraction of its power. So the run time tells nothing about the power
limit (bivalence point) unless the unit only switches on and off.

Sources: per day, the diary's histogram "classes" (from the runs, exact to
the second, and the hourly outdoor means of that day, written at midnight)
or, for days without it, the long-term statistics of a run time counter of
heating and, if there is one, a start counter of heating (look-back, only
templates or mappings that have them). Without a start counter (P1P2MQTT
counts the starts of all modes only) the look-back days count for the share
and "runs continuously below", not for starts and minutes per start: each
class keeps the hours and seconds whose starts are known apart. A counter
without a sum (state class measurement, P1P2MQTT's hours) gives its hourly
change as the step of the hourly maximum (runtime.py). Classes count from 24
hours (own assumption, one day).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from .curve import CLASS_WIDTH, class_lower
from .model import Activity
from .runs import Run

HOUR = timedelta(hours=1)
CONTINUOUS_SHARE = 0.9  # own assumption, see the module
MIN_CLASS_HOURS = 24.0  # own assumption, one day
# An hour with this much time without a known compressor state is left out
# (own assumption): its runs are not known.
MAX_GAP_SECONDS = 600.0
# Run time counters: unit -> minutes.
MINUTE_FACTORS = {"s": 1 / 60, "min": 1.0, "h": 60.0, "d": 1440.0}

NEVER_CONTINUOUS = "never_continuous"
NO_SHORT_RUNS = "no_short_runs"
TOO_FEW_HOURS = "too_few_hours"

# Activities that are not heating (a run's seconds per activity).
_NOT_HEATING = (Activity.DHW.value, Activity.COOLING.value)


def _heating_share(run: Run) -> float:
    """Share of a run's time that belongs to heating: all but hot water and
    cooling (defrost and unknown time belong to heating); 1 without an
    activity."""
    total = sum(run.activity_seconds.values())
    if total <= 0:
        return 1.0
    other = sum(run.activity_seconds.get(a, 0.0) for a in _NOT_HEATING)
    return max(0.0, 1.0 - other / total)


def heating_start(run: Run) -> bool:
    return run.counted and _heating_share(run) >= 0.5


def _overlap(start: datetime, end: datetime, lo: datetime, hi: datetime) -> float:
    return max((min(end, hi) - max(start, lo)).total_seconds(), 0.0)


def _key(temperature: float) -> str:
    return str(int(class_lower(temperature)))


def day_classes(
    runs: Sequence[Run],
    open_run: Run | None,
    outdoor: Mapping[datetime, float],
    now: datetime,
    gaps: Sequence[tuple[datetime, datetime]] = (),
) -> dict[str, list[float]]:
    """Histogram of the hours in `outdoor` (start of hour -> mean °C):
    class lower bound -> [hours, heating seconds, heating starts]. Hours
    within a gap of the compressor state are left out."""
    every = [*runs, *([open_run] if open_run else [])]
    result: dict[str, list[float]] = {}
    for hour, temperature in outdoor.items():
        end = min(hour + HOUR, now)
        if end <= hour:
            continue
        if sum(_overlap(lo, hi, hour, end) for lo, hi in gaps) > MAX_GAP_SECONDS:
            continue
        seconds = sum(
            _overlap(r.start, r.end or now, hour, end) * _heating_share(r)
            for r in every
        )
        starts = sum(1 for r in every if hour <= r.start < end and heating_start(r))
        row = result.setdefault(_key(temperature), [0.0, 0.0, 0.0])
        row[0] += (end - hour).total_seconds() / 3600
        row[1] += seconds
        row[2] += starts
    return {k: [round(v[0], 3), round(v[1]), int(v[2])] for k, v in result.items()}


def statistics_classes(
    runtime_minutes: Mapping[datetime, float],
    starts: Mapping[datetime, float] | None,
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
) -> dict[date, dict[str, list[float]]]:
    """The same histogram per local day from the hourly change of a run time
    counter (minutes) and a start counter of heating (look-back), plus the
    hours and seconds whose starts are known: [hours, seconds, starts,
    hours with starts, seconds with starts]. `starts` None: no start counter."""
    days: dict[date, dict[str, list[float]]] = {}
    for hour, minutes in runtime_minutes.items():
        temperature = outdoor.get(hour)
        if temperature is None or minutes is None or minutes < 0:
            continue
        # A counter jumping (reset, new unit) is no hour of running.
        seconds = min(minutes * 60, 3600.0)
        row = days.setdefault(hour.astimezone(tz).date(), {}).setdefault(
            _key(temperature), [0.0, 0.0, 0.0, 0.0, 0.0]
        )
        row[0] += 1
        row[1] += seconds
        if starts is not None:
            row[2] += max(starts.get(hour) or 0, 0)
            row[3] += 1
            row[4] += seconds
    return days


@dataclass(frozen=True)
class DutyClass:
    """One outdoor class over a period."""

    lower: float
    hours: float
    heating_seconds: float
    starts: int
    # Hours and seconds whose starts are known (look-back without a start
    # counter leaves them out); None: all of them.
    start_hours: float | None = None
    start_seconds: float | None = None

    @property
    def share(self) -> float:
        return self.heating_seconds / (self.hours * 3600) if self.hours else 0.0

    @property
    def hours_with_starts(self) -> float:
        return self.hours if self.start_hours is None else self.start_hours

    @property
    def starts_per_day(self) -> float | None:
        hours = self.hours_with_starts
        return 24 * self.starts / hours if hours else None

    @property
    def minutes_per_start(self) -> float | None:
        seconds = (
            self.heating_seconds if self.start_seconds is None else self.start_seconds
        )
        return seconds / 60 / self.starts if self.starts else None

    def as_dict(self) -> dict[str, Any]:
        per_start = self.minutes_per_start
        per_day = self.starts_per_day
        return {
            "lower": self.lower,
            "hours": round(self.hours, 1),
            "share_percent": round(100 * self.share, 1),
            "starts_per_day": None if per_day is None else round(per_day, 1),
            "minutes_per_start": None if per_start is None else round(per_start),
        }


@dataclass(frozen=True)
class DutyFigures:
    """Classes of a period and the two figures; None with a reason."""

    classes: list[DutyClass]
    continuous_below: float | None
    continuous_reason: str | None
    short_runs_from: float | None
    short_reason: str | None
    days: int = 0
    days_from_statistics: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    @property
    def hours(self) -> float:
        return sum(c.hours for c in self.classes)

    @property
    def usable(self) -> bool:
        return any(c.hours >= MIN_CLASS_HOURS for c in self.classes)


def duty_figures(
    entries: Iterable[Mapping[str, Any]],
    first: date,
    last: date,
    *,
    short_minutes: float,
    statistics: Mapping[date, Mapping[str, Sequence[float]]] | None = None,
) -> DutyFigures:
    """Classes over the days first … last: the diary's "classes" where a day
    has them, else the statistics day."""
    diary = {
        day: entry.get("classes")
        for entry in entries
        if first <= (day := date.fromisoformat(entry["day"])) <= last
    }
    statistics = statistics or {}
    # Per class: hours, seconds, starts, hours and seconds with starts.
    sums: dict[float, list[float]] = {}
    days = from_statistics = 0
    day = first
    while day <= last:
        classes = diary.get(day)
        if classes is None and (classes := statistics.get(day)) is not None:
            from_statistics += 1
        if classes:
            days += 1
            for key, values in classes.items():
                hours, seconds, starts, *known = values
                # The diary's rows (three values) know every start.
                start_hours, start_seconds = known or (hours, seconds)
                row = sums.setdefault(float(key), [0.0] * 5)
                row[0] += hours
                row[1] += seconds
                row[2] += starts
                row[3] += start_hours
                row[4] += start_seconds
        day += timedelta(days=1)
    rows = [
        DutyClass(lower, hours, seconds, int(starts), start_hours, start_seconds)
        for lower, (hours, seconds, starts, start_hours, start_seconds) in sorted(
            sums.items()
        )
    ]
    below, below_reason = _continuous_below(rows)
    short, short_reason = _short_runs_from(rows, short_minutes)
    return DutyFigures(
        classes=rows,
        continuous_below=below,
        continuous_reason=below_reason,
        short_runs_from=short,
        short_reason=short_reason,
        days=days,
        days_from_statistics=from_statistics,
    )


def _continuous_below(rows: Sequence[DutyClass]) -> tuple[float | None, str | None]:
    usable = [r for r in rows if r.hours >= MIN_CLASS_HOURS]
    if not usable:
        return None, TOO_FEW_HOURS
    # The warmest class at 90 % or more: the share falls with the outdoor
    # temperature anyway, and a hybrid's coldest classes (boiler alone)
    # or one transition class must not hide the classes above.
    found = [r.lower + CLASS_WIDTH for r in usable if r.share >= CONTINUOUS_SHARE]
    return (max(found), None) if found else (None, NEVER_CONTINUOUS)


def _short_runs_from(
    rows: Sequence[DutyClass], short_minutes: float
) -> tuple[float | None, str | None]:
    usable = [r for r in rows if r.hours_with_starts >= MIN_CLASS_HOURS and r.starts]
    if not usable:
        return None, TOO_FEW_HOURS
    found: float | None = None
    for row in reversed(usable):  # warmest first
        per_start = row.minutes_per_start
        if per_start is None or per_start >= short_minutes:
            break
        found = row.lower
    return (found, None) if found is not None else (None, NO_SHORT_RUNS)


def expected_continuous_below(
    heating_limit: float | None, slope_kw_per_k: float | None, min_kw: float | None
) -> float | None:
    """Where the heat demand reaches the smallest power: heating limit minus
    smallest power over the heat load per kelvin (signature slope)."""
    if heating_limit is None or not slope_kw_per_k or not min_kw:
        return None
    per_kelvin = abs(slope_kw_per_k)
    return round(heating_limit - min_kw / per_kelvin, 1)


def choose(previous: DutyFigures, current: DutyFigures) -> str:
    """Which season the sensors show: the last complete one when it has a
    continuous class, else the current one when it has, else the one with
    more hours (a tie keeps the previous season), as the heat load."""
    if previous.continuous_below is not None:
        return "previous"
    if current.continuous_below is not None:
        return "current"
    return "current" if current.hours > previous.hours else "previous"


def figures_as_attributes(figures: DutyFigures) -> dict[str, Any]:
    return {
        "classes": [c.as_dict() for c in figures.classes],
        "days": figures.days,
        "days_from_statistics": figures.days_from_statistics,
        "hours": round(figures.hours, 1),
        "continuous_share_percent": round(100 * CONTINUOUS_SHARE),
        "min_class_hours": MIN_CLASS_HOURS,
    }


def duty_value(duty: Mapping[str, Any], key: str) -> float | None:
    """`continuous_below` or `short_runs_from` of the chosen season."""
    figures = duty.get(duty.get("season", ""))
    return None if not isinstance(figures, DutyFigures) else getattr(figures, key)


def duty_attributes(duty: Mapping[str, Any], key: str) -> dict[str, Any]:
    """Attributes of a sensor (`key` continuous_below or short_runs_from):
    the chosen season's classes, the reason, the other season's value."""
    season = duty.get("season")
    figures = duty.get(season or "")
    if not isinstance(figures, DutyFigures):
        return {}
    other = duty.get("current" if season == "previous" else "previous")
    reason = "continuous_reason" if key == "continuous_below" else "short_reason"
    return {
        "season": season,
        "reason": getattr(figures, reason),
        **figures_as_attributes(figures),
        "other_season": None
        if not isinstance(other, DutyFigures)
        else getattr(other, key),
        "expected_continuous_below": duty.get("expected_continuous_below"),
        "short_run_minutes": duty.get("short_run_minutes"),
    }


def hour_steps(highest: Mapping[datetime, float]) -> dict[datetime, float]:
    """Hourly change of a counter without a sum from its hourly maxima: the
    step from the hour before, only between neighbouring hours and never
    negative (a reset or a gap gives no hour)."""
    result: dict[datetime, float] = {}
    for hour, value in highest.items():
        before = highest.get(hour - HOUR)
        if before is not None and value >= before:
            result[hour] = value - before
    return result


def runtime_minutes(change: float | None, unit: str | None) -> float | None:
    """Hourly change of a run time counter in minutes; None for an unknown
    unit."""
    if change is None:
        return None
    factor = MINUTE_FACTORS.get((unit or "").lower())
    return None if factor is None else change * factor
