"""Heat costs and the comparison with a gas boiler. Pure Python, no HA imports.

Rules (docs/ENTWICKLUNG.md, "Emissionsfaktoren (Stufe 2)"):

- Prices are in €/kWh (not ct/kWh), gross as paid. They are never assumed:
  every price is a required parameter, None means unknown and the figures
  built from it are None.
- Electricity cost covers all electricity of the heat pump: every mode,
  running and standby, backup heater included. Energy without a price is
  never counted as free; the cost is then unknown and the hours are reported.
- Heat cost and the gas comparison use heating plus hot water on the boundary
  of the seasonal ratio (energy.combined_ratio): electricity of both modes
  plus standby, backup heater included (SEPEMO H3). Cooling is left out - a
  gas boiler cannot cool.
- Gas is billed in kWh of the gross calorific value Hs (DVGW G 685). Gas for
  the same heat = heat / η_Hs, with the field efficiency of condensing
  boilers η_Hs = 0.87 (86.6 % on Hs, Jagnow/Wolff, DBU 2004, 60 boilers).
- CO₂ of gas = kWh_Hs * 0.906 (Hs → Hi, BAFA) * factor on Hi. Electricity
  and gas factors come in pairs of the same method and are never mixed:
  with upstream chains 406 / 240 (default), direct 344 / 201.
- An annual base price of gas is prorated per local day as the annual price
  ÷ 365 or 366 (as in Tarifwacht), partial days by their share of real hours.
- An annual base price of electricity counts only for a meter of the heat pump
  alone (heat pump tariff); it is prorated the same way and belongs to heating
  and hot water. On the household meter it is paid anyway and left out.
- Both base prices count from the first hour with data on (`data_from`):
  a period the meters cover only in part (statistics since a few days)
  would otherwise set a whole season of base price against a few days of
  heat.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo

from .dated import Dated, Price, value_at
from .energy import SEASONAL_MODES, Totals
from .model import Mode
from .periods import local_midnight

# Field efficiency of condensing gas boilers on Hs (Jagnow/Wolff, DBU 2004;
# also cited by Fraunhofer ISE), docs/ENTWICKLUNG.md.
BOILER_EFFICIENCY_HS = 0.87
# Conversion from gross (Hs) to net calorific value (Hi) of natural gas,
# BAFA Infoblatt CO₂-Faktoren 2025.
HS_TO_HI = 0.906
# Below this heat (kWh) the heat cost per kWh is not shown.
MIN_HEAT_KWH = 0.5


@dataclass(frozen=True)
class EmissionFactors:
    """A pair of emission factors of the same method, in g CO₂(-eq) per kWh."""

    electricity: float  # per kWh electricity
    gas_hi: float  # per kWh gas on the net calorific value Hi
    hs_to_hi: float = HS_TO_HI

    @property
    def gas_hs(self) -> float:
        """Factor per kWh gas on the gross calorific value Hs (as billed)."""
        return self.gas_hi * self.hs_to_hi


# Electricity: UBA Climate Change 16/2026, Tab. 1/2 (German mix 2025,
# estimate). Gas with upstream: GEG Anlage 9 (240 g; reference to Hi and
# upstream chains inferred, not stated there). Gas direct: BAFA Infoblatt
# CO₂-Faktoren 2025, 3.4 (201 g on Hi; UBA CC 28/2022).
WITH_UPSTREAM = EmissionFactors(electricity=406.0, gas_hi=240.0)
DIRECT = EmissionFactors(electricity=344.0, gas_hi=201.0)


@dataclass(frozen=True)
class ElectricityCost:
    """Electricity of a period and its cost.

    `heat_*` is the share of heating and hot water with standby (no cooling).
    A cost is None when some of its electricity has no price.
    """

    electricity_kwh: float  # all modes, standby and backup heater
    heat_electricity_kwh: float  # heating + hot water + standby
    cost_eur: float | None
    heat_cost_eur: float | None
    fallback_hours: int  # hours priced with the fixed price
    missing_hours: int  # hours with electricity but without any price
    missing_kwh: float
    heat_missing_kwh: float
    hourly_hours: int = 0  # hours priced with their own hourly price

    def __add__(self, other: ElectricityCost) -> ElectricityCost:
        """Both parts together; a cost unknown in one is unknown in the sum."""
        return ElectricityCost(
            electricity_kwh=self.electricity_kwh + other.electricity_kwh,
            heat_electricity_kwh=self.heat_electricity_kwh + other.heat_electricity_kwh,
            cost_eur=None
            if self.cost_eur is None or other.cost_eur is None
            else self.cost_eur + other.cost_eur,
            heat_cost_eur=None
            if self.heat_cost_eur is None or other.heat_cost_eur is None
            else self.heat_cost_eur + other.heat_cost_eur,
            fallback_hours=self.fallback_hours + other.fallback_hours,
            missing_hours=self.missing_hours + other.missing_hours,
            missing_kwh=self.missing_kwh + other.missing_kwh,
            heat_missing_kwh=self.heat_missing_kwh + other.heat_missing_kwh,
            hourly_hours=self.hourly_hours + other.hourly_hours,
        )

    @property
    def average_price(self) -> float | None:
        """Mean price paid in €/kWh (None when unknown or no electricity)."""
        if self.cost_eur is None or self.electricity_kwh <= 0:
            return None
        return self.cost_eur / self.electricity_kwh


@dataclass(frozen=True)
class CostComparison:
    """Heat pump against a gas boiler for the same heat (heating + hot water).

    Money in €, energy in kWh, CO₂ in kg. Savings are gas minus heat pump
    (positive: the heat pump is cheaper or cleaner). None where an input is
    missing.
    """

    heat_kwh: float  # heating + hot water
    electricity: ElectricityCost
    heat_pump_cost_eur: float | None  # electricity for heating + hot water
    electricity_base_cost_eur: float  # prorated base price of a heat pump meter
    heat_cost_per_kwh: float | None  # €/kWh heat
    boiler_efficiency: float  # η on Hs
    gas_kwh: float  # Hs
    gas_energy_cost_eur: float | None
    gas_base_cost_eur: float  # prorated annual base price, 0 without
    gas_cost_eur: float | None
    gas_cost_per_kwh: float | None  # €/kWh heat
    factors: EmissionFactors
    heat_pump_co2_kg: float
    gas_co2_kg: float
    savings_eur: float | None
    savings_co2_kg: float


# No electricity cost at all (the neutral element of ElectricityCost +).
NO_ELECTRICITY = ElectricityCost(0.0, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0)
# Less than this (kWh) is rounding noise of sums and differences, not energy
# that would need a price.
NOISE_KWH = 1e-6


def _price(value: float | None) -> float | None:
    """A usable price or None (NaN and infinity count as no price)."""
    return value if value is not None and math.isfinite(value) else None


def electricity_cost(
    hours: Mapping[datetime, Totals],
    *,
    price: Price,
    hourly_prices: Mapping[datetime, float] | None = None,
) -> ElectricityCost:
    """Cost of the electricity in `hours` (UTC hour start → booked energy).

    With `hourly_prices` (€/kWh per UTC hour start) each hour is priced on
    its own; an hour without one falls back to the fixed `price`, or without
    that counts as missing. Without `hourly_prices`, `price` applies to all.
    A dated `price` (dated.Dated) gives each hour the price of its time.
    """
    fallback = missing = hourly_count = 0
    cost = heat_cost = 0.0
    total = heat_total = missing_kwh = heat_missing = 0.0
    for hour, totals in hours.items():
        heat_side = totals.electricity(*SEASONAL_MODES) + totals.standby()
        kwh = heat_side + totals.electricity(Mode.COOLING)
        total += kwh
        heat_total += heat_side
        hourly = None if hourly_prices is None else _price(hourly_prices.get(hour))
        rate = hourly if hourly is not None else _price(value_at(price, hour))
        if abs(kwh) < NOISE_KWH:
            continue
        if rate is None:
            missing += 1
            missing_kwh += kwh
            heat_missing += heat_side
            continue
        if hourly is not None:
            hourly_count += 1
        elif hourly_prices is not None:
            fallback += 1
        cost += kwh * rate
        heat_cost += heat_side * rate
    return ElectricityCost(
        electricity_kwh=total,
        heat_electricity_kwh=heat_total,
        cost_eur=None if missing_kwh else cost,
        heat_cost_eur=None if heat_missing else heat_cost,
        fallback_hours=fallback,
        missing_hours=missing,
        missing_kwh=missing_kwh,
        heat_missing_kwh=heat_missing,
        hourly_hours=hourly_count,
    )


def gas_for_heat(heat_kwh: float, efficiency: float = BOILER_EFFICIENCY_HS) -> float:
    """Gas (kWh, Hs) a boiler with the efficiency on Hs needs for the heat."""
    if not 0 < efficiency <= 1:
        raise ValueError("boiler efficiency on Hs must be in (0, 1]")
    return heat_kwh / efficiency


def base_price_share(
    annual: float, start: datetime, end: datetime, tz: tzinfo
) -> float:
    """Share of an annual base price for [start, end).

    Each local day carries annual ÷ 365 (366 in leap years); a partial day
    its share of the day's real hours (23 or 25 at DST changes).
    """
    if end <= start:
        return 0.0
    share = 0.0
    day = start.astimezone(tz).date()
    while (day_start := local_midnight(day, tz)) < end:
        next_day = day + timedelta(days=1)
        day_end = local_midnight(next_day, tz)
        overlap = min(end, day_end) - max(start, day_start)
        if overlap > timedelta(0):
            share += overlap / (day_end - day_start) / _days_in_year(day)
        day = next_day
    return annual * share


def dated_base_share(
    annual: Price, start: datetime, end: datetime, tz: tzinfo
) -> float:
    """base_price_share of a plain or dated annual price: each segment with
    the annual price valid in it (none: nothing)."""
    if not isinstance(annual, Dated):
        value = _price(annual)
        return 0.0 if value is None else base_price_share(value, start, end, tz)
    return sum(
        (
            base_price_share(value, lower, upper, tz)
            for lower, upper, value in annual.segments(start, end)
            if _price(value) is not None
        ),
        0.0,
    )


def _days_in_year(day: date) -> int:
    return (date(day.year + 1, 1, 1) - date(day.year, 1, 1)).days


def heat_cost_per_kwh(
    cost_eur: float | None, heat_kwh: float, min_heat: float = MIN_HEAT_KWH
) -> float | None:
    """Cost per kWh of heat; None without cost or below the minimum heat."""
    if cost_eur is None or heat_kwh <= 0 or heat_kwh < min_heat:
        return None
    return cost_eur / heat_kwh


def compare_with_gas(
    hours: Mapping[datetime, Totals],
    start: datetime,
    end: datetime,
    tz: tzinfo,
    *,
    electricity_price: Price,
    gas_price: float | None,
    hourly_prices: Mapping[datetime, float] | None = None,
    gas_base_price_per_year: Price = None,
    electricity_base_price_per_year: Price = None,
    boiler_efficiency: float = BOILER_EFFICIENCY_HS,
    factors: EmissionFactors = WITH_UPSTREAM,
    data_from: datetime | None = None,
) -> CostComparison:
    """Costs and CO₂ of the heat pump and of a gas boiler in [start, end).

    Only hours of `hours` starting in [start, end) count. `electricity_price`
    and `gas_price` are €/kWh (gas on Hs); `gas_base_price_per_year` is € per
    year and is prorated to the period, as is `electricity_base_price_per_year`
    (only for a separate heat pump meter).
    """
    period = {h: t for h, t in hours.items() if start <= h < end}
    electricity = electricity_cost(
        period, price=electricity_price, hourly_prices=hourly_prices
    )
    heat = sum(t.heat(*SEASONAL_MODES) for t in period.values())
    return compare_costs(
        electricity,
        heat,
        start,
        end,
        tz,
        gas_price=gas_price,
        gas_base_price_per_year=gas_base_price_per_year,
        electricity_base_price_per_year=electricity_base_price_per_year,
        boiler_efficiency=boiler_efficiency,
        factors=factors,
        data_from=data_from,
    )


def compare_costs(
    electricity: ElectricityCost,
    heat: float,
    start: datetime,
    end: datetime,
    tz: tzinfo,
    *,
    gas_price: float | None,
    gas_base_price_per_year: Price = None,
    electricity_base_price_per_year: Price = None,
    boiler_efficiency: float = BOILER_EFFICIENCY_HS,
    factors: EmissionFactors = WITH_UPSTREAM,
    data_from: datetime | None = None,
) -> CostComparison:
    """As compare_with_gas, from the electricity cost of [start, end) and the
    heat of heating and hot water in it (priced elsewhere, prices.py).

    `data_from`: the first hour with data; the base prices count from there
    (None: from `start`)."""
    gas = gas_for_heat(heat, boiler_efficiency)
    base_start = start if data_from is None else max(start, data_from)

    gas_price = _price(gas_price)
    gas_energy_cost = None if gas_price is None else gas * gas_price
    gas_base_cost = dated_base_share(gas_base_price_per_year, base_start, end, tz)
    gas_cost = None if gas_energy_cost is None else gas_energy_cost + gas_base_cost
    electricity_base_cost = dated_base_share(
        electricity_base_price_per_year, base_start, end, tz
    )
    heat_pump_cost = (
        None
        if electricity.heat_cost_eur is None
        else electricity.heat_cost_eur + electricity_base_cost
    )

    heat_pump_co2 = electricity.heat_electricity_kwh * factors.electricity / 1000
    gas_co2 = gas * factors.gas_hs / 1000
    return CostComparison(
        heat_kwh=heat,
        electricity=electricity,
        heat_pump_cost_eur=heat_pump_cost,
        electricity_base_cost_eur=electricity_base_cost,
        heat_cost_per_kwh=heat_cost_per_kwh(heat_pump_cost, heat),
        boiler_efficiency=boiler_efficiency,
        gas_kwh=gas,
        gas_energy_cost_eur=gas_energy_cost,
        gas_base_cost_eur=gas_base_cost,
        gas_cost_eur=gas_cost,
        gas_cost_per_kwh=heat_cost_per_kwh(gas_cost, heat),
        factors=factors,
        heat_pump_co2_kg=heat_pump_co2,
        gas_co2_kg=gas_co2,
        savings_eur=(
            None
            if gas_cost is None or heat_pump_cost is None
            else gas_cost - heat_pump_cost
        ),
        savings_co2_kg=gas_co2 - heat_pump_co2,
    )
