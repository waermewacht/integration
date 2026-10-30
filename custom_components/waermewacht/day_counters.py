"""Find day counters among the energy entities, from the long-term statistics.

Used by the config flow (refuse such a mapping) and the daily analysis
(repair issue for entries made before the check).
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .counter import looks_like_day_counter
from .profiles import Template

# Hours of statistics the test looks at.
WINDOW = timedelta(days=4)


def counts_by_state(template: Template | None) -> bool:
    """True if the entry books its energy counters as lifetime counters.

    Templates with day values give every counter `day_tz`; templates with
    hourly statistics book from the statistics, which handle resets.
    """
    return template is None or not (template.day_values or template.hourly_statistics)


async def async_day_counters(hass: HomeAssistant, entity_ids: list[str]) -> list[str]:
    """The entities whose statistics restarted like a day counter lately."""
    if not entity_ids or "recorder" not in hass.config.components:
        return []
    end = dt_util.utcnow()
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        end - WINDOW,
        end,
        set(entity_ids),
        "hour",
        {"energy": "kWh"},
        {"state"},
    )
    return [
        entity_id
        for entity_id in entity_ids
        if looks_like_day_counter(
            [r["state"] for r in rows.get(entity_id, []) if r.get("state") is not None]
        )
    ]
