"""Run and defrost detection, including restarts and mode changes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.waermewacht.model import Activity, Mode
from custom_components.waermewacht.runs import RunTracker

T0 = datetime(2026, 1, 15, 5, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def started(tracker: RunTracker) -> RunTracker:
    """Compressor seen off first, so the next start is observed."""
    tracker.set_compressor(False, at(0))
    tracker.set_activity(Activity.OFF, at(0))
    return tracker


def test_run_from_off_to_off() -> None:
    tracker = started(RunTracker())
    tracker.set_compressor(True, at(10))
    tracker.set_activity(Activity.HEATING, at(10))
    run = tracker.set_compressor(False, at(55))
    assert run is not None
    assert run.counted and not run.uncertain
    assert run.seconds(at(60)) == 45 * 60
    assert run.activity_seconds == {"heating": 45 * 60}
    assert tracker.last_on == at(55)


def test_running_when_first_seen_is_no_start() -> None:
    tracker = RunTracker()
    tracker.set_compressor(True, at(0))
    run = tracker.set_compressor(False, at(30))
    assert run is not None
    assert not run.counted


def test_restart_during_run_is_no_new_start() -> None:
    """on -> unavailable -> unknown -> on within seconds: the same run."""
    tracker = started(RunTracker())
    tracker.set_compressor(True, at(10))
    tracker.set_compressor(None, at(20))
    tracker.set_compressor(None, at(20.02))
    tracker.set_compressor(True, at(20.05))
    run = tracker.set_compressor(False, at(40))
    assert run is not None
    assert run.counted and not run.uncertain
    assert run.start == at(10)


def test_restart_with_restored_state() -> None:
    """Home Assistant restarts mid-run: the stored open run continues."""
    tracker = started(RunTracker())
    tracker.set_compressor(True, at(10))
    tracker.set_activity(Activity.HEATING, at(10))
    data = tracker.as_dict()

    restored = RunTracker()
    restored.restore(data, saved_at=at(20))
    restored.set_compressor(True, at(21))
    restored.set_activity(Activity.HEATING, at(21))
    run = restored.set_compressor(False, at(40))
    assert run is not None
    assert run.counted and not run.uncertain
    assert run.start == at(10)


def test_long_outage_makes_run_uncertain() -> None:
    tracker = started(RunTracker())
    tracker.set_compressor(True, at(10))
    tracker.set_compressor(None, at(20))
    run = tracker.set_compressor(False, at(80))
    assert run is not None
    assert run.uncertain


def test_mode_change_within_one_run() -> None:
    """Observed: heating switches to hot water without the compressor stopping."""
    tracker = started(RunTracker())
    tracker.set_compressor(True, at(10))
    tracker.set_activity(Activity.HEATING, at(10))
    assert tracker.mode is Mode.HEATING
    tracker.set_activity(Activity.DHW, at(63))
    assert tracker.mode is Mode.DHW
    run = tracker.set_compressor(False, at(120))
    assert run is not None
    assert run.activity_seconds == {"heating": 53 * 60, "dhw": 57 * 60}


def test_defrost_belongs_to_the_mode_before() -> None:
    tracker = started(RunTracker())
    tracker.set_compressor(True, at(10))
    tracker.set_activity(Activity.HEATING, at(10))
    assert tracker.set_activity(Activity.DEFROST, at(40)) is None
    assert tracker.mode is Mode.HEATING
    defrost = tracker.set_activity(Activity.HEATING, at(43.5))
    assert defrost is not None
    assert defrost.start == at(40) and defrost.end == at(43.5)
    # The compressor kept running: still one run.
    assert tracker.open_run is not None


def test_restart_during_defrost_is_one_defrost() -> None:
    """Observed: defrost -> unavailable -> unknown -> defrost during a restart."""
    tracker = started(RunTracker())
    tracker.set_compressor(True, at(10))
    tracker.set_activity(Activity.HEATING, at(10))
    tracker.set_activity(Activity.DEFROST, at(40))
    tracker.set_activity(None, at(41))
    tracker.set_activity(Activity.DEFROST, at(41.1))
    defrost = tracker.set_activity(Activity.HEATING, at(43))
    assert defrost is not None
    assert defrost.start == at(40)


def test_was_running_since() -> None:
    tracker = started(RunTracker())
    assert not tracker.was_running_since(at(0))
    tracker.set_compressor(True, at(10))
    assert tracker.was_running_since(at(5))
    tracker.set_compressor(False, at(20))
    assert tracker.was_running_since(at(15))
    assert not tracker.was_running_since(at(25))


def test_mode_survives_unknown_activity() -> None:
    tracker = started(RunTracker())
    tracker.set_activity(Activity.DHW, at(1))
    tracker.set_activity(None, at(2))
    assert tracker.mode is Mode.DHW
    tracker.set_activity(Activity.OFF, at(3))
    assert tracker.mode is Mode.DHW
