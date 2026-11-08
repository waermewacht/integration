"""Health check 4.13: conspicuous status messages. Pure Python, no HA imports.

The activity entity of some heat pumps also reports protection functions,
faults and waits, mostly self-made status templates under a manual mapping
("Durchflussüberwachung", "Hochdrucksicherung", "Schaltspielsperre"), but
also the Bosch PointT "alarm". Wärmewacht knows none of them as a mode: they
count as "other" and the energy stays with the mode before. This rule counts
how often each such text was entered and flags protection and fault
messages that come back again and again (seen 2026-11: "Durchfluss-
überwachung" once per heating cycle for days).

- Entered: the text of the activity entity changes to it from another
  known text. Unknown and unavailable in between change nothing, so a
  restart (unavailable -> unknown -> the same text) is no entry, and the
  first text after the setup neither. Counted per local day; the last
  WINDOW_DAYS days (today included) are kept, at most MAX_TEXTS texts a day
  (more go under OVERFLOW) of at most MAX_LENGTH characters.
- Only texts that carry no mode (Activity.OTHER) are counted.
- Kind by words (lower case, umlauts as ae/oe/ue, "-" and "_" as spaces):
  a WAITING word first (utility lock, minimum standstill, flushing: normal
  waits that say "EVU-Abschaltung" must not count as a fault), then a
  PROTECTION word, then a PAUSE word (a plain "Sperre"; "Hochdrucksperre" is
  protection). Anything else is unclassified and shown, never counted.
- On with at least MIN_ENTRIES entries of protection messages in the window
  (own assumption: one is chance, a daily return is a pattern; a pump that
  reports a flow monitor once per cycle gets there within a day). Unknown
  (too_few_days) while fewer than WINDOW_DAYS days are observed and it is
  not on. No hysteresis: the rolling window is one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .health import TOO_FEW_DAYS, Finding

WINDOW_DAYS = 7
MIN_ENTRIES = 3  # own assumption, docs/GESUNDHEITSCHECK.md 4.13
MAX_TEXTS = 20  # different texts per day
MAX_LENGTH = 60
OVERFLOW = "…"

PROTECTION = "protection"
WAITING = "waiting"
UNCLASSIFIED = "unclassified"

# Checked first: normal waits whose names may hold a protection word.
WAITING_WORDS = (
    # German
    "evu",
    "netzbelastung",
    "netzbetreiber",
    "sg ready",
    "smart grid",
    "schaltspielsperre",
    "mindeststandzeit",
    "mindestlaufzeit",
    "mindestpause",
    "einschaltverzögerung",
    "anlaufverzögerung",
    "spülen",
    "spülung",
    "primärpumpenvorlauf",
    "pumpenvorlauf",
    "pumpennachlauf",
    "nachlauf",
    "bereitschaft",
    "betriebsbereit",
    "standby",
    # English
    "utility",
    "demand response",
    "anti cycl",
    "minimum off",
    "minimum run",
    "min off",
    "start delay",
    "compressor delay",
    "pre run",
    "overrun",
    "purge",
    "flush",
    "ready",
)
# Protection functions and faults.
PROTECTION_WORDS = (
    # German
    "störung",
    "alarm",
    "fehler",
    "durchfluss",
    "niederdruck",
    "hochdruck",
    "druck",
    "frostschutz",
    "taupunkt",
    "einsatzgrenze",
    "sicherung",
    "abschaltung",
    "notbetrieb",
    # English
    "error",
    "fault",
    "failure",
    "pressure",
    "flow switch",
    "flow monitor",
    "low flow",
    "no flow",
    "frost protection",
    "antifreeze",
    "dew point",
    "operating limit",
    "safety",
    "lockout",
    "emergency",
)
# Checked last: a plain lock or pause.
PAUSE_WORDS = (
    "sperre",
    "gesperrt",
    "pause",
    "warte",
    "wait",
    "block",
    "lock",
    "delay",
)

_UMLAUTS = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "-": " ", "_": " "}
)


def _normal(text: str) -> str:
    return " ".join(text.casefold().translate(_UMLAUTS).split())


def _normals(words: Iterable[str]) -> tuple[str, ...]:
    return tuple(_normal(w) for w in words)


_WAITING = _normals(WAITING_WORDS)
_PROTECTION = _normals(PROTECTION_WORDS)
_PAUSE = _normals(PAUSE_WORDS)


def kind(text: str) -> str:
    """PROTECTION, WAITING or UNCLASSIFIED."""
    value = _normal(text)
    if any(w in value for w in _WAITING):
        return WAITING
    if any(w in value for w in _PROTECTION):
        return PROTECTION
    if any(w in value for w in _PAUSE):
        return WAITING
    return UNCLASSIFIED


@dataclass
class StatusCounter:
    """Entries of status texts per local day (ISO date -> text -> count)."""

    days: dict[str, dict[str, int]] = field(default_factory=dict)
    since: date | None = None  # counting since (first day observed)
    last: str | None = None  # last known text of the activity entity

    def observe(self, state: str | None, day: date, other: bool) -> bool:
        """A state of the activity entity; `other`: it carries no mode.

        True when an entry was counted (to be saved). A new text alone
        waits for the next save of the live file (a stop saves it too)."""
        if state is None or state.strip() in ("", "unknown", "unavailable"):
            return False
        text = state.strip()[:MAX_LENGTH]
        if text == self.last:
            return False
        previous, self.last = self.last, text
        if previous is None or not other:
            return False
        counts = self.days.setdefault(day.isoformat(), {})
        if text not in counts and len(counts) >= MAX_TEXTS:
            text = OVERFLOW
        counts[text] = counts.get(text, 0) + 1
        return True

    def prune(self, today: date) -> bool:
        """Drop the days before the window; True if any was dropped."""
        first = (today - timedelta(days=WINDOW_DAYS - 1)).isoformat()
        old = [d for d in self.days if d < first]
        for day in old:
            del self.days[day]
        return bool(old)

    def finding(self, today: date) -> Finding:
        return status_messages(self.days, today, self.since)

    def as_dict(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "since": self.since.isoformat() if self.since else None,
            "last": self.last,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> StatusCounter:
        if not data:
            return cls()
        since = data.get("since")
        return cls(
            days={
                str(d): {str(t): int(n) for t, n in counts.items()}
                for d, counts in (data.get("days") or {}).items()
            },
            since=date.fromisoformat(since) if since else None,
            last=data.get("last"),
        )


def _sorted(counts: Mapping[str, int]) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def status_messages(
    days: Mapping[str, Mapping[str, int]],
    today: date,
    since: date | None,
    *,
    threshold: int = MIN_ENTRIES,
    length: int = WINDOW_DAYS,
) -> Finding:
    """Entries of protection messages in the last `length` days (today
    included) against `threshold`."""
    first = (today - timedelta(days=length - 1)).isoformat()
    last = today.isoformat()
    total: dict[str, int] = {}
    for day, counts in days.items():
        if first <= day <= last:
            for text, count in counts.items():
                total[text] = total.get(text, 0) + count
    by_kind: dict[str, dict[str, int]] = {PROTECTION: {}, WAITING: {}, UNCLASSIFIED: {}}
    for text, count in total.items():
        by_kind[UNCLASSIFIED if text == OVERFLOW else kind(text)][text] = count
    protection = _sorted(by_kind[PROTECTION])
    entries = sum(protection.values())
    top = next(iter(protection.items()), (None, 0))
    observed = 0 if since is None else max(0, min(length, (today - since).days + 1))
    evidence: dict[str, Any] = {
        "entries_7d": entries,
        "most_frequent": top[0],
        "most_frequent_count": top[1],
        "protection": protection,
        "waiting": _sorted(by_kind[WAITING]),
        "unclassified": _sorted(by_kind[UNCLASSIFIED]),
        "days_observed": observed,
        "threshold_entries": threshold,
    }
    if entries >= threshold:
        return Finding(True, None, evidence)
    if observed < length:
        return Finding(None, TOO_FEW_DAYS, evidence)
    return Finding(False, None, evidence)
