"""Energy per mode and the ratios built from it. Pure Python, no HA imports.

Electricity of a mode is booked as running (compressor ran during the
interval) or standby (it stood still). Following Fraunhofer ISE, the ratios
per mode leave standby out; the seasonal ratio of heating and hot water
includes it. Cooling never enters the seasonal ratio.
"""

from __future__ import annotations

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


def aux_share(totals: Totals, min_electricity: float) -> float | None:
    """Backup heater share of the electricity for heating and hot water, in %."""
    electricity = totals.electricity(*SEASONAL_MODES) + totals.standby()
    if electricity <= 0 or electricity < min_electricity:
        return None
    aux = sum(totals.get(Kind.AUX, m) for m in SEASONAL_MODES)
    return 100 * aux / electricity
