"""Period marks: lifetime totals at the start of each period. Pure Python.

A period's energy is `totals now - mark`. Marks are taken at local period
boundaries (day, month, season); energy from before the setup is brought in
by a negative mark (the backfilled energy between period start and setup).
The cooling season is the calendar year (YEAR): cooling runs from spring to
autumn and would be cut in two by a heating season starting in July.
Boundaries are local midnights, so days have 23 or 25 hours at DST changes.
They are returned in UTC: Python subtracts and compares two datetimes of the
same zone by wall clock, which loses or doubles the hour of a time change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, tzinfo
from enum import StrEnum
from typing import Any

from .energy import Totals


class Period(StrEnum):
    """Time windows of the ratio sensors."""

    TODAY = "today"
    YESTERDAY = "yesterday"
    MONTH = "month"
    SEASON = "season"
    TOTAL = "total"
    YEAR = "year"  # calendar year: the season of cooling


# Windows with a ratio sensor each (YEAR stands in for SEASON when cooling).
RATIO_PERIODS = (
    Period.TODAY,
    Period.YESTERDAY,
    Period.MONTH,
    Period.SEASON,
    Period.TOTAL,
)


def local_midnight(day: date, tz: tzinfo) -> datetime:
    """Midnight of `day` in `tz`, as UTC."""
    return datetime.combine(day, time(0), tzinfo=tz).astimezone(UTC)


def period_start(
    period: Period, now: datetime, tz: tzinfo, season_month: int
) -> datetime | None:
    """Start (UTC) of the local period containing `now` (None for TOTAL)."""
    local = now.astimezone(tz)
    today = local.date()
    match period:
        case Period.TODAY:
            return local_midnight(today, tz)
        case Period.YESTERDAY:
            return local_midnight(date.fromordinal(today.toordinal() - 1), tz)
        case Period.MONTH:
            return local_midnight(today.replace(day=1), tz)
        case Period.SEASON:
            year = today.year if today.month >= season_month else today.year - 1
            return local_midnight(date(year, season_month, 1), tz)
        case Period.YEAR:
            return local_midnight(date(today.year, 1, 1), tz)
        case Period.TOTAL:
            return None


ROLLING = (Period.TODAY, Period.MONTH, Period.SEASON, Period.YEAR)


@dataclass
class PeriodMarks:
    """Marks for today, yesterday, month, season and total."""

    tz: tzinfo
    season_month: int
    marks: dict[Period, Totals] = field(default_factory=dict)
    starts: dict[Period, datetime | None] = field(default_factory=dict)
    # Season start month the stored marks were made with (None: not restored).
    stored_season_month: int | None = None

    def initialize(
        self, now: datetime, energy_since: Callable[[datetime | None], Totals]
    ) -> None:
        """First setup: `energy_since(start)` is the energy from `start` until now
        (from the recorder statistics; start None = all available)."""
        for period in (*ROLLING, Period.YESTERDAY, Period.TOTAL):
            start = period_start(period, now, self.tz, self.season_month)
            self.starts[period] = start
            self.marks[period] = -energy_since(start)

    def due(self, now: datetime) -> bool:
        """Whether a period boundary has passed since the last rollover."""
        return any(
            self.starts.get(p) != period_start(p, now, self.tz, self.season_month)
            for p in ROLLING
        )

    def rollover(self, now: datetime, totals: Totals) -> bool:
        """Start new periods whose boundary has passed; True if anything changed."""
        changed = False
        for period in ROLLING:
            start = period_start(period, now, self.tz, self.season_month)
            if self.starts.get(period) == start:
                continue
            if period is Period.TODAY:
                previous = self.starts.get(Period.TODAY)
                yesterday = period_start(
                    Period.YESTERDAY, now, self.tz, self.season_month
                )
                if previous == yesterday and Period.TODAY in self.marks:
                    self.marks[Period.YESTERDAY] = self.marks[Period.TODAY]
                    self.starts[Period.YESTERDAY] = yesterday
                else:
                    # Home Assistant was off over a whole day: yesterday unknown.
                    self.marks.pop(Period.YESTERDAY, None)
                    self.starts[Period.YESTERDAY] = None
            self.marks[period] = totals.copy()
            self.starts[period] = start
            changed = True
        return changed

    def energy(self, period: Period, totals: Totals) -> Totals | None:
        """Energy of the period, or None when it is unknown."""
        if period is Period.YESTERDAY:
            if self.starts.get(Period.YESTERDAY) is None:
                return None
            if Period.YESTERDAY not in self.marks or Period.TODAY not in self.marks:
                return None
            return self.marks[Period.TODAY] - self.marks[Period.YESTERDAY]
        mark = self.marks.get(period)
        return None if mark is None else totals - mark

    def as_dict(self) -> dict[str, Any]:
        return {
            "season_month": self.season_month,
            "marks": {p.value: m.as_dict() for p, m in self.marks.items()},
            "starts": {
                p.value: s.isoformat() if s else None for p, s in self.starts.items()
            },
        }

    def restore(self, data: dict[str, Any]) -> None:
        self.stored_season_month = data.get("season_month")
        self.marks = {
            Period(p): Totals.from_dict(m) for p, m in data.get("marks", {}).items()
        }
        self.starts = {
            Period(p): datetime.fromisoformat(s) if s else None
            for p, s in data.get("starts", {}).items()
        }
