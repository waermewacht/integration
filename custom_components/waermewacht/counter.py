"""Turn readings of an energy counter into increments.

Pure Python, no Home Assistant imports. Same idea as the meter trackers of
Einspeisewacht and Tarifwacht, without splitting into quarter hours.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, tzinfo
from enum import StrEnum
from itertools import pairwise
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

# A day counter (energy "today") taken for a lifetime counter: it falls by half
# or more at the same local hour on different days (own assumption; the rule of
# Speicherwacht without the hour). A lifetime counter falls when it is replaced
# or its device restarts at 0, at any hour; its dips are small. One hour either
# way covers the days of the clock change.
DAY_COUNTER_MIN_KWH = 0.1
DAY_COUNTER_HOUR_SLACK = 1

# The other way round, a lifetime counter taken for a day counter (template
# with day values): it rises on several days and never falls to below half.
# A day counter falls at every day change after a day with energy. Values of
# the previous day (MELCloud) change about once a day, also upwards; for them
# a day counts only with several rising hours (own assumptions).
LIFETIME_MIN_DAYS = 2
LIFETIME_RISING_HOURS_PREVIOUS_DAY = 3


class CounterEvent(StrEnum):
    """What a reading did besides delivering energy."""

    FIRST = "first"  # no previous reading: baseline only
    DIP = "dip"  # step back (noise, defrost): baseline held, nothing booked
    RESET = "reset"  # counter started anew: new baseline
    JUMP = "jump"  # implausibly large increase: new baseline, nothing booked


def looks_like_day_counter(rows: list[tuple[datetime, float]], tz: tzinfo) -> bool:
    """True if hourly counter values (hour start, value at its end) restart
    like a day counter: two falls to below half at the same local hour
    (± 1 h) on different local days.

    Without `day_tz` such a counter books nothing after its first day once a
    day stays below 1 kWh (the step back is a dip) and loses the first hour
    of every other day (the step back is a reset).
    """
    falls = [
        after_at.astimezone(tz)
        for (_, before), (after_at, after) in pairwise(rows)
        if before >= DAY_COUNTER_MIN_KWH and after < before * 0.5
    ]
    for i, first in enumerate(falls):
        for second in falls[i + 1 :]:
            apart = abs(first.hour - second.hour)
            if (
                first.date() != second.date()
                and min(apart, 24 - apart) <= DAY_COUNTER_HOUR_SLACK
            ):
                return True
    return False


def looks_like_lifetime_counter(
    rows: list[tuple[datetime, float]], tz: tzinfo, *, previous_day: bool = False
) -> bool:
    """True if hourly counter values (hour start, value at its end) never
    restart and rise on at least two local days (at least 0.1 kWh a day).

    With `day_tz` such a counter is booked from its whole value at a day
    change, or never once that value is implausible for one day.
    """
    rising_hours: dict[date, int] = {}
    rise: dict[date, float] = {}
    for (_, before), (at, after) in pairwise(rows):
        if before >= DAY_COUNTER_MIN_KWH and after < before * 0.5:
            return False
        if after > before:
            day = at.astimezone(tz).date()
            rising_hours[day] = rising_hours.get(day, 0) + 1
            rise[day] = rise.get(day, 0.0) + after - before
    needed = LIFETIME_RISING_HOURS_PREVIOUS_DAY if previous_day else 1
    days = [
        day
        for day, hours in rising_hours.items()
        if hours >= needed and rise[day] >= DAY_COUNTER_MIN_KWH
    ]
    return len(days) >= LIFETIME_MIN_DAYS


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
    A day value is plausible up to `max_kw` since local midnight; the gap
    between two values says nothing, as a fetch may bring several hours at
    once. An implausible value is not booked and leaves the baseline alone.
    """

    max_kw: float | None = None
    day_tz: tzinfo | None = None
    # Day values of the previous day (MELCloud): a whole day of energy may
    # arrive just after midnight.
    previous_day: bool = False
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
            return self._update_day(value, at, previous_value, previous_time)
        delta = value - previous_value
        if delta < 0:
            if -delta <= max(RESET_MIN_KWH, RESET_FRACTION * previous_value):
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

    def _update_day(
        self, value: float, at: datetime, previous_value: float, previous: datetime
    ) -> CounterUpdate:
        if value == previous_value:
            # Attribute updates: the time of the last change dates the value.
            return CounterUpdate()
        if not self._plausible_day_value(value, at):
            return CounterUpdate(event=CounterEvent.JUMP)
        if self._new_day(previous, at):
            self.last_value, self.last_time = value, at
            return CounterUpdate(delta=max(value, 0.0), event=CounterEvent.RESET)
        delta = value - previous_value
        self.last_time = at
        if delta < 0:
            return CounterUpdate(event=CounterEvent.DIP)
        self.last_value = value
        return CounterUpdate(delta=delta)

    def _new_day(self, previous: datetime, at: datetime) -> bool:
        return (
            previous.astimezone(self.day_tz).date() != at.astimezone(self.day_tz).date()
        )

    def _plausible_day_value(self, value: float, at: datetime) -> bool:
        if self.max_kw is None:
            return True
        day = at.astimezone(self.day_tz).date()
        # Aware datetimes of different zones subtract in real time (23/25 h days).
        midnight = datetime.combine(day, time(0), tzinfo=self.day_tz)
        hours = (at - midnight).total_seconds() / 3600
        if self.previous_day:
            hours += 24
        return value <= self.max_kw * POWER_MARGIN * hours + JUMP_TOLERANCE_KWH

    def as_dict(self) -> dict[str, Any]:
        return {
            "last_value": self.last_value,
            "last_time": self.last_time.isoformat() if self.last_time else None,
        }

    def restore(self, data: dict[str, Any]) -> None:
        self.last_value = data.get("last_value")
        last_time = data.get("last_time")
        self.last_time = datetime.fromisoformat(last_time) if last_time else None
