"""Wärmewacht: efficiency and operating behaviour of a heat pump."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .runtime import HeatPumpRuntime
from .services import async_setup_services

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]
ISSUES = (
    "missing_entity",
    "energy_unit",
    "counter_stuck",
    "source_unavailable",
    "outdoor_temp_stuck",
    "outdoor_temp_implausible",
    "flow_return_swapped",
    "activity_foreign",
    "energy_stale",
    "source_changed",
)

type WaermewachtConfigEntry = ConfigEntry[HeatPumpRuntime]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions (once, for all entries)."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: WaermewachtConfigEntry) -> bool:
    """Set up one heat pump."""
    runtime = HeatPumpRuntime(hass, entry)
    await runtime.async_start()
    entry.runtime_data = runtime

    async def _async_on_stop(event: Event) -> None:
        await runtime.async_stop()

    # Write the books when Home Assistant shuts down: a restart in the middle
    # of a run then continues it instead of counting a new start.
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_on_stop)
    )
    # Options or entities changed: reload.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Once: the past into the statistics of the energy sensors (now registered).
    entry.async_create_background_task(
        hass, runtime.async_import_history(), "waermewacht_import_history"
    )
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: WaermewachtConfigEntry
) -> None:
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: WaermewachtConfigEntry
) -> bool:
    """Unload; the runtime writes its state for the next setup."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(
    hass: HomeAssistant, entry: WaermewachtConfigEntry
) -> None:
    """Delete the stored books and the repair issues of the entry."""
    await HeatPumpRuntime(hass, entry).async_remove()
    for key in ISSUES:
        ir.async_delete_issue(hass, DOMAIN, f"{entry.entry_id}_{key}")
