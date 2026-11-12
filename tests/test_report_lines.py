"""Lines of the report for a bug report (button.py): the hours left out of
the statistics per counter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.waermewacht.button import _rejected_hours
from custom_components.waermewacht.model import Signal
from custom_components.waermewacht.runtime import REJECTED_KEPT, HeatPumpRuntime

H0 = datetime(2026, 11, 10, 13, tzinfo=UTC)


def test_latest_rejected_hours_are_kept_per_counter() -> None:
    runtime = SimpleNamespace(rejected_hours={})
    hours = [H0 + timedelta(hours=i) for i in range(5)]
    # Each read of the statistics finds the same hours again: no duplicates.
    HeatPumpRuntime._note_rejected(runtime, Signal.ELEC_DHW, hours[:2])
    HeatPumpRuntime._note_rejected(runtime, Signal.ELEC_DHW, hours[:2])
    assert runtime.rejected_hours == {"elec_dhw": hours[:2]}
    HeatPumpRuntime._note_rejected(runtime, Signal.ELEC_DHW, hours[2:])
    assert runtime.rejected_hours["elec_dhw"] == hours[-REJECTED_KEPT:]


def test_report_line_names_counter_and_hours() -> None:
    assert _rejected_hours({}) == "none"
    line = _rejected_hours(
        {"heat_dhw": [H0], "elec_dhw": [H0, H0 + timedelta(hours=1)]}
    )
    assert line == (
        "elec_dhw 2026-11-10 13:00Z, 2026-11-10 14:00Z; heat_dhw 2026-11-10 13:00Z"
    )
