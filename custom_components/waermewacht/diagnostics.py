"""Diagnostics download: mapping, counter events, run and energy summary.

No personal data: the entry name is left out; entity ids, energy totals and
run counts describe the installation, not the household.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import WaermewachtConfigEntry
from .const import CONF_ENTITIES, CONF_TEMPLATE
from .periods import Period


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
        "period_starts": {
            p.value: s.isoformat() if s else None
            for p, s in runtime.marks.starts.items()
        },
    }
