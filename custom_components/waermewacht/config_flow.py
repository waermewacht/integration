"""Config flow: name and source, then the entities per mode (prefilled).

A template (EMS-ESP, Bosch HomeCom and, marked beta, further makers) finds the heat pump in the entity registry by platform
and unique id and fills in the entities; everything stays editable. Without
a template, the user picks the entities. Reconfiguring shows the entity step
again; the options hold the thresholds. Every change reloads the entry.

"Gas boiler" in the first step leads to an entry of its own kind (gas.py):
a gas counter (kWh or m³), optionally hot water apart, and the outdoor
temperature; its options are the boiler efficiency, the conversion of m³
and the prices.
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

from .charges import DISINFECTION_TEMP_C
from .const import (
    CONF_AUX_MILD_FROM,
    CONF_BOILER_EFFICIENCY,
    CONF_CALORIFIC_VALUE,
    CONF_CRITICAL_RUN,
    CONF_DESIGN_TEMP,
    CONF_DISINFECTION_TEMP,
    CONF_EFFICIENCY_DROP,
    CONF_ELECTRICITY_BASE_PRICE,
    CONF_ELECTRICITY_PRICE,
    CONF_ENTITIES,
    CONF_GAS_BASE_PRICE,
    CONF_GAS_PRICE,
    CONF_HISTORY,
    CONF_KIND,
    CONF_KNOWN_SIGNALS,
    CONF_MIN_ELECTRICITY,
    CONF_MIN_POWER,
    CONF_NAME,
    CONF_RATED_POWER,
    CONF_SEASON_START,
    CONF_SHORT_RUN,
    CONF_SOURCE,
    CONF_STARTS_PER_HOUR,
    CONF_TEMPLATE,
    CONF_Z_NUMBER,
    DEFAULT_CRITICAL_RUN_MINUTES,
    DEFAULT_MIN_ELECTRICITY_KWH,
    DEFAULT_SEASON_START_MONTH,
    DEFAULT_SHORT_RUN_MINUTES,
    DEFAULT_STARTS_PER_HOUR,
    DOMAIN,
    GAS_DHW,
    GAS_HEATING,
    GAS_TOTAL,
    KIND_GAS,
    SOURCE_GAS,
    SOURCE_MANUAL,
    VOLUME_UNIT,
)
from .costs import BOILER_EFFICIENCY_HS
from .counter import UNIT_FACTORS
from .health import DROP_PERCENT, MILD_FROM
from .health_extra import LPH_FACTORS
from .model import (
    AUX_SIGNALS,
    ELEC_SIGNALS,
    ENERGY_SIGNALS,
    HEAT_SIGNALS,
    Signal,
    has_elec,
)
from .profiles import Match, RegistryEntry, drop_foreign_activity, find
from .templates import TEMPLATES

# Form sections and the signals in them.
SECTIONS: dict[str, tuple[Signal, ...]] = {
    "heating": (Signal.HEAT_HEATING, Signal.ELEC_HEATING, Signal.AUX_HEATING),
    "dhw": (Signal.HEAT_DHW, Signal.ELEC_DHW, Signal.AUX_DHW, Signal.DHW_TEMP),
    "cooling": (Signal.HEAT_COOLING, Signal.ELEC_COOLING),
    "operation": (
        Signal.COMPRESSOR,
        Signal.ACTIVITY,
        Signal.STARTS_TOTAL,
        Signal.ELEC_TOTAL,
        Signal.AUX_TOTAL,
        Signal.ELEC_DEFROST,
        Signal.ELEC_STANDBY,
    ),
    # Activity from several entities (activity.py), collapsed when unused.
    "activity_parts": (
        Signal.DEFROST_FLAG,
        Signal.DHW_FLAG,
        Signal.COOLING_FLAG,
        Signal.HEATING_FLAG,
        Signal.COOLING_MODE,
    ),
    "measurements": (
        Signal.OUTDOOR_TEMP,
        Signal.FLOW_TEMP,
        Signal.RETURN_TEMP,
        Signal.FLOW_RATE,
    ),
}
FORM_SIGNALS = tuple(s for signals in SECTIONS.values() for s in signals)


# Flow units in Home Assistant's spelling and in lower case.
FLOW_UNITS = sorted({*LPH_FACTORS, "L/h", "L/min", "L/s", "mL/s"})


def _selector(signal: Signal) -> selector.EntitySelector:
    if signal in ENERGY_SIGNALS:
        filters = selector.EntityFilterSelectorConfig(
            domain="sensor",
            device_class="energy",
            unit_of_measurement=list(UNIT_FACTORS),
        )
    elif signal in (
        Signal.DEFROST_FLAG,
        Signal.DHW_FLAG,
        Signal.COOLING_FLAG,
        Signal.HEATING_FLAG,
    ):
        filters = selector.EntityFilterSelectorConfig(
            domain=["binary_sensor", "switch"]
        )
    elif signal is Signal.COOLING_MODE:
        filters = selector.EntityFilterSelectorConfig(domain=["select", "sensor"])
    elif signal is Signal.COMPRESSOR:
        # On/off, or a speed or modulation in % (Bosch HomeCom).
        filters = selector.EntityFilterSelectorConfig(
            domain=["binary_sensor", "sensor"]
        )
    elif signal in (
        Signal.OUTDOOR_TEMP,
        Signal.FLOW_TEMP,
        Signal.RETURN_TEMP,
        Signal.DHW_TEMP,
    ):
        filters = selector.EntityFilterSelectorConfig(
            domain="sensor", device_class="temperature"
        )
    elif signal is Signal.FLOW_RATE:
        # Many integrations give a flow in L/min without a device class
        # (P1P2MQTT): either one, as long as Wärmewacht knows the unit.
        return selector.EntitySelector(
            selector.EntitySelectorConfig(
                filter=[
                    selector.EntityFilterSelectorConfig(
                        domain="sensor", device_class="volume_flow_rate"
                    ),
                    selector.EntityFilterSelectorConfig(
                        domain="sensor", unit_of_measurement=FLOW_UNITS
                    ),
                ]
            )
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
                    "collapsed": name in ("cooling", "measurements", "activity_parts")
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
    signals = {Signal(key) for key in entities}
    complete = any(
        HEAT_SIGNALS[m] in signals and has_elec(signals, m) for m in HEAT_SIGNALS
    )
    # Without a complete mode: cycling (and electricity) only, which needs
    # the compressor.
    if not complete and Signal.COMPRESSOR.value not in entities:
        return "no_mode"
    if Signal.AUX_TOTAL.value in entities and any(
        s.value in entities for s in AUX_SIGNALS.values()
    ):
        return "aux_twice"  # the backup heater would be booked twice
    if Signal.ELEC_TOTAL.value in entities and any(
        s.value in entities for s in ELEC_SIGNALS.values()
    ):
        return "elec_twice"
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
    ]

    def state_of(entity_id: str) -> str | None:
        return state.state if (state := hass.states.get(entity_id)) else None

    return [
        drop_foreign_activity(m, state_of)
        for template in TEMPLATES.values()
        for m in find(template, entries)
    ]


def disabled_entities(hass: HomeAssistant) -> list[str]:
    """Disabled entities a template would use (bosch_homecom disables the
    energy per mode by default)."""
    registry = er.async_get(hass)
    entries = [
        RegistryEntry(e.entity_id, e.platform, e.unique_id, e.original_name)
        for e in registry.entities.values()
    ]
    disabled = {
        e.entity_id for e in registry.entities.values() if e.disabled_by is not None
    }
    return sorted(
        entity_id
        for template in TEMPLATES.values()
        for match in find(template, entries)
        for signal, entity_id in match.entities.items()
        if entity_id in disabled and signal in FORM_SIGNALS
    )


# Gas boiler: counters in an energy unit or in m³, with statistics.
GAS_UNITS = [*UNIT_FACTORS, VOLUME_UNIT]
GAS_COUNTERS = (GAS_TOTAL, GAS_HEATING, GAS_DHW)
STATISTIC_CLASSES = ("total", "total_increasing")


def _number(
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


def gas_schema(values: dict[str, Any]) -> vol.Schema:
    """The gas form; `values` prefill it."""
    counter = selector.EntitySelector(
        selector.EntitySelectorConfig(
            filter=[
                selector.EntityFilterSelectorConfig(
                    domain="sensor",
                    device_class=device_class,
                    unit_of_measurement=GAS_UNITS,
                )
                for device_class in ("gas", "energy")
            ]
        )
    )
    outdoor = selector.EntitySelector(
        selector.EntitySelectorConfig(
            filter=selector.EntityFilterSelectorConfig(
                domain="sensor", device_class="temperature"
            )
        )
    )

    def suggested(key: str) -> dict[str, Any]:
        return {"suggested_value": values.get(key)}

    return vol.Schema(
        {
            **{
                vol.Optional(key, description=suggested(key)): counter
                for key in GAS_COUNTERS
            },
            vol.Required(
                Signal.OUTDOOR_TEMP.value,
                description=suggested(Signal.OUTDOOR_TEMP.value),
            ): outdoor,
            vol.Optional(
                CONF_CALORIFIC_VALUE, description=suggested(CONF_CALORIFIC_VALUE)
            ): _number(8, 13, 0.001, "kWh/m³"),
            vol.Optional(CONF_Z_NUMBER, description=suggested(CONF_Z_NUMBER)): _number(
                0.8, 1.1, 0.0001, ""
            ),
        }
    )


def validate_gas(hass: HomeAssistant, values: dict[str, Any]) -> str | None:
    """Error key, or None if the gas mapping can be used."""
    if GAS_TOTAL in values and GAS_HEATING in values:
        return "gas_twice"
    if GAS_TOTAL not in values and GAS_HEATING not in values:
        return "gas_none"
    volume = False
    for key in GAS_COUNTERS:
        if (entity_id := values.get(key)) is None:
            continue
        if (state := hass.states.get(entity_id)) is None:
            continue
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if unit not in GAS_UNITS:
            return "gas_unit"
        if state.attributes.get("state_class") not in STATISTIC_CLASSES:
            return "gas_no_statistics"
        volume |= unit == VOLUME_UNIT
    if volume and not (values.get(CONF_CALORIFIC_VALUE) and values.get(CONF_Z_NUMBER)):
        return "gas_calorific_value"
    return None


def split_gas(values: dict[str, Any]) -> tuple[dict[str, str], dict[str, float]]:
    """Form values -> entities and options (conversion of m³)."""
    keys = (*GAS_COUNTERS, Signal.OUTDOOR_TEMP.value)
    entities = {k: values[k] for k in keys if values.get(k)}
    options = {
        k: values[k] for k in (CONF_CALORIFIC_VALUE, CONF_Z_NUMBER) if values.get(k)
    }
    return entities, options


def _label(match: Match) -> str:
    """Name of a found heat pump in the setup; templates without a real
    installation behind them are marked."""
    label = match.template.label
    if match.prefix:
        label = f"{label} ({match.prefix})"
    return f"{label} (beta)" if match.template.experimental else label


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
            if source == SOURCE_GAS:
                return await self.async_step_gas()
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
            selector.SelectOptionDict(value=key, label=_label(m))
            for key, m in matches.items()
        ]
        options.append(
            selector.SelectOptionDict(value=SOURCE_MANUAL, label=SOURCE_MANUAL)
        )
        options.append(selector.SelectOptionDict(value=SOURCE_GAS, label=SOURCE_GAS))
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
        placeholders = {"found": str(len(matches))}
        # The hint on disabled entities only when there are some.
        if disabled := disabled_entities(self.hass):
            placeholders["disabled"] = ", ".join(disabled)
        return self.async_show_form(
            step_id="user_disabled" if disabled else "user",
            data_schema=schema,
            description_placeholders=placeholders,
        )

    async def async_step_user_disabled(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The first step, shown with the hint on disabled entities."""
        return await self.async_step_user(user_input)

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
        if entry.data.get(CONF_KIND) == KIND_GAS:
            return await self.async_step_gas()
        return await self.async_step_entities()

    async def async_step_gas(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """A gas boiler: its counters and the outdoor temperature."""
        errors: dict[str, str] = {}
        values: dict[str, Any] = dict(self._prefill)
        if self.source == SOURCE_RECONFIGURE:
            values.update(self._get_reconfigure_entry().options)
        if user_input is not None:
            values = {k: v for k, v in user_input.items() if v not in (None, "")}
            if (error := validate_gas(self.hass, values)) is None:
                return await self._async_finish_gas(values)
            errors["base"] = error
        return self.async_show_form(
            step_id="gas", data_schema=gas_schema(values), errors=errors
        )

    async def _async_finish_gas(self, values: dict[str, Any]) -> ConfigFlowResult:
        entities, conversion = split_gas(values)
        if self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            options = {
                k: v
                for k, v in entry.options.items()
                if k not in (CONF_CALORIFIC_VALUE, CONF_Z_NUMBER)
            }
            return self.async_update_and_abort(
                entry,
                data={**entry.data, CONF_ENTITIES: entities},
                options={**options, **conversion},
            )
        main = entities.get(GAS_TOTAL) or entities[GAS_HEATING]
        await self.async_set_unique_id(f"{KIND_GAS}:{main}")
        self._abort_if_unique_id_configured()
        name = self._name if self._name != "Wärmepumpe" else "Gasheizung"
        return self.async_create_entry(
            title=name,
            data={CONF_NAME: name, CONF_KIND: KIND_GAS, CONF_ENTITIES: entities},
            options=conversion,
        )

    async def _async_finish(self, entities: dict[str, str]) -> ConfigFlowResult:
        if self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            # The update listener reloads the entry.
            return self.async_update_and_abort(
                entry,
                data={
                    **entry.data,
                    CONF_ENTITIES: entities,
                    CONF_KNOWN_SIGNALS: _known(entry.data.get(CONF_TEMPLATE)),
                },
            )
        unique_id = self._unique_id or next(
            entities[s.value]
            for s in (
                *HEAT_SIGNALS.values(),
                *ELEC_SIGNALS.values(),
                Signal.ELEC_TOTAL,
                Signal.COMPRESSOR,
            )
            if s.value in entities
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
                CONF_KNOWN_SIGNALS: _known(self._template),
            },
        )


def _known(template_key: str | None) -> list[str]:
    """Signals the template offers now: a later version adopts only newer ones."""
    template = TEMPLATES.get(template_key or "")
    return sorted(s.value for s in template.signals) if template else []


# Optional settings in sections of the options form; an empty field is unset.
OPTIONAL_SECTIONS: dict[str, tuple[str, ...]] = {
    "costs": (
        CONF_ELECTRICITY_PRICE,
        CONF_ELECTRICITY_BASE_PRICE,
        CONF_GAS_PRICE,
        CONF_GAS_BASE_PRICE,
    ),
    "heat_load": (CONF_DESIGN_TEMP, CONF_RATED_POWER, CONF_MIN_POWER),
}


class WaermewachtOptionsFlow(OptionsFlow):
    """Thresholds, season start, prices and design outdoor temperature."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self.config_entry.data.get(CONF_KIND) == KIND_GAS:
            return await self.async_step_gas()
        if user_input is not None:
            data = {k: v for k, v in user_input.items() if k not in OPTIONAL_SECTIONS}
            for name in OPTIONAL_SECTIONS:
                data.update(
                    {k: v for k, v in (user_input.get(name) or {}).items() if v != ""}
                )
            return self.async_create_entry(data=data)
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
                    CONF_AUX_MILD_FROM,
                    default=options.get(CONF_AUX_MILD_FROM, MILD_FROM),
                ): number(-5, 15, 0.5, "°C"),
                vol.Required(
                    CONF_EFFICIENCY_DROP,
                    default=options.get(CONF_EFFICIENCY_DROP, DROP_PERCENT),
                ): number(5, 50, 1, "%"),
                vol.Required(
                    CONF_DISINFECTION_TEMP,
                    default=options.get(CONF_DISINFECTION_TEMP, DISINFECTION_TEMP_C),
                ): number(45, 80, 1, "°C"),
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
        optional: dict[str, selector.Selector] = {
            CONF_ELECTRICITY_PRICE: number(0, 200, 0.01, "ct/kWh"),
            CONF_ELECTRICITY_BASE_PRICE: number(0, 2000, 0.01, "€/a"),
            CONF_GAS_PRICE: number(0, 100, 0.01, "ct/kWh"),
            CONF_GAS_BASE_PRICE: number(0, 2000, 0.01, "€/a"),
            CONF_DESIGN_TEMP: number(-30, 5, 0.1, "°C"),
            CONF_RATED_POWER: number(0.5, 50, 0.1, "kW"),
            CONF_MIN_POWER: number(0.2, 20, 0.1, "kW"),
        }
        for name, keys in OPTIONAL_SECTIONS.items():
            schema = schema.extend(
                {
                    vol.Required(name): section(
                        vol.Schema(
                            {
                                vol.Optional(
                                    key,
                                    description={"suggested_value": options.get(key)},
                                ): optional[key]
                                for key in keys
                            }
                        ),
                        {"collapsed": not any(k in options for k in keys)},
                    )
                }
            )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_gas(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """A gas boiler: efficiency, conversion of m³, prices, design temperature."""
        if user_input is not None:
            return self.async_create_entry(
                data={k: v for k, v in user_input.items() if v not in (None, "")}
            )
        options = self.config_entry.options

        def suggested(key: str) -> dict[str, Any]:
            return {"suggested_value": options.get(key)}

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BOILER_EFFICIENCY,
                    default=options.get(CONF_BOILER_EFFICIENCY, BOILER_EFFICIENCY_HS),
                ): _number(0.5, 1.0, 0.01, ""),
                **{
                    vol.Optional(key, description=suggested(key)): field
                    for key, field in (
                        (CONF_DESIGN_TEMP, _number(-30, 5, 0.1, "°C")),
                        (CONF_GAS_PRICE, _number(0, 100, 0.01, "ct/kWh")),
                        (CONF_GAS_BASE_PRICE, _number(0, 2000, 0.01, "€/a")),
                        (CONF_CALORIFIC_VALUE, _number(8, 13, 0.001, "kWh/m³")),
                        (CONF_Z_NUMBER, _number(0.8, 1.1, 0.0001, "")),
                    )
                },
            }
        )
        return self.async_show_form(step_id="gas", data_schema=schema)
