"""Suggested cost settings from the sister integrations Tarifwacht and
Einspeisewacht, for the options form only (no dependency at runtime).

Read from their config entries as they store them (Tarifwacht 0.2.2,
Einspeisewacht: as Tarifwacht's solar_flow.from_einspeisewacht reads it):

- Tarifwacht, subentry "solar": feed-in, PV and battery meters, feed-in
  rate (ct/kWh); the tariff subentry marked current, if it is a dynamic
  tariff with a total price sensor (`dynamic_total`): that sensor. A tariff
  "exchange price plus surcharges" (`dynamic_market`) has only the exchange
  price as a sensor, not the price paid per kWh: nothing is suggested.
- Einspeisewacht: its meter (the feed-in) and its first rate (ct/kWh).

The grid import meter is never suggested: it switches the split into grid
and own electricity on, and a suggestion would be saved with any change of
the options.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_BATTERY_CHARGED_ENTITY,
    CONF_BATTERY_DISCHARGED_ENTITY,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_FEED_IN_ENTITY,
    CONF_FEED_IN_TARIFF,
    CONF_PV_ENTITY,
)

TARIFWACHT = "tarifwacht"
EINSPEISEWACHT = "einspeisewacht"

# Tarifwacht's solar subentry key -> Wärmewacht option.
TARIFWACHT_SOLAR = {
    "feed_in_entity": CONF_FEED_IN_ENTITY,
    "pv_entity": CONF_PV_ENTITY,
    "charged_entity": CONF_BATTERY_CHARGED_ENTITY,
    "discharged_entity": CONF_BATTERY_DISCHARGED_ENTITY,
    "feed_in_rate": CONF_FEED_IN_TARIFF,
}


@dataclass
class Suggestions:
    """Suggested option values and where they came from."""

    values: dict[str, Any] = field(default_factory=dict)
    source: str | None = None  # TARIFWACHT or EINSPEISEWACHT
    title: str | None = None  # title of that entry
    found: bool = False  # a sister entry exists (used or not)


def from_tarifwacht(hass: HomeAssistant) -> tuple[dict[str, Any], str | None]:
    """Values from the first Tarifwacht entry and its title."""
    entries = hass.config_entries.async_entries(TARIFWACHT)
    if not entries:
        return {}, None
    entry = entries[0]
    values: dict[str, Any] = {}
    for subentry in entry.subentries.values():
        data = subentry.data
        if subentry.subentry_type == "solar":
            for key, option in TARIFWACHT_SOLAR.items():
                if data.get(key) not in (None, ""):
                    values[option] = data[key]
        elif (
            subentry.subentry_type == "tariff"
            and data.get("current")
            and data.get("kind") == "dynamic_total"
            and data.get("price_entity")
        ):
            values[CONF_ELECTRICITY_PRICE_ENTITY] = data["price_entity"]
    return values, entry.title


def from_einspeisewacht(hass: HomeAssistant) -> tuple[dict[str, Any], str | None]:
    """Values from the first Einspeisewacht entry and its title."""
    entries = hass.config_entries.async_entries(EINSPEISEWACHT)
    if not entries:
        return {}, None
    entry = entries[0]
    values: dict[str, Any] = {}
    if meter := entry.data.get("meter_entity"):
        values[CONF_FEED_IN_ENTITY] = meter
    rates = entry.data.get("rates") or []
    if rates:
        with contextlib.suppress(TypeError, ValueError):
            values[CONF_FEED_IN_TARIFF] = float(rates[0])
    return values, entry.title


def suggestions(hass: HomeAssistant) -> Suggestions:
    """What the sisters suggest; Tarifwacht first, Einspeisewacht adds what
    Tarifwacht did not have."""
    result = Suggestions()
    for domain, read in (
        (TARIFWACHT, from_tarifwacht),
        (EINSPEISEWACHT, from_einspeisewacht),
    ):
        values, title = read(hass)
        if title is None:
            continue
        result.found = True
        new = {k: v for k, v in values.items() if k not in result.values}
        if new and result.source is None:
            result.source, result.title = domain, title
        result.values.update(new)
    return result
