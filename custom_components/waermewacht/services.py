"""Actions: report (ratios of any period, with months), performance curve
(ratio over outdoor temperature) and heat load (energy signature)."""

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
from .curve import curve_as_dicts, performance_curve
from .heat_load import heat_load, heat_load_as_dict
from .model import Signal
from .periods import Period, period_start

if TYPE_CHECKING:
    from . import WaermewachtConfigEntry

SERVICE_REPORT = "report"
SERVICE_CURVE = "performance_curve"
SERVICE_HEAT_LOAD = "heat_load"
ATTR_CONFIG_ENTRY = "config_entry"
ATTR_START = "start"
ATTR_END = "end"
ATTR_SCOPE = "scope"
ATTR_DESIGN_TEMP = "design_outdoor_temp"
# Scope of the curve as offered -> scope of curve.py.
CURVE_SCOPES = {"heating": "heating", "heating_dhw": "combined"}

REPORT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): ConfigEntrySelector({"integration": DOMAIN}),
        vol.Optional(ATTR_START): cv.datetime,
        vol.Optional(ATTR_END): cv.datetime,
    }
)


CURVE_SCHEMA = REPORT_SCHEMA.extend(
    {vol.Optional(ATTR_SCOPE, default="heating"): vol.In(list(CURVE_SCOPES))}
)
HEAT_LOAD_SCHEMA = REPORT_SCHEMA.extend(
    {vol.Optional(ATTR_DESIGN_TEMP): vol.Coerce(float)}
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

    def _analysis_window(
        call: ServiceCall, default_previous: bool
    ) -> tuple[WaermewachtConfigEntry, datetime, datetime]:
        entry: WaermewachtConfigEntry = service.async_get_config_entry(
            hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY]
        )
        runtime = entry.runtime_data
        if Signal.OUTDOOR_TEMP not in runtime.entities:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_outdoor"
            )
        if "recorder" not in hass.config.components:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_recorder"
            )
        now = dt_util.utcnow()
        current, previous = runtime.seasons(now)
        # Default: the current season, or the last complete one (heat load).
        start = (
            _as_utc(call.data[ATTR_START])
            if ATTR_START in call.data
            else previous
            if default_previous
            else current
        )
        default_end = (
            current if default_previous and ATTR_START not in call.data else now
        )
        end = _as_utc(call.data[ATTR_END]) if ATTR_END in call.data else default_end
        if start >= end:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="start_after_end"
            )
        return entry, start, end

    async def curve(call: ServiceCall) -> ServiceResponse:
        entry, start, end = _analysis_window(call, default_previous=False)
        runtime = entry.runtime_data
        hours, outdoor = await runtime.async_analysis_data(start, end)
        rows = performance_curve(
            hours,
            outdoor,
            runtime.tz,
            CURVE_SCOPES[call.data[ATTR_SCOPE]],
            min_electricity=runtime.min_electricity,
        )
        return {
            "start": dt_util.as_local(start).isoformat(),
            "end": dt_util.as_local(end).isoformat(),
            "scope": call.data[ATTR_SCOPE],
            "classes": curve_as_dicts(rows),
        }

    async def load(call: ServiceCall) -> ServiceResponse:
        entry, start, end = _analysis_window(call, default_previous=True)
        runtime = entry.runtime_data
        hours, outdoor = await runtime.async_analysis_data(start, end)
        result = heat_load(
            hours,
            outdoor,
            runtime.tz,
            design_temp=call.data.get(ATTR_DESIGN_TEMP, runtime.design_temp),
        )
        return {
            "start": dt_util.as_local(start).isoformat(),
            "end": dt_util.as_local(end).isoformat(),
            **heat_load_as_dict(result),
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_CURVE,
        curve,
        schema=CURVE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_HEAT_LOAD,
        load,
        schema=HEAT_LOAD_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
