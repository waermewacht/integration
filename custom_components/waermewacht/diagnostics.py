"""Diagnostics download: mapping, counter events, run and energy summary.

No personal data: the entry name is left out; entity ids, energy totals and
run counts describe the installation, not the household.

`source_entities` lists every entity of the devices behind the mapping
(platform, unique id, unit, state), so a user of another maker can send what
a new template needs. Serial numbers and entry ids are masked (anonymize.py);
device names and areas are left out.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from . import WaermewachtConfigEntry
from .anonymize import Masker
from .const import CONF_ENTITIES, CONF_TEMPLATE
from .periods import Period


def _source_entities(hass: HomeAssistant, entity_ids: set[str]) -> dict[str, Any]:
    """Devices behind the mapped entities and all their entities, masked."""
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    mask = Masker()
    entries = [e for i in sorted(entity_ids) if (e := entities.async_get(i))]
    device_ids = {e.device_id for e in entries if e.device_id}
    chosen = {e.entity_id: e for e in entries}
    for device_id in sorted(device_ids):
        for entry in er.async_entries_for_device(
            entities, device_id, include_disabled_entities=True
        ):
            chosen[entry.entity_id] = entry
    result = []
    for entity_id in sorted(chosen):
        entry = chosen[entity_id]
        state = hass.states.get(entity_id)
        attributes = state.attributes if state else {}
        result.append(
            {
                "entity_id": mask(entity_id),
                "unique_id": mask(entry.unique_id),
                "platform": entry.platform,
                "disabled_by": entry.disabled_by,
                "device_class": entry.original_device_class
                or attributes.get("device_class"),
                "unit": attributes.get("unit_of_measurement"),
                "state_class": attributes.get("state_class"),
                # Masked like ids (a number may be a serial); the fake keeps
                # the length, so the magnitude of a counter stays visible.
                "state": mask(state.state) if state else None,
            }
        )
    models = []
    for device_id in sorted(device_ids):
        if device := devices.async_get(device_id):
            models.append(
                {
                    "manufacturer": device.manufacturer,
                    "model": device.model,
                    "model_id": mask(device.model_id),
                    "sw_version": device.sw_version,
                    "hw_version": device.hw_version,
                }
            )
    return {"devices": models, "entities": result}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WaermewachtConfigEntry
) -> dict[str, Any]:
    runtime = entry.runtime_data
    now = dt_util.utcnow()
    states = {}
    for signal, entity_id in runtime.entities.items():
        state = hass.states.get(entity_id)
        states[signal.value] = (
            None
            if state is None
            else {
                "state": state.state,
                "unit": state.attributes.get("unit_of_measurement"),
                "state_class": state.attributes.get("state_class"),
            }
        )
    month = runtime.energy(Period.MONTH)
    return {
        "config": {
            "template": entry.data.get(CONF_TEMPLATE),
            "entities": entry.data.get(CONF_ENTITIES),
            "options": dict(entry.options),
        },
        "states": states,
        "since": runtime.since.isoformat() if runtime.since else None,
        "events": runtime.events,
        "tracker": runtime.tracker.as_dict(),
        "findings": {
            k: f.as_attributes() | {"problem": f.problem}
            for k, f in runtime.findings.items()
        },
        "diary_days": len(runtime.diary),
        "runs_kept": len(runtime.runs),
        "defrosts_kept": len(runtime.defrosts),
        "today": runtime.cycles("today", now).__dict__,
        "totals": runtime.totals.as_dict(),
        "month": month.as_dict() if month else None,
        "source": _source_entities(hass, set(runtime.entities.values())),
        "period_starts": {
            p.value: s.isoformat() if s else None
            for p, s in runtime.marks.starts.items()
        },
    }
