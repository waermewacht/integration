"""Buttons: restart the efficiency comparison after a deliberate change;
recompute the look-back before the setup from the statistics."""

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
    buttons: list[HeatPumpEntity] = []
    if _heating(entry.runtime_data):
        buttons.append(RestartComparison(entry))
    if not entry.runtime_data.template.previous_day:
        buttons.append(RebuildHistory(entry))
    async_add_entities(buttons)


class RestartComparison(HeatPumpEntity, ButtonEntity):
    """After a new heating curve: the next 28 days become the reference of
    "Efficiency dropped" instead of the previous season."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: WaermewachtConfigEntry) -> None:
        super().__init__(entry, "restart_comparison")

    async def async_press(self) -> None:
        await self.runtime.async_restart_comparison()


class RebuildHistory(HeatPumpEntity, ButtonEntity):
    """The energy before the setup anew from the statistics: after meters
    were added under Reconfigure or an update corrected the rules."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: WaermewachtConfigEntry) -> None:
        super().__init__(entry, "rebuild_history")

    async def async_press(self) -> None:
        await self.runtime.async_rebuild_history()
