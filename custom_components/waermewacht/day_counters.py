"""Find counters of the wrong kind among the energy entities, from the
long-term statistics: day counters where lifetime counters are booked, and
lifetime counters where a template books day values.

Used by the config flow (a warning, a second submit keeps the counters) and
once a day by the runtime (repair issue for entries made before the check).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .counter import looks_like_day_counter, looks_like_lifetime_counter
from .profiles import Template

_LOGGER = logging.getLogger(__name__)

# Hours of statistics the test looks at.
WINDOW = timedelta(days=4)

# The wrong kind, also the key of the config flow error and the repair issue.
DAY_COUNTER = "day_counter"
LIFETIME_COUNTER = "lifetime_counter"


def wrong_kind(template: Template | None) -> str | None:
    """The kind of counter that would be booked wrongly in this entry.

    Templates with hourly statistics book from the statistics, which take
    either kind; own mappings (no template) book lifetime counters.
    """
    if template is None:
        return DAY_COUNTER
    if template.hourly_statistics:
        return None
    return LIFETIME_COUNTER if template.day_values else DAY_COUNTER


async def async_wrong_counters(
    hass: HomeAssistant,
    entity_ids: list[str],
    kind: str,
    *,
    previous_day: bool = False,
) -> list[str]:
    """The entities whose statistics of the last days look like `kind`.

    A failed query finds nothing: the check must never block a setup.
    """
    if not entity_ids or "recorder" not in hass.config.components:
        return []
    end = dt_util.utcnow()
    try:
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
    except Exception:
        _LOGGER.exception("Reading statistics to check the counters failed")
        return []
    tz = dt_util.get_default_time_zone()

    def matches(series: list[tuple[datetime, float]]) -> bool:
        if kind == LIFETIME_COUNTER:
            return looks_like_lifetime_counter(series, tz, previous_day=previous_day)
        return looks_like_day_counter(series, tz)

    return [
        entity_id
        for entity_id in entity_ids
        if matches(
            [
                (_start(r["start"]), r["state"])
                for r in rows.get(entity_id, [])
                if r.get("state") is not None
            ]
        )
    ]


def _start(value: datetime | float) -> datetime:
    """Statistics rows carry the hour start as a timestamp (or datetime)."""
    return value if isinstance(value, datetime) else dt_util.utc_from_timestamp(value)
