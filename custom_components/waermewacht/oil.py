"""Oil boiler in the gas mode. Pure Python, no HA imports.

An oil boiler is a gas boiler entry (gas.py, readings.py) with another fuel
(docs/ENTWICKLUNG.md, "Gas-Modus", Ölheizung):

- Oil in kWh on the gross calorific value Hs, as gas, so that the boiler
  efficiencies on Hs stay comparable. A litre of heating oil EL is
  KWH_PER_LITRE_HS by default (Hi 10 kWh/l after HeizkostenV § 9, divided by
  the ratio Hi/Hs 0.938 of the BAFA infosheet), adjustable in the options.
- Efficiency on Hs chosen by boiler type (BOILER_TYPES), or an own value.
- Price in € per 100 l as quoted by dealers, converted to €/kWh Hs.
- Readings by hand: an oil meter counts up like a gas meter (readings.py
  as is). A tank level counts down and jumps at a refill; `consumed` turns
  levels and refills into a counter of the oil used.
"""

from __future__ import annotations

import bisect
import itertools
from collections.abc import Sequence

from .readings import NEGATIVE, Reading

# kWh (Hs) per litre of heating oil EL: 10 kWh/l (Hi) / 0.938.
KWH_PER_LITRE_HI = 10.0
HI_PER_HS = 0.938
KWH_PER_LITRE_HS = round(KWH_PER_LITRE_HI / HI_PER_HS, 2)  # 10.66

# Boiler type -> efficiency on Hs (own conversion of the generator
# expenditure factors after DIN V 4701-10, IWU 2005; docs/ENTWICKLUNG.md).
CONDENSING = "condensing"
LOW_TEMPERATURE = "low_temperature"
CONSTANT_TEMPERATURE = "constant_temperature"
CUSTOM = "custom"  # own value in the option boiler_efficiency
BOILER_TYPES: dict[str, float] = {
    CONDENSING: 0.87,
    LOW_TEMPERATURE: 0.79,
    CONSTANT_TEMPERATURE: 0.70,
}

# Errors when adding a tank level or removing a refill (translation keys).
TANK_RISING = "tank_rising"
REFILL_NOT_POSITIVE = "refill_not_positive"


def price_per_kwh(
    eur_per_100_litres: float | None, kwh_per_litre: float
) -> float | None:
    """€/kWh (Hs) from a price in € per 100 l."""
    if eur_per_100_litres is None:
        return None
    if kwh_per_litre <= 0:
        raise ValueError("kWh per litre must be positive")
    return eur_per_100_litres / 100 / kwh_per_litre


def efficiency(boiler_type: str | None, own: float | None) -> float | None:
    """Efficiency on Hs of the boiler type, or the own value for CUSTOM;
    None when the own value is missing."""
    if boiler_type == CUSTOM or boiler_type is None:
        return own
    return BOILER_TYPES.get(boiler_type, own)


def consumed(levels: Sequence[Reading], refills: Sequence[Reading]) -> list[Reading]:
    """A counter of the oil used (litres), at the times of the tank levels.

    It starts at 0 with the first level. Between two levels it grows by the
    drop of the level plus every refill in between: a refill at the very
    minute of a level counts before that level (the level is read after
    filling up). Refills before the first level do not count.
    """
    times = [r.at for r in refills]
    result: list[Reading] = []
    total = 0.0
    for i, level in enumerate(levels):
        if i:
            before = levels[i - 1]
            lo = bisect.bisect_right(times, before.at)
            hi = bisect.bisect_right(times, level.at)
            added = sum(r.value for r in refills[lo:hi])
            total += before.value - level.value + added
        result.append(Reading(level.at, total))
    return result


def check_tank(levels: Sequence[Reading], refills: Sequence[Reading]) -> str | None:
    """Error key if the levels rise anywhere more than the refills explain."""
    if any(r.value < 0 for r in levels):
        return NEGATIVE
    if any(r.value <= 0 for r in refills):
        return REFILL_NOT_POSITIVE
    used = consumed(levels, refills)
    # Tolerance for float sums: 1000.3 - 1500.1 + 499.8 is not exactly 0.
    if any(b.value < a.value - 1e-6 for a, b in itertools.pairwise(used)):
        return TANK_RISING
    return None
