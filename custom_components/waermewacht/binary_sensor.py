"""Binary sensors (problem): conspicuous cycling and the health check.

The health check's findings come from the daily analysis (health.py,
docs/GESUNDHEITSCHECK.md): unknown with a `reason` until there are enough
data; the evidence is in the attributes, long lists not recorded.
"""

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
from .model import AUX_SIGNALS, HEAT_SIGNALS, Mode, Signal, has_elec
from .runtime import HeatPumpRuntime


def _heating(runtime: HeatPumpRuntime) -> bool:
    return (
        HEAT_SIGNALS[Mode.HEATING] in runtime.entities
        and has_elec(runtime.entities, Mode.HEATING)
        and Signal.OUTDOOR_TEMP in runtime.entities
    )


def _aux(runtime: HeatPumpRuntime) -> bool:
    return any(s in runtime.entities for s in (*AUX_SIGNALS.values(), Signal.AUX_TOTAL))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaermewachtConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    if Signal.COMPRESSOR in runtime.entities:
        entities.append(CyclingProblem(entry))
    if _heating(runtime):
        entities.append(HealthProblem(entry, "efficiency_drop"))
        if _aux(runtime):
            entities.append(HealthProblem(entry, "aux_mild_weather"))
    # Normal and disinfection charges need the storage temperature.
    if runtime.has_charges and Signal.DHW_TEMP in runtime.entities:
        entities.append(HealthProblem(entry, "dhw_efficiency_drop"))
        if any(s in runtime.entities for s in (Signal.AUX_DHW, Signal.AUX_TOTAL)):
            entities.append(HealthProblem(entry, "aux_dhw_charges"))
    async_add_entities(entities)


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


class HealthProblem(HeatPumpEntity, BinarySensorEntity):
    """A finding of the daily health check."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    # Lists per class or day: shown, not recorded (write load).
    _unrecorded_attributes = frozenset({"classes", "days"})

    def __init__(self, entry: WaermewachtConfigEntry, key: str) -> None:
        super().__init__(entry, key)
        self._key = key

    @property
    def is_on(self) -> bool | None:
        return self.runtime.findings[self._key].problem

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.runtime.findings[self._key].as_attributes()
