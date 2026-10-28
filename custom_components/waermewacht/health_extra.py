"""Health check, further rules: defrosts, spread, oversizing, standby, flow.

Pure Python, no Home Assistant imports. Design, thresholds and sources:
docs/GESUNDHEITSCHECK.md (4.3, 4.4, 4.7, 4.8, 4.10 e), field values in
docs/ENTWICKLUNG.md section 3. Checks return a health.Finding (problem
True/False, or None with a reason); figures without a sourced limit are
frozen dataclasses and never raise an alarm.

- Defrosts (4.3), figures only: count, defrosts starting in an hour with an
  outdoor mean of 10 °C or more, mean and longest minutes, over a window of
  the defrost history; defrosts per compressor run hour per 2-K class of the
  day mean from the diary, current season against the previous one. No
  source for usual frequency or duration, and the humidity that drives
  frosting is unknown.
- Spread (4.4), figure: time-weighted spread while the compressor heats,
  from the diary of the last 7 days, only days with a mean below 5 °C (high
  load, little modulation), at least 10 h of heating. Field reference
  WPsmart im Bestand: 6.8 K (3.2-9.8 K).
- Oversizing (4.7), figure: rated heating power at A-7/W35 (data sheet,
  option) over the standard heat load at the design outdoor temperature.
  Fraunhofer ISE WP-QS: about 1.5 in the field mean - a mean, no limit. With
  the smallest power (option) also whether the measured heat load at +7 °C
  is below it, so that cycling in the transition season is to be expected.
- Standby (4.8): mean standby power of the last 7 diary days (standby kWh
  over the hours without a run) against the median of the 30 days before;
  rising from +50 % and +10 W (own assumptions). Bosch/Buderus report a
  constant model value (~25 W), so there it shows nothing real; the lowest
  and highest day tell a model value from a measurement.
- Flow (4.10 e): flow 0 for 15 minutes of heating, or a measured flow more
  than 10 times off the flow the heat implies, heat power / (1.163 Wh/(l·K)
  * spread) (specific heat of water). Without a heat power signal the heat
  power is the heat counter's rise over the heating time (one day). Catches
  unit errors such as l/h reported as L/min.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any

from .averages import Mean
from .curve import CLASS_WIDTH, class_lower
from .curve import MIN_DAYS as CLASS_MIN_DAYS
from .energy import Kind
from .health import TOO_FEW_DAYS, Finding
from .heat_load import HeatLoad
from .runs import Defrost

# 4.3, own assumptions (no source for usual frequency or duration).
WARM_DEFROST_FROM = 10.0  # °C hourly mean: defrosting there is odd
DEFROST_DAYS = 7
# 4.4: WPsmart im Bestand (Fraunhofer ISE 2020), 29 air/water heat pumps.
FIELD_SPREAD_K = 6.8
FIELD_SPREAD_RANGE = (3.2, 9.8)
SPREAD_COLD_BELOW = 5.0  # °C day mean, own assumption
SPREAD_MIN_SECONDS = 10 * 3600.0  # own assumption
SPREAD_DAYS = 7
# 4.7: Fraunhofer ISE WP-QS, power at A-7/W35 about 50 % above the heat load.
FIELD_OVERSIZE = 1.5
MILD_OUTDOOR = 7.0  # °C, transition season for the smallest power
# 4.8, own assumptions.
STANDBY_RISE_PERCENT = 50.0
STANDBY_RISE_W = 10.0
STANDBY_RECENT_DAYS = 7
STANDBY_REFERENCE_DAYS = 30
MIN_RECENT_DAYS = 5
MIN_REFERENCE_DAYS = 14
MIN_IDLE_HOURS = 2.0  # a day needs this much time without a run
# 4.10 e: specific heat of water, 4.187 kJ/(kg·K) / 3.6 = 1.163 Wh/(kg·K),
# taken per litre (1 kg/l; the factor below dwarfs the difference).
WATER_WH_PER_L_K = 1.163
FLOW_FACTOR = 10.0  # own assumption, wide: catches unit errors only
ZERO_FLOW_SECONDS = 15 * 60.0  # own assumption
FLOW_MIN_SECONDS = 3600.0  # heating time, as for swapped sensors
FLOW_MIN_HEAT_KWH = 1.0  # 100 steps of a 0.01 kWh counter
FLOW_MIN_SPREAD = 2.0  # K; below that the division is unstable

NO_RATED_POWER = "no_rated_power"
NO_DESIGN_TEMP = "no_design_temp"
HEAT_LOAD_INSUFFICIENT = "heat_load_insufficient"
TOO_LITTLE_HEATING = "too_little_heating"
NO_STANDBY = "no_standby"
NO_FLOW_RATE = "no_flow_rate"
SPREAD_TOO_SMALL = "spread_too_small"

# Volume flow units of Home Assistant (lower case) -> l/h.
_GALLON = 3.785411784
_CUBIC_FOOT = 28.316846592
LPH_FACTORS: dict[str, float] = {
    "l/h": 1.0,
    "l/min": 60.0,
    "l/s": 3600.0,
    "ml/s": 3.6,
    "m³/h": 1000.0,
    "m³/min": 60_000.0,
    "m³/s": 3_600_000.0,
    "gal/h": _GALLON,
    "gal/min": 60 * _GALLON,
    "gal/d": _GALLON / 24,
    "ft³/min": 60 * _CUBIC_FOOT,
}


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _day(entry: Mapping[str, Any]) -> date:
    return date.fromisoformat(entry["day"])


def _window(
    entries: Iterable[Mapping[str, Any]], first: date, last: date
) -> list[Mapping[str, Any]]:
    """Diary entries of the days first … last."""
    return [e for e in entries if first <= _day(e) <= last]


def day_hours(day: date, tz: tzinfo) -> float:
    """Real hours of a local day (23, 24 or 25)."""
    start = datetime.combine(day, time(0), tzinfo=tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
    return (end.astimezone(UTC) - start).total_seconds() / 3600


# 4.3 Defrosts.


@dataclass(frozen=True)
class DefrostFigures:
    """Defrosts of one window, against the hourly outdoor mean at their start."""

    defrosts: int
    warm_defrosts: int  # started in an hour with a mean >= warm_from
    unknown_outdoor: int  # no hourly outdoor mean at the start
    mean_minutes: float | None  # finished defrosts only
    longest_minutes: float | None
    warm_from: float = WARM_DEFROST_FROM

    def as_attributes(self) -> dict[str, Any]:
        return {
            "defrosts_7d": self.defrosts,
            "warm_defrosts_7d": self.warm_defrosts,
            "mean_minutes_7d": _round(self.mean_minutes, 1),
            "longest_minutes_7d": _round(self.longest_minutes, 1),
            "warm_from": self.warm_from,
        }


def defrost_figures(
    defrosts: Iterable[Defrost],
    outdoor: Mapping[datetime, float],
    start: datetime,
    end: datetime,
    *,
    warm_from: float = WARM_DEFROST_FROM,
) -> DefrostFigures:
    """Defrosts starting in [start, end); `outdoor` maps UTC hour starts to
    hourly means (long-term statistics)."""
    chosen = [d for d in defrosts if start <= d.start < end]
    minutes = [
        (d.end - d.start).total_seconds() / 60 for d in chosen if d.end is not None
    ]
    warm = unknown = 0
    for defrost in chosen:
        hour = defrost.start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        value = outdoor.get(hour)
        if value is None:
            unknown += 1
        elif value >= warm_from:
            warm += 1
    return DefrostFigures(
        defrosts=len(chosen),
        warm_defrosts=warm,
        unknown_outdoor=unknown,
        mean_minutes=sum(minutes) / len(minutes) if minutes else None,
        longest_minutes=max(minutes, default=None),
        warm_from=warm_from,
    )


@dataclass(frozen=True)
class DefrostClass:
    """Defrosts per compressor run hour in one class [lower, upper) of the
    day mean outdoor temperature."""

    lower: float
    upper: float
    days: int
    run_hours: float
    defrosts: int

    @property
    def per_run_hour(self) -> float | None:
        """None for a class with too few days (as in the performance curve)."""
        if self.days < CLASS_MIN_DAYS or self.run_hours <= 0:
            return None
        return self.defrosts / self.run_hours


def defrost_classes(
    entries: Iterable[Mapping[str, Any]],
    first: date,
    last: date,
    *,
    width: float = CLASS_WIDTH,
) -> list[DefrostClass]:
    """Classes from the diary days first … last with an outdoor mean and a run.

    Only for sources that report defrosts; elsewhere every day has 0.
    """
    sums: dict[float, list[float]] = {}
    for entry in _window(entries, first, last):
        outdoor = entry.get("outdoor")
        run_seconds = entry.get("run_seconds") or 0
        if outdoor is None or run_seconds <= 0:
            continue
        row = sums.setdefault(class_lower(outdoor, width), [0, 0.0, 0])
        row[0] += 1
        row[1] += run_seconds / 3600
        row[2] += entry.get("defrosts") or 0
    return [
        DefrostClass(lower, lower + width, int(days), hours, int(count))
        for lower, (days, hours, count) in sorted(sums.items())
    ]


def compare_defrost_classes(
    current: Sequence[DefrostClass], previous: Sequence[DefrostClass]
) -> list[dict[str, Any]]:
    """Classes with a rate in both seasons; `factor` = current / previous."""
    before = {c.lower: c for c in previous}
    rows = []
    for cls in current:
        old = before.get(cls.lower)
        if old is None or cls.per_run_hour is None or old.per_run_hour is None:
            continue
        rows.append(
            {
                "lower": cls.lower,
                "upper": cls.upper,
                "days_current": cls.days,
                "days_previous": old.days,
                "per_run_hour_current": round(cls.per_run_hour, 2),
                "per_run_hour_previous": round(old.per_run_hour, 2),
                "factor": round(cls.per_run_hour / old.per_run_hour, 2)
                if old.per_run_hour > 0
                else None,
            }
        )
    return rows


# 4.4 Spread.


@dataclass(frozen=True)
class SpreadFigure:
    """Spread while the compressor heats; value None with a reason."""

    value: float | None  # K, cold days of the window
    hours: float  # heating time of the cold days
    days: int  # cold days with heating
    all_days: float | None  # K, every day of the window
    reason: str | None = None
    cold_below: float = SPREAD_COLD_BELOW

    def as_attributes(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "heating_hours": round(self.hours, 1),
            "cold_days": self.days,
            "cold_below": self.cold_below,
            "all_days": _round(self.all_days, 1),
            "field_reference": FIELD_SPREAD_K,
            "field_range": list(FIELD_SPREAD_RANGE),
        }


def spread_figure(
    entries: Iterable[Mapping[str, Any]],
    today: date,
    *,
    cold_below: float = SPREAD_COLD_BELOW,
    min_seconds: float = SPREAD_MIN_SECONDS,
    length: int = SPREAD_DAYS,
) -> SpreadFigure:
    """Time-weighted spread from the diary days before `today` (key "spread":
    weighted and seconds while the compressor heats)."""
    window = _window(entries, today - timedelta(days=length), today - timedelta(days=1))
    cold, every = Mean(), Mean()
    days = 0
    for entry in window:
        mean = Mean.from_dict(entry.get("spread"))
        if mean.seconds <= 0:
            continue
        every.weighted += mean.weighted
        every.seconds += mean.seconds
        outdoor = entry.get("outdoor")
        if outdoor is not None and outdoor < cold_below:
            cold.weighted += mean.weighted
            cold.seconds += mean.seconds
            days += 1
    enough = cold.seconds >= min_seconds and cold.value is not None
    return SpreadFigure(
        value=cold.value if enough else None,
        hours=cold.seconds / 3600,
        days=days,
        all_days=every.value,
        reason=None if enough else TOO_LITTLE_HEATING,
        cold_below=cold_below,
    )


# 4.7 Oversizing.


@dataclass(frozen=True)
class OversizeFigure:
    """Rated power over the heat load; factor None with a reason."""

    factor: float | None  # rated / standard heat load at the design temperature
    rated_kw: float | None
    heat_load_kw: float | None  # standard (without gains)
    measured_factor: float | None  # rated / measured heat load (with gains)
    load_mild_kw: float | None  # measured line at MILD_OUTDOOR
    min_kw: float | None
    cycling_expected: bool | None  # load_mild below the smallest power
    reason: str | None = None

    def as_attributes(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "rated_kw": self.rated_kw,
            "heat_load_kw": _round(self.heat_load_kw, 2),
            "measured_factor": _round(self.measured_factor, 2),
            "load_at_7c_kw": _round(self.load_mild_kw, 2),
            "min_kw": self.min_kw,
            "cycling_expected": self.cycling_expected,
            "field_mean": FIELD_OVERSIZE,
        }


def oversizing(
    load: HeatLoad | None, rated_kw: float | None, *, min_kw: float | None = None
) -> OversizeFigure:
    """Oversizing factor from the heat load of the last complete season."""
    mild = standard = measured = None
    if load is not None and load.sufficient:
        assert load.intercept_kw is not None and load.slope_kw_per_k is not None
        mild = max(load.intercept_kw + load.slope_kw_per_k * MILD_OUTDOOR, 0.0)
        standard, measured = load.standard_kw, load.measured_kw
    expected = None if mild is None or min_kw is None else 0 < mild < min_kw
    factor = measured_factor = None
    if rated_kw is None:
        reason: str | None = NO_RATED_POWER
    elif mild is None:
        reason = HEAT_LOAD_INSUFFICIENT
    elif standard is None or standard <= 0 or measured is None or measured <= 0:
        reason = NO_DESIGN_TEMP
    else:
        reason = None
        factor, measured_factor = rated_kw / standard, rated_kw / measured
    return OversizeFigure(
        factor=factor,
        rated_kw=rated_kw,
        heat_load_kw=standard,
        measured_factor=measured_factor,
        load_mild_kw=mild,
        min_kw=min_kw,
        cycling_expected=expected,
        reason=reason,
    )


# 4.8 Standby.

_STANDBY_PREFIX = f"{Kind.STANDBY.value}_"


def standby_day(entry: Mapping[str, Any], tz: tzinfo) -> tuple[float, float] | None:
    """Standby kWh and hours without a run of one diary day.

    None without standby (not separable, or a gap) or with too little time
    without a run.
    """
    energy = entry.get("energy") or {}
    kwh = sum(v for k, v in energy.items() if k.startswith(_STANDBY_PREFIX))
    if kwh <= 0:
        return None
    hours = day_hours(_day(entry), tz) - (entry.get("run_seconds") or 0) / 3600
    if hours < MIN_IDLE_HOURS:
        return None
    return kwh, hours


def standby_rise(
    entries: Iterable[Mapping[str, Any]],
    today: date,
    tz: tzinfo,
    *,
    rise_percent: float = STANDBY_RISE_PERCENT,
    rise_w: float = STANDBY_RISE_W,
) -> Finding:
    """Standby power of the last 7 days against the median of the 30 before."""
    entries = list(entries)
    recent_first = today - timedelta(days=STANDBY_RECENT_DAYS)
    reference_first = recent_first - timedelta(days=STANDBY_REFERENCE_DAYS)

    def days(first: date, last: date) -> list[tuple[float, float]]:
        return [
            d
            for e in _window(entries, first, last)
            if (d := standby_day(e, tz)) is not None
        ]

    recent = days(recent_first, today - timedelta(days=1))
    reference = days(reference_first, recent_first - timedelta(days=1))
    powers = [1000 * kwh / hours for kwh, hours in recent]
    mean = (
        1000 * sum(k for k, _ in recent) / sum(h for _, h in recent) if recent else None
    )
    median = (
        statistics.median(1000 * kwh / hours for kwh, hours in reference)
        if reference
        else None
    )
    evidence: dict[str, Any] = {
        "mean_power_w_7d": _round(mean, 1),
        "min_day_w": _round(min(powers, default=None), 1),
        "max_day_w": _round(max(powers, default=None), 1),
        "reference_w": _round(median, 1),
        "days_7d": len(recent),
        "reference_days": len(reference),
        "threshold_percent": rise_percent,
        "threshold_w": rise_w,
    }
    if not recent and not reference:
        return Finding(None, NO_STANDBY, evidence)
    if (
        mean is None
        or median is None
        or len(recent) < MIN_RECENT_DAYS
        or len(reference) < MIN_REFERENCE_DAYS
    ):
        return Finding(None, TOO_FEW_DAYS, evidence)
    rise = mean - median
    percent = 100 * rise / median  # median > 0: only days with standby
    evidence.update(rise_w=round(rise, 1), rise_percent=round(percent, 1))
    return Finding(rise >= rise_w and percent >= rise_percent, None, evidence)


# 4.10 e Flow.


def to_lph(value: float, unit: str | None) -> float:
    """Convert a volume flow to l/h; raises KeyError for unknown units."""
    return value * LPH_FACTORS[(unit or "").lower()]


def expected_flow(heat_kwh: float, seconds: float, spread: float) -> float:
    """Flow in l/h that carries the mean heat power at this spread."""
    watts = 1000 * heat_kwh / (seconds / 3600)
    return watts / (WATER_WH_PER_L_K * spread)


def flow_plausibility(
    heat_kwh: float,
    spread: Mean,
    flow_rate: Mean,
    *,
    factor: float = FLOW_FACTOR,
) -> Finding:
    """Measured against expected flow over the time the compressor heated.

    `spread` and `flow_rate` (l/h) are sampled under the same condition;
    `heat_kwh` is the rise of the heating heat counter in the same span (a
    day). The heating time is the spread's sample time.
    """
    seconds = spread.seconds
    evidence: dict[str, Any] = {
        "heating_hours": round(seconds / 3600, 1),
        "heat_kwh": round(heat_kwh, 2),
        "spread_k": _round(spread.value, 1),
        "factor": factor,
    }
    if seconds < FLOW_MIN_SECONDS or heat_kwh < FLOW_MIN_HEAT_KWH:
        return Finding(None, TOO_LITTLE_HEATING, evidence)
    if spread.value is None or spread.value < FLOW_MIN_SPREAD:
        return Finding(None, SPREAD_TOO_SMALL, evidence)
    if flow_rate.value is None:
        return Finding(None, NO_FLOW_RATE, evidence)
    expected = expected_flow(heat_kwh, seconds, spread.value)
    measured = flow_rate.value
    ratio = measured / expected
    evidence.update(
        heat_kw=round(heat_kwh / (seconds / 3600), 2),
        measured_lph=round(measured),
        expected_lph=round(expected),
        ratio=round(ratio, 2),
    )
    return Finding(ratio > factor or ratio < 1 / factor, None, evidence)


def flow_plausibility_entry(
    entry: Mapping[str, Any], *, factor: float = FLOW_FACTOR
) -> Finding:
    """flow_plausibility for one diary day (keys "energy", "spread",
    "flow_rate")."""
    energy = entry.get("energy") or {}
    finding = flow_plausibility(
        float(energy.get(f"{Kind.HEAT.value}_heating", 0.0)),
        Mean.from_dict(entry.get("spread")),
        Mean.from_dict(entry.get("flow_rate")),
        factor=factor,
    )
    finding.evidence["day"] = entry.get("day")
    return finding


@dataclass
class ZeroFlow:
    """Heating time with a flow of 0 since the last positive flow.

    Call `add` only while the compressor heats (the spread's condition).
    Unknown flow changes nothing; pauses between runs neither count nor
    reset, so a sensor stuck at 0 shows even with short runs.
    """

    seconds: float = 0.0
    limit: float = ZERO_FLOW_SECONDS

    def add(self, flow_lph: float | None, seconds: float) -> None:
        if flow_lph is None or seconds <= 0:
            return
        self.seconds = self.seconds + seconds if flow_lph <= 0 else 0.0

    @property
    def problem(self) -> bool:
        return self.seconds >= self.limit
