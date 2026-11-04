"""Base entity: one device per heat pump (config entry), updated by the runtime."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, VERSION

if TYPE_CHECKING:
    from . import WaermewachtConfigEntry
    from .runtime import HeatPumpRuntime


def own_entities(hass: HomeAssistant, entity_ids: Iterable[str]) -> list[str]:
    """Those of Wärmewacht itself: an entry reading one would read its own
    results (seen 2026-11: standby electricity mapped to the entry's own
    standby sensor). The forms refuse them; older entries ignore them."""
    registry = er.async_get(hass)
    return sorted(
        entity_id
        for entity_id in set(entity_ids)
        if (entry := registry.async_get(entity_id)) is not None
        and entry.platform == DOMAIN
    )


class HeatPumpEntity(Entity):
    """An entity of the Wärmewacht device of one heat pump."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: WaermewachtConfigEntry, key: str) -> None:
        self.runtime: HeatPumpRuntime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Wärmewacht",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.runtime.add_listener(self.async_write_ha_state))
