"""Signals a template learned after an entry was set up. Pure Python.

A template gains signals over time (the hot water temperature in 0.1.0b8,
defrost and standby electricity in 0.1.0b9). An existing entry does not get
them by itself; the user would have to reconfigure. Instead, at setup the
signals the template offers now but did not offer when the entry was last
set up or reconfigured are taken over, if the template finds them for the
same heat pump and the entry has none. Each entry remembers the signals its
template knew; a signal the user removed later is known and stays removed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .model import Signal
from .profiles import Match

# Signals added to templates after 0.1.0b7. Entries from before that do not
# know which signals their template offered then: all others count as known.
LATER_SIGNALS = frozenset({Signal.DHW_TEMP, Signal.ELEC_DEFROST, Signal.ELEC_STANDBY})


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


def own_match(matches: Iterable[Match], configured: Mapping[str, str]) -> Match | None:
    """The match sharing the most entities with the entry (its heat pump)."""
    entity_ids = set(configured.values())
    best, overlap = None, 0
    for match in matches:
        shared = len(entity_ids & set(match.entities.values()))
        if shared > overlap:
            best, overlap = match, shared
    return best
