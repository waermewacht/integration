"""Action waermewacht.report: ratios of any period, with months."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service
from homeassistant.helpers.selector import ConfigEntrySelector
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .periods import Period, period_start

if TYPE_CHECKING:
    from . import WaermewachtConfigEntry

SERVICE_REPORT = "report"
ATTR_CONFIG_ENTRY = "config_entry"
ATTR_START = "start"
ATTR_END = "end"

REPORT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): ConfigEntrySelector({"integration": DOMAIN}),
        vol.Optional(ATTR_START): cv.datetime,
        vol.Optional(ATTR_END): cv.datetime,
    }
)


def _as_utc(moment: datetime) -> datetime:
    """Times without zone are local time of Home Assistant."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(moment)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""

    async def report(call: ServiceCall) -> ServiceResponse:
        entry: WaermewachtConfigEntry = service.async_get_config_entry(
            hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY]
        )
        runtime = entry.runtime_data
        now = dt_util.utcnow()
        # Default: the current season until now.
        start = (
            _as_utc(call.data[ATTR_START])
            if ATTR_START in call.data
            else period_start(
                Period.SEASON, now, runtime.tz, runtime.marks.season_month
            )
        )
        end = _as_utc(call.data[ATTR_END]) if ATTR_END in call.data else now
        if start is None or start >= end:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="start_after_end"
            )
        if "recorder" not in hass.config.components:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_recorder"
            )
        figures = await runtime.async_report(start, end)
        return {
            "start": dt_util.as_local(start).isoformat(),
            "end": dt_util.as_local(end).isoformat(),
            **figures,
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_REPORT,
        report,
        schema=REPORT_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
