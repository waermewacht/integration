"""Hourly changes of a meter from the long-term statistics: implausible hours.

Pure Python, no Home Assistant imports. The live counters (counter.py) check
every reading; changes read back from the statistics (look-back before the
setup, hourly booking, gas counters, house meters for the allocation) are
checked here (rule in plausible_hours, same as in Tarifwacht and
Einspeisewacht).

Left-out hours are missing hours for the caller, never 0.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

HOUR = timedelta(hours=1)


def plausible_hours(
    rows: Iterable[tuple[datetime, float, float | None]], max_kwh: float
) -> tuple[dict[datetime, float], list[datetime]]:
    """Hourly changes of a meter (start, change in kWh, state of the row;
    in order) split into the plausible ones and the hours left out.

    The bound is `max_kwh` per hour since the previous row: while Home
    Assistant was off, the recorder writes no rows, and the first row
    afterwards holds the whole gap (the first row of the series: one hour).
    Left out:

    - more than the bound: a unit glitch of the source, e.g. Wh reported as
      kWh for a moment (state 107 -> 109851.5);
    - less than 0: the sum restarted (meter replaced or reset in the
      statistics);
    - the fall back after such a jump (109851.5 -> 110.131): Home Assistant
      takes the fall for a new meter cycle and adds the whole reading to the
      sum, which can stay under the bound. Also when the wrong reading lasted
      a few hours: until the state falls below the jump's, the fall back is
      still expected (a row without a state ends the wait).

    A state that falls without a jump before (meter reset to 0) stays. Same
    rule in Tarifwacht (lookback.plausible_hours), Wärmewacht
    (plausible.plausible_hours) and Einspeisewacht (report.plausible_hours);
    only the bound per hour differs.
    """
    kept: dict[datetime, float] = {}
    left_out: list[datetime] = []
    jump_state: float | None = None
    previous: datetime | None = None
    for hour, change, state in rows:
        hours = 1.0 if previous is None else (hour - previous) / HOUR
        previous = hour
        bound = max_kwh * max(hours, 1.0)
        back = jump_state is not None and state is not None and state < jump_state
        if change < 0 or change > bound or back:
            left_out.append(hour)
            jump_state = state if change > bound else None
        else:
            kept[hour] = change
            # A wrong reading may last a few hours: the fall back comes later.
            if state is None:
                jump_state = None
    return kept, left_out
