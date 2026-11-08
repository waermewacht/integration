"""Heat pump electricity from the grid or from own PV and battery, per hour.

Only the costs change, never a performance factor. Rules (README "Kosten"):

- proportional (grid import, feed-in and PV meters set; battery optional):
  house consumption = grid import + PV - feed-in + battery discharge -
  battery charge (solar.SolarSettings.consumption); the heat pump takes
  from the grid the share the house took: grid share = heat pump
  electricity x grid import / house consumption (0..1).
- heat pump first (only the grid import meter, or no PV/feed-in meter):
  the grid import of the hour goes to the heat pump first: grid share =
  min(heat pump electricity, grid import).
- cost = grid share x grid price + (heat pump electricity - grid share) x
  feed-in tariff (what the own electricity would have earned).
- Per mode (heating, hot water, cooling; standby apart): the grid share of
  the hour applies to each, so hot water at noon on PV and heating at night
  from the grid get their own shares (`by_mode`).
- An hour without statistics of a meter it needs counts as all from the
  grid (`hours_all_grid`). § 51 EEG (no feed-in payment at negative prices)
  is left out: the price sensor need not give exchange prices.

Within an hour, PV, house and heat pump are netted (hourly statistics).
Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from .costs import NOISE_KWH
from .energy import SEASONAL_MODES, Totals
from .model import Mode
from .solar import HourFlows, SolarSettings

# Keys of Allocation.by_mode: the modes and standby.
STANDBY = "standby"
PARTS = (Mode.HEATING.value, Mode.DHW.value, Mode.COOLING.value, STANDBY)

PROPORTIONAL = "proportional"
HEAT_PUMP_FIRST = "heat_pump_first"
NONE = "none"


@dataclass(frozen=True)
class SplitSettings:
    """How heat pump electricity is split between grid and own electricity."""

    rule: str  # PROPORTIONAL or HEAT_PUMP_FIRST
    feed_in_rate: float  # EUR/kWh, what own electricity would have earned
    solar: SolarSettings


def rule_for(*, pv: bool, feed_in: bool) -> str:
    """Proportional when the house consumption can be computed."""
    return PROPORTIONAL if pv and feed_in else HEAT_PUMP_FIRST


@dataclass(frozen=True)
class Allocation:
    """Heat pump electricity of a period split into grid and own (kWh), and
    what the own electricity saved against the grid price (EUR)."""

    kwh_grid: float = 0.0
    kwh_own: float = 0.0
    hours_all_grid: int = 0  # hours without the meters' statistics
    saving_eur: float = 0.0  # own kWh x (grid price - feed-in tariff)
    heat_saving_eur: float = 0.0  # its share of heating, hot water, standby
    # Per PARTS key: (kWh from the grid, kWh own); keys with electricity only.
    by_mode: dict[str, tuple[float, float]] = field(default_factory=dict)

    def __add__(self, other: Allocation) -> Allocation:
        by_mode = dict(self.by_mode)
        for key, (grid, own) in other.by_mode.items():
            before = by_mode.get(key, (0.0, 0.0))
            by_mode[key] = (before[0] + grid, before[1] + own)
        return Allocation(
            self.kwh_grid + other.kwh_grid,
            self.kwh_own + other.kwh_own,
            self.hours_all_grid + other.hours_all_grid,
            self.saving_eur + other.saving_eur,
            self.heat_saving_eur + other.heat_saving_eur,
            by_mode,
        )

    @property
    def grid_share(self) -> float | None:
        total = self.kwh_grid + self.kwh_own
        return self.kwh_grid / total if total > 0 else None


def mode_kwh(totals: Totals) -> dict[str, float]:
    """Heat pump electricity of `totals` per PARTS key (those above 0)."""
    values = {m.value: totals.electricity(m) for m in Mode}
    values[STANDBY] = totals.standby()
    return {key: values[key] for key in PARTS if values[key] > 0}


def split_by_mode(totals: Totals, own_share: float) -> dict[str, tuple[float, float]]:
    """(grid, own) per PARTS key with one own share for all (0..1)."""
    return {
        key: (kwh * (1 - own_share), kwh * own_share)
        for key, kwh in mode_kwh(totals).items()
    }


def grid_kwh(
    heat_pump: float, flows: HourFlows, rule: str, solar: SolarSettings
) -> float:
    """Heat pump electricity of the hour taken from the grid (0..heat_pump)."""
    if heat_pump <= 0:
        return 0.0
    if rule == PROPORTIONAL:
        house = solar.consumption(flows)
        if house > 0:
            share = min(1.0, max(0.0, flows.purchase / house))
            return heat_pump * share
    return min(heat_pump, max(0.0, flows.purchase))


def _rate(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None


def allocate(
    hours: Mapping[datetime, Totals],
    flows: Mapping[datetime, HourFlows],
    prices: Mapping[datetime, float],
    fixed: float | None,
    split: SplitSettings,
) -> Allocation:
    """Split the heat pump electricity of `hours` (UTC hour starts).

    `flows` holds the hours with every meter the rule needs; the others are
    all grid. The grid price of an hour is its price in `prices`, else
    `fixed`; without either there is no saving (the cost is unknown anyway).
    """
    result = Allocation()
    for hour, totals in hours.items():
        heat_side = totals.electricity(*SEASONAL_MODES) + totals.standby()
        heat_pump = heat_side + totals.electricity(Mode.COOLING)
        if heat_pump < NOISE_KWH:
            continue
        found = flows.get(hour)
        if found is None:
            result = result + Allocation(
                kwh_grid=heat_pump,
                hours_all_grid=1,
                by_mode=split_by_mode(totals, 0.0),
            )
            continue
        grid = grid_kwh(heat_pump, found, split.rule, split.solar)
        own = heat_pump - grid
        rate = _rate(prices.get(hour))
        if rate is None:
            rate = _rate(fixed)
        saving = 0.0 if rate is None else own * (rate - split.feed_in_rate)
        result = result + Allocation(
            kwh_grid=grid,
            kwh_own=own,
            saving_eur=saving,
            heat_saving_eur=saving * max(0.0, heat_side) / heat_pump,
            by_mode=split_by_mode(totals, own / heat_pump),
        )
    return result
