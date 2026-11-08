"""Turn readings of an energy counter into increments.

Pure Python, no Home Assistant imports. Same idea as the meter trackers of
Einspeisewacht and Tarifwacht, without splitting into quarter hours.

Copies: speicherwacht/custom_components/speicherwacht/counter.py (derived).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
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
# The hours count from the last rise, not from the last reading: a source that
# drops out repeats its old value when it comes back, then catches up with
# several kWh (observed: P1P2MQTT, 2 and 3 kWh within a minute after the same
# value, stalled 36 and 52 minutes). At most this far back, so that a counter
# idle for weeks (cooling in winter) still rejects glitches.
CATCH_UP_HOURS = 1.0
# A jump that falls back to at least the value before it was a glitch of the
# source (observed in Tarifwacht: 107 -> 109851.5 -> 110.131 kWh, Wh as kWh
# for one reading): the real increase across it is booked when the fall back
# comes, if plausible for the time since the value before the jump. Waited
# for this long at most (own assumption; glitches seen lasted one reading).
JUMP_RECOVERY = timedelta(hours=24)

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
    # Fall back after a jump to at least the value before it: the real
    # increase across the glitch is booked (less what was booked during it).
    RECOVERED = "recovered"


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
class PendingJump:
    """A jump that may still fall back (see JUMP_RECOVERY)."""

    before: float  # value before the jump
    before_time: datetime  # its reading
    before_rose: datetime | None  # when the baseline rose before the jump
    at: datetime  # the jump
    level: float  # highest value since the jump
    booked: float = 0.0  # booked since the jump (rises at the glitch level)

    def as_dict(self) -> dict[str, Any]:
        return {
            "before": self.before,
            "before_time": self.before_time.isoformat(),
            "before_rose": self.before_rose.isoformat() if self.before_rose else None,
            "at": self.at.isoformat(),
            "level": self.level,
            "booked": self.booked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingJump:
        rose = data.get("before_rose")
        return cls(
            before=float(data["before"]),
            before_time=datetime.fromisoformat(data["before_time"]),
            before_rose=datetime.fromisoformat(rose) if rose else None,
            at=datetime.fromisoformat(data["at"]),
            level=float(data["level"]),
            booked=float(data.get("booked", 0.0)),
        )


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
    # When the baseline last moved up (first value, rise, reset, jump).
    rose_time: datetime | None = None
    # The latest jump while it may still fall back (lifetime counters only).
    jump: PendingJump | None = None

    def update(self, value: float, at: datetime) -> CounterUpdate:
        """Process a reading in kWh taken at `at` (timezone-aware)."""
        previous_value, previous_time = self.last_value, self.last_time
        if previous_time is not None and at < previous_time:
            return CounterUpdate()  # out of order: keep the newer baseline
        if previous_value is None or previous_time is None:
            self.last_value, self.last_time, self.rose_time = value, at, at
            return CounterUpdate(event=CounterEvent.FIRST)
        if self.day_tz is not None:
            return self._update_day(value, at, previous_value, previous_time)
        if self.jump is not None and at - self.jump.at > JUMP_RECOVERY:
            self.jump = None
        delta = value - previous_value
        if delta < 0:
            if (recovered := self._recover(value, at)) is not None:
                return recovered
            if -delta <= max(RESET_MIN_KWH, RESET_FRACTION * previous_value):
                self.last_time = at
                return CounterUpdate(event=CounterEvent.DIP)
            if self.jump is not None and value < self.jump.before:
                self.jump = None  # below the value before the jump: a reset
            self.last_value, self.last_time, self.rose_time = value, at, at
            return CounterUpdate(event=CounterEvent.RESET)
        rose_time = self.rose_time
        self.last_value, self.last_time = value, at
        if delta == 0:
            return CounterUpdate()
        self.rose_time = at
        if not self._plausible(delta, at, previous_time, rose_time):
            if self.jump is None:  # a second jump keeps the first value
                self.jump = PendingJump(
                    before=previous_value,
                    before_time=previous_time,
                    before_rose=rose_time,
                    at=at,
                    level=value,
                )
            self.jump.level = max(self.jump.level, value)
            return CounterUpdate(event=CounterEvent.JUMP)
        if self.jump is not None:
            self.jump.booked += delta
            self.jump.level = max(self.jump.level, value)
        return CounterUpdate(delta=delta)

    def _plausible(
        self,
        delta: float,
        at: datetime,
        previous_time: datetime,
        rose_time: datetime | None,
    ) -> bool:
        """An increase within `max_kw` for the time since the last reading,
        or since the last rise (at most CATCH_UP_HOURS back)."""
        if self.max_kw is None:
            return True
        hours = (at - previous_time).total_seconds() / 3600
        if rose_time is not None:
            since_rise = (at - rose_time).total_seconds() / 3600
            hours = max(hours, min(since_rise, CATCH_UP_HOURS))
        return delta <= self.max_kw * POWER_MARGIN * hours + JUMP_TOLERANCE_KWH

    def _recover(self, value: float, at: datetime) -> CounterUpdate | None:
        """A fall back after a jump to at least the value before it, nearer
        to that value than to the glitch level: the jump was a glitch. Books
        the increase since the value before the jump, less what rises at the
        glitch level booked, if plausible for the time since that value (the
        jump bound, counted from there). A dip at the new level (defrost,
        noise) after a real jump is no fall back."""
        jump = self.jump
        if jump is None or value < jump.before:
            return None
        if value - jump.before >= (jump.level - jump.before) / 2:
            return None
        if not self._plausible(
            value - jump.before, at, jump.before_time, jump.before_rose
        ):
            return None  # not the glitch falling back: as before
        self.jump = None
        self.last_value, self.last_time, self.rose_time = value, at, at
        return CounterUpdate(
            delta=max(value - jump.before - jump.booked, 0.0),
            event=CounterEvent.RECOVERED,
        )

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
        data = {
            "last_value": self.last_value,
            "last_time": self.last_time.isoformat() if self.last_time else None,
            "rose_time": self.rose_time.isoformat() if self.rose_time else None,
        }
        if self.jump is not None:
            data["jump"] = self.jump.as_dict()
        return data

    def restore(self, data: dict[str, Any]) -> None:
        self.last_value = data.get("last_value")
        last_time = data.get("last_time")
        self.last_time = datetime.fromisoformat(last_time) if last_time else None
        rose_time = data.get("rose_time")
        self.rose_time = datetime.fromisoformat(rose_time) if rose_time else None
        jump = data.get("jump")
        self.jump = PendingJump.from_dict(jump) if jump else None
