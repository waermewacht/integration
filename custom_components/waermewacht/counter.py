"""Turn readings of an energy counter into increments.

Pure Python, no Home Assistant imports. Same idea as the meter trackers of
Einspeisewacht and Tarifwacht, without splitting into quarter hours.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo
from enum import StrEnum
from typing import Any

# Factor to kWh for the units an energy sensor may report.
UNIT_FACTORS = {"Wh": 0.001, "kWh": 1.0, "MWh": 1000.0}

# Lifetime counters step back without a reset: noise (observed −0.02 kWh) and,
# on heat counters, defrosts, which subtract the heat taken from the house
# (observed −0.31 kWh in steps during one defrost). The old maximum stays the
# baseline, so only heat above it is booked: that is the net heat, and the
# recovery after the dip is not booked twice. A reset is a drop by more than
# 10 % (like Home Assistant's own rule) and more than 1 kWh.
RESET_FRACTION = 0.1
RESET_MIN_KWH = 1.0

# Increases above max_kw × hours × margin + tolerance are glitches. The
# tolerance covers counters in whole kWh, which step by 1 kWh at once.
POWER_MARGIN = 1.5
JUMP_TOLERANCE_KWH = 1.0


class CounterEvent(StrEnum):
    """What a reading did besides delivering energy."""

    FIRST = "first"  # no previous reading: baseline only
    DIP = "dip"  # step back (noise, defrost): baseline held, nothing booked
    RESET = "reset"  # counter started anew: new baseline
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

    `day_tz` marks a day counter (cloud day values, e.g. Bosch HomeCom): it
    starts anew when the local date in `day_tz` changes. The first value of a
    new day is energy of that day, even when it is higher than the last
    value of the day before (long pause). Within a day it behaves like a
    lifetime counter: a step back is a dip (observed at the change from
    summer time, when the doubled hour is overwritten), never a new day.
    """

    max_kw: float | None = None
    day_tz: tzinfo | None = None
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
        if self.day_tz is not None:
            if value == previous_value:
                # Attribute updates: the time of the last change dates the value.
                return CounterUpdate()
            if self._new_day(previous_time, at):
                return self._start_day(value, at)
        delta = value - previous_value
        if delta < 0:
            if self.day_tz is not None or -delta <= max(
                RESET_MIN_KWH, RESET_FRACTION * previous_value
            ):
                self.last_time = at
                return CounterUpdate(event=CounterEvent.DIP)
            self.last_value, self.last_time = value, at
            return CounterUpdate(event=CounterEvent.RESET)
        self.last_value, self.last_time = value, at
        if self.max_kw is not None:
            hours = (at - previous_time).total_seconds() / 3600
            if delta > self.max_kw * POWER_MARGIN * hours + JUMP_TOLERANCE_KWH:
                return CounterUpdate(event=CounterEvent.JUMP)
        return CounterUpdate(delta=delta)

    def _new_day(self, previous: datetime, at: datetime) -> bool:
        return (
            previous.astimezone(self.day_tz).date() != at.astimezone(self.day_tz).date()
        )

    def _start_day(self, value: float, at: datetime) -> CounterUpdate:
        self.last_value, self.last_time = value, at
        if self.max_kw is not None:
            local = at.astimezone(self.day_tz)
            midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
            hours = (local - midnight).total_seconds() / 3600
            if value > self.max_kw * POWER_MARGIN * hours + JUMP_TOLERANCE_KWH:
                return CounterUpdate(event=CounterEvent.JUMP)
        return CounterUpdate(delta=max(value, 0.0), event=CounterEvent.RESET)

    def as_dict(self) -> dict[str, Any]:
        return {
            "last_value": self.last_value,
            "last_time": self.last_time.isoformat() if self.last_time else None,
        }

    def restore(self, data: dict[str, Any]) -> None:
        self.last_value = data.get("last_value")
        last_time = data.get("last_time")
        self.last_time = datetime.fromisoformat(last_time) if last_time else None
