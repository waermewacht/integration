"""Energy per mode and the ratios built from it. Pure Python, no HA imports.

Electricity of a mode is booked as running (compressor ran during the
interval) or standby (it stood still). Following Fraunhofer ISE, the ratios
per mode leave standby out; the seasonal ratio of heating and hot water
includes it. Cooling never enters the seasonal ratio.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .model import Mode


class Kind(StrEnum):
    """What an amount of energy is."""

    HEAT = "heat"  # heat delivered (for cooling: heat removed)
    ELEC = "elec"  # compressor electricity while running
    STANDBY = "standby"  # electricity booked while the compressor stood still
    AUX = "aux"  # electric backup heater
    BOILER = "boiler"  # heat the boiler of a hybrid system reports
    FUEL = "fuel"  # fuel of that boiler (not heat pump energy)


SEASONAL_MODES = (Mode.HEATING, Mode.DHW)


@dataclass
class Totals:
    """Energy in kWh per kind and mode; may be negative (period marks)."""

    values: dict[str, float] = field(default_factory=dict)

    @staticmethod
    def key(kind: Kind, mode: Mode) -> str:
        return f"{kind.value}_{mode.value}"

    def get(self, kind: Kind, mode: Mode) -> float:
        return self.values.get(self.key(kind, mode), 0.0)

    def add(self, kind: Kind, mode: Mode, kwh: float) -> None:
        key = self.key(kind, mode)
        self.values[key] = self.values.get(key, 0.0) + kwh

    def __add__(self, other: Totals) -> Totals:
        keys = self.values.keys() | other.values.keys()
        return Totals(
            {k: self.values.get(k, 0.0) + other.values.get(k, 0.0) for k in keys}
        )

    def __sub__(self, other: Totals) -> Totals:
        keys = self.values.keys() | other.values.keys()
        return Totals(
            {k: self.values.get(k, 0.0) - other.values.get(k, 0.0) for k in keys}
        )

    def __neg__(self) -> Totals:
        return Totals({k: -v for k, v in self.values.items()})

    def copy(self) -> Totals:
        return Totals(dict(self.values))

    def as_dict(self) -> dict[str, float]:
        return dict(self.values)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Totals:
        return cls({k: float(v) for k, v in (data or {}).items()})

    # Sums used by the ratios.

    def heat(self, *modes: Mode) -> float:
        return sum(self.get(Kind.HEAT, m) for m in modes)

    def electricity(self, *modes: Mode) -> float:
        """Running electricity plus backup heater of the modes."""
        return sum(self.get(Kind.ELEC, m) + self.get(Kind.AUX, m) for m in modes)

    def standby(self) -> float:
        return sum(self.get(Kind.STANDBY, m) for m in Mode)

    def boiler_heat(
        self, efficiency: float, fuel_modes: Collection[Mode], *modes: Mode
    ) -> float:
        """Heat of the boiler of a hybrid system: what it reports, or for the
        `fuel_modes` (no heat counter) its fuel times the efficiency."""
        return sum(
            efficiency * self.get(Kind.FUEL, m)
            if m in fuel_modes
            else self.get(Kind.BOILER, m)
            for m in modes
        )


# Heat of the building below this (kWh) gives no share of the heat pump: a
# few counter steps would swing it (own assumption, about one hour of
# heating in mild weather).
MIN_SHARE_HEAT_KWH = 1.0


def building_totals(
    totals: Totals, efficiency: float, fuel_modes: Collection[Mode]
) -> Totals:
    """`totals` with the boiler's heat added to the heat of each mode.

    For the building's figures only (heat load, energy signature, degree
    days, flow curve): ratios must never see the boiler's heat.
    """
    result = totals.copy()
    for mode in Mode:
        if boiler := totals.boiler_heat(efficiency, fuel_modes, mode):
            result.add(Kind.HEAT, mode, boiler)
    return result


def building_hours[K](
    hours: Mapping[K, Totals], efficiency: float, fuel_modes: Collection[Mode]
) -> dict[K, Totals]:
    """building_totals of every hour."""
    return {h: building_totals(t, efficiency, fuel_modes) for h, t in hours.items()}


def replace_boiler[K](
    hours: Mapping[K, Totals], boiler: Mapping[K, Totals]
) -> dict[K, Totals]:
    """`hours` with their boiler heat and fuel taken from `boiler` (hourly
    changes of the boiler's own counters): complete also for the time before
    a boiler was mapped, which the own sensors cannot know."""
    result: dict[K, Totals] = {}
    for hour in hours.keys() | boiler.keys():
        totals = hours[hour].copy() if hour in hours else Totals()
        for kind in (Kind.BOILER, Kind.FUEL):
            for mode in Mode:
                totals.values.pop(Totals.key(kind, mode), None)
        if hour in boiler:
            totals = totals + boiler[hour]
        result[hour] = totals
    return result


def heat_pump_share(
    totals: Totals, efficiency: float, fuel_modes: Collection[Mode], *modes: Mode
) -> float | None:
    """Heat pump heat in % of the heat of heat pump and boiler (heat basis,
    as field studies of hybrid systems report it); None below
    MIN_SHARE_HEAT_KWH or with a negative balance."""
    pump = totals.heat(*modes)
    boiler = totals.boiler_heat(efficiency, fuel_modes, *modes)
    whole = pump + boiler
    if whole < MIN_SHARE_HEAT_KWH or pump < 0 or boiler < 0:
        return None
    return 100 * pump / whole


def ratio(heat: float, electricity: float, min_electricity: float) -> float | None:
    """Heat over electricity; None without heat or below the minimum electricity.

    A day without a compressor run is unknown, never 0 (0 would drag averages
    and statistics down).
    """
    if heat <= 0 or electricity <= 0 or electricity < min_electricity:
        return None
    return heat / electricity


def mode_ratio(totals: Totals, mode: Mode, min_electricity: float) -> float | None:
    """Ratio of one mode without standby (cooling: energy efficiency ratio)."""
    return ratio(totals.heat(mode), totals.electricity(mode), min_electricity)


def combined_ratio(
    totals: Totals, min_electricity: float, *, with_standby: bool = True
) -> float | None:
    """Heating plus hot water; with standby this is the seasonal ratio (JAZ)."""
    electricity = totals.electricity(*SEASONAL_MODES)
    if with_standby:
        electricity += totals.standby()
    return ratio(totals.heat(*SEASONAL_MODES), electricity, min_electricity)


def aux_share(
    totals: Totals, min_electricity: float, mode: Mode | None = None
) -> float | None:
    """Backup heater share of the electricity for heating and hot water, in %.

    With `mode`, the share within that mode (its electricity and standby).
    """
    if mode is None:
        modes: tuple[Mode, ...] = SEASONAL_MODES
        electricity = totals.electricity(*modes) + totals.standby()
    else:
        modes = (mode,)
        electricity = totals.electricity(mode) + totals.get(Kind.STANDBY, mode)
    if electricity <= 0 or electricity < min_electricity:
        return None
    aux = sum(totals.get(Kind.AUX, m) for m in modes)
    return 100 * aux / electricity
