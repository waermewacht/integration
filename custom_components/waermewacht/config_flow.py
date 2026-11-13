"""Config flow: name and source, then the entities per mode (prefilled).

A template (EMS-ESP, Bosch HomeCom and, marked beta, further makers) finds the heat pump in the entity registry by platform
and unique id and fills in the entities; everything stays editable. Without
a template, the user picks the entities. Reconfiguring shows the entity step
again; the options hold the thresholds. Every change reloads the entry.

"Gas boiler" in the first step leads to an entry of its own kind (gas.py):
a gas counter (kWh or m³), optionally hot water apart, and the outdoor
temperature; its options are the boiler efficiency, the conversion of m³
and the prices. "Oil boiler" leads to the same kind with data.fuel = "oil"
(oil.py): counters in kWh or litres, readings of an oil meter or a tank
level, the efficiency by boiler type and a price per 100 l.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .adopt import known_signals
from .charges import DISINFECTION_TEMP_C
from .const import (
    CONF_AUX_MILD_FROM,
    CONF_BATTERY_CHARGED_ENTITY,
    CONF_BATTERY_DISCHARGED_ENTITY,
    CONF_BOILER_EFFICIENCY,
    CONF_BOILER_TYPE,
    CONF_CALORIFIC_VALUE,
    CONF_CRITICAL_RUN,
    CONF_DESIGN_TEMP,
    CONF_DISINFECTION_TEMP,
    CONF_EFFICIENCY_DROP,
    CONF_ELECTRICITY_BASE_PRICE,
    CONF_ELECTRICITY_PRICE,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_ENTITIES,
    CONF_FEED_IN_ENTITY,
    CONF_FEED_IN_TARIFF,
    CONF_FLOW_IN_CIRCUIT,
    CONF_FUEL,
    CONF_GAS_BASE_PRICE,
    CONF_GAS_PRICE,
    CONF_GRID_IMPORT_ENTITY,
    CONF_HISTORY,
    CONF_KIND,
    CONF_KNOWN_SIGNALS,
    CONF_KWH_PER_LITRE,
    CONF_MANUAL_UNIT,
    CONF_MIN_ELECTRICITY,
    CONF_MIN_POWER,
    CONF_NAME,
    CONF_OIL_PRICE,
    CONF_PRICE_CHANGES,
    CONF_PV_ENTITY,
    CONF_RATED_POWER,
    CONF_SEASON_START,
    CONF_SHORT_RUN,
    CONF_SOURCE,
    CONF_STARTS_NOW,
    CONF_STARTS_OFFSET,
    CONF_STARTS_PER_DAY,
    CONF_STARTS_PER_HOUR,
    CONF_TEMPLATE,
    CONF_Z_NUMBER,
    DEFAULT_CRITICAL_RUN_MINUTES,
    DEFAULT_MIN_ELECTRICITY_KWH,
    DEFAULT_SEASON_START_MONTH,
    DEFAULT_SHORT_RUN_MINUTES,
    DEFAULT_STARTS_PER_HOUR,
    DOMAIN,
    FUEL_OIL,
    GAS_DHW,
    GAS_HEATING,
    GAS_MANUAL_UNITS,
    GAS_TOTAL,
    KIND_GAS,
    LITRE_UNIT,
    MANUAL_UNITS,
    OIL_MANUAL_UNITS,
    SOURCE_GAS,
    SOURCE_MANUAL,
    SOURCE_OIL,
    TANK,
    VOLUME_UNIT,
)
from .costs import BOILER_EFFICIENCY_HS
from .counter import UNIT_FACTORS
from .dated import CHANGE_FROM as DATED_FROM
from .day_counters import async_wrong_counters, wrong_kind
from .duty import MINUTE_FACTORS
from .entity import own_entities
from .health import DROP_PERCENT, MILD_FROM
from .health_extra import LPH_FACTORS
from .model import (
    AUX_SIGNALS,
    BOILER_SIGNALS,
    ELEC_SIGNALS,
    ENERGY_SIGNALS,
    HEAT_SIGNALS,
    Mode,
    Signal,
    fuel_modes,
    has_boiler,
    has_elec,
    has_heat,
)
from .oil import BOILER_TYPES, CUSTOM, KWH_PER_LITRE_HS
from .oil import efficiency as boiler_type_efficiency
from .prices import ACCEPTED_UNITS, price_factor
from .profiles import (
    Match,
    RegistryEntry,
    drop_foreign_activity,
    find,
    parse_compressor,
)
from .sisters import suggestions
from .summary import boiler_summary, heat_pump_summary
from .templates import TEMPLATES

# Form sections and the signals in them.
SECTIONS: dict[str, tuple[Signal, ...]] = {
    "heating": (Signal.HEAT_HEATING, Signal.ELEC_HEATING, Signal.AUX_HEATING),
    "dhw": (Signal.HEAT_DHW, Signal.ELEC_DHW, Signal.AUX_DHW, Signal.DHW_TEMP),
    "cooling": (Signal.HEAT_COOLING, Signal.ELEC_COOLING),
    # Boiler of a hybrid system (collapsed when unused).
    "boiler": (
        Signal.BOILER_HEAT_HEATING,
        Signal.BOILER_HEAT_DHW,
        Signal.FUEL_HEATING,
        Signal.FUEL_DHW,
    ),
    "operation": (
        Signal.COMPRESSOR,
        Signal.ACTIVITY,
        Signal.STARTS_TOTAL,
    ),
    # Rare meters, collapsed when unused: one meter for all modes instead of
    # per mode, and electricity a source counts apart (Lambda, iDM).
    "totals": (
        Signal.HEAT_TOTAL,
        Signal.ELEC_TOTAL,
        Signal.AUX_TOTAL,
        Signal.ELEC_DEFROST,
        Signal.ELEC_STANDBY,
        Signal.RUNTIME_HEATING,
        Signal.STARTS_HEATING,
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
        Signal.SYSTEM_PRESSURE,
    ),
}
FORM_SIGNALS = tuple(s for signals in SECTIONS.values() for s in signals)
# Sections that came after the first release of the form.
LATER_SECTIONS = frozenset({"boiler", "totals"})


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
    elif signal is Signal.RUNTIME_HEATING:
        # Hours, minutes or seconds of compressor heating (duty.py), also
        # without a device class (P1P2MQTT: "h", state class measurement).
        return selector.EntitySelector(
            selector.EntitySelectorConfig(
                filter=[
                    selector.EntityFilterSelectorConfig(
                        domain="sensor", device_class="duration"
                    ),
                    selector.EntityFilterSelectorConfig(
                        domain="sensor", unit_of_measurement=list(MINUTE_FACTORS)
                    ),
                ]
            )
        )
    elif signal in (Signal.STARTS_TOTAL, Signal.STARTS_HEATING):
        # Also a counter helper counting the starts (forum 07.11.); its state
        # is a whole number like a sensor's.
        filters = selector.EntityFilterSelectorConfig(domain=["sensor", "counter"])
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
    elif signal is Signal.SYSTEM_PRESSURE:
        filters = selector.EntityFilterSelectorConfig(
            domain="sensor", device_class="pressure"
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


# A template's form: what it did not find, collapsed at the end.
MORE = "more"
# Filled by templates only for a look-back (duty.py): they do not open their
# collapsed section, or every EMS-ESP entry would show it open.
QUIET_SIGNALS = frozenset({Signal.RUNTIME_HEATING, Signal.STARTS_HEATING})


def entities_schema(values: dict[str, str], top: set[str] | None = None) -> vol.Schema:
    """The entity form, one section per mode; `values` prefill it.

    With `top` (a template's finds) the mode sections hold only those
    fields, and every other field goes to the collapsed section "more": a
    beginner filled the empty fields of a template with entities that only
    sounded alike (frost protection as defrost, ViCare 2026-11).
    """
    groups = {
        name: tuple(s for s in signals if top is None or s.value in top)
        for name, signals in SECTIONS.items()
    }
    if top is not None:
        groups[MORE] = tuple(s for s in FORM_SIGNALS if s.value not in top)
    collapsible = (
        "cooling",
        "boiler",
        "totals",
        "measurements",
        "activity_parts",
        MORE,
    )
    return vol.Schema(
        {
            # Sections added later are optional: input from before them
            # (stored flows, tests) stays valid. No default: the frontend
            # takes a section's default over its fields' suggested values
            # and left the boiler empty on a reconfigure (forum 07.11.).
            (
                vol.Optional(name) if name in LATER_SECTIONS else vol.Required(name)
            ): section(
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
                    "collapsed": name in collapsible
                    and not any(
                        values.get(s.value) for s in signals if s not in QUIET_SIGNALS
                    )
                },
            )
            for name, signals in groups.items()
            if signals
        }
    )


def flatten(user_input: dict[str, Any]) -> dict[str, str]:
    """Section values -> {signal: entity_id} without empty fields."""
    return {
        key: value
        for name in (*SECTIONS, MORE)
        for key, value in (user_input.get(name) or {}).items()
        if value
    }


def validate(hass: HomeAssistant, entities: dict[str, str]) -> str | None:
    """Error key, or None if the mapping can be used."""
    if own_entities(hass, entities.values()):
        return "own_entity"
    signals = {Signal(key) for key in entities}
    complete = any(has_heat(signals, m) and has_elec(signals, m) for m in HEAT_SIGNALS)
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
    if Signal.HEAT_TOTAL.value in entities and any(
        HEAT_SIGNALS[m].value in entities for m in (Mode.HEATING, Mode.DHW)
    ):
        return "heat_twice"  # the heat of heating or hot water twice
    # One counter in two fields books it twice, as heat and electricity
    # even at a COP of 1 (forum 07.11.: the DHW electricity meter as heat).
    counters = [entities[s.value] for s in ENERGY_SIGNALS if s.value in entities]
    if len(counters) != len(set(counters)):
        return "counter_twice"
    # The boiler only counts next to the heat pump's heating (its share,
    # the building's heat).
    if has_boiler(signals) and not has_heat(signals, Mode.HEATING):
        return "boiler_without_heat_pump"
    # A status text as compressor ("state_4", forum/issue #4 2026-11-09):
    # no run would ever be counted, without any notice.
    if (entity_id := entities.get(Signal.COMPRESSOR.value)) is not None:
        state = hass.states.get(entity_id)
        if (
            state is not None
            and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
            and parse_compressor(state.state) is None
        ):
            return "compressor_text"
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
OIL_UNITS = [*UNIT_FACTORS, LITRE_UNIT]
GAS_COUNTERS = (GAS_TOTAL, GAS_HEATING, GAS_DHW)
BOILER_TYPE_CHOICES = [*BOILER_TYPES, CUSTOM]
# Errors of the oil form with texts of their own (gas key -> oil key).
OIL_ERRORS = {
    "gas_none": "oil_none",
    "gas_twice": "oil_twice",
    "gas_unit": "oil_unit",
    "gas_no_statistics": "oil_no_statistics",
}
STATISTIC_CLASSES = ("total", "total_increasing")


def _number(
    minimum: float, maximum: float, step: float | Literal["any"], unit: str
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


def boiler_type_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=BOILER_TYPE_CHOICES,
            translation_key=CONF_BOILER_TYPE,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def gas_schema(values: dict[str, Any], *, oil: bool = False) -> vol.Schema:
    """The gas form (or the oil form); `values` prefill it."""
    counter = selector.EntitySelector(
        selector.EntitySelectorConfig(
            filter=[
                selector.EntityFilterSelectorConfig(
                    domain="sensor",
                    device_class=device_class,
                    unit_of_measurement=OIL_UNITS if oil else GAS_UNITS,
                )
                for device_class in (("energy", "volume") if oil else ("gas", "energy"))
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
                Signal.FLOW_TEMP.value,
                description=suggested(Signal.FLOW_TEMP.value),
            ): outdoor,
            vol.Optional(
                CONF_FLOW_IN_CIRCUIT,
                default=bool(values.get(CONF_FLOW_IN_CIRCUIT)),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_MANUAL_UNIT, description=suggested(CONF_MANUAL_UNIT)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(OIL_MANUAL_UNITS if oil else GAS_MANUAL_UNITS),
                    translation_key=CONF_MANUAL_UNIT,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            **(
                {
                    vol.Required(
                        CONF_BOILER_TYPE, description=suggested(CONF_BOILER_TYPE)
                    ): boiler_type_selector(),
                    vol.Optional(
                        CONF_BOILER_EFFICIENCY,
                        description=suggested(CONF_BOILER_EFFICIENCY),
                    ): _number(0.5, 1.0, 0.01, ""),
                }
                if oil
                else {
                    vol.Optional(
                        CONF_CALORIFIC_VALUE,
                        description=suggested(CONF_CALORIFIC_VALUE),
                    ): _number(8, 13, 0.001, "kWh/m³"),
                    vol.Optional(
                        CONF_Z_NUMBER, description=suggested(CONF_Z_NUMBER)
                    ): _number(0.8, 1.1, "any", ""),
                }
            ),
        }
    )


def validate_gas(
    hass: HomeAssistant, values: dict[str, Any], *, oil: bool = False
) -> str | None:
    """Error key, or None if the gas (or oil) mapping can be used."""
    error = _validate_gas(hass, values, oil=oil)
    return OIL_ERRORS.get(error, error) if oil and error else error


def _validate_gas(
    hass: HomeAssistant, values: dict[str, Any], *, oil: bool
) -> str | None:
    keys = (*GAS_COUNTERS, Signal.OUTDOOR_TEMP.value, Signal.FLOW_TEMP.value)
    if own_entities(hass, (values[k] for k in keys if values.get(k))):
        return "own_entity"
    if (
        oil
        and boiler_type_efficiency(
            values.get(CONF_BOILER_TYPE), values.get(CONF_BOILER_EFFICIENCY)
        )
        is None
    ):
        return "boiler_efficiency_missing"
    if (unit := values.get(CONF_MANUAL_UNIT)) is not None:
        # Readings by hand: no counter, no flow (no hourly gas).
        if any(k in values for k in (*GAS_COUNTERS, Signal.FLOW_TEMP.value)):
            return "gas_manual_and_counter"
        if MANUAL_UNITS[unit] == VOLUME_UNIT and not (
            values.get(CONF_CALORIFIC_VALUE) and values.get(CONF_Z_NUMBER)
        ):
            return "gas_calorific_value"
        return None
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
        if unit not in (OIL_UNITS if oil else GAS_UNITS):
            return "gas_unit"
        if state.attributes.get("state_class") not in STATISTIC_CLASSES:
            return "gas_no_statistics"
        volume |= unit == VOLUME_UNIT
    if volume and not (values.get(CONF_CALORIFIC_VALUE) and values.get(CONF_Z_NUMBER)):
        return "gas_calorific_value"
    if (flow := values.get(Signal.FLOW_TEMP.value)) and (
        (state := hass.states.get(flow)) is not None
        and state.attributes.get("state_class") != "measurement"
    ):
        return "gas_flow_no_statistics"
    return None


# Options set in the gas or oil form (the rest under the cog).
# A reconfigure replaces exactly these; the gas efficiency is set under the
# cog and must stay.
GAS_FORM_OPTIONS = (CONF_CALORIFIC_VALUE, CONF_Z_NUMBER)
OIL_FORM_OPTIONS = (CONF_BOILER_TYPE, CONF_BOILER_EFFICIENCY)


def split_gas(values: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    """Form values -> entities and options (conversion of m³)."""
    keys = (*GAS_COUNTERS, Signal.OUTDOOR_TEMP.value, Signal.FLOW_TEMP.value)
    entities = {k: values[k] for k in keys if values.get(k)}
    options = {
        k: values[k] for k in (*GAS_FORM_OPTIONS, *OIL_FORM_OPTIONS) if values.get(k)
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
    # 1.2: known signals only once found or configured (adopt.py).
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._name = ""
        self._template: str | None = None
        self._unique_id: str | None = None
        self._prefill: dict[str, str] = {}
        # Signals the template found for the heat pump (known once set up).
        self._found: set[str] = set()
        # Fields shown in the mode sections (a template's); None: all.
        self._top: set[str] | None = None
        # Entity -> other entities of the same counter (backfill only).
        self._history: dict[str, list[str]] = {}
        # Mapping that drew the warning on the kind of a counter: sent again
        # unchanged, it is kept (the check can be wrong, e.g. a lifetime
        # counter that restarted at 0 twice at the same hour).
        self._counter_warned: dict[str, str] | None = None

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
            if source == SOURCE_OIL:
                return await self.async_step_oil()
            if (match := matches.get(source)) is not None:
                self._template = match.template.key
                self._unique_id = source
                self._prefill = {
                    s.value: e for s, e in match.entities.items() if s in FORM_SIGNALS
                }
                self._found = {s.value for s in match.entities}
                self._top = set(self._prefill)
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
        options.append(selector.SelectOptionDict(value=SOURCE_OIL, label=SOURCE_OIL))
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
            error = validate(self.hass, values)
            if error is None and values != self._counter_warned:
                error = await self._async_counter_kind(values)
                if error is not None:
                    self._counter_warned = values
            if error is None:
                return await self._async_finish(values)
            errors["base"] = error
        return self.async_show_form(
            step_id="entities",
            data_schema=entities_schema(values, self._top),
            errors=errors,
        )

    async def _async_counter_kind(self, entities: dict[str, str]) -> str | None:
        """Warning key if a chosen energy counter is of the wrong kind for
        the entry (day counter for lifetime, or the other way round); on a
        reconfigure only among the newly chosen ones."""
        before: dict[str, str] = {}
        key = self._template
        if self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            key = entry.data.get(CONF_TEMPLATE)
            before = entry.data.get(CONF_ENTITIES, {})
        template = TEMPLATES.get(key or "")
        if (kind := wrong_kind(template)) is None:
            return None
        found = await async_wrong_counters(
            self.hass,
            [
                entities[s.value]
                for s in ENERGY_SIGNALS
                if s.value in entities
                and entities[s.value] != before.get(s.value)
                # The boiler's counters are lifetime counters of their own.
                and s not in BOILER_SIGNALS
            ],
            kind,
            previous_day=template is not None and template.previous_day,
        )
        return kind if found else None

    def _moved_unique_id(self, entry: ConfigEntry, unique_id: str) -> str | None:
        """The new unique id, unless another entry still carries it."""
        holder = self.hass.config_entries.async_entry_for_domain_unique_id(
            DOMAIN, unique_id
        )
        return unique_id if holder in (None, entry) else entry.unique_id

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        self._prefill = dict(entry.data[CONF_ENTITIES])
        if entry.data.get(CONF_TEMPLATE):
            self._top = set(self._prefill)
        if entry.data.get(CONF_KIND) == KIND_GAS:
            if entry.data.get(CONF_FUEL) == FUEL_OIL:
                return await self.async_step_oil()
            return await self.async_step_gas()
        return await self.async_step_entities()

    async def async_step_gas(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """A gas boiler: its counters and the outdoor temperature."""
        return await self._async_boiler_step(user_input, oil=False)

    async def async_step_oil(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """An oil boiler: its counters, the outdoor temperature, its type."""
        return await self._async_boiler_step(user_input, oil=True)

    async def _async_boiler_step(
        self, user_input: dict[str, Any] | None, *, oil: bool
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        values: dict[str, Any] = dict(self._prefill)
        if self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            values.update(entry.options)
            if manual := entry.data.get(CONF_MANUAL_UNIT):
                values[CONF_MANUAL_UNIT] = manual
            if entry.data.get(CONF_FLOW_IN_CIRCUIT):
                values[CONF_FLOW_IN_CIRCUIT] = True
        if user_input is not None:
            values = {k: v for k, v in user_input.items() if v not in (None, "")}
            error = validate_gas(self.hass, values, oil=oil)
            if error is None and self.source == SOURCE_RECONFIGURE:
                # Tank levels count down, meters up: the stored readings
                # would not fit the other kind (review 07.11.).
                before = self._get_reconfigure_entry().data.get(CONF_MANUAL_UNIT)
                after = values.get(CONF_MANUAL_UNIT)
                if before and after and (before == TANK) != (after == TANK):
                    error = "tank_unit_change"
            if error is None:
                return await self._async_finish_gas(values, oil=oil)
            errors["base"] = error
        return self.async_show_form(
            step_id="oil" if oil else "gas",
            data_schema=gas_schema(values, oil=oil),
            errors=errors,
        )

    async def _async_finish_gas(
        self, values: dict[str, Any], *, oil: bool
    ) -> ConfigFlowResult:
        entities, conversion = split_gas(values)
        manual = values.get(CONF_MANUAL_UNIT)
        # Only with a flow sensor; kept in the data, as the sensor is.
        circuit = (
            {CONF_FLOW_IN_CIRCUIT: True}
            if values.get(CONF_FLOW_IN_CIRCUIT) and Signal.FLOW_TEMP.value in entities
            else {}
        )
        if self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            options = {
                k: v
                for k, v in entry.options.items()
                if k not in (OIL_FORM_OPTIONS if oil else GAS_FORM_OPTIONS)
            }
            data = {
                k: v
                for k, v in entry.data.items()
                if k not in (CONF_MANUAL_UNIT, CONF_FLOW_IN_CIRCUIT)
            }
            # The main counter identifies the boiler, also after a change;
            # readings by hand keep their id (and the stored readings).
            unique_id = (
                entry.unique_id
                if manual
                else self._moved_unique_id(entry, _gas_unique_id(entities))
            )
            return self.async_update_and_abort(
                entry,
                unique_id=unique_id,
                data={
                    **data,
                    CONF_ENTITIES: entities,
                    **({CONF_MANUAL_UNIT: manual} if manual else {}),
                    **circuit,
                },
                options={**options, **conversion},
            )
        if manual:
            await self.async_set_unique_id(f"{KIND_GAS}:manual:{uuid4().hex}")
        else:
            unique_id = _gas_unique_id(entities)
            # Its own text: a second entry is no way to add fields later.
            if existing := self.hass.config_entries.async_entry_for_domain_unique_id(
                DOMAIN, unique_id
            ):
                return self.async_abort(
                    reason="oil_already_configured"
                    if oil
                    else "gas_already_configured",
                    description_placeholders={"title": existing.title},
                )
            await self.async_set_unique_id(unique_id)
        if self._name != "Wärmepumpe":
            name = self._name
        else:
            name = "Ölheizung" if oil else "Gasheizung"
        return self.async_create_entry(
            title=name,
            data={
                CONF_NAME: name,
                CONF_KIND: KIND_GAS,
                **({CONF_FUEL: FUEL_OIL} if oil else {}),
                CONF_ENTITIES: entities,
                **({CONF_MANUAL_UNIT: manual} if manual else {}),
                **circuit,
            },
            options=conversion,
        )

    async def _async_finish(self, entities: dict[str, str]) -> ConfigFlowResult:
        if self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            # An own mapping is identified by its first counter, a found
            # heat pump by its source, which a reconfigure does not change.
            unique_id = (
                entry.unique_id
                if entry.data.get(CONF_TEMPLATE)
                else self._moved_unique_id(entry, _manual_unique_id(entities))
            )
            # The update listener reloads the entry.
            return self.async_update_and_abort(
                entry,
                unique_id=unique_id,
                data={
                    **entry.data,
                    CONF_ENTITIES: entities,
                    CONF_KNOWN_SIGNALS: _known(
                        entry.data.get(CONF_TEMPLATE),
                        entry.data.get(CONF_KNOWN_SIGNALS),
                        {*entry.data.get(CONF_ENTITIES, {}), *entities},
                    ),
                },
            )
        unique_id = self._unique_id or _manual_unique_id(entities)
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
                CONF_KNOWN_SIGNALS: _known(
                    self._template, [], {*self._found, *entities}
                ),
            },
        )


def _manual_unique_id(entities: dict[str, str]) -> str:
    """An own mapping is identified by its first counter (or the compressor)."""
    return next(
        entities[s.value]
        for s in (
            *HEAT_SIGNALS.values(),
            Signal.HEAT_TOTAL,
            *ELEC_SIGNALS.values(),
            Signal.ELEC_TOTAL,
            Signal.COMPRESSOR,
        )
        if s.value in entities
    )


def _gas_unique_id(entities: dict[str, str]) -> str:
    main = entities.get(GAS_TOTAL) or entities[GAS_HEATING]
    return f"{KIND_GAS}:{main}"


def _known(
    template_key: str | None, known: list[str] | None, offered: Iterable[str]
) -> list[str]:
    """Signals the entry had an entity for (adopt.known_signals): one the
    template did not find stays unknown and is taken over once it appears."""
    template = TEMPLATES.get(template_key or "")
    return known_signals(template.signals, known, offered) if template else []


# The options form: on top what nearly everyone sets, the rest in sections
# that start collapsed (forms got too full, 08.11.2026). Sections only group
# the form: the options are stored flat as ever, an empty field is unset.
OPTION_TOP: tuple[str, ...] = (CONF_ELECTRICITY_PRICE, CONF_DESIGN_TEMP)
OPTIONAL_SECTIONS: dict[str, tuple[str, ...]] = {
    "costs": (
        CONF_ELECTRICITY_PRICE_ENTITY,
        CONF_ELECTRICITY_BASE_PRICE,
        CONF_GAS_PRICE,
        CONF_GAS_BASE_PRICE,
    ),
    "pv": (
        CONF_GRID_IMPORT_ENTITY,
        CONF_FEED_IN_ENTITY,
        CONF_PV_ENTITY,
        CONF_BATTERY_CHARGED_ENTITY,
        CONF_BATTERY_DISCHARGED_ENTITY,
        CONF_FEED_IN_TARIFF,
    ),
    "heat_load": (CONF_RATED_POWER, CONF_MIN_POWER),
    "limits": (
        CONF_MIN_ELECTRICITY,
        CONF_SHORT_RUN,
        CONF_CRITICAL_RUN,
        CONF_STARTS_PER_HOUR,
        CONF_STARTS_PER_DAY,
        CONF_AUX_MILD_FROM,
        CONF_EFFICIENCY_DROP,
        CONF_DISINFECTION_TEMP,
        CONF_SEASON_START,
    ),
}
# Settings with a default: always stored (the form shows the default).
OPTION_DEFAULTS: dict[str, Any] = {
    CONF_MIN_ELECTRICITY: DEFAULT_MIN_ELECTRICITY_KWH,
    CONF_SHORT_RUN: DEFAULT_SHORT_RUN_MINUTES,
    CONF_CRITICAL_RUN: DEFAULT_CRITICAL_RUN_MINUTES,
    CONF_STARTS_PER_HOUR: DEFAULT_STARTS_PER_HOUR,
    CONF_AUX_MILD_FROM: MILD_FROM,
    CONF_EFFICIENCY_DROP: DROP_PERCENT,
    CONF_DISINFECTION_TEMP: DISINFECTION_TEMP_C,
    # The select stores the month as text ("7").
    CONF_SEASON_START: str(DEFAULT_SEASON_START_MONTH),
}
# The section that holds the fields an error is about: shown open.
ERROR_SECTIONS = {
    "price_unit": "costs",
    "battery_both": "pv",
    "meter_unit": "pv",
    "change_from_required": "price_change",
    "change_empty": "price_change",
    "change_exists": "price_change",
}

# Section "Price change from a date": a new price state (dated.py) or the
# removal of one. Its fields are not options of their own.
SECTION_PRICE_CHANGE = "price_change"
CHANGE_FROM_KEY = DATED_FROM  # as stored
CHANGE_FROM = "change_from"
REMOVE_CHANGE = "remove_change"
CHANGE_FIELDS: dict[str, str] = {
    "change_electricity_price": CONF_ELECTRICITY_PRICE,
    "change_electricity_base_price": CONF_ELECTRICITY_BASE_PRICE,
    "change_gas_price": CONF_GAS_PRICE,
    "change_gas_base_price": CONF_GAS_BASE_PRICE,
}


def apply_price_change(
    changes: list[dict[str, Any]], section_input: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], str | None]:
    """The price changes after the section's input: one removed and/or one
    added. (changes, error key or None)."""
    section_input = section_input or {}
    result = [dict(c) for c in changes]
    if remove := section_input.get(REMOVE_CHANGE):
        result = [c for c in result if str(c[CHANGE_FROM_KEY]) != str(remove)]
    values = {
        field: float(section_input[key])
        for key, field in CHANGE_FIELDS.items()
        if section_input.get(key) not in ("", None)
    }
    day = section_input.get(CHANGE_FROM)
    if not day and not values:
        return result, None
    if not day:
        return changes, "change_from_required"
    if not values:
        return changes, "change_empty"
    if any(str(c[CHANGE_FROM_KEY]) == str(day) for c in result):
        return changes, "change_exists"
    result.append({CHANGE_FROM_KEY: str(day), **values})
    return sorted(result, key=lambda c: str(c[CHANGE_FROM_KEY])), None


# Meters of the house for the split into grid and own electricity.
HOUSE_METERS = (
    CONF_GRID_IMPORT_ENTITY,
    CONF_FEED_IN_ENTITY,
    CONF_PV_ENTITY,
    CONF_BATTERY_CHARGED_ENTITY,
    CONF_BATTERY_DISCHARGED_ENTITY,
)
# Stored once the options were saved: the sisters' values are suggested
# only until then (a suggestion is saved with any change).
SISTERS_OFFERED = "sister_suggestions_offered"


def _unit_of(hass: HomeAssistant, entity_id: str) -> str | None:
    """Unit of an entity: of its state, else of its registry entry."""
    state = hass.states.get(entity_id)
    if state is not None and (unit := state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)):
        return str(unit)
    entry = er.async_get(hass).async_get(entity_id)
    return entry.unit_of_measurement if entry else None


class WaermewachtOptionsFlow(OptionsFlow):
    """Thresholds, season start, prices and design outdoor temperature."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self.config_entry.data.get(CONF_KIND) == KIND_GAS:
            if self.config_entry.data.get(CONF_FUEL) == FUEL_OIL:
                return await self.async_step_oil()
            return await self.async_step_gas()
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        options: dict[str, Any] = dict(self.config_entry.options)
        if user_input is not None:
            data = {
                k: v
                for k, v in user_input.items()
                if k not in OPTIONAL_SECTIONS
                and k != SECTION_PRICE_CHANGE
                and v not in ("", None)
            }
            for name, keys in OPTIONAL_SECTIONS.items():
                if name not in user_input:
                    # Not sent at all: what is stored stays.
                    data.update({k: options[k] for k in keys if k in options})
                    continue
                data.update(
                    {
                        k: v
                        for k, v in (user_input[name] or {}).items()
                        if v not in ("", None)
                    }
                )
            data[SISTERS_OFFERED] = True
            self._apply_starts_now(data, options)
            changes, change_error = apply_price_change(
                list(options.get(CONF_PRICE_CHANGES) or []),
                user_input.get(SECTION_PRICE_CHANGE),
            )
            if changes:
                data[CONF_PRICE_CHANGES] = changes
            if change_error:
                errors["base"] = change_error
            price_entity = data.get(CONF_ELECTRICITY_PRICE_ENTITY)
            unit = _unit_of(self.hass, price_entity) if price_entity else None
            if price_entity and price_factor(unit) is None:
                # Prices in other units (currencies, per MWh of gas…) are not
                # guessed.
                errors["base"] = "price_unit"
                placeholders = {
                    "entity": price_entity,
                    "unit": unit or "–",
                    "units": ACCEPTED_UNITS,
                }
            elif bool(data.get(CONF_BATTERY_CHARGED_ENTITY)) != bool(
                data.get(CONF_BATTERY_DISCHARGED_ENTITY)
            ):
                errors["base"] = "battery_both"
            elif wrong := next(
                (
                    data[key]
                    for key in HOUSE_METERS
                    if data.get(key)
                    and _unit_of(self.hass, data[key]) not in UNIT_FACTORS
                ),
                None,
            ):
                errors["base"] = "meter_unit"
                placeholders = {"entity": wrong}
            elif not errors:
                return self.async_create_entry(data=data)
            options = data
        # Sections open: the one an error is about, those with suggestions.
        expanded = {ERROR_SECTIONS[e] for e in errors.values() if e in ERROR_SECTIONS}
        step_id = "init"
        if user_input is None and not options.get(SISTERS_OFFERED):
            # Once: meters and price sensor from Tarifwacht or Einspeisewacht.
            found = suggestions(self.hass)
            offered = {k: v for k, v in found.values.items() if k not in options}
            if offered and found.source:
                options = {**offered, **options}
                expanded |= {
                    name
                    for name, keys in OPTIONAL_SECTIONS.items()
                    if any(k in offered for k in keys)
                }
                step_id = f"init_{found.source}"
                placeholders = {"entry": found.title or found.source}
            elif not found.found:
                step_id = "init_tip"
                # Links as placeholders: translations may hold no URLs.
                placeholders = {
                    "tarifwacht_url": "https://github.com/tarifwacht/integration",
                    "einspeisewacht_url": "https://github.com/einspeisewacht/integration",
                }

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

        fields: dict[str, selector.Selector] = {
            CONF_ELECTRICITY_PRICE: number(0, 200, 0.01, "ct/kWh"),
            CONF_DESIGN_TEMP: number(-30, 5, 0.1, "°C"),
            CONF_ELECTRICITY_PRICE_ENTITY: selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            CONF_ELECTRICITY_BASE_PRICE: number(0, 2000, 0.01, "€/a"),
            CONF_GAS_PRICE: number(0, 100, 0.01, "ct/kWh"),
            CONF_GAS_BASE_PRICE: number(0, 2000, 0.01, "€/a"),
            **dict.fromkeys(
                HOUSE_METERS,
                selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="energy"
                    )
                ),
            ),
            CONF_FEED_IN_TARIFF: number(0, 100, 0.001, "ct/kWh"),
            CONF_RATED_POWER: number(0.5, 50, 0.1, "kW"),
            CONF_MIN_POWER: number(0.2, 20, 0.1, "kW"),
            CONF_MIN_ELECTRICITY: number(0, 10, 0.1, "kWh"),
            CONF_SHORT_RUN: number(1, 60, 1, "min"),
            CONF_CRITICAL_RUN: number(1, 60, 1, "min"),
            CONF_STARTS_PER_HOUR: number(1, 12, 1, "/h"),
            # Optional (empty: off), for on/off heat pumps.
            CONF_STARTS_PER_DAY: number(1, 200, 1, "/d"),
            CONF_AUX_MILD_FROM: number(-5, 15, 0.5, "°C"),
            CONF_EFFICIENCY_DROP: number(5, 50, 1, "%"),
            CONF_DISINFECTION_TEMP: number(45, 80, 1, "°C"),
            CONF_SEASON_START: selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[str(m) for m in range(1, 13)],
                    translation_key="month",
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }

        def marker(key: str) -> vol.Marker:
            """A setting with a default always has a value; the others are
            suggested (empty: unset). No default on a section: the frontend
            would take it over the values of its fields (forum 07.11.)."""
            if key in OPTION_DEFAULTS:
                value = options.get(key, OPTION_DEFAULTS[key])
                return vol.Required(
                    key, default=str(value) if key == CONF_SEASON_START else value
                )
            return vol.Optional(key, description={"suggested_value": options.get(key)})

        schema = vol.Schema({marker(key): fields[key] for key in OPTION_TOP})
        # Hybrid system whose boiler reports only its fuel: heat = fuel x η.
        mapped = {
            Signal(key)
            for key in self.config_entry.data.get(CONF_ENTITIES, {})
            if key in Signal._value2member_map_
        }
        if fuel_modes(mapped):
            schema = schema.extend(
                {
                    vol.Required(
                        CONF_BOILER_EFFICIENCY,
                        default=options.get(
                            CONF_BOILER_EFFICIENCY, BOILER_EFFICIENCY_HS
                        ),
                    ): number(0.5, 1.0, 0.01, "")
                }
            )
        starts_now = self._starts_now(mapped)
        for name, keys in OPTIONAL_SECTIONS.items():
            part = {marker(key): fields[key] for key in keys}
            if name == "limits" and starts_now is not None:
                part[
                    vol.Optional(
                        CONF_STARTS_NOW, description={"suggested_value": starts_now}
                    )
                ] = number(0, 10_000_000, 1, "")
            schema = schema.extend(
                {
                    vol.Optional(name): section(
                        vol.Schema(part),
                        {"collapsed": name not in expanded},
                    )
                }
            )
        # Price change from a date (collapsed): new prices, or remove one.
        change_part: dict[Any, Any] = {
            vol.Optional(CHANGE_FROM): selector.DateSelector(),
            **{
                vol.Optional(key): fields[field] for key, field in CHANGE_FIELDS.items()
            },
        }
        stored = list(self.config_entry.options.get(CONF_PRICE_CHANGES) or [])
        if stored:
            change_part[vol.Optional(REMOVE_CHANGE)] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[str(c[CHANGE_FROM_KEY]) for c in stored],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        schema = schema.extend(
            {
                vol.Optional(SECTION_PRICE_CHANGE): section(
                    vol.Schema(change_part),
                    {"collapsed": SECTION_PRICE_CHANGE not in expanded},
                )
            }
        )
        template = TEMPLATES.get(self.config_entry.data.get(CONF_TEMPLATE) or "")
        # Whole kWh is known only from the readings of the loaded entry.
        coarse_heat_modes = (
            getattr(
                getattr(self.config_entry, "runtime_data", None),
                "coarse_heat_modes",
                None,
            )
            if self.config_entry.state is ConfigEntryState.LOADED
            else None
        )
        placeholders["summary"] = heat_pump_summary(
            self.config_entry.data.get(CONF_ENTITIES, {}),
            self.config_entry.options,
            template.label if template else None,
            self.hass.config.language,
            coarse_heat=bool(coarse_heat_modes and coarse_heat_modes()),
            no_statistics=self._no_statistics(),
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    def _no_statistics(self) -> set[Signal]:
        """Mapped temperatures whose state has no state class: Home Assistant
        keeps no long-term statistics of them (the look-back needs them)."""
        entities = self.config_entry.data.get(CONF_ENTITIES, {})
        result = set()
        for signal in (Signal.OUTDOOR_TEMP, Signal.FLOW_TEMP, Signal.RETURN_TEMP):
            entity_id = entities.get(signal.value)
            state = self.hass.states.get(entity_id) if entity_id else None
            if state is not None and not state.attributes.get("state_class"):
                result.add(signal)
        return result

    def _runtime(self) -> Any:
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return None
        return getattr(self.config_entry, "runtime_data", None)

    def _starts_now(self, mapped: set[Signal]) -> int | None:
        """Starts total shown in the field: only without a start counter of
        the heat pump and with the entry loaded (the own count lives there)."""
        runtime = self._runtime()
        if Signal.STARTS_TOTAL in mapped or runtime is None:
            return None
        total, _ = runtime.starts_total()
        return total

    def _apply_starts_now(self, data: dict[str, Any], options: dict[str, Any]) -> None:
        """The entered total becomes the offset to the own count; without a
        new total the stored offset stays (options are replaced as a whole)."""
        entered = data.pop(CONF_STARTS_NOW, None)
        runtime = self._runtime()
        if entered is not None and runtime is not None:
            total, _ = runtime.starts_total()
            if total is None or int(entered) != total:
                data[CONF_STARTS_OFFSET] = int(entered) - runtime.own_starts
                return
        if CONF_STARTS_OFFSET in options:
            data[CONF_STARTS_OFFSET] = options[CONF_STARTS_OFFSET]

    def _boiler_summary(self, *, oil: bool) -> dict[str, str]:
        entry = self.config_entry
        return {
            "summary": boiler_summary(
                entry.data,
                entry.data.get(CONF_ENTITIES, {}),
                entry.options,
                oil=oil,
                language=self.hass.config.language,
            )
        }

    # The same form with a hint in the costs section (texts of a form are
    # per step; its placeholders are not translated).
    async def async_step_init_tarifwacht(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_init(user_input)

    async def async_step_init_einspeisewacht(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_init(user_input)

    async def async_step_init_tip(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_init(user_input)

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
                        (CONF_Z_NUMBER, _number(0.8, 1.1, "any", "")),  # 4 decimals
                    )
                },
            }
        )
        return self.async_show_form(
            step_id="gas",
            data_schema=schema,
            description_placeholders=self._boiler_summary(oil=False),
        )

    async def async_step_oil(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """An oil boiler: boiler type (or own efficiency), litre, price,
        design temperature."""
        errors: dict[str, str] = {}
        options = dict(self.config_entry.options)
        if user_input is not None:
            values = {k: v for k, v in user_input.items() if v not in (None, "")}
            if (
                boiler_type_efficiency(
                    values.get(CONF_BOILER_TYPE), values.get(CONF_BOILER_EFFICIENCY)
                )
                is not None
            ):
                return self.async_create_entry(data=values)
            errors["base"] = "boiler_efficiency_missing"
            options = values

        def suggested(key: str) -> dict[str, Any]:
            return {"suggested_value": options.get(key)}

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BOILER_TYPE, description=suggested(CONF_BOILER_TYPE)
                ): boiler_type_selector(),
                vol.Required(
                    CONF_KWH_PER_LITRE,
                    default=options.get(CONF_KWH_PER_LITRE, KWH_PER_LITRE_HS),
                ): _number(8, 12, 0.01, "kWh/l"),
                **{
                    vol.Optional(key, description=suggested(key)): field
                    for key, field in (
                        (CONF_BOILER_EFFICIENCY, _number(0.5, 1.0, 0.01, "")),
                        (CONF_DESIGN_TEMP, _number(-30, 5, 0.1, "°C")),
                        (CONF_OIL_PRICE, _number(0, 500, 0.01, "€/100 l")),
                    )
                },
            }
        )
        return self.async_show_form(
            step_id="oil",
            data_schema=schema,
            errors=errors,
            description_placeholders=self._boiler_summary(oil=True),
        )
