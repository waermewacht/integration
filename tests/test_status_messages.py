"""Health check 4.13: entries of status texts without a mode, per day."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from custom_components.waermewacht.health import TOO_FEW_DAYS
from custom_components.waermewacht.status_messages import (
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


def test_an_entry_is_a_change_to_the_text() -> None:
    counter = StatusCounter(since=WEEK_AGO)
    # The first text after the setup: no entry (the one before is unknown),
    # also when it carries no mode.
    assert not counter.observe("Störung", TODAY, True)
    assert counter.last == "Störung"
    assert not counter.observe("Heizen", TODAY, False)
    for _ in range(4):
        assert counter.observe("Durchflussüberwachung", TODAY, True)
        # An attribute change repeats the same text: no entry.
        assert not counter.observe("Durchflussüberwachung", TODAY, True)
        assert not counter.observe("Heizen", TODAY, False)
    assert counter.days == {TODAY.isoformat(): {"Durchflussüberwachung": 4}}


def test_a_restart_is_no_entry() -> None:
    counter = StatusCounter(since=WEEK_AGO)
    counter.observe("Heizen", TODAY, False)
    counter.observe("Sperre", TODAY, True)
    for state in ("unavailable", "unknown", "", None, "Sperre"):
        counter.observe(state, TODAY, True)
    assert counter.days[TODAY.isoformat()] == {"Sperre": 1}
    # Stored and read back (live file), still no entry.
    again = StatusCounter.from_dict(counter.as_dict())
    assert not again.observe("Sperre", TODAY, True)
    assert again == counter


def test_texts_per_day_are_bounded() -> None:
    counter = StatusCounter(since=WEEK_AGO, last="Heizen")
    for i in range(MAX_TEXTS + 5):
        counter.observe(f"Fehler {i}", TODAY, True)
    counts = counter.days[TODAY.isoformat()]
    assert len(counts) == MAX_TEXTS + 1
    assert counts[OVERFLOW] == 5
    counter.observe("x" * 200, TODAY, True)
    assert counter.last == "x" * 60


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
