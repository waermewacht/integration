"""Electricity prices from a sensor (dynamic tariff). Pure Python, no HA imports.

Rules (docs/ENTWICKLUNG.md, "Strompreis aus einem Sensor"):

- Units: ct/kWh, €/kWh (EUR/kWh) and €/MWh (EUR/MWh); any other unit is
  refused, never guessed.
- The price of an hour (UTC hour start) is the mean of the sensor in that
  hour: the hourly mean of the long-term statistics, else the time-weighted
  mean of its recorded states. Within the hour, consumption is not weighted
  (15-minute prices count as their hourly mean).
- Electricity of an hour gets the price of that hour (costs.electricity_cost);
  an hour without one falls back to the fixed price, or without that counts
  as missing (the cost is then unknown).
- Sources with day values book a day's energy in one hour: it gets the mean
  price of its local day.
- A period (month, season: both start at a local midnight) sums the priced
  local days from its start, plus what the statistics do not hold yet (the
  running hour, late counters) at the current price of the sensor, else the
  fixed price.
- With grid, PV and battery meters, own electricity of an hour is priced at
  the feed-in tariff instead (allocation.py): the day's saving is taken off
  its cost. The rest of a period counts as from the grid.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, tzinfo
from itertools import pairwise

from .allocation import Allocation, SplitSettings, allocate
from .costs import NO_ELECTRICITY, ElectricityCost, electricity_cost
from .energy import SEASONAL_MODES, Kind, Totals
from .model import Mode
from .periods import local_midnight
from .solar import HourFlows

HOUR = timedelta(hours=1)

# Unit (lower case, without spaces) -> factor to €/kWh.
PRICE_UNITS: dict[str, float] = {
    "ct/kwh": 0.01,
    "cent/kwh": 0.01,
    "eur/kwh": 1.0,
    "€/kwh": 1.0,
    "eur/mwh": 0.001,
    "€/mwh": 0.001,
}
# As the error message of the options names them.
ACCEPTED_UNITS = "ct/kWh, €/kWh (EUR/kWh), €/MWh (EUR/MWh)"

# Where the prices of a cost came from (attribute price_source).
SENSOR, FIXED, MIXED = "sensor", "fixed", "mixed"


def price_factor(unit: str | None) -> float | None:
    """Factor from `unit` to €/kWh, None for a unit not accepted."""
    if not unit:
        return None
    return PRICE_UNITS.get("".join(unit.split()).lower())


def to_eur_per_kwh(value: float | None, unit: str | None) -> float | None:
    """A price in €/kWh, None for no value or a unit not accepted."""
    factor = price_factor(unit)
    if factor is None or value is None or not math.isfinite(value):
        return None
    return value * factor


def floor_hour(at: datetime) -> datetime:
    """Start of the UTC hour of `at` (whole-hour offsets keep it local too)."""
    return at.replace(minute=0, second=0, microsecond=0)


def hours_between(start: datetime, end: datetime) -> list[datetime]:
    """Hour starts in [start, end), `start` a full hour."""
    result = []
    hour = start
    while hour < end:
        result.append(hour)
        hour += HOUR
    return result


def hourly_means(
    samples: Iterable[tuple[datetime, float | None]],
    start: datetime,
    end: datetime,
) -> dict[datetime, float]:
    """Time-weighted mean per UTC hour in [start, end) of a stepwise value.

    Each sample holds until the next one (the last until `end`); a value
    None (unavailable) holds nothing. Hours without any known time are left
    out; a partly known hour is the mean of its known part.
    """
    sums: dict[datetime, list[float]] = {}
    ordered = sorted(samples, key=lambda sample: sample[0])
    for (at, value), (until, _) in pairwise([*ordered, (end, None)]):
        if value is None:
            continue
        lo, hi = max(at, start), min(until, end)
        while lo < hi:
            hour = floor_hour(lo)
            step = min(hour + HOUR, hi)
            seconds = (step - lo).total_seconds()
            found = sums.setdefault(hour, [0.0, 0.0])
            found[0] += value * seconds
            found[1] += seconds
            lo = step
    return {hour: total / seconds for hour, (total, seconds) in sums.items() if seconds}


def day_mean_prices(
    prices: Mapping[datetime, float], hours: Iterable[datetime], tz: tzinfo
) -> dict[datetime, float]:
    """For each of `hours` the mean price of its local day (day values)."""
    by_day: dict[date, list[float]] = {}
    for hour, price in prices.items():
        by_day.setdefault(hour.astimezone(tz).date(), []).append(price)
    means = {day: sum(values) / len(values) for day, values in by_day.items()}
    return {
        hour: means[day]
        for hour in hours
        if (day := hour.astimezone(tz).date()) in means
    }


@dataclass(frozen=True)
class PricedDay:
    """The priced hours of one local day."""

    electricity: ElectricityCost  # all of it at the grid price
    heat_kwh: float  # heating and hot water (the gas comparison)
    allocation: Allocation | None = None  # grid and own electricity


def price_days(
    hours: Mapping[datetime, Totals],
    prices: Mapping[datetime, float],
    fixed: float | None,
    tz: tzinfo,
    flows: Mapping[datetime, HourFlows] | None = None,
    split: SplitSettings | None = None,
) -> dict[datetime, PricedDay]:
    """Hourly energy priced hour by hour and summed per local day (key: the
    day's start in UTC); with `split`, its own electricity apart."""
    days: dict[date, dict[datetime, Totals]] = {}
    for hour, totals in hours.items():
        days.setdefault(hour.astimezone(tz).date(), {})[hour] = totals
    return {
        local_midnight(day, tz): PricedDay(
            electricity_cost(day_hours, price=fixed, hourly_prices=prices),
            sum(t.heat(*SEASONAL_MODES) for t in day_hours.values()),
            None
            if split is None
            else allocate(day_hours, flows or {}, prices, fixed, split),
        )
        for day, day_hours in days.items()
    }


def period_allocation(
    days: Mapping[datetime, PricedDay], start: datetime
) -> Allocation | None:
    """Grid and own electricity of the priced days from `start` on (None
    without the meters)."""
    found = [p.allocation for d, p in days.items() if d >= start]
    if not found or any(a is None for a in found):
        return None
    total = Allocation()
    for allocation in found:
        assert allocation is not None
        total = total + allocation
    return total


def period_cost(
    days: Mapping[datetime, PricedDay],
    start: datetime,
    totals: Totals,
    *,
    current: float | None,
    fixed: float | None,
    at: datetime,
) -> tuple[ElectricityCost, float]:
    """Electricity cost and heat (heating + hot water) of a period from
    `start` (a local midnight) whose energy so far is `totals`.

    The priced days from `start` on, plus the rest of `totals` that they do
    not hold (the hour running, hours the statistics have not written yet)
    priced at `current`, else at `fixed`; booked as one hour at `at`.
    """
    electricity = NO_ELECTRICITY
    for day, priced in days.items():
        if day >= start:
            electricity = electricity + priced.electricity
    heat_side = totals.electricity(*SEASONAL_MODES) + totals.standby()
    cooling = totals.electricity(Mode.COOLING)
    rest = Totals()
    rest.add(Kind.ELEC, Mode.HEATING, heat_side - electricity.heat_electricity_kwh)
    rest.add(
        Kind.ELEC,
        Mode.COOLING,
        cooling - (electricity.electricity_kwh - electricity.heat_electricity_kwh),
    )
    electricity = electricity + electricity_cost(
        {at: rest},
        price=fixed,
        hourly_prices={} if current is None else {at: current},
    )
    if (allocation := period_allocation(days, start)) is not None:
        # Own electricity at the feed-in tariff instead of the grid price.
        electricity = replace(
            electricity,
            cost_eur=None
            if electricity.cost_eur is None
            else electricity.cost_eur - allocation.saving_eur,
            heat_cost_eur=None
            if electricity.heat_cost_eur is None
            else electricity.heat_cost_eur - allocation.heat_saving_eur,
        )
    return electricity, totals.heat(*SEASONAL_MODES)


def price_source(electricity: ElectricityCost) -> str:
    """sensor, fixed or mixed: which prices the cost was built from."""
    if electricity.hourly_hours and electricity.fallback_hours:
        return MIXED
    if electricity.fallback_hours:
        return FIXED
    return SENSOR
