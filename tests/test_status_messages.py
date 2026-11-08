"""Health check 4.13: entries of status texts without a mode, per day."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.waermewacht.health import TOO_FEW_DAYS
from custom_components.waermewacht.status_messages import (
    BEFORE_DEFROST,
    MAX_TEXTS,
    MIN_ENTRIES,
    OVERFLOW,
    PROTECTION,
    UNCLASSIFIED,
    WAITING,
    StatusCounter,
    kind,
    status_messages,
)
from custom_components.waermewacht.templates import TEMPLATES

TODAY = date(2026, 11, 8)
WEEK_AGO = TODAY - timedelta(days=6)
NOON = datetime(2026, 11, 8, 11, tzinfo=UTC)

# A status template of a real heat pump (simon42 forum, 2026-11), its texts
# as the user's template reports them.
REAL = {
    "Durchflussüberwachung": PROTECTION,
    "Niederdruckabschaltung": PROTECTION,
    "Hochdrucksicherung": PROTECTION,
    "Taupunktwaechter": PROTECTION,
    "Untere Einsatzgrenze": PROTECTION,
    "Schaltspielsperre": WAITING,
    "Netzbelastung": WAITING,
    "Sperre": WAITING,
    "Mindeststandzeit": WAITING,
    "Primärpumpenvorlauf": WAITING,
    "Spülen": WAITING,
    "Vorlaufgrenze": UNCLASSIFIED,
}


@pytest.mark.parametrize(("text", "expected"), REAL.items())
def test_kinds_of_a_real_status_list(text: str, expected: str) -> None:
    assert kind(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Stoerung", PROTECTION),  # umlaut written out
        ("STÖRUNG 12", PROTECTION),
        ("Frostschutz", PROTECTION),
        ("alarm", PROTECTION),  # Bosch PointT
        ("Low pressure fault", PROTECTION),
        ("Flow switch open", PROTECTION),
        ("Hochdrucksperre", PROTECTION),  # protection beats a plain lock
        ("EVU-Abschaltung", WAITING),  # a utility lock is no fault
        ("EVU Sperre", WAITING),
        ("SG_Ready", WAITING),
        ("Utility lock", WAITING),
        ("Anti cycling", WAITING),
        ("Standby", WAITING),
        ("Flow temperature limit", UNCLASSIFIED),
        ("Pool", UNCLASSIFIED),
    ],
)
def test_kinds(text: str, expected: str) -> None:
    assert kind(text) == expected


def test_the_texts_carry_no_mode_in_a_manual_mapping() -> None:
    """Only texts without a mode are counted: the real list is "other"."""
    from custom_components.waermewacht.model import Activity

    manual = TEMPLATES["ems_esp"]
    for text in REAL:
        assert manual.parse_activity(text) is Activity.OTHER


def at(minutes: float) -> datetime:
    return NOON + timedelta(minutes=minutes)


def test_an_entry_is_a_change_to_the_text() -> None:
    counter = StatusCounter(since=WEEK_AGO)
    # The first text after the setup: no entry (the one before is unknown),
    # also when it carries no mode.
    assert not counter.observe("Störung", at(0), TODAY, True)
    assert counter.last == "Störung"
    assert not counter.observe("Heizen", at(1), TODAY, False)
    for i in range(4):
        # A protection entry waits for a defrost, then counts.
        assert not counter.observe(
            "Durchflussüberwachung", at(10 + 30 * i), TODAY, True
        )
        # An attribute change repeats the same text: no entry.
        assert not counter.observe(
            "Durchflussüberwachung", at(11 + 30 * i), TODAY, True
        )
        assert not counter.observe("Heizen", at(12 + 30 * i), TODAY, False)
        assert counter.settle(at(21 + 30 * i))
    assert counter.days == {TODAY.isoformat(): {"Durchflussüberwachung": 4}}
    assert not counter.pending


def test_a_restart_is_no_entry() -> None:
    counter = StatusCounter(since=WEEK_AGO)
    counter.observe("Heizen", at(0), TODAY, False)
    counter.observe("Sperre", at(1), TODAY, True)
    for state in ("unavailable", "unknown", "", None, "Sperre"):
        counter.observe(state, at(2), TODAY, True)
    assert counter.days[TODAY.isoformat()] == {"Sperre": 1}
    # Stored and read back (live file), still no entry.
    again = StatusCounter.from_dict(counter.as_dict())
    assert not again.observe("Sperre", at(3), TODAY, True)
    assert again == counter


def test_a_waiting_entry_is_dropped_at_a_restart() -> None:
    counter = StatusCounter(since=WEEK_AGO, last="Heizen")
    counter.observe("Durchflussüberwachung", at(0), TODAY, True)
    assert "pending" not in counter.as_dict()
    again = StatusCounter.from_dict(counter.as_dict())
    assert not again.pending
    assert not again.observe("Durchflussüberwachung", at(1), TODAY, True)
    assert not again.settle(at(60))
    assert again.days == {}


def test_texts_per_day_are_bounded() -> None:
    counter = StatusCounter(since=WEEK_AGO, last="Heizen")
    for i in range(MAX_TEXTS + 5):
        counter.observe(f"Fehler {i}", at(i), TODAY, True)
    counter.settle(at(60))
    counts = counter.days[TODAY.isoformat()]
    assert len(counts) == MAX_TEXTS + 1
    assert counts[OVERFLOW] == 5
    counter.observe("x" * 200, at(61), TODAY, True)
    assert counter.last == "x" * 60


def defrost_pattern(counter: StatusCounter, start: float, gap: float) -> None:
    """Heizen -> Durchflussüberwachung -> (gap) Abtauen -> Heizen, as the
    activity entity of a Dimplex-like controller reports it (simon42 forum,
    2026-11; the compressor keeps running)."""
    counter.observe("Heizen", at(start), TODAY, False)
    counter.observe("Durchflussüberwachung", at(start + 30), TODAY, True)
    counter.observe("Abtauen", at(start + 30 + gap), TODAY, False)
    counter.defrost(at(start + 30 + gap))
    counter.observe("Heizen", at(start + 35 + gap), TODAY, False)
    counter.settle(at(start + 60 + gap))


def test_the_flow_monitor_before_a_defrost_is_no_entry() -> None:
    counter = StatusCounter(since=WEEK_AGO)
    for cycle in range(10):
        defrost_pattern(counter, 90 * cycle, 2)
    assert counter.days == {}
    assert not counter.pending
    result = counter.finding(TODAY)
    assert result.problem is False
    assert result.evidence["entries_7d"] == 0


def test_the_flow_monitor_amid_a_cycle_counts() -> None:
    counter = StatusCounter(since=WEEK_AGO)
    for cycle in range(3):
        counter.observe("Heizen", at(60 * cycle), TODAY, False)
        counter.observe("Durchflussüberwachung", at(60 * cycle + 20), TODAY, True)
        counter.observe("Heizen", at(60 * cycle + 22), TODAY, False)
    # Counted once the time passed without a defrost, the last one not yet.
    assert counter.days == {TODAY.isoformat(): {"Durchflussüberwachung": 2}}
    minutes = BEFORE_DEFROST.total_seconds() / 60
    assert not counter.settle(at(140 + minutes))
    assert counter.settle(at(141 + minutes))
    assert counter.finding(TODAY).problem is True


def test_a_defrost_after_the_time_does_not_excuse() -> None:
    counter = StatusCounter(since=WEEK_AGO)
    for cycle in range(3):
        defrost_pattern(counter, 90 * cycle, 15)
    assert counter.days == {TODAY.isoformat(): {"Durchflussüberwachung": 3}}
    assert counter.finding(TODAY).problem is True
    # Counted at the defrost, also without a settle before.
    counter = StatusCounter(since=WEEK_AGO, last="Heizen")
    counter.observe("Durchflussüberwachung", at(0), TODAY, True)
    assert counter.defrost(at(15)) == (True, 0)
    assert counter.days == {TODAY.isoformat(): {"Durchflussüberwachung": 1}}
    # Exactly ten minutes is still before the defrost.
    counter.observe("Heizen", at(20), TODAY, False)
    counter.observe("Durchflussüberwachung", at(30), TODAY, True)
    assert counter.defrost(at(30) + BEFORE_DEFROST) == (False, 1)


def test_one_waiting_entry_per_text() -> None:
    """Entered again before the time is over: the first one ended without a
    defrost and counts, the second waits."""
    counter = StatusCounter(since=WEEK_AGO, last="Heizen")
    assert not counter.observe("Durchflussüberwachung", at(0), TODAY, True)
    counter.observe("Heizen", at(1), TODAY, False)
    assert counter.observe("Durchflussüberwachung", at(3), TODAY, True)
    assert counter.days == {TODAY.isoformat(): {"Durchflussüberwachung": 1}}
    assert len(counter.pending) == 1
    counter.observe("Abtauen", at(5), TODAY, False)
    assert counter.defrost(at(5)) == (False, 1)
    assert counter.days == {TODAY.isoformat(): {"Durchflussüberwachung": 1}}


def test_a_waiting_entry_counts_on_its_day() -> None:
    counter = StatusCounter(since=WEEK_AGO, last="Heizen")
    late = datetime(2026, 11, 7, 22, 55, tzinfo=UTC)  # 23:55 local
    yesterday = TODAY - timedelta(days=1)
    counter.observe("Hochdrucksicherung", late, yesterday, True)
    assert counter.settle(late + timedelta(minutes=11))
    assert counter.days == {yesterday.isoformat(): {"Hochdrucksicherung": 1}}


def test_waits_count_at_once() -> None:
    counter = StatusCounter(since=WEEK_AGO, last="Heizen")
    assert counter.observe("Schaltspielsperre", at(0), TODAY, True)
    assert not counter.pending
    counter.observe("Abtauen", at(2), TODAY, False)
    assert counter.defrost(at(2)) == (False, 0)
    assert counter.days == {TODAY.isoformat(): {"Schaltspielsperre": 1}}


def test_old_days_are_dropped() -> None:
    counter = StatusCounter(
        days={
            (TODAY - timedelta(days=7)).isoformat(): {"Fehler": 9},
            WEEK_AGO.isoformat(): {"Fehler": 1},
        }
    )
    assert counter.prune(TODAY)
    assert list(counter.days) == [WEEK_AGO.isoformat()]
    assert not counter.prune(TODAY)


def test_flow_monitor_once_per_cycle_is_conspicuous() -> None:
    """The real case: the flow monitor reports once per heating cycle."""
    days = {
        (TODAY - timedelta(days=d)).isoformat(): {
            "Durchflussüberwachung": 2,
            "Schaltspielsperre": 3,
            "Netzbelastung": 1,
            "Vorlaufgrenze": 1,
        }
        for d in range(6)
    }
    result = status_messages(days, TODAY, WEEK_AGO)
    assert result.problem is True
    assert result.evidence["entries_7d"] == 12
    assert result.evidence["most_frequent"] == "Durchflussüberwachung"
    assert result.evidence["most_frequent_count"] == 12
    assert result.evidence["protection"] == {"Durchflussüberwachung": 12}
    assert result.evidence["waiting"] == {"Schaltspielsperre": 18, "Netzbelastung": 6}
    assert result.evidence["unclassified"] == {"Vorlaufgrenze": 6}
    assert result.evidence["threshold_entries"] == MIN_ENTRIES


def test_waits_are_no_finding() -> None:
    days = {TODAY.isoformat(): {"Sperre": 40, "Mindeststandzeit": 30, "Spülen": 5}}
    result = status_messages(days, TODAY, WEEK_AGO)
    assert result.problem is False
    assert result.evidence["entries_7d"] == 0
    assert result.evidence["most_frequent"] is None


def test_threshold_over_all_protection_texts() -> None:
    days = {
        TODAY.isoformat(): {"Hochdrucksicherung": 1},
        WEEK_AGO.isoformat(): {"Niederdruckabschaltung": 1},
    }
    assert status_messages(days, TODAY, WEEK_AGO).problem is False
    days[TODAY.isoformat()]["Taupunktwaechter"] = 1
    assert status_messages(days, TODAY, WEEK_AGO).problem is True
    # A day before the window does not count.
    days = {(TODAY - timedelta(days=7)).isoformat(): {"Störung": 5}}
    assert status_messages(days, TODAY, WEEK_AGO).problem is False


def test_unknown_until_a_week_is_observed() -> None:
    since = TODAY - timedelta(days=2)
    result = status_messages({TODAY.isoformat(): {"Störung": 1}}, TODAY, since)
    assert result.problem is None
    assert result.reason == TOO_FEW_DAYS
    assert result.evidence["days_observed"] == 3
    # On is on, also in the first days.
    result = status_messages({TODAY.isoformat(): {"Störung": 3}}, TODAY, since)
    assert result.problem is True
    assert status_messages({}, TODAY, None).reason == TOO_FEW_DAYS
