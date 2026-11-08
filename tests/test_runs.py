"""Run and defrost detection, including restarts and mode changes."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.waermewacht.model import Activity, Mode
from custom_components.waermewacht.runs import (
    DEFROST_LATE,
    Defrost,
    RunTracker,
    defrost_aux_by_day,
)

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


def test_replay_of_recorded_history() -> None:
    """Backfill: recorded states give the same runs as live tracking:
    including a restart mid-run and a defrost that spans a restart."""
    from custom_components.waermewacht.runs import ACTIVITY, COMPRESSOR, replay

    events = [
        (at(0), COMPRESSOR, True),  # already running at the start: no start
        (at(0), ACTIVITY, Activity.HEATING),
        (at(20), COMPRESSOR, False),
        (at(20), ACTIVITY, Activity.OFF),
        (at(60), COMPRESSOR, True),
        (at(60), ACTIVITY, Activity.HEATING),
        (at(80), ACTIVITY, Activity.DEFROST),
        (at(81), ACTIVITY, None),  # Home Assistant restarts
        (at(81), COMPRESSOR, None),
        (at(81.1), ACTIVITY, Activity.DEFROST),
        (at(81.1), COMPRESSOR, True),
        (at(84), ACTIVITY, Activity.HEATING),
        (at(120), COMPRESSOR, False),
        (at(200), COMPRESSOR, True),  # still running now
    ]
    tracker, runs, defrosts = replay(reversed(events))
    assert [(r.counted, r.seconds(at(0))) for r in runs] == [
        (False, 20 * 60),
        (True, 60 * 60),
    ]
    assert len(defrosts) == 1 and defrosts[0].start == at(80)
    assert tracker.open_run is not None and tracker.open_run.counted


def test_source_gap_during_run_makes_it_uncertain() -> None:
    """A counter missing during a run while the compressor reading froze."""
    tracker = started(RunTracker())
    tracker.set_compressor(True, at(10))
    assert not tracker.source_gap(at(15), at(19))  # 4 minutes: tolerated
    assert tracker.source_gap(at(15), at(21))
    assert not tracker.source_gap(at(15), at(30))  # already marked
    run = tracker.set_compressor(False, at(600))
    assert run is not None and run.uncertain


def test_source_gap_before_the_run_does_not_count() -> None:
    """A meter gone for days does not taint every run."""
    tracker = started(RunTracker())
    tracker.set_compressor(True, at(10))
    assert not tracker.source_gap(at(-600), at(60))
    run = tracker.set_compressor(False, at(70))
    assert run is not None and not run.uncertain
    assert not RunTracker().source_gap(at(0), at(60))  # no open run


def test_backup_heater_energy_belongs_to_the_defrost() -> None:
    tracker = started(RunTracker())
    tracker.set_compressor(True, at(10))
    tracker.set_activity(Activity.DHW, at(10))
    assert tracker.defrost_at(at(20)) is None
    tracker.set_activity(Activity.DEFROST, at(30))
    running = tracker.defrost_at(at(31))
    assert running is tracker.open_defrost
    running.add_aux(Mode.DHW, 0.2)
    defrost = tracker.set_activity(Activity.DHW, at(38))
    assert defrost is running
    # Counters report a moment late: still the defrost, then no longer.
    assert tracker.defrost_at(at(38)) is defrost
    assert tracker.defrost_at(at(38) + DEFROST_LATE) is defrost
    assert tracker.defrost_at(at(38) + DEFROST_LATE + timedelta(seconds=1)) is None
    defrost.add_aux(Mode.DHW, 0.05)
    assert abs(defrost.aux(Mode.DHW) - 0.25) < 1e-9
    assert defrost.aux(Mode.HEATING) == 0.0


def test_stored_defrost_with_and_without_heater() -> None:
    plain = Defrost(start=at(0), end=at(4))
    assert "aux_kwh" not in plain.as_dict()  # stored as before
    assert Defrost.from_dict(plain.as_dict()) == plain
    heated = Defrost(start=at(0), end=at(4), aux_kwh={"heating": 0.3})
    assert Defrost.from_dict(heated.as_dict()) == heated


def test_defrost_heater_per_local_day() -> None:
    tz = ZoneInfo("Europe/Berlin")
    late = datetime(2026, 1, 14, 23, 30, tzinfo=UTC)  # 15.01. 00:30 local
    defrosts = [
        Defrost(start=late, end=late + timedelta(minutes=4), aux_kwh={"heating": 0.3}),
        Defrost(start=at(0), end=at(4), aux_kwh={"heating": 0.2, "dhw": 0.5}),
        Defrost(start=at(60), end=at(64)),
    ]
    assert defrost_aux_by_day(defrosts, Mode.HEATING, tz) == {date(2026, 1, 15): 0.5}
    assert defrost_aux_by_day(defrosts, Mode.DHW, tz) == {date(2026, 1, 15): 0.5}


def test_gaps_and_observation_start() -> None:
    """The first known state starts the observation; an outage longer than
    the tolerance is a gap, a restart of seconds is none."""
    tracker = RunTracker()
    tracker.set_compressor(None, at(0))
    assert tracker.observed_since is None
    tracker.set_compressor(False, at(1))
    assert tracker.observed_since == at(1)
    tracker.set_compressor(None, at(10))
    tracker.set_compressor(False, at(10.5))  # 30 s: a restart
    tracker.set_compressor(None, at(20))
    tracker.set_compressor(True, at(80))
    assert tracker.take_gaps() == [(at(20), at(80))]
    assert tracker.take_gaps() == []


def test_downtime_after_restore_is_a_gap() -> None:
    tracker = started(RunTracker())
    data = tracker.as_dict()
    restored = RunTracker()
    restored.restore(data, saved_at=at(5))
    assert restored.observed_since == at(0)
    restored.set_compressor(False, at(125))
    assert restored.take_gaps() == [(at(5), at(125))]


def test_books_without_observation_start() -> None:
    """Books of 0.4.5 and older have no observation start."""
    data = started(RunTracker()).as_dict()
    del data["observed_since"]
    restored = RunTracker()
    restored.restore(data, saved_at=at(5))
    assert restored.observed_since is None
