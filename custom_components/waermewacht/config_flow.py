"""Config flow: name and source, then the entities per mode (prefilled).

A template (EMS-ESP) finds the heat pump in the entity registry by platform
and unique id and fills in the entities; everything stays editable. Without
a template, the user picks the entities. Reconfiguring shows the entity step
again; the options hold the thresholds. Every change reloads the entry.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_CRITICAL_RUN,
    CONF_ENTITIES,
    CONF_HISTORY,
    CONF_MIN_ELECTRICITY,
    CONF_NAME,
    CONF_SEASON_START,
    CONF_SHORT_RUN,
    CONF_SOURCE,
    CONF_STARTS_PER_HOUR,
    CONF_TEMPLATE,
    DEFAULT_CRITICAL_RUN_MINUTES,
    DEFAULT_MIN_ELECTRICITY_KWH,
    DEFAULT_SEASON_START_MONTH,
    DEFAULT_SHORT_RUN_MINUTES,
    DEFAULT_STARTS_PER_HOUR,
    DOMAIN,
    SOURCE_MANUAL,
)
from .counter import UNIT_FACTORS
from .model import AUX_SIGNALS, ELEC_SIGNALS, ENERGY_SIGNALS, HEAT_SIGNALS, Signal
from .profiles import TEMPLATES, Match, RegistryEntry, find

# Form sections and the signals in them.
SECTIONS: dict[str, tuple[Signal, ...]] = {
    "heating": (Signal.HEAT_HEATING, Signal.ELEC_HEATING, Signal.AUX_HEATING),
    "dhw": (Signal.HEAT_DHW, Signal.ELEC_DHW, Signal.AUX_DHW),
    "cooling": (Signal.HEAT_COOLING, Signal.ELEC_COOLING),
    "operation": (
        Signal.COMPRESSOR,
        Signal.ACTIVITY,
        Signal.STARTS_TOTAL,
        Signal.AUX_TOTAL,
    ),
    "measurements": (
        Signal.OUTDOOR_TEMP,
        Signal.FLOW_TEMP,
        Signal.RETURN_TEMP,
        Signal.FLOW_RATE,
    ),
}
FORM_SIGNALS = tuple(s for signals in SECTIONS.values() for s in signals)


def _selector(signal: Signal) -> selector.EntitySelector:
    if signal in ENERGY_SIGNALS:
        filters = selector.EntityFilterSelectorConfig(
            domain="sensor",
            device_class="energy",
            unit_of_measurement=list(UNIT_FACTORS),
        )
    elif signal is Signal.COMPRESSOR:
        filters = selector.EntityFilterSelectorConfig(domain="binary_sensor")
    elif signal in (Signal.OUTDOOR_TEMP, Signal.FLOW_TEMP, Signal.RETURN_TEMP):
        filters = selector.EntityFilterSelectorConfig(
            domain="sensor", device_class="temperature"
        )
    elif signal is Signal.FLOW_RATE:
        filters = selector.EntityFilterSelectorConfig(
            domain="sensor", device_class="volume_flow_rate"
        )
    else:
        filters = selector.EntityFilterSelectorConfig(domain="sensor")
    return selector.EntitySelector(selector.EntitySelectorConfig(filter=filters))


def entities_schema(values: dict[str, str]) -> vol.Schema:
    """The entity form, one section per mode; `values` prefill it."""
    return vol.Schema(
        {
            vol.Required(name): section(
                vol.Schema(
                    {
                        vol.Optional(
                            signal.value,
                            description={"suggested_value": values.get(signal.value)},
                        ): _selector(signal)
                        for signal in signals
                    }
                ),
                {
                    "collapsed": name in ("cooling", "measurements")
                    and not any(values.get(s.value) for s in signals)
                },
            )
            for name, signals in SECTIONS.items()
        }
    )


def flatten(user_input: dict[str, Any]) -> dict[str, str]:
    """Section values -> {signal: entity_id} without empty fields."""
    return {
        key: value
        for name in SECTIONS
        for key, value in (user_input.get(name) or {}).items()
        if value
    }


def validate(hass: HomeAssistant, entities: dict[str, str]) -> str | None:
    """Error key, or None if the mapping can be used."""
    complete = any(
        HEAT_SIGNALS[m].value in entities and ELEC_SIGNALS[m].value in entities
        for m in HEAT_SIGNALS
    )
    if not complete:
        return "no_mode"
    if Signal.AUX_TOTAL.value in entities and any(
        s.value in entities for s in AUX_SIGNALS.values()
    ):
        return "aux_twice"  # the backup heater would be booked twice
    for signal in ENERGY_SIGNALS:
        if (entity_id := entities.get(signal.value)) is None:
            continue
        state = hass.states.get(entity_id)
        if (
            state is not None
            and state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) not in UNIT_FACTORS
        ):
            return "energy_unit"
    return None


def detect(hass: HomeAssistant) -> list[Match]:
    """Heat pumps the templates find among entities that report a state."""
    registry = er.async_get(hass)
    entries = [
        RegistryEntry(e.entity_id, e.platform, e.unique_id)
        for e in registry.entities.values()
        if e.disabled_by is None
        and (state := hass.states.get(e.entity_id)) is not None
        and state.state != STATE_UNAVAILABLE
    ]
    return [m for template in TEMPLATES.values() for m in find(template, entries)]


def _source_key(match: Match) -> str:
    return f"{match.template.key}:{match.prefix}"


class WaermewachtConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one heat pump."""

    VERSION = 1

    def __init__(self) -> None:
        self._name = ""
        self._template: str | None = None
        self._unique_id: str | None = None
        self._prefill: dict[str, str] = {}
        # Entity -> other entities of the same counter (backfill only).
        self._history: dict[str, list[str]] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return WaermewachtOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        matches = {_source_key(m): m for m in detect(self.hass)}
        if user_input is not None:
            self._name = user_input[CONF_NAME]
            source = user_input[CONF_SOURCE]
            if (match := matches.get(source)) is not None:
                self._template = match.template.key
                self._unique_id = source
                self._prefill = {
                    s.value: e for s, e in match.entities.items() if s in FORM_SIGNALS
                }
                self._history = {
                    match.entities[s]: aliases for s, aliases in match.history.items()
                }
            return await self.async_step_entities()

        options: list[selector.SelectOptionDict] = [
            selector.SelectOptionDict(
                value=key,
                label=f"EMS-ESP ({m.prefix})" if m.prefix else "EMS-ESP",
            )
            for key, m in matches.items()
        ]
        options.append(
            selector.SelectOptionDict(value=SOURCE_MANUAL, label=SOURCE_MANUAL)
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Wärmepumpe"): str,
                vol.Required(
                    CONF_SOURCE, default=options[0]["value"]
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        translation_key="source",
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            description_placeholders={"found": str(len(matches))},
        )

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        values = self._prefill
        if user_input is not None:
            values = flatten(user_input)
            if (error := validate(self.hass, values)) is None:
                return await self._async_finish(values)
            errors["base"] = error
        return self.async_show_form(
            step_id="entities", data_schema=entities_schema(values), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        self._prefill = dict(entry.data[CONF_ENTITIES])
        return await self.async_step_entities()

    async def _async_finish(self, entities: dict[str, str]) -> ConfigFlowResult:
        if self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            # The update listener reloads the entry.
            return self.async_update_and_abort(
                entry, data={**entry.data, CONF_ENTITIES: entities}
            )
        unique_id = self._unique_id or next(
            entities[s.value] for s in HEAT_SIGNALS.values() if s.value in entities
        )
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=self._name,
            data={
                CONF_NAME: self._name,
                CONF_TEMPLATE: self._template,
                CONF_ENTITIES: entities,
                CONF_HISTORY: {
                    entity: aliases
                    for entity, aliases in self._history.items()
                    if entity in entities.values()
                },
            },
        )


class WaermewachtOptionsFlow(OptionsFlow):
    """Thresholds and season start."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options

        def number(
            minimum: float, maximum: float, step: float, unit: str
        ) -> selector.NumberSelector:
            return selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=minimum,
                    max=maximum,
                    step=step,
                    unit_of_measurement=unit,
                    mode=selector.NumberSelectorMode.BOX,
                )
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MIN_ELECTRICITY,
                    default=options.get(
                        CONF_MIN_ELECTRICITY, DEFAULT_MIN_ELECTRICITY_KWH
                    ),
                ): number(0, 10, 0.1, "kWh"),
                vol.Required(
                    CONF_SHORT_RUN,
                    default=options.get(CONF_SHORT_RUN, DEFAULT_SHORT_RUN_MINUTES),
                ): number(1, 60, 1, "min"),
                vol.Required(
                    CONF_CRITICAL_RUN,
                    default=options.get(
                        CONF_CRITICAL_RUN, DEFAULT_CRITICAL_RUN_MINUTES
                    ),
                ): number(1, 60, 1, "min"),
                vol.Required(
                    CONF_STARTS_PER_HOUR,
                    default=options.get(CONF_STARTS_PER_HOUR, DEFAULT_STARTS_PER_HOUR),
                ): number(1, 12, 1, "/h"),
                vol.Required(
                    CONF_SEASON_START,
                    default=str(
                        options.get(CONF_SEASON_START, DEFAULT_SEASON_START_MONTH)
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[str(m) for m in range(1, 13)],
                        translation_key="month",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
