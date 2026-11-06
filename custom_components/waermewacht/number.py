"""Gas boiler with readings by hand: the meter reading as a number entity.

Typing a value adds a reading at the current time (readings.py); its state
is the last reading. Older readings (e.g. from bills) go in with the action
add_gas_reading, which takes a time. A tank level (oil) has a second
number for the litres of a refill (action add_oil_refill with a time).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import LITRE_UNIT, VOLUME_UNIT
from .entity import HeatPumpEntity

if TYPE_CHECKING:
    from . import GasConfigEntry
    from .gas_runtime import GasRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    if getattr(runtime, "manual", False):
        async_add_entities(
            [GasReadingNumber(entry)]
            + ([OilRefillNumber(entry)] if getattr(runtime, "tank", False) else [])
        )


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
        if self.runtime.tank:
            self._attr_translation_key = "tank_level"
            self._attr_native_unit_of_measurement = LITRE_UNIT
            self._attr_device_class = NumberDeviceClass.VOLUME_STORAGE
            self._attr_native_step = 1.0
        elif unit == LITRE_UNIT:
            self._attr_native_unit_of_measurement = unit
            self._attr_device_class = NumberDeviceClass.VOLUME
        else:
            self._attr_native_unit_of_measurement = unit
            self._attr_device_class = (
                NumberDeviceClass.GAS
                if unit == VOLUME_UNIT
                else NumberDeviceClass.ENERGY
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


class OilRefillNumber(HeatPumpEntity, NumberEntity):
    """Enter the litres of a refill of the tank (now)."""

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100_000.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = LITRE_UNIT
    _attr_device_class = NumberDeviceClass.VOLUME

    runtime: GasRuntime  # type: ignore[assignment]

    def __init__(self, entry: GasConfigEntry) -> None:
        super().__init__(entry, "oil_refill")  # type: ignore[arg-type]

    @property
    def native_value(self) -> float | None:
        refills = self.runtime.refills
        return refills[-1].value if refills else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        refills = self.runtime.refills
        return {
            "last_refill": (
                dt_util.as_local(refills[-1].at).isoformat() if refills else None
            ),
            "refills": len(refills),
        }

    async def async_set_native_value(self, value: float) -> None:
        await self.runtime.async_add_refill(dt_util.utcnow(), value)
