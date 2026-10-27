"""Base entity: one device per heat pump (config entry), updated by the runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, VERSION

if TYPE_CHECKING:
    from . import WaermewachtConfigEntry
    from .runtime import HeatPumpRuntime


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
