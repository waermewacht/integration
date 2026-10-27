"""Turn readings of an energy counter into increments.

Pure Python, no Home Assistant imports. Same idea as the meter trackers of
Einspeisewacht and Tarifwacht, without splitting into quarter hours.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

# Factor to kWh for the units an energy sensor may report.
UNIT_FACTORS = {"Wh": 0.001, "kWh": 1.0, "MWh": 1000.0}

# Lifetime counters sometimes step back a little (observed: −0.02 kWh on an
# EMS-ESP heat counter). That is noise, not a reset: the old maximum stays the
# baseline, otherwise the same energy would be booked twice.
JITTER_KWH = 0.1

# Increases above max_kw × hours × margin + tolerance are glitches. The
# tolerance covers counters in whole kWh, which step by 1 kWh at once.
POWER_MARGIN = 1.5
JUMP_TOLERANCE_KWH = 1.0


class CounterEvent(StrEnum):
    """What a reading did besides delivering energy."""

    FIRST = "first"  # no previous reading: baseline only
    JITTER = "jitter"  # small step back: ignored
    RESET = "reset"  # counter went back to (near) zero
    JUMP = "jump"  # implausibly large increase: new baseline, nothing booked


def to_kwh(value: float, unit: str | None) -> float:
    """Convert a counter value to kWh; raises KeyError for unknown units."""
    return value * UNIT_FACTORS[unit or ""]


@dataclass
class CounterUpdate:
    """Result of one reading."""

    delta: float = 0.0
    event: CounterEvent | None = None


@dataclass
class Counter:
    """Track the last reading of a cumulative counter.

    `daily_reset` marks counters that restart at zero every day (cloud day
    values): after a reset, the new value itself is energy of the new day.
    """

    max_kw: float | None = None
    daily_reset: bool = False
    last_value: float | None = None
    last_time: datetime | None = None

    def update(self, value: float, at: datetime) -> CounterUpdate:
        """Process a reading in kWh taken at `at` (timezone-aware)."""
        previous_value, previous_time = self.last_value, self.last_time
        if previous_time is not None and at < previous_time:
            return CounterUpdate()  # out of order: keep the newer baseline
        if previous_value is None or previous_time is None:
            self.last_value, self.last_time = value, at
            return CounterUpdate(event=CounterEvent.FIRST)
        delta = value - previous_value
        if delta < 0:
            if self.daily_reset:
                self.last_value, self.last_time = value, at
                return CounterUpdate(delta=max(value, 0.0), event=CounterEvent.RESET)
            if -delta <= JITTER_KWH:
                self.last_time = at
                return CounterUpdate(event=CounterEvent.JITTER)
            self.last_value, self.last_time = value, at
            return CounterUpdate(event=CounterEvent.RESET)
        self.last_value, self.last_time = value, at
        if self.max_kw is not None:
            hours = (at - previous_time).total_seconds() / 3600
            if delta > self.max_kw * POWER_MARGIN * hours + JUMP_TOLERANCE_KWH:
                return CounterUpdate(event=CounterEvent.JUMP)
        return CounterUpdate(delta=delta)

    def as_dict(self) -> dict[str, Any]:
        return {
            "last_value": self.last_value,
            "last_time": self.last_time.isoformat() if self.last_time else None,
        }

    def restore(self, data: dict[str, Any]) -> None:
        self.last_value = data.get("last_value")
        last_time = data.get("last_time")
        self.last_time = datetime.fromisoformat(last_time) if last_time else None
