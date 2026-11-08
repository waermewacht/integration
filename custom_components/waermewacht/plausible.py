"""Hourly changes of a meter from the long-term statistics: implausible hours.

Pure Python, no Home Assistant imports. The live counters (counter.py) check
every reading; changes read back from the statistics (look-back before the
setup, hourly booking, gas counters, house meters for the allocation) are
checked here, by the same rule as Tarifwacht (lookback.plausible_hours,
2026-11-08):

- more than `max_kwh` in one hour: a unit glitch of the source, e.g. Wh
  reported as kWh for a moment (state 107 -> 109851.5);
- less than 0: the sum restarted (meter replaced or reset in the statistics);
- the hour after such a jump in which the state falls again
  (109851.5 -> 110.131): Home Assistant takes the fall for a new meter cycle
  and adds the whole reading to the sum, which can stay under `max_kwh`.
  Unlike Tarifwacht also when the wrong reading lasted a few hours: until
  the state falls below the jump's, the fall back is still expected.

Left-out hours are missing hours for the caller, never 0.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime


def plausible_hours(
    rows: Iterable[tuple[datetime, float, float | None]], max_kwh: float
) -> tuple[dict[datetime, float], list[datetime]]:
    """Hourly changes (hour start, change, state of the row; in order) split
    into the plausible ones and the hours left out."""
    kept: dict[datetime, float] = {}
    left_out: list[datetime] = []
    jump_state: float | None = None
    for hour, change, state in rows:
        back = jump_state is not None and state is not None and state < jump_state
        if change < 0 or change > max_kwh or back:
            left_out.append(hour)
            jump_state = state if change > max_kwh else None
        else:
            kept[hour] = change
            # A wrong reading may last a few hours: the fall back comes later.
            if state is None:
                jump_state = None
    return kept, left_out
