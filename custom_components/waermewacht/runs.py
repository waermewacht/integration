"""Compressor runs and defrosts from on/off and activity states.

Pure Python, no Home Assistant imports. Unknown states (`None`: the source is
unavailable or Home Assistant restarts) never start, end or split anything:
the last known state holds, and a long gap only marks the affected run as
uncertain. A run that was already going when first seen is not a start.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .const import GAP_TOLERANCE_SECONDS
from .model import Activity, Mode


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass
class Run:
    """One compressor run from on to off."""

    start: datetime
    end: datetime | None = None
    counted: bool = True  # the start was observed: it is a compressor start
    uncertain: bool = False  # a long gap hides the real start or end
    # Seconds per activity while running (a run may switch heating -> DHW).
    activity_seconds: dict[str, float] = field(default_factory=dict)

    def seconds(self, now: datetime) -> float:
        return ((self.end or now) - self.start).total_seconds()

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": _iso(self.end),
            "counted": self.counted,
            "uncertain": self.uncertain,
            "activity_seconds": dict(self.activity_seconds),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Run:
        return cls(
            start=datetime.fromisoformat(data["start"]),
            end=_dt(data.get("end")),
            counted=data.get("counted", True),
            uncertain=data.get("uncertain", False),
            activity_seconds=dict(data.get("activity_seconds", {})),
        )


@dataclass
class Defrost:
    """One defrost, from the activity switching to defrost until it leaves it."""

    start: datetime
    end: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"start": self.start.isoformat(), "end": _iso(self.end)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Defrost:
        return cls(
            start=datetime.fromisoformat(data["start"]), end=_dt(data.get("end"))
        )


@dataclass
class RunTracker:
    """Follow the compressor state and the activity of one heat pump."""

    gap_tolerance: float = GAP_TOLERANCE_SECONDS
    compressor: bool | None = None  # last known state
    activity: Activity | None = None  # last known activity
    activity_since: datetime | None = None  # None while the activity is unknown
    unknown_since: datetime | None = None  # compressor state unknown since
    last_on: datetime | None = None  # end of the latest run
    last_mode: Mode | None = None  # latest heating/DHW/cooling activity
    open_run: Run | None = None
    open_defrost: Defrost | None = None

    @property
    def mode(self) -> Mode | None:
        """Mode energy belongs to now (a defrost belongs to the mode before)."""
        if self.activity is not None and self.activity.mode is not None:
            return self.activity.mode
        return self.last_mode

    def was_running_since(self, since: datetime | None) -> bool:
        """Whether the compressor ran at any time after `since`."""
        if self.compressor or self.open_run is not None:
            return True
        return since is not None and self.last_on is not None and self.last_on > since

    def set_compressor(self, on: bool | None, at: datetime) -> Run | None:
        """Process a compressor state; returns a run that ended."""
        if on is None:
            if self.unknown_since is None:
                self.unknown_since = at
            return None
        gap = (at - self.unknown_since).total_seconds() if self.unknown_since else 0.0
        self.unknown_since = None
        long_gap = gap > self.gap_tolerance
        if on:
            if self.open_run is not None:
                self.open_run.uncertain |= long_gap
            else:
                # Seen for the first time while running: no observed start.
                counted = self.compressor is False
                self.open_run = Run(start=at, counted=counted, uncertain=long_gap)
                if self.activity_since is not None:
                    self.activity_since = at
            self.compressor = True
            return None
        self.compressor = False
        run = self.open_run
        if run is None:
            return None
        self._accumulate(at)
        run.end = at
        run.uncertain |= long_gap
        self.open_run = None
        self.last_on = at
        return run

    def set_activity(self, activity: Activity | None, at: datetime) -> Defrost | None:
        """Process an activity; returns a defrost that ended."""
        self._accumulate(at)
        if activity is None:
            # Keep the last known activity: defrost -> unknown -> defrost is one.
            self.activity_since = None
            return None
        previous = self.activity
        self.activity, self.activity_since = activity, at
        if activity.mode is not None:
            self.last_mode = activity.mode
        if activity is Activity.DEFROST and previous is not Activity.DEFROST:
            self.open_defrost = Defrost(start=at)
            return None
        if activity is not Activity.DEFROST and self.open_defrost is not None:
            defrost, self.open_defrost = self.open_defrost, None
            defrost.end = at
            return defrost
        return None

    def tick(self, at: datetime) -> None:
        """Bring the activity time of the open run up to `at`."""
        self._accumulate(at)

    def _accumulate(self, at: datetime) -> None:
        if self.activity is None or self.activity_since is None:
            return
        if self.open_run is not None and at > self.activity_since:
            seconds = (at - self.activity_since).total_seconds()
            key = self.activity.value
            self.open_run.activity_seconds[key] = (
                self.open_run.activity_seconds.get(key, 0.0) + seconds
            )
        self.activity_since = at

    def as_dict(self) -> dict[str, Any]:
        return {
            "compressor": self.compressor,
            "activity": self.activity.value if self.activity else None,
            "activity_since": _iso(self.activity_since),
            "unknown_since": _iso(self.unknown_since),
            "last_on": _iso(self.last_on),
            "last_mode": self.last_mode.value if self.last_mode else None,
            "open_run": self.open_run.as_dict() if self.open_run else None,
            "open_defrost": self.open_defrost.as_dict() if self.open_defrost else None,
        }

    def restore(self, data: dict[str, Any], saved_at: datetime) -> None:
        """Restore after a restart; the time since `saved_at` counts as a gap."""
        self.compressor = data.get("compressor")
        activity = data.get("activity")
        self.activity = Activity(activity) if activity else None
        # The activity is unknown until the source reports again.
        self.activity_since = None
        self.unknown_since = _dt(data.get("unknown_since")) or saved_at
        self.last_on = _dt(data.get("last_on"))
        last_mode = data.get("last_mode")
        self.last_mode = Mode(last_mode) if last_mode else None
        run = data.get("open_run")
        self.open_run = Run.from_dict(run) if run else None
        defrost = data.get("open_defrost")
        self.open_defrost = Defrost.from_dict(defrost) if defrost else None
