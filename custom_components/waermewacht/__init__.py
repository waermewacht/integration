"""Wärmewacht: efficiency and operating behaviour of a heat pump."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant

from .runtime import HeatPumpRuntime

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

type WaermewachtConfigEntry = ConfigEntry[HeatPumpRuntime]


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
    """Delete the stored books."""
    await HeatPumpRuntime(hass, entry).async_remove()
