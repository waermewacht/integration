"""Mask identifiers in texts for the diagnostics. Pure Python, no HA imports.

Unique ids and entity ids of heat pump integrations carry serial numbers and
config entry ids ("102011489-dhw1", "01JZM7…_produced_heating",
"sensor.luxtronik_2113_01267_dhw_temperature"). The diagnostics list them so
users of other makers can send a fixture for a new template; the template
logic only needs their shape. Each distinct identifier is replaced by a made
up one of the same kind and length, the same everywhere in one download.
"""

from __future__ import annotations

import re

# ULIDs (config entry ids since 2024), uuid4 hex (older entries), and runs of
# at least four digits (serial numbers, gateway ids).
_PATTERN = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}|[0-9a-f]{32}|\d{4,}")


class Masker:
    """Replaces identifiers consistently within one diagnostics download."""

    def __init__(self) -> None:
        self._fake: dict[str, str] = {}

    def _replacement(self, token: str) -> str:
        if token in self._fake:
            return self._fake[token]
        n = len(self._fake) + 1
        if token.isdigit():
            fake = ("1" + f"{n:0{len(token) - 1}d}")[: len(token)]
        elif len(token) == 26:
            fake = f"01JZ{n:022d}"
        else:
            fake = f"{n:032x}"
        self._fake[token] = fake
        return fake

    def __call__(self, text: str | None) -> str | None:
        if text is None:
            return None
        return _PATTERN.sub(lambda m: self._replacement(m.group(0)), text)
