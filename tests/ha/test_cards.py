"""The cards: the websocket command hands the card "Now" the source entities."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import ACTIVITY, COMPRESSOR, FLOW, RETURN
from .test_init import setup


async def test_sources_for_the_card_now(hass: HomeAssistant, hass_ws_client) -> None:
    assert await async_setup_component(hass, "websocket_api", {})
    entry: MockConfigEntry = await setup(hass)
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "waermewacht/sources", "device_id": device.id}
    )
    reply = await client.receive_json()
    assert reply["success"]
    assert reply["result"]["entities"] == {
        "activity": ACTIVITY,
        "compressor": COMPRESSOR,
        "flow_temp": FLOW,
        "return_temp": RETURN,
    }
    await client.send_json(
        {"id": 2, "type": "waermewacht/sources", "device_id": "nope"}
    )
    reply = await client.receive_json()
    assert not reply["success"]
    assert reply["error"]["code"] == "not_found"


async def test_card_file_is_served(hass: HomeAssistant, hass_client) -> None:
    """The integration serves its card file itself (no Lovelace resource)."""
    assert await async_setup_component(hass, "http", {})
    await setup(hass)
    client = await hass_client()
    response = await client.get("/waermewacht/waermewacht-card.js")
    assert response.status == 200
    assert "waermewacht-card-editor" in await response.text()
