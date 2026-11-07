"""The Lovelace cards (frontend/waermewacht-card.js).

The integration serves the file itself and registers it with the frontend
as a dashboard resource (frontend_resource.py), so nobody has to add one; a
new version busts the cache by its query string. The cards read Wärmewacht's own entities through the
entity registry (device and translation key); the card "Now" also shows the
source's activity and temperatures, which only the entry knows: the
websocket command "waermewacht/sources" hands them out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import CONF_KIND, DOMAIN, KIND_GAS, VERSION
from .model import Signal

CARD_FILE = "waermewacht-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILE}"
# The URL the frontend loads: a new version is a new URL (no stale cache).
CARD_RESOURCE_URL = f"{CARD_URL}?v={VERSION}"
# Source signals the card "Now" shows.
NOW_SIGNALS = (
    Signal.ACTIVITY,
    Signal.COMPRESSOR,
    Signal.OUTDOOR_TEMP,
    Signal.FLOW_TEMP,
    Signal.RETURN_TEMP,
    Signal.DHW_TEMP,
)


async def async_setup_cards(hass: HomeAssistant) -> None:
    """Serve the cards and register the websocket command; without http
    (tests) only the command. The frontend learns of the cards per entry
    (frontend_resource.async_register_card)."""
    websocket_api.async_register_command(hass, ws_sources)
    if getattr(hass, "http", None) is None:
        return
    from homeassistant.components.http import StaticPathConfig

    path = Path(__file__).parent / "frontend" / CARD_FILE
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), True)]
    )


def source_entities(hass: HomeAssistant, device_id: str) -> dict[str, str] | None:
    """The source entities a card shows for a Wärmewacht device; None if the
    device is no loaded heat pump entry of Wärmewacht."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    # Since HA 2026.11 a device belongs to one entry (`config_entry_id`);
    # `config_entries` warns and goes in 2027.10. Older versions only have it.
    if hasattr(device, "config_entry_id"):
        entry_ids = [device.config_entry_id] if device.config_entry_id else []
    else:
        entry_ids = list(device.config_entries)
    for entry_id in entry_ids:
        entry = hass.config_entries.async_get_entry(entry_id)
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.data.get(CONF_KIND) == KIND_GAS  # no heat pump
            or entry.state is not ConfigEntryState.LOADED
        ):
            continue
        entities: dict[Any, str] = getattr(entry.runtime_data, "entities", {})
        return {s.value: entities[s] for s in NOW_SIGNALS if s in entities}
    return None


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/sources", vol.Required("device_id"): str}
)
@callback
def ws_sources(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Source entities of a Wärmewacht device for the card "Now"."""
    entities = source_entities(hass, msg["device_id"])
    if entities is None:
        connection.send_error(msg["id"], "not_found", "No Wärmewacht heat pump")
        return
    connection.send_result(msg["id"], {"entities": entities})
