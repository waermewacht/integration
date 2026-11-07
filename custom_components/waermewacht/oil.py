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
  levels and refills into a counter of the oil used. A level up to
  TANK_TOLERANCE_LITRES above what the refills explain (gauge read badly,
  oil warmer) is netted against the next drop; more is refused.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from datetime import datetime

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

# Litres a tank level may lie above the counter so far without a refill.
# Gauges and dipsticks read tens of litres off, and in summer a week uses
# about as much; a delivery is far more (dealers deliver from about 500 l).
# Own choice (Andy 07.11.2026), no source: docs/ENTWICKLUNG.md, Ölheizung.
TANK_TOLERANCE_LITRES = 100.0
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

    The counter never falls: a level above what the refills explain keeps
    it where it is, and the next drop counts only beyond that (the rise is
    netted). Over several levels the oil used stays right.
    """
    return [Reading(at, peak) for at, _, peak in _running(levels, refills)]


def _running(
    levels: Sequence[Reading], refills: Sequence[Reading]
) -> list[tuple[datetime, float, float]]:
    """Per level its time, the plain sum (not netted) and the highest sum
    so far."""
    times = [r.at for r in refills]
    result: list[tuple[datetime, float, float]] = []
    total = peak = 0.0
    for i, level in enumerate(levels):
        if i:
            before = levels[i - 1]
            lo = bisect.bisect_right(times, before.at)
            hi = bisect.bisect_right(times, level.at)
            added = sum(r.value for r in refills[lo:hi])
            total += before.value - level.value + added
        peak = max(peak, total)
        result.append((level.at, total, peak))
    return result


def check_tank(levels: Sequence[Reading], refills: Sequence[Reading]) -> str | None:
    """Error key if a level lies more than TANK_TOLERANCE_LITRES above what
    the levels before and the refills explain."""
    if any(r.value < 0 for r in levels):
        return NEGATIVE
    if any(r.value <= 0 for r in refills):
        return REFILL_NOT_POSITIVE
    # 1e-6 for float sums: 1000.3 - 1500.1 + 499.8 is not exactly 0.
    limit = TANK_TOLERANCE_LITRES + 1e-6
    if any(peak - total > limit for _, total, peak in _running(levels, refills)):
        return TANK_RISING
    return None
