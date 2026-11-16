"""Signals a template learned after an entry was set up. Pure Python.

A template gains signals over time (the hot water temperature in 0.1.0b8,
defrost and standby electricity in 0.1.1). An existing entry does not get
them by itself; the user would have to reconfigure. Instead, at setup the
signals the entry has not known yet are taken over, if the template finds
them for the same heat pump and the entry has none. A signal is known once
the entry had an entity for it (found by the template or configured); a
signal the user removed later is known and stays removed. A signal whose
entity the source does not deliver yet (bosch_homecom's compressor status
before 1.6.1, a source still starting) stays unknown until it does.

A source may also deliver a counter in a better form later (EMS-ESP's
backup heater per mode in 0.01 kWh besides whole kWh): an entry using the
older form, which the template lists as an alias of the preferred one,
moves to the preferred one; the older one stays for the backfill.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .model import Signal
from .profiles import Match

# Signals added to templates after 0.1.0b7. Entries from before that do not
# know which signals their template offered then: all others count as known.
LATER_SIGNALS = frozenset({Signal.DHW_TEMP, Signal.ELEC_DEFROST, Signal.ELEC_STANDBY})

# Signals a template offered before its source delivered them. Up to 0.2.5
# an entry counted every signal of its template as known, found or not, and
# never took these over (fixed by known_signals; repaired once on migration).
OFFERED_EARLY: dict[str, frozenset[Signal]] = {
    "bosch_homecom": frozenset({Signal.ACTIVITY}),
}


def signals_to_adopt(
    template_signals: Iterable[Signal],
    known: Iterable[str] | None,
    configured: Mapping[str, str],
) -> list[Signal]:
    """Template signals the entry has not seen yet and has no entity for."""
    signals = list(template_signals)
    seen = (
        set(known)
        if known is not None
        else {s.value for s in signals if s not in LATER_SIGNALS}
    )
    return [s for s in signals if s.value not in seen and s.value not in configured]


def known_signals(
    template_signals: Iterable[Signal],
    known: Iterable[str] | None,
    offered: Iterable[str],
) -> list[str]:
    """The signals to remember as known: those known before and those the
    entry has an entity for on offer now (found or configured)."""
    signals = list(template_signals)
    seen = (
        set(known)
        if known is not None
        else {s.value for s in signals if s not in LATER_SIGNALS}
    )
    seen.update(offered)
    return sorted(s.value for s in signals if s.value in seen)


def preferred_entities(match: Match, configured: Mapping[str, str]) -> dict[str, str]:
    """{signal: entity} where the entry uses an older form of the counter the
    template prefers now (one of its aliases, Match.history)."""
    return {
        signal.value: entity_id
        for signal, entity_id in match.entities.items()
        if (current := configured.get(signal.value)) is not None
        and current != entity_id
        and current in match.history.get(signal, [])
    }


def forget_offered_early(
    template_key: str | None, known: list[str] | None, configured: Mapping[str, str]
) -> list[str] | None:
    """Known signals without the ones offered before the source delivered
    them (OFFERED_EARLY), unless the entry uses them."""
    early = OFFERED_EARLY.get(template_key or "", frozenset())
    if known is None or not early:
        return known
    return [s for s in known if not (Signal(s) in early and s not in configured)]


def own_match(matches: Iterable[Match], configured: Mapping[str, str]) -> Match | None:
    """The match sharing the most entities with the entry (its heat pump)."""
    entity_ids = set(configured.values())
    best, overlap = None, 0
    for match in matches:
        shared = len(entity_ids & set(match.entities.values()))
        if shared > overlap:
            best, overlap = match, shared
    return best


def moved_match(
    matches: Iterable[Match],
    configured: Mapping[str, str],
    stale: set[str],
    own_key: str | None,
    taken: set[str],
) -> Match | None:
    """The heat pump of a template entry when a reconfigure looks again,
    because some of its entities are gone (`stale`: no state or unavailable).
    A source can rename all of them at once (EMS-ESP's entity format
    "multiple instances" puts the MQTT base in front, waermewacht#9). The
    match still sharing entities with the entry, else the one with the
    entry's source key ("template:prefix"), else the only match no other entry
    uses (`taken`: their source keys). None when nothing is stale or the heat
    pump cannot be told."""
    if not stale & set(configured.values()):
        return None
    candidates = list(matches)
    if (match := own_match(candidates, configured)) is not None:
        return match
    for match in candidates:
        if f"{match.template.key}:{match.prefix}" == own_key:
            return match
    free = [m for m in candidates if f"{m.template.key}:{m.prefix}" not in taken]
    return free[0] if len(free) == 1 else None


def replacements(
    match: Match, configured: Mapping[str, str], stale: set[str]
) -> dict[str, str]:
    """{signal: new entity} for the configured signals whose entity is gone
    and which the match has under another id."""
    return {
        key: match.entities[Signal(key)]
        for key, entity_id in configured.items()
        if entity_id in stale
        and key in Signal._value2member_map_
        and Signal(key) in match.entities
        and match.entities[Signal(key)] != entity_id
    }
