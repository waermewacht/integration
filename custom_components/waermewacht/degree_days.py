"""Degree days and heating heat per degree day. Pure Python, no HA imports.

Rule (docs/ENTWICKLUNG.md, "Normaußentemperatur, Gradtage, Heizlast"):
degree days G20/15 after VDI 3807 Blatt 1 - per day 20 °C minus the day's
mean outdoor temperature, but only on days with a mean below the heating
limit of 15 °C (DWD description of the HDD 3807 data set). Both values are
configurable, because G20/15 fits a heat pump with a heating limit of about
15 °C poorly (feasibility study, same document, "Stufe 2/3 - Machbarkeit").
Heating degree days with a single base (base minus mean when the mean is
below the base) are the special case reference == limit.

The day mean is the mean of the hourly outdoor means of one LOCAL day
(23 or 25 hours at DST changes). A day needs at least 20 valid hourly values,
otherwise it is skipped and counted as missing. Hourly values outside
-35 … +45 °C are discarded (sun or exhaust air on the sensor).

"Heat per degree day" scatters by about 18 % from month to month, so the
integration shows it as a season value only; this module computes it for any
period and leaves that choice to the caller. Days with degree days but
without heating heat are reported (heating off, summer mode held by hand).
The degree days themselves follow the standard, but the heat per degree day
uses heating days only (at least MIN_HEATING_DAY_KWH): G20/15 counts every
cool summer and autumn day, and a season that started heating in October
would otherwise show a third of the real value.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo

from .energy import Totals
from .model import Mode
from .periods import local_midnight

OUTDOOR_MIN = -35.0  # °C, plausible range of an hourly outdoor mean
OUTDOOR_MAX = 45.0
MIN_DAY_HOURS = 20  # valid hourly outdoor values a day needs
# Below this sum the heat per degree day is not shown (a few mild days would
# give a huge, meaningless value). Not from a standard: about one cold day.
MIN_DEGREE_DAYS = 10.0  # K·d
# A day with less heating heat is not a heating day (own assumption: pumps,
# a short run on a cool summer morning).
MIN_HEATING_DAY_KWH = 1.0


@dataclass(frozen=True)
class DegreeDayBase:
    """Indoor reference and heating limit of a degree day sum.

    A day counts when its mean outdoor temperature is below `limit`; it then
    adds `reference - mean`. G20/15 is (20, 15); heating degree days with a
    single base b are (b, b).
    """

    reference: float  # °C, the day mean is subtracted from this
    limit: float  # °C, heating limit: only days with a mean below count

    def __post_init__(self) -> None:
        if not (math.isfinite(self.reference) and math.isfinite(self.limit)):
            raise ValueError("degree day base must be finite")
        if self.limit > self.reference:
            raise ValueError("heating limit above the indoor reference")

    @classmethod
    def single(cls, base: float) -> DegreeDayBase:
        """Heating degree days with one base temperature."""
        return cls(base, base)

    def day_value(self, mean: float) -> float:
        """Degree days (K·d) of one day with the mean outdoor temperature."""
        return self.reference - mean if mean < self.limit else 0.0


# Default: VDI 3807 Blatt 1 (docs/ENTWICKLUNG.md).
G20_15 = DegreeDayBase(20.0, 15.0)


@dataclass(frozen=True)
class DayDegrees:
    """One local day with a valid mean outdoor temperature."""

    day: date
    hours: int  # valid hourly outdoor values
    mean_outdoor: float  # °C
    degree_days: float  # K·d
    heating_kwh: float  # heating heat (Mode.HEATING) booked in this day's hours


@dataclass(frozen=True)
class DegreeDays:
    """Degree days of a period of local days and the heating heat on them.

    `heating_kwh` is the heating heat of the counted days only, so that it
    matches the degree days; heat on missing days is in
    `heating_kwh_missing_days`.
    """

    base: DegreeDayBase
    start: date  # first local day
    end: date  # local day after the last one
    degree_days: float  # K·d
    days_counted: int
    missing_days: tuple[date, ...]  # fewer than the minimum hourly values
    days_without_heating: tuple[date, ...]  # degree days > 0, no heating heat
    heating_kwh: float
    heating_kwh_missing_days: float
    degree_days_heating: float  # K·d of the heating days only
    kwh_per_degree_day: float | None  # heating days; None below the minimum

    @property
    def days_missing(self) -> int:
        return len(self.missing_days)


def valid_outdoor(value: float | None) -> bool:
    """An hourly outdoor mean inside the plausible range."""
    return (
        value is not None
        and math.isfinite(value)
        and OUTDOOR_MIN <= value <= OUTDOOR_MAX
    )


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=n) for n in range((end - start).days)]


def daily_degree_days(
    hours: Mapping[datetime, Totals],
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
    start: date,
    end: date,
    base: DegreeDayBase = G20_15,
    *,
    min_hours: int = MIN_DAY_HOURS,
) -> tuple[list[DayDegrees], list[date], dict[date, float]]:
    """Per local day in [start, end): the valid days and the missing days.

    `hours` and `outdoor` are keyed by UTC hour starts; an hour belongs to the
    local day its start falls in. Returns the valid days, the missing days
    (fewer than `min_hours` valid outdoor values) and the heating heat of
    every day in the range (missing ones included).
    """
    first = local_midnight(start, tz)
    last = local_midnight(end, tz)
    temps: dict[date, list[float]] = {}
    for hour, value in outdoor.items():
        if first <= hour < last and valid_outdoor(value):
            temps.setdefault(hour.astimezone(tz).date(), []).append(value)
    heat: dict[date, float] = {}
    for hour, totals in hours.items():
        if first <= hour < last:
            day = hour.astimezone(tz).date()
            heat[day] = heat.get(day, 0.0) + totals.heat(Mode.HEATING)

    valid: list[DayDegrees] = []
    missing: list[date] = []
    for day in _days(start, end):
        values = temps.get(day, [])
        if len(values) < min_hours:
            missing.append(day)
            continue
        mean = sum(values) / len(values)
        valid.append(
            DayDegrees(
                day=day,
                hours=len(values),
                mean_outdoor=mean,
                degree_days=base.day_value(mean),
                heating_kwh=heat.get(day, 0.0),
            )
        )
    return valid, missing, heat


def heat_per_degree_day(
    days: Iterable[DayDegrees],
    *,
    min_degree_days: float = MIN_DEGREE_DAYS,
    min_heating_kwh: float = MIN_HEATING_DAY_KWH,
) -> tuple[float | None, float]:
    """Heating heat per degree day over the heating days, and their degree
    days. None below `min_degree_days` or without heating heat."""
    # Heat on a heating day above the limit (0 K·d) still counts, as in the
    # period sum of VDI 3807; only days without heating drop out.
    heating_days = [d for d in days if d.heating_kwh >= min_heating_kwh]
    total = sum(d.degree_days for d in heating_days)
    heat = sum(d.heating_kwh for d in heating_days)
    if total <= 0 or total < min_degree_days or heat <= 0:
        return None, total
    return heat / total, total


def degree_days(
    hours: Mapping[datetime, Totals],
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
    start: date,
    end: date,
    base: DegreeDayBase = G20_15,
    *,
    min_hours: int = MIN_DAY_HOURS,
    min_degree_days: float = MIN_DEGREE_DAYS,
) -> DegreeDays:
    """Degree days, heating heat and heat per degree day of [start, end).

    `start` and `end` are local dates, `end` exclusive. The heat per degree
    day is None when the degree days are 0 or below `min_degree_days`.
    """
    valid, missing, heat = daily_degree_days(
        hours, outdoor, tz, start, end, base, min_hours=min_hours
    )
    total = sum(d.degree_days for d in valid)
    heating = sum(d.heating_kwh for d in valid)
    per_degree_day, heating_degree_days = heat_per_degree_day(
        valid, min_degree_days=min_degree_days
    )
    return DegreeDays(
        base=base,
        start=start,
        end=end,
        degree_days=total,
        days_counted=len(valid),
        missing_days=tuple(missing),
        days_without_heating=tuple(
            d.day for d in valid if d.degree_days > 0 and d.heating_kwh <= 0
        ),
        heating_kwh=heating,
        heating_kwh_missing_days=sum(heat.get(day, 0.0) for day in missing),
        degree_days_heating=heating_degree_days,
        kwh_per_degree_day=per_degree_day,
    )
