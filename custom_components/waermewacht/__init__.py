"""Wärmewacht: efficiency and operating behaviour of a heat pump."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, STATE_UNAVAILABLE, Platform
from homeassistant.core import CALLBACK_TYPE, Event, HassJob, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey

from .adopt import own_match, signals_to_adopt
from .const import (
    CONF_ENTITIES,
    CONF_KIND,
    CONF_KNOWN_SIGNALS,
    CONF_TEMPLATE,
    DOMAIN,
    KIND_GAS,
)
from .gas_runtime import GasRuntime
from .profiles import RegistryEntry, find
from .rename import renamed_data, renamed_unique_id, sources
from .runtime import HeatPumpRuntime
from .services import async_setup_services
from .templates import TEMPLATES

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]
# A gas boiler has figures only.
GAS_PLATFORMS: list[Platform] = [Platform.SENSOR]
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
    "flow_implausible",
    "flow_zero",
    "day_counter",
)

type WaermewachtConfigEntry = ConfigEntry[HeatPumpRuntime]
type GasConfigEntry = ConfigEntry[GasRuntime]

# Renames come in bursts ("recreate entity IDs" of a device): the entries
# reload once, this long after the last one.
RENAME_RELOAD_DELAY = timedelta(seconds=3)
# Entries whose sources were renamed and which wait for that reload.
RENAMED: HassKey[set[str]] = HassKey(f"{DOMAIN}_renamed")
# A reload picks up the renamed sources; a disabled or unloaded entry reads
# them at its next setup.
RELOAD_STATES = (
    ConfigEntryState.LOADED,
    ConfigEntryState.SETUP_IN_PROGRESS,
    ConfigEntryState.SETUP_RETRY,
    ConfigEntryState.SETUP_ERROR,
)


def is_gas(entry: ConfigEntry) -> bool:
    """Whether the entry is a gas boiler (gas.py), not a heat pump."""
    return entry.data.get(CONF_KIND) == KIND_GAS


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions and follow renamed sources (once, for all entries)."""
    async_setup_services(hass)
    _async_follow_renames(hass)
    return True


@callback
def _async_follow_renames(hass: HomeAssistant) -> None:
    """Follow source entities renamed in the entity registry.

    Home Assistant's own helpers listen per entry (helper_integration.py).
    One listener for all entries also sees entries that are reloading or
    failed to set up, and an id renamed again before the reload. The entry
    data changes at once; the reload follows when the burst is over.
    Removed entities are left to the repair issue "missing_entity".
    """
    waiting = hass.data.setdefault(RENAMED, set())
    cancel: CALLBACK_TYPE | None = None

    @callback
    def _reload(_now: datetime) -> None:
        nonlocal cancel
        cancel = None
        for entry_id in sorted(waiting):
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None and entry.state in RELOAD_STATES:
                hass.config_entries.async_schedule_reload(entry_id)
        waiting.clear()

    @callback
    def _is_rename(data: er.EventEntityRegistryUpdatedData) -> bool:
        return data["action"] == "update" and "old_entity_id" in data

    @callback
    def _on_rename(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        nonlocal cancel
        old: str = event.data["old_entity_id"]  # type: ignore[typeddict-item]
        new = event.data["entity_id"]
        for entry in hass.config_entries.async_entries(DOMAIN):
            used = sources(entry.data)
            if old not in used:
                continue
            if new in used:
                # Two sources would become one entity: leave it to the user.
                _LOGGER.warning(
                    "%s: %s was renamed to %s, which is already a source; "
                    "please reconfigure",
                    entry.title,
                    old,
                    new,
                )
                continue
            changes: dict[str, Any] = {"data": renamed_data(entry.data, old, new)}
            unique_id = renamed_unique_id(entry.unique_id, old, new)
            if unique_id and not hass.config_entries.async_entry_for_domain_unique_id(
                DOMAIN, unique_id
            ):
                changes["unique_id"] = unique_id
            if entry.state is ConfigEntryState.LOADED and isinstance(
                entry.runtime_data, HeatPumpRuntime
            ):
                entry.runtime_data.follow_rename(old, new)
            waiting.add(entry.entry_id)
            hass.config_entries.async_update_entry(entry, **changes)
            _LOGGER.info("%s: source %s renamed to %s", entry.title, old, new)
        if waiting:
            if cancel is not None:
                cancel()
            cancel = async_call_later(
                hass,
                RENAME_RELOAD_DELAY,
                HassJob(_reload, "waermewacht_renamed", cancel_on_shutdown=True),
            )

    hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED, _on_rename, event_filter=_is_rename
    )


async def async_setup_entry(hass: HomeAssistant, entry: WaermewachtConfigEntry) -> bool:
    """Set up one heat pump or gas boiler."""
    if is_gas(entry):
        return await _async_setup_gas(hass, entry)
    _adopt_new_signals(hass, entry)
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


async def _async_setup_gas(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    runtime = GasRuntime(hass, entry)
    entry.runtime_data = runtime
    await runtime.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, GAS_PLATFORMS)
    return True


def _adopt_new_signals(hass: HomeAssistant, entry: WaermewachtConfigEntry) -> None:
    """Take over signals the template learned since the entry was set up
    (adopt.py); before the runtime starts, so no reload is needed."""
    template = TEMPLATES.get(entry.data.get(CONF_TEMPLATE) or "")
    if template is None:
        return
    configured: dict[str, str] = dict(entry.data.get(CONF_ENTITIES) or {})
    known = entry.data.get(CONF_KNOWN_SIGNALS)
    current = sorted(s.value for s in template.signals)
    todo = signals_to_adopt(template.signals, known, configured)
    added: dict[str, str] = {}
    if todo:
        registry = er.async_get(hass)
        entries = [
            RegistryEntry(
                e.entity_id,
                e.platform,
                e.unique_id,
                e.original_name,
                usable=e.disabled_by is None
                and (state := hass.states.get(e.entity_id)) is not None
                and state.state != STATE_UNAVAILABLE,
            )
            for e in registry.entities.values()
            if e.platform == template.platform
        ]
        match = own_match(find(template, entries), configured)
        if match is not None:
            added = {s.value: match.entities[s] for s in todo if s in match.entities}
    if not added and known == current:
        return
    if added:
        _LOGGER.info("Taking over new signals of %s: %s", template.label, added)
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_ENTITIES: {**configured, **added},
            CONF_KNOWN_SIGNALS: current,
        },
    )


async def _async_update_listener(
    hass: HomeAssistant, entry: WaermewachtConfigEntry
) -> None:
    if entry.entry_id in hass.data.get(RENAMED, ()):
        return  # renamed sources: the reload follows the burst
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: WaermewachtConfigEntry
) -> bool:
    """Unload; the runtime writes its state for the next setup."""
    platforms = GAS_PLATFORMS if is_gas(entry) else PLATFORMS
    unloaded = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(
    hass: HomeAssistant, entry: WaermewachtConfigEntry
) -> None:
    """Delete the stored books and the repair issues of the entry."""
    if is_gas(entry):
        return  # nothing stored, no repair issues
    await HeatPumpRuntime(hass, entry).async_remove()
    for key in ISSUES:
        ir.async_delete_issue(hass, DOMAIN, f"{entry.entry_id}_{key}")
