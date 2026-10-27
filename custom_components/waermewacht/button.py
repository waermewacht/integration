"""Button: restart the efficiency comparison after a deliberate change."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WaermewachtConfigEntry
from .binary_sensor import _heating
from .entity import HeatPumpEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaermewachtConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if _heating(entry.runtime_data):
        async_add_entities([RestartComparison(entry)])


class RestartComparison(HeatPumpEntity, ButtonEntity):
    """After a new heating curve: the next 28 days become the reference of
    "Efficiency dropped" instead of the previous season."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: WaermewachtConfigEntry) -> None:
        super().__init__(entry, "restart_comparison")

    async def async_press(self) -> None:
        await self.runtime.async_restart_comparison()
