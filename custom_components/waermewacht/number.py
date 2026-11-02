"""Gas boiler with readings by hand: the meter reading as a number entity.

Typing a value adds a reading at the current time (readings.py); its state
is the last reading. Older readings (e.g. from bills) go in with the action
add_gas_reading, which takes a time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import VOLUME_UNIT
from .entity import HeatPumpEntity

if TYPE_CHECKING:
    from . import GasConfigEntry
    from .gas_runtime import GasRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if getattr(entry.runtime_data, "manual", False):
        async_add_entities([GasReadingNumber(entry)])


class GasReadingNumber(HeatPumpEntity, NumberEntity):
    """Enter the gas meter reading."""

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.0
    _attr_native_max_value = 99_999_999.0
    _attr_native_step = 0.001

    runtime: GasRuntime  # type: ignore[assignment]

    def __init__(self, entry: GasConfigEntry) -> None:
        super().__init__(entry, "gas_reading")  # type: ignore[arg-type]
        unit = self.runtime.manual_unit
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = (
            NumberDeviceClass.GAS if unit == VOLUME_UNIT else NumberDeviceClass.ENERGY
        )

    @property
    def native_value(self) -> float | None:
        readings = self.runtime.readings
        return readings[-1].value if readings else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        readings = self.runtime.readings
        return {
            "last_reading": (
                dt_util.as_local(readings[-1].at).isoformat() if readings else None
            ),
            "readings": len(readings),
        }

    async def async_set_native_value(self, value: float) -> None:
        await self.runtime.async_add_reading(dt_util.utcnow(), value)
