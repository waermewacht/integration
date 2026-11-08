"""Hourly energy flows of the house: grid, PV, battery.

Kopie von tarifwacht/custom_components/tarifwacht/solar.py (Stand 8e9669a),
hier nicht ändern - Änderungen dort und hierher ziehen. Copied: HourFlows,
SolarSettings (consumption, pv_alone), detect_same_inverter and their
constants; the rest of Tarifwacht's module (tariffs, savings) is not used
here. How Wärmewacht shares these flows with the heat pump is its own code
(allocation.py).

The household consumption is derived from the meters:
- battery behind the PV inverter (hybrid inverter, DC coupled, e.g. Fronius
  Gen24, Huawei, Kostal): the PV meter is the inverter's AC output, battery
  energy included. Consumption = purchase - feed-in + inverter output; PV
  without battery = inverter output + (charged - discharged) x efficiency.
- battery with its own inverter (AC coupled): consumption = purchase -
  feed-in + PV - charged + discharged; PV without battery = PV.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

# Inverter efficiency for battery energy behind a hybrid inverter (DC to AC).
# Own assumption; 0.90 to 0.97 moves a year by a few euros only.
DEFAULT_EFFICIENCY = 0.95

# Coupling detection: hours with this much discharge and no charge.
DETECT_MIN_DISCHARGE = 0.2  # kWh
DETECT_MIN_HOURS = 10


@dataclass(frozen=True)
class HourFlows:
    """Metered energy of one UTC hour in kWh (all >= 0)."""

    purchase: float = 0.0
    feed_in: float = 0.0
    pv: float = 0.0
    charged: float = 0.0
    discharged: float = 0.0


@dataclass(frozen=True)
class SolarSettings:
    """How the meters are to be read and what feed-in earns."""

    # True: the PV meter is the output of a hybrid inverter with the battery.
    same_inverter: bool
    feed_in_rate: float  # EUR/kWh
    negative_unpaid: bool = False
    efficiency: float = DEFAULT_EFFICIENCY

    def consumption(self, hour: HourFlows) -> float:
        """Household consumption of the hour (never below 0)."""
        value = hour.purchase - hour.feed_in + hour.pv
        if not self.same_inverter:
            value += hour.discharged - hour.charged
        return max(0.0, value)

    def pv_alone(self, hour: HourFlows) -> float:
        """PV energy on the AC side as if there were no battery."""
        if not self.same_inverter:
            return max(0.0, hour.pv)
        return max(0.0, hour.pv + (hour.charged - hour.discharged) * self.efficiency)


def detect_same_inverter(hours: Mapping[datetime, HourFlows]) -> bool | None:
    """Whether the battery sits behind the PV inverter, from the data.

    In hours of discharging without charging (mostly nights), a hybrid
    inverter puts the battery energy out on its AC meter (about the discharge
    times its efficiency); a separate PV inverter shows nothing at night.
    None with too few such hours or no clear answer.
    """
    ratios = [
        h.pv / h.discharged
        for h in hours.values()
        if h.discharged >= DETECT_MIN_DISCHARGE and h.charged < 0.01
    ]
    if len(ratios) < DETECT_MIN_HOURS:
        return None
    low = statistics.quantiles(ratios, n=4)[0]
    if low >= 0.5:
        return True
    if low <= 0.1:
        return False
    return None
