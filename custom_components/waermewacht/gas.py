"""Gas boiler before the switch: heat load, heating limit and hot water share.

Pure Python, no Home Assistant imports. A gas entry has no heat pump logic;
it reuses the pure building blocks heat_load.py, degree_days.py and costs.py
(docs/ENTWICKLUNG.md, "Gas-Modus").

Rules:
- Gas is in kWh of the gross calorific value Hs, as on the bill (DVGW G 685).
  A meter in m³ is converted with calorific value * Z-number of the bill.
  Heat = gas * η_Hs, by default the field efficiency of condensing boilers
  0.87 (costs.BOILER_EFFICIENCY_HS). η goes linearly into the heat load.
- Hot water is separated in one of three ways:
  - a counter of its own ("counter"): from a total counter it is subtracted
    hour by hour; a heating counter stays as it is;
  - from a total counter without one ("summer_base"): the median gas of full
    days with a mean outdoor temperature of at least 15 °C (heating limit of
    VDI 3807, degree_days.G20_15) is hot water; every day gives up to that
    much, each of its hours by the same share. Needs MIN_SUMMER_DAYS such
    days in the window ("no_summer_days" otherwise: nothing is subtracted,
    the share is unknown). Hot water in summer is a little lower (warmer cold
    water), so the share is rather low;
  - a heating counter without a hot water counter ("heating_only"): no hot
    water figures.
  Only the slope of the signature enters the standard heat load, so a hot
  water base left in shifts the heating limit, not the standard heat load.
- The window is the last 365 full local days: a household that measures
  before the switch rarely has whole seasons.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo

from .costs import BOILER_EFFICIENCY_HS, base_price_share
from .curve import MIN_DAY_HOURS, daily_samples
from .degree_days import G20_15, DegreeDays, degree_days
from .energy import Kind, Totals
from .heat_load import HeatLoad, heat_load
from .model import Mode
from .periods import local_midnight

WINDOW_DAYS = 365
# Hot water from summer days (own assumption: two weeks give a stable median).
SUMMER_FROM = G20_15.limit
MIN_SUMMER_DAYS = 14

COUNTER = "counter"
SUMMER_BASE = "summer_base"
NO_SUMMER_DAYS = "no_summer_days"
HEATING_ONLY = "heating_only"


@dataclass
class GasSplit:
    """Hourly gas (kWh Hs) for heating and hot water, and how it was split."""

    heating: dict[datetime, float]
    dhw: dict[datetime, float]
    method: str
    summer_days: int = 0
    summer_base_kwh: float | None = None  # gas per day for hot water

    @property
    def dhw_known(self) -> bool:
        return self.method in (COUNTER, SUMMER_BASE)


def volume_to_kwh(
    hourly: Mapping[datetime, float], calorific_value: float, z_number: float
) -> dict[datetime, float]:
    """m³ per hour -> kWh (Hs) per hour, as the bill converts."""
    if calorific_value <= 0 or z_number <= 0:
        raise ValueError("calorific value and Z-number must be positive")
    factor = calorific_value * z_number
    return {hour: m3 * factor for hour, m3 in hourly.items()}


def _as_totals(hourly: Mapping[datetime, float]) -> dict[datetime, Totals]:
    result = {}
    for hour, kwh in hourly.items():
        totals = Totals()
        totals.add(Kind.HEAT, Mode.HEATING, kwh)
        result[hour] = totals
    return result


def summer_base(
    gas: Mapping[datetime, float],
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
    *,
    from_temp: float = SUMMER_FROM,
    min_days: int = MIN_SUMMER_DAYS,
) -> tuple[float | None, int]:
    """Median gas of full days with a mean of at least `from_temp`, and the
    number of such days; None with fewer than `min_days`."""
    days = [
        d.totals.heat(Mode.HEATING)
        for d in daily_samples(_as_totals(gas), outdoor, tz)
        if d.energy_hours >= MIN_DAY_HOURS and d.mean_outdoor >= from_temp
    ]
    if len(days) < min_days:
        return None, len(days)
    return statistics.median(days), len(days)


def split_dhw(
    gas: Mapping[datetime, float],
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
    *,
    includes_dhw: bool,
    dhw: Mapping[datetime, float] | None = None,
) -> GasSplit:
    """Heating and hot water gas per hour; `gas` is a total counter when
    `includes_dhw`, else a heating counter."""
    if dhw is not None:
        heating = (
            {h: max(0.0, kwh - dhw.get(h, 0.0)) for h, kwh in gas.items()}
            if includes_dhw
            else dict(gas)
        )
        return GasSplit(heating, dict(dhw), COUNTER)
    if not includes_dhw:
        return GasSplit(dict(gas), {}, HEATING_ONLY)
    base, count = summer_base(gas, outdoor, tz)
    if base is None:
        return GasSplit(dict(gas), {}, NO_SUMMER_DAYS, summer_days=count)
    per_day: dict[date, float] = {}
    for hour, kwh in gas.items():
        day = hour.astimezone(tz).date()
        per_day[day] = per_day.get(day, 0.0) + kwh
    heating: dict[datetime, float] = {}
    water: dict[datetime, float] = {}
    for hour, kwh in gas.items():
        total = per_day[hour.astimezone(tz).date()]
        share = min(1.0, base / total) if total > 0 else 0.0
        water[hour] = kwh * share
        heating[hour] = kwh - water[hour]
    return GasSplit(heating, water, SUMMER_BASE, count, base)


def heat_hours(split: GasSplit, efficiency: float) -> dict[datetime, Totals]:
    """Heat per hour (heating and hot water) from the split gas."""
    if not 0 < efficiency <= 1:
        raise ValueError("boiler efficiency on Hs must be in (0, 1]")
    hours: dict[datetime, Totals] = {}
    for mode, values in ((Mode.HEATING, split.heating), (Mode.DHW, split.dhw)):
        for hour, kwh in values.items():
            hours.setdefault(hour, Totals()).add(Kind.HEAT, mode, kwh * efficiency)
    return hours


def window(now: datetime, tz: tzinfo, days: int = WINDOW_DAYS) -> tuple[date, date]:
    """First local day and the (exclusive) day after the last of the window."""
    today = now.astimezone(tz).date()
    return today - timedelta(days=days), today


@dataclass
class GasAnalysis:
    """Figures of one gas boiler over the window."""

    start: date
    end: date  # exclusive
    efficiency: float
    split: GasSplit
    heat_load: HeatLoad
    degree_days: DegreeDays
    gas_kwh: float  # heating and hot water, Hs
    heating_kwh: float  # gas
    dhw_kwh: float  # gas; 0 unless known
    gas_days: int  # local days with gas data
    cost_eur: float | None = None
    base_cost_eur: float | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def dhw_share(self) -> float | None:
        """Hot water in % of the gas; None unless separated."""
        if not self.split.dhw_known or self.gas_kwh <= 0:
            return None
        return 100 * self.dhw_kwh / self.gas_kwh

    @property
    def heat_kwh(self) -> float:
        return self.gas_kwh * self.efficiency


def analyse(
    gas: Mapping[datetime, float],
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
    start: date,
    end: date,
    *,
    includes_dhw: bool,
    dhw: Mapping[datetime, float] | None = None,
    efficiency: float = BOILER_EFFICIENCY_HS,
    design_temp: float | None = None,
    gas_price: float | None = None,
    gas_base_price: float | None = None,
) -> GasAnalysis:
    """Heat load, degree days, hot water share and gas of [start, end).

    `gas`, `dhw` and `outdoor` are keyed by UTC hour starts; only hours of
    the window count. Prices in €/kWh (Hs) and € per year.
    """
    first, last = local_midnight(start, tz), local_midnight(end, tz)

    def inside(values: Mapping[datetime, float]) -> dict[datetime, float]:
        return {h: v for h, v in values.items() if first <= h < last}

    gas_in, outdoor_in = inside(gas), inside(outdoor)
    split = split_dhw(
        gas_in,
        outdoor_in,
        tz,
        includes_dhw=includes_dhw,
        dhw=None if dhw is None else inside(dhw),
    )
    hours = heat_hours(split, efficiency)
    heating = sum(split.heating.values())
    water = sum(split.dhw.values())
    total = heating + water
    cost = base = None
    if gas_price is not None:
        cost = total * gas_price
        if gas_base_price is not None:
            base = base_price_share(gas_base_price, first, last, tz)
            cost += base
    reasons = [] if split.dhw_known or split.method == HEATING_ONLY else [split.method]
    return GasAnalysis(
        start=start,
        end=end,
        efficiency=efficiency,
        split=split,
        heat_load=heat_load(hours, outdoor_in, tz, design_temp=design_temp),
        degree_days=degree_days(hours, outdoor_in, tz, start, end),
        gas_kwh=total,
        heating_kwh=heating,
        dhw_kwh=water,
        gas_days=len({h.astimezone(tz).date() for h in gas_in}),
        cost_eur=cost,
        base_cost_eur=base,
        reasons=reasons,
    )
