"""Gas boiler with meter readings entered by hand. Pure Python, no HA imports.

Many gas boilers have no counter in Home Assistant, but a gas meter in the
basement. The user enters its reading now and then (weekly is best); each
period between two readings is one point of the energy signature instead of
a week (docs/ENTWICKLUNG.md, "Gas-Modus", step 3):

- A period counts when it lasts MIN_DAYS to MAX_DAYS (own assumption: shorter
  periods carry the noise of single days, longer ones blur the weather), has
  hourly outdoor values for at least MIN_COVERAGE of its hours, a mean below
  heat_load.MAX_WEEK_OUTDOOR and heating (degree_days.MIN_HEATING_DAY_KWH of
  heat per day on average).
- Its power is the heating heat over all its real hours; the line is fitted
  with each period weighted by its hours, so that a month does not count as
  much as a week. The rules of the weekly signature apply otherwise (spread,
  frost days); instead of 8 weeks it needs MIN_PERIODS periods covering
  MIN_PERIOD_DAYS days.
- Gas is never spread over hours by an assumed curve: that would put the
  points of a month onto a line made up beforehand.
- Hot water: the median gas per day of the periods with a mean of at least
  15 °C (gas.SUMMER_FROM) is hot water, if they cover gas.MIN_SUMMER_DAYS
  days; it is subtracted per day from every period ("summer_base"), else
  nothing is ("no_summer_days").
- Gas of the window (365 days) between the readings by linear interpolation.
"""

from __future__ import annotations

import bisect
import itertools
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo

from .costs import base_price_share
from .curve import MIN_DAY_HOURS
from .degree_days import (
    G20_15,
    MIN_DEGREE_DAYS,
    MIN_HEATING_DAY_KWH,
    DegreeDays,
    daily_degree_days,
    valid_outdoor,
)
from .gas import (
    MIN_SUMMER_DAYS,
    NO_SUMMER_DAYS,
    SUMMER_BASE,
    SUMMER_FROM,
    GasAnalysis,
    GasSplit,
)
from .heat_load import FROST, MAX_WEEK_OUTDOOR, HeatLoad, WeekPoint, fit_signature
from .periods import local_midnight

MIN_DAYS = 5.0  # a period shorter than this does not enter the signature
MAX_DAYS = 35.0  # nor a longer one (monthly readings still count)
MIN_COVERAGE = 0.9  # share of a period's hours with an outdoor value
MIN_PERIODS = 4
MIN_PERIOD_DAYS = 56  # as the 8 weeks of the weekly signature
TOO_FEW_PERIODS = "too_few_periods"
MAX_READINGS = 2000  # about 40 years of weekly readings

# Errors when adding a reading (translation keys).
NOT_RISING = "reading_not_rising"
NEGATIVE = "reading_negative"


@dataclass(frozen=True)
class Reading:
    """A meter reading in the meter's unit (m³ or kWh) at a UTC time."""

    at: datetime
    value: float


def check_reading(
    readings: Sequence[Reading], at: datetime, value: float
) -> str | None:
    """Error key if `value` at `at` does not fit between its neighbours (a
    meter only counts up; a reading at the same time replaces the old one)."""
    if value < 0:
        return NEGATIVE
    others = [r for r in readings if r.at != at]
    before = [r.value for r in others if r.at < at]
    after = [r.value for r in others if r.at > at]
    if (before and value < max(before)) or (after and value > min(after)):
        return NOT_RISING
    return None


def add_reading(readings: Sequence[Reading], reading: Reading) -> list[Reading]:
    """The readings with `reading` added (replacing one at the same time)."""
    result = [r for r in readings if r.at != reading.at]
    bisect.insort(result, reading, key=lambda r: r.at)
    return result[-MAX_READINGS:]


@dataclass(frozen=True)
class Period:
    """The time between two readings."""

    start: datetime
    end: datetime
    gas_kwh: float  # Hs
    outdoor_hours: int  # hours with a valid outdoor value
    mean_outdoor: float | None
    degree_days: float  # G20/15, shares of the days it touches
    frost_days: int  # local days wholly inside with a mean below 0 °C

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600

    @property
    def days(self) -> float:
        return self.hours / 24

    @property
    def coverage(self) -> float:
        return self.outdoor_hours / self.hours if self.hours > 0 else 0.0


def to_kwh(
    readings: Sequence[Reading],
    *,
    volume: bool,
    calorific_value: float | None = None,
    z_number: float | None = None,
) -> list[tuple[datetime, float]]:
    """(time, kWh Hs) of the readings; m³ times calorific value and Z-number."""
    if not volume:
        return [(r.at, r.value) for r in readings]
    if not calorific_value or not z_number or calorific_value <= 0 or z_number <= 0:
        raise ValueError("calorific value and Z-number must be positive")
    factor = calorific_value * z_number
    return [(r.at, r.value * factor) for r in readings]


def periods(
    readings: Sequence[tuple[datetime, float]],
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
) -> list[Period]:
    """Periods between consecutive readings (kWh), with their weather.

    Outdoor values are hourly means keyed by UTC hour starts; an hour belongs
    to the period its start falls in.
    """
    day_values: dict[date, list[float]] = {}
    for hour, value in outdoor.items():
        if valid_outdoor(value):
            day_values.setdefault(hour.astimezone(tz).date(), []).append(value)
    day_mean = {
        d: sum(v) / len(v) for d, v in day_values.items() if len(v) >= MIN_DAY_HOURS
    }
    hours = sorted(h for h, v in outdoor.items() if valid_outdoor(v))
    result = []
    for (start, first), (end, last) in itertools.pairwise(readings):
        lo = bisect.bisect_left(hours, start)
        hi = bisect.bisect_left(hours, end)
        inside = hours[lo:hi]
        per_day: dict[date, int] = {}
        for hour in inside:
            day = hour.astimezone(tz).date()
            per_day[day] = per_day.get(day, 0) + 1
        degree = sum(
            G20_15.day_value(day_mean[d]) * n / len(day_values[d])
            for d, n in per_day.items()
            if d in day_mean
        )
        frost = sum(
            1
            for d, n in per_day.items()
            if d in day_mean and n == len(day_values[d]) and day_mean[d] < FROST
        )
        result.append(
            Period(
                start=start,
                end=end,
                gas_kwh=max(0.0, last - first),
                outdoor_hours=len(inside),
                mean_outdoor=(
                    sum(outdoor[h] for h in inside) / len(inside) if inside else None
                ),
                degree_days=degree,
                frost_days=frost,
            )
        )
    return result


def _usable(period: Period) -> bool:
    return (
        period.days >= MIN_DAYS
        and period.coverage >= MIN_COVERAGE
        and period.mean_outdoor is not None
    )


def summer_base(found: Sequence[Period]) -> tuple[float | None, int]:
    """Hot water gas per day (median of warm periods) and their days; None
    when they cover fewer than gas.MIN_SUMMER_DAYS days."""
    warm = [
        p
        for p in found
        if _usable(p) and p.mean_outdoor is not None and p.mean_outdoor >= SUMMER_FROM
    ]
    days = round(sum(p.days for p in warm))
    if days < MIN_SUMMER_DAYS:
        return None, days
    return statistics.median(p.gas_kwh / p.days for p in warm), days


def _heating_kwh(period: Period, dhw_per_day: float | None, efficiency: float) -> float:
    gas = period.gas_kwh - (dhw_per_day or 0.0) * period.days
    return max(0.0, gas) * efficiency


def signature_points(
    found: Sequence[Period], dhw_per_day: float | None, efficiency: float, tz: tzinfo
) -> list[WeekPoint]:
    """Periods that enter the signature, as points like weeks."""
    points = []
    for period in found:
        if not _usable(period) or period.days > MAX_DAYS:
            continue
        assert period.mean_outdoor is not None
        if period.mean_outdoor >= MAX_WEEK_OUTDOOR:
            continue
        heat = _heating_kwh(period, dhw_per_day, efficiency)
        if heat / period.days < MIN_HEATING_DAY_KWH:
            continue
        points.append(
            WeekPoint(
                start=period.start.astimezone(tz).date(),
                days=round(period.days),
                hours=round(period.hours),
                mean_outdoor=period.mean_outdoor,
                power_kw=heat / period.hours,
                frost_days=period.frost_days,
            )
        )
    return points


def readings_signature(
    found: Sequence[Period],
    dhw_per_day: float | None,
    efficiency: float,
    tz: tzinfo,
    *,
    design_temp: float | None = None,
) -> HeatLoad:
    """Energy signature from the periods between readings."""
    points = signature_points(found, dhw_per_day, efficiency, tz)
    return fit_signature(
        points,
        enough=len(points) >= MIN_PERIODS
        and sum(p.days for p in points) >= MIN_PERIOD_DAYS,
        too_few=TOO_FEW_PERIODS,
        design_temp=design_temp,
        weighted=True,
    )


def _between(readings: Sequence[tuple[datetime, float]], at: datetime) -> float:
    """Meter reading (kWh) at `at`, linear between the readings around it."""
    times = [t for t, _ in readings]
    i = bisect.bisect_right(times, at)
    if i == 0:
        return readings[0][1]
    if i == len(readings):
        return readings[-1][1]
    (t0, v0), (t1, v1) = readings[i - 1], readings[i]
    return v0 + (v1 - v0) * (at - t0) / (t1 - t0)


def inside(found: Sequence[Period], start: datetime, end: datetime) -> list[Period]:
    """Periods lying wholly in [start, end)."""
    return [p for p in found if start <= p.start and p.end <= end]


def analyse_readings(
    readings: Sequence[tuple[datetime, float]],
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
    start: date,
    end: date,
    *,
    efficiency: float,
    design_temp: float | None = None,
    gas_price: float | None = None,
    gas_base_price: float | None = None,
) -> GasAnalysis:
    """The figures of a gas boiler entry (gas.GasAnalysis) from readings in
    kWh (Hs) for the local days [start, end)."""
    if not 0 < efficiency <= 1:
        raise ValueError("boiler efficiency on Hs must be in (0, 1]")
    first, last = local_midnight(start, tz), local_midnight(end, tz)
    found = inside(periods(readings, outdoor, tz), first, last)
    dhw_per_day, summer_days = summer_base(found)
    method = SUMMER_BASE if dhw_per_day is not None else NO_SUMMER_DAYS
    load = readings_signature(
        found, dhw_per_day, efficiency, tz, design_temp=design_temp
    )

    # Gas of the window between the readings it overlaps.
    gas = covered = 0.0
    if len(readings) >= 2:
        a, b = max(first, readings[0][0]), min(last, readings[-1][0])
        if b > a:
            gas = _between(readings, b) - _between(readings, a)
            covered = (b - a) / timedelta(days=1)
    water = min(gas, (dhw_per_day or 0.0) * covered)
    heating = gas - water

    # Degree days of the window; heat per degree day over heating periods.
    days, missing, _ = daily_degree_days({}, outdoor, tz, start, end)
    heated = [
        p
        for p in found
        if _usable(p)
        and _heating_kwh(p, dhw_per_day, efficiency) / p.days >= MIN_HEATING_DAY_KWH
    ]
    heat = sum(_heating_kwh(p, dhw_per_day, efficiency) for p in heated)
    degree = sum(p.degree_days for p in heated)
    degree_days = DegreeDays(
        base=G20_15,
        start=start,
        end=end,
        degree_days=sum(d.degree_days for d in days),
        days_counted=len(days),
        missing_days=tuple(missing),
        days_without_heating=(),
        heating_kwh=heat,
        heating_kwh_missing_days=0.0,
        degree_days_heating=degree,
        kwh_per_degree_day=heat / degree if degree >= MIN_DEGREE_DAYS else None,
    )

    cost = base = None
    if gas_price is not None:
        cost = gas * gas_price
        if gas_base_price is not None:
            base = base_price_share(gas_base_price, first, last, tz)
            cost += base
    return GasAnalysis(
        start=start,
        end=end,
        efficiency=efficiency,
        split=GasSplit({}, {}, method, summer_days, dhw_per_day),
        heat_load=load,
        degree_days=degree_days,
        gas_kwh=gas,
        heating_kwh=heating,
        dhw_kwh=water if dhw_per_day is not None else 0.0,
        gas_days=int(covered),
        cost_eur=cost,
        base_cost_eur=base,
        reasons=[] if dhw_per_day is not None else [NO_SUMMER_DAYS],
        design_temp=design_temp,
    )
