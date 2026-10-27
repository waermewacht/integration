"""Binary sensor: conspicuous cycling within the last 24 hours."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WaermewachtConfigEntry
from .entity import HeatPumpEntity
from .model import Signal


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaermewachtConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if Signal.COMPRESSOR in entry.runtime_data.entities:
        async_add_entities([CyclingProblem(entry)])


class CyclingProblem(HeatPumpEntity, BinarySensorEntity):
    """On with more starts per hour than allowed or several critical runs."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry: WaermewachtConfigEntry) -> None:
        super().__init__(entry, "cycling_problem")

    @property
    def is_on(self) -> bool:
        return bool(self.runtime.cycling_problem()["problem"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self.runtime.cycling_problem()
        result.pop("problem")
        result["starts_per_hour_limit"] = self.runtime.starts_per_hour
        return result
