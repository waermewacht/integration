"""Config flow: detection (EMS-ESP, Bosch HomeCom), manual mapping, errors, options."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, section
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.config_flow import (
    SECTIONS,
    _selector,
    entities_schema,
)
from custom_components.waermewacht.const import CONF_ENTITIES, CONF_TEMPLATE, DOMAIN
from custom_components.waermewacht.model import Signal

from .conftest import ENERGY, entry_data, form_input

# Options without the optional sections (stored values stay, defaults apply).
REQUIRED_OPTIONS: dict[str, Any] = {
    "limits": {
        "min_electricity": 0.5,
        "short_run_minutes": 10,
        "critical_run_minutes": 6,
        "starts_per_hour": 3,
        "season_start_month": "7",
    },
}

EMPTY_SECTIONS = {
    "heating": {},
    "dhw": {},
    "cooling": {},
    "operation": {},
    "measurements": {},
    "activity_parts": {},
}


def add_ems_esp(hass: HomeAssistant) -> None:
    """Registry entries and states as EMS-ESP creates them (values made up)."""
    registry = er.async_get(hass)
    for domain, key in (
        ("sensor", "nrgheat"),
        ("sensor", "meterheat"),
        ("sensor", "dhw_nrg"),
        ("sensor", "dhw_meter"),
        ("binary_sensor", "hpcompon"),
        ("sensor", "hpactivity"),
    ):
        entry = registry.async_get_or_create(
            domain, "mqtt", f"boiler_{key}", suggested_object_id=f"boiler_{key}"
        )
        if key in ("hpcompon", "hpactivity"):
            hass.states.async_set(entry.entity_id, "off")
        else:
            hass.states.async_set(entry.entity_id, "100.0", ENERGY)


async def test_ems_esp_is_found_and_prefilled(hass: HomeAssistant) -> None:
    add_ems_esp(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    # Nothing disabled: the step without the hint.
    assert result["step_id"] == "user"
    assert result["description_placeholders"] == {"found": "1"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "ems_esp:"}
    )
    assert result["step_id"] == "entities"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        form_input(
            result,
            heating={
                "heat_heating": "sensor.boiler_nrgheat",
                "elec_heating": "sensor.boiler_meterheat",
            },
            operation={"compressor": "binary_sensor.boiler_hpcompon"},
        ),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "WP"
    assert result["data"][CONF_TEMPLATE] == "ems_esp"
    assert (
        result["data"][CONF_ENTITIES]["compressor"] == "binary_sensor.boiler_hpcompon"
    )
    assert result["result"].unique_id == "ems_esp:"


async def test_template_form_shows_its_finds_and_collapses_the_rest(
    hass: HomeAssistant,
) -> None:
    """A template's form: the mode sections hold what it found, every other
    field is in the collapsed section "more" (a beginner filled the empty
    fields of the ViCare template with look-alikes, 2026-11). A field filled
    there is taken over."""
    add_ems_esp(hass)
    hass.states.async_set("sensor.outdoor", "5.0", {"unit_of_measurement": "°C"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "ems_esp:"}
    )
    shown = {str(k): k for k in result["data_schema"].schema}
    assert set(shown) == {"heating", "dhw", "operation", "more"}

    def fields(name: str) -> set[str]:
        return {str(k) for k in result["data_schema"].schema[shown[name]].schema.schema}

    assert fields("heating") == {"heat_heating", "elec_heating"}
    assert fields("operation") == {"compressor", "activity"}
    assert {"aux_heating", "defrost_flag", "elec_standby", "outdoor_temp"} <= fields(
        "more"
    )
    assert not fields("more") & (fields("heating") | fields("operation"))
    assert result["data_schema"].schema[shown["more"]].options["collapsed"] is True
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        form_input(
            result,
            heating={
                "heat_heating": "sensor.boiler_nrgheat",
                "elec_heating": "sensor.boiler_meterheat",
            },
            operation={"compressor": "binary_sensor.boiler_hpcompon"},
            more={"outdoor_temp": "sensor.outdoor"},
        ),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ENTITIES]["outdoor_temp"] == "sensor.outdoor"


def test_manual_form_shows_every_section() -> None:
    assert {str(k) for k in entities_schema({}).schema} == set(SECTIONS)


def test_sections_carry_no_default_over_their_prefill() -> None:
    """The frontend (computeInitialHaFormData) takes a section's default over
    the suggested values of its fields: with `default={}` the boiler of a
    hybrid stayed empty on a reconfigure, and OK dropped its counters
    (forum 07.11.). As sent to the frontend, no section has a default and
    the boiler's fields carry their entities."""
    values = {
        "heat_heating": "sensor.heat",
        "elec_heating": "sensor.elec",
        "boiler_heat_heating": "sensor.boiler_heat",
        "fuel_dhw": "sensor.boiler_gas_dhw",
    }
    schema = entities_schema(values, set(values)).schema
    # No default: as a new marker of the same kind (HA swaps voluptuous for
    # probatio, each with its own UNDEFINED).
    assert all(key.default is type(key)("x").default for key in schema)
    (boiler_key,) = (key for key in schema if str(key) == "boiler")
    boiler = {
        str(key): (key.description or {}).get("suggested_value")
        for key in schema[boiler_key].schema.schema
    }
    assert boiler == {
        "boiler_heat_heating": "sensor.boiler_heat",
        "fuel_dhw": "sensor.boiler_gas_dhw",
    }


def add_homecom(hass: HomeAssistant, *, enabled: bool) -> None:
    """Registry entries as bosch_homecom creates them (gateway id made up);
    the energy per mode is disabled by default."""
    registry = er.async_get(hass)
    for key, per_mode in (
        ("heat_produced_ch", True),
        ("energy_compressor_ch", True),
        ("local_compressor_speed", False),
        ("heat_produced_total", False),
    ):
        entry = registry.async_get_or_create(
            "sensor",
            "bosch_homecom",
            f"101234567-{key}",
            suggested_object_id=f"boschcom_k40_101234567_{key}",
            disabled_by=er.RegistryEntryDisabler.INTEGRATION
            if per_mode and not enabled
            else None,
        )
        if entry.disabled_by is None:
            hass.states.async_set(
                entry.entity_id, "0" if "speed" in key else "1.5", ENERGY
            )


async def test_homecom_points_to_disabled_entities(hass: HomeAssistant) -> None:
    add_homecom(hass, enabled=False)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user_disabled"
    assert result["description_placeholders"] == {
        "found": "0",
        "disabled": "sensor.boschcom_k40_101234567_energy_compressor_ch, "
        "sensor.boschcom_k40_101234567_heat_produced_ch",
    }
    # The step with the hint goes on like the plain one.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "manual"}
    )
    assert result["step_id"] == "entities"


async def test_homecom_is_found_and_prefilled(hass: HomeAssistant) -> None:
    add_homecom(hass, enabled=True)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["description_placeholders"]["found"] == "1"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "bosch_homecom:101234567"}
    )
    assert result["step_id"] == "entities"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        form_input(
            result,
            heating={
                "heat_heating": "sensor.boschcom_k40_101234567_heat_produced_ch",
                "elec_heating": "sensor.boschcom_k40_101234567_energy_compressor_ch",
            },
            operation={
                "compressor": "sensor.boschcom_k40_101234567_local_compressor_speed"
            },
        ),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TEMPLATE] == "bosch_homecom"


def test_starts_total_offers_counter_helpers() -> None:
    """A counter helper counting the compressor starts (forum 07.11.)."""
    (only,) = _selector(Signal.STARTS_TOTAL).config["filter"]
    assert set(only["domain"]) == {"sensor", "counter"}


async def test_starts_total_from_counter_helper(hass: HomeAssistant) -> None:
    """The form takes a counter helper as the starts total."""
    hass.states.async_set("sensor.heat", "1.0", ENERGY)
    hass.states.async_set("sensor.elec", "1.0", ENERGY)
    hass.states.async_set("counter.wp_starts", "1503")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "manual"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **EMPTY_SECTIONS,
            "heating": {"heat_heating": "sensor.heat", "elec_heating": "sensor.elec"},
            "operation": {"starts_total": "counter.wp_starts"},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ENTITIES]["starts_total"] == "counter.wp_starts"


def test_flow_rate_without_device_class_is_offered() -> None:
    """P1P2MQTT and others give L/min without device class volume_flow_rate."""
    filters = _selector(Signal.FLOW_RATE).config["filter"]
    assert {"domain": ["sensor"], "device_class": ["volume_flow_rate"]} in filters
    units = next(
        f["unit_of_measurement"] for f in filters if "unit_of_measurement" in f
    )
    assert {"L/min", "l/min", "L/h", "m³/h"} <= set(units)


async def test_manual_needs_one_complete_mode(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.heat", "1.0", ENERGY)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "manual"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**EMPTY_SECTIONS, "heating": {"heat_heating": "sensor.heat"}},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_mode"}


async def test_manual_elec_total_completes_a_mode(hass: HomeAssistant) -> None:
    """Compressor electricity as one meter (Waterkotte), not with per mode."""
    for entity_id in ("sensor.heat", "sensor.elec", "sensor.elec_heating"):
        hass.states.async_set(entity_id, "1.0", ENERGY)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "manual"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **EMPTY_SECTIONS,
            "heating": {
                "heat_heating": "sensor.heat",
                "elec_heating": "sensor.elec_heating",
            },
            "totals": {"elec_total": "sensor.elec"},
        },
    )
    assert result["errors"] == {"base": "elec_twice"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **EMPTY_SECTIONS,
            "heating": {"heat_heating": "sensor.heat"},
            "totals": {"elec_total": "sensor.elec"},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_same_counter_in_two_fields(hass: HomeAssistant) -> None:
    """The DHW electricity meter also as DHW heat (forum 07.11.): refused."""
    for entity_id in ("sensor.heat", "sensor.elec", "sensor.dhw_elec"):
        hass.states.async_set(entity_id, "1.0", ENERGY)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "manual"}
    )
    heating = {"heat_heating": "sensor.heat", "elec_heating": "sensor.elec"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **EMPTY_SECTIONS,
            "heating": heating,
            "dhw": {"heat_dhw": "sensor.dhw_elec", "elec_dhw": "sensor.dhw_elec"},
        },
    )
    assert result["errors"] == {"base": "counter_twice"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**EMPTY_SECTIONS, "heating": heating, "dhw": {"elec_dhw": "sensor.dhw_elec"}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_manual_compressor_only_is_cycling(hass: HomeAssistant) -> None:
    """Without heat counters (ViCare): cycling and electricity only."""
    hass.states.async_set("binary_sensor.compressor", "off")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "manual"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**EMPTY_SECTIONS, "operation": {"compressor": "binary_sensor.compressor"}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "binary_sensor.compressor"


async def test_status_text_as_compressor_is_refused(hass: HomeAssistant) -> None:
    """A status text (Genvex Connect "state_4", issue #4 2026-11-09) never
    tells a run; a capacity in % does."""
    hass.states.async_set("sensor.vmc_status", "state_4")
    hass.states.async_set("sensor.pac_capacity", "0.0", {"unit_of_measurement": "%"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "manual"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**EMPTY_SECTIONS, "operation": {"compressor": "sensor.vmc_status"}},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "compressor_text"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**EMPTY_SECTIONS, "operation": {"compressor": "sensor.pac_capacity"}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_unavailable_compressor_is_no_text(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.pac_capacity", "unavailable")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "manual"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**EMPTY_SECTIONS, "operation": {"compressor": "sensor.pac_capacity"}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_own_sensor_as_source_is_refused(hass: HomeAssistant) -> None:
    """Standby electricity mapped to the entry's own standby sensor (ViCare
    user, 2026-11): the entry would read its own results."""
    hass.states.async_set("binary_sensor.compressor", "off")
    own = er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, "01JZ_standby", suggested_object_id="wp_standby_electricity"
    )
    hass.states.async_set(own.entity_id, "0.5", ENERGY)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "manual"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **EMPTY_SECTIONS,
            "operation": {"compressor": "binary_sensor.compressor"},
            "totals": {"elec_standby": own.entity_id},
        },
    )
    assert result["errors"] == {"base": "own_entity"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**EMPTY_SECTIONS, "operation": {"compressor": "binary_sensor.compressor"}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


def test_look_back_counters_keep_their_section_collapsed() -> None:
    """The EMS-ESP template fills the run time and start counters of heating
    (look-back only): the special meters section stays collapsed; a real
    special meter still opens it."""
    from custom_components.waermewacht.config_flow import entities_schema

    def totals(values: dict[str, str]) -> bool:
        schema = entities_schema(values).schema
        return next(v for k, v in schema.items() if str(k) == "totals").options[
            "collapsed"
        ]

    quiet = {
        "runtime_heating": "sensor.boiler_uptimecompheating",
        "starts_heating": "sensor.boiler_heatingstarts",
    }
    assert totals(quiet) is True
    assert totals({**quiet, "elec_total": "sensor.elec"}) is False


async def test_options(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="WP", data=entry_data())
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "electricity_price": 27.75,
            "design_outdoor_temp": -12.0,
            # Optional: a gas price without base price.
            "costs": {"gas_price": 11.5},
            "limits": {
                "min_electricity": 1.0,
                "short_run_minutes": 12,
                "critical_run_minutes": 5,
                "starts_per_hour": 4,
                "season_start_month": "9",
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["season_start_month"] == "9"
    # Section values are stored flat; empty fields stay unset.
    assert entry.options["electricity_price"] == 27.75
    assert entry.options["gas_price"] == 11.5
    assert "gas_base_price" not in entry.options
    assert entry.options["design_outdoor_temp"] == -12.0
    assert "costs" not in entry.options
    assert "limits" not in entry.options
    # Defaults of fields not sent are stored as well.
    assert entry.options["disinfection_temp"] == 60.0


STORED_OPTIONS = {
    "electricity_price": 27.75,
    "design_outdoor_temp": -12.0,
    "electricity_price_entity": "sensor.price",
    "gas_price": 12.0,
    "grid_import_entity": "sensor.grid_import",
    "feed_in_tariff": 7.94,
    "rated_power_kw": 5.4,
    "min_power_kw": 1.8,
    "min_electricity": 1.0,
    "short_run_minutes": 12,
    "critical_run_minutes": 5,
    "starts_per_hour": 4,
    "starts_per_day": 30,
    "aux_mild_from": 3.0,
    "efficiency_drop_percent": 20,
    "disinfection_temp": 58,
    "season_start_month": "9",
    "sister_suggestions_offered": True,
}


async def test_options_form_few_fields_on_top(hass: HomeAssistant) -> None:
    """Forms got too full (08.11.2026): on top only the electricity price
    and the design outdoor temperature, the rest in sections that start
    collapsed, also with values stored in them."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(), options=STORED_OPTIONS
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    schema = result["data_schema"].schema
    top = [str(k) for k, v in schema.items() if not isinstance(v, section)]
    assert top == ["electricity_price", "design_outdoor_temp"]
    assert collapsed(result) == {
        "costs": True,
        "pv": True,
        "heat_load": True,
        "limits": True,
        "price_change": True,
    }
    # No section has a default (the frontend would take it over the values
    # of its fields), and the fields carry the stored values.
    assert all(
        key.default is type(key)("x").default
        for key, value in schema.items()
        if isinstance(value, section)
    )
    # The summary of the entry on top of the form.
    summary = result["description_placeholders"]["summary"]
    assert summary.startswith("**Set up**\n- **Source:** Template EMS-ESP\n")
    assert "- **Electricity price:** sensor (else 27.75 ct/kWh)" in summary
    assert "- **PV split:** heat pump first" in summary
    sent = unchanged_input(result)
    assert sent["limits"]["short_run_minutes"] == 12
    assert sent["limits"]["starts_per_day"] == 30
    assert sent["pv"]["feed_in_tariff"] == 7.94


async def test_options_saved_unopened_keep_their_values(hass: HomeAssistant) -> None:
    """Saved without opening a section, every stored value stays; also when
    a client leaves a section out entirely."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(), options=STORED_OPTIONS
    )
    entry.add_to_hass(hass)
    for meter in ("sensor.grid_import",):
        hass.states.async_set(meter, "100", KWH)
    hass.states.async_set("sensor.price", "30", {"unit_of_measurement": "ct/kWh"})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], unchanged_input(result)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == STORED_OPTIONS
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"electricity_price": 30.0, "design_outdoor_temp": -12.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {**STORED_OPTIONS, "electricity_price": 30.0}


async def test_options_price_change_from_a_date(hass: HomeAssistant) -> None:
    """A price change is added in its section, listed in the summary, kept
    when saved unchanged and removed again; errors open the section."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(), options=STORED_OPTIONS
    )
    entry.add_to_hass(hass)
    hass.states.async_set("sensor.grid_import", "100", KWH)
    hass.states.async_set("sensor.price", "30", {"unit_of_measurement": "ct/kWh"})

    async def save(change: dict) -> dict:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        sent = unchanged_input(result)
        sent["price_change"] = change
        return await hass.config_entries.options.async_configure(
            result["flow_id"], sent
        )

    result = await save({"change_gas_price": 14.0})
    assert result["errors"] == {"base": "change_from_required"}
    assert collapsed(result)["price_change"] is False
    result = await save({"change_from": "2027-01-01", "change_gas_price": 14.0})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["price_changes"] == [{"from": "2027-01-01", "gas_price": 14.0}]
    # Shown on top, kept when saved unchanged.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    summary = result["description_placeholders"]["summary"]
    assert "- **Price changes:** from 2027-01-01: gas 14 ct/kWh" in summary
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], unchanged_input(result)
    )
    assert entry.options["price_changes"] == [{"from": "2027-01-01", "gas_price": 14.0}]
    result = await save({"remove_change": "2027-01-01"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "price_changes" not in entry.options


async def test_reconfigure_shows_stored_meters_in_their_sections(
    hass: HomeAssistant,
) -> None:
    """Reconfigure: a meter stored before the section "totals" existed (in
    "operation" then) is shown there, its section open; submitted unchanged
    the mapping stays."""
    entities = {
        "heat_heating": "sensor.heat",
        "elec_total": "sensor.elec",
        "compressor": "binary_sensor.compressor",
    }
    for entity_id_ in ("sensor.heat", "sensor.elec"):
        hass.states.async_set(entity_id_, "1.0", ENERGY)
    hass.states.async_set("binary_sensor.compressor", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        unique_id="sensor.heat",
        data={**entry_data(), CONF_TEMPLATE: None, CONF_ENTITIES: entities},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    assert result["step_id"] == "entities"
    sent = unchanged_input(result)
    assert sent["totals"] == {"elec_total": "sensor.elec"}
    shown = collapsed(result)
    assert shown["totals"] is False
    assert shown["cooling"] is True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], sent)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_ENTITIES] == entities


async def test_options_price_sensor_unit(hass: HomeAssistant) -> None:
    """A price sensor in ct/kWh, €/kWh or €/MWh; other units are refused."""
    entry = MockConfigEntry(domain=DOMAIN, title="WP", data=entry_data())
    entry.add_to_hass(hass)
    required = REQUIRED_OPTIONS
    hass.states.async_set("sensor.price", "0.31", {"unit_of_measurement": "EUR"})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**required, "costs": {"electricity_price_entity": "sensor.price"}},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "price_unit"}
    assert result["description_placeholders"]["unit"] == "EUR"

    hass.states.async_set("sensor.price", "120", {"unit_of_measurement": "EUR/MWh"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**required, "costs": {"electricity_price_entity": "sensor.price"}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["electricity_price_entity"] == "sensor.price"
    assert "electricity_price" not in entry.options


KWH = {"unit_of_measurement": "kWh", "device_class": "energy"}


def suggested_costs(result: Any) -> dict[str, Any]:
    """Suggested values of the price and PV sections of an options form."""
    schema = result["data_schema"].schema
    return {
        str(marker): (marker.description or {}).get("suggested_value")
        for name in ("costs", "pv")
        for marker in next(v for k, v in schema.items() if str(k) == name).schema.schema
    }


def collapsed(result: Any) -> dict[str, bool]:
    """Sections of a form and whether they start collapsed."""
    return {
        str(key): value.options["collapsed"]
        for key, value in result["data_schema"].schema.items()
        if isinstance(value, section)
    }


def unchanged_input(result: Any) -> dict[str, Any]:
    """What the frontend sends for a form submitted unchanged, without
    opening a section (computeInitialHaFormData): each field's suggested
    value, else its default; sections nested, collapsed or not."""

    def values(schema: dict[Any, Any]) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for key, value in schema.items():
            if isinstance(value, section):
                data[str(key)] = values(value.schema.schema)
                continue
            suggested = (key.description or {}).get("suggested_value")
            if suggested is not None:
                data[str(key)] = suggested
            elif key.default is not type(key)("x").default:
                data[str(key)] = key.default()
        return data

    return values(result["data_schema"].schema)


def tarifwacht_entry(kind: str) -> MockConfigEntry:
    return MockConfigEntry(
        domain="tarifwacht",
        title="Haus",
        data={"name": "Haus", "meter_entity": "sensor.grid_import"},
        version=2,
        subentries_data=[
            {
                "data": {
                    "feed_in_entity": "sensor.feed_in",
                    "pv_entity": "sensor.pv",
                    "charged_entity": "sensor.charged",
                    "discharged_entity": "sensor.discharged",
                    "feed_in_rate": 7.86,
                    "same_inverter": False,
                },
                "subentry_id": "solar1",
                "subentry_type": "solar",
                "title": "PV",
                "unique_id": None,
            },
            {
                "data": {
                    "kind": kind,
                    "current": True,
                    "price_entity": "sensor.tibber_price",
                },
                "subentry_id": "tariff1",
                "subentry_type": "tariff",
                "title": "Tibber",
                "unique_id": None,
            },
        ],
    )


async def test_options_suggest_meters_and_price_from_tarifwacht(
    hass: HomeAssistant,
) -> None:
    tarifwacht_entry("dynamic_total").add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="WP", data=entry_data())
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init_tarifwacht"
    assert result["description_placeholders"]["entry"] == "Haus"
    suggested = suggested_costs(result)
    assert suggested["electricity_price_entity"] == "sensor.tibber_price"
    assert suggested["feed_in_entity"] == "sensor.feed_in"
    assert suggested["pv_entity"] == "sensor.pv"
    assert suggested["battery_charged_entity"] == "sensor.charged"
    assert suggested["feed_in_tariff"] == 7.86
    # The grid import meter switches the split on: never suggested.
    assert suggested["grid_import_entity"] is None
    # The sections with suggestions are open, the others collapsed.
    assert collapsed(result) == {
        "costs": False,
        "pv": False,
        "heat_load": True,
        "limits": True,
        "price_change": True,
    }


async def test_exchange_price_of_tarifwacht_is_not_suggested(
    hass: HomeAssistant,
) -> None:
    """A tariff "exchange price plus surcharges" has no full price sensor."""
    tarifwacht_entry("dynamic_market").add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="WP", data=entry_data())
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    suggested = suggested_costs(result)
    assert suggested["electricity_price_entity"] is None
    assert suggested["feed_in_entity"] == "sensor.feed_in"


async def test_options_suggest_from_einspeisewacht_once(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain="einspeisewacht",
        title="PV Dach",
        data={"meter_entity": "sensor.feed_in", "rates": [7.86]},
    ).add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="WP", data=entry_data())
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init_einspeisewacht"
    assert result["description_placeholders"]["entry"] == "PV Dach"
    assert suggested_costs(result)["feed_in_entity"] == "sensor.feed_in"
    # Saved without the suggestion (fields cleared): not suggested again.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**REQUIRED_OPTIONS, "pv": {}}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "feed_in_entity" not in entry.options
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    assert suggested_costs(result)["feed_in_entity"] is None


async def test_options_tip_without_sisters(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="WP", data=entry_data())
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init_tip"
    assert result["description_placeholders"]["tarifwacht_url"] == (
        "https://github.com/tarifwacht/integration"
    )


async def test_options_house_meters(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="WP", data=entry_data())
    entry.add_to_hass(hass)
    for meter in ("sensor.grid_import", "sensor.charged", "sensor.discharged"):
        hass.states.async_set(meter, "100", KWH)
    hass.states.async_set("sensor.pv_power", "100", {"unit_of_measurement": "W"})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **REQUIRED_OPTIONS,
            "pv": {
                "grid_import_entity": "sensor.grid_import",
                "battery_charged_entity": "sensor.charged",
            },
        },
    )
    assert result["errors"] == {"base": "battery_both"}
    # The section the error is about is open.
    assert collapsed(result)["pv"] is False
    assert collapsed(result)["limits"] is True
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **REQUIRED_OPTIONS,
            "pv": {
                "grid_import_entity": "sensor.grid_import",
                "pv_entity": "sensor.pv_power",
            },
        },
    )
    assert result["errors"] == {"base": "meter_unit"}
    assert result["description_placeholders"]["entity"] == "sensor.pv_power"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **REQUIRED_OPTIONS,
            "electricity_price": 30.0,
            "pv": {
                "grid_import_entity": "sensor.grid_import",
                "battery_charged_entity": "sensor.charged",
                "battery_discharged_entity": "sensor.discharged",
                "feed_in_tariff": 8.0,
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["grid_import_entity"] == "sensor.grid_import"
    assert entry.options["feed_in_tariff"] == 8.0


async def test_new_template_signals_are_taken_over(hass: HomeAssistant) -> None:
    """An entry from before the hot water temperature existed gets it."""
    add_ems_esp(hass)
    registry = er.async_get(hass)
    found = registry.async_get_or_create(
        "sensor", "mqtt", "boiler_dhw_curtemp", suggested_object_id="boiler_dhw_curtemp"
    )
    hass.states.async_set(found.entity_id, "47.5", {"unit_of_measurement": "°C"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data=entry_data(
            entities={
                "heat_heating": "sensor.boiler_nrgheat",
                "elec_heating": "sensor.boiler_meterheat",
                "compressor": "binary_sensor.boiler_hpcompon",
            }
        ),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.data[CONF_ENTITIES]["dhw_temp"] == found.entity_id
    # Known from now on: removing it by hand keeps it removed.
    assert "dhw_temp" in entry.data["template_signals"]


async def test_reconfigure_own_mapping_moves_the_unique_id(hass: HomeAssistant) -> None:
    """An own mapping is identified by its first counter, also after a change;
    not when another entry already carries the new one."""
    for entity_id in ("sensor.heat", "sensor.heat_new", "sensor.elec"):
        hass.states.async_set(entity_id, "1.0", ENERGY)
    entities = {"heat_heating": "sensor.heat", "elec_heating": "sensor.elec"}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        unique_id="sensor.heat",
        data=entry_data(**{CONF_TEMPLATE: None, CONF_ENTITIES: entities}),
    )
    entry.add_to_hass(hass)

    async def reconfigure(heat: str) -> None:
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                **EMPTY_SECTIONS,
                "heating": {"heat_heating": heat, "elec_heating": "sensor.elec"},
            },
        )
        assert result["reason"] == "reconfigure_successful"

    await reconfigure("sensor.heat_new")
    assert entry.unique_id == "sensor.heat_new"
    MockConfigEntry(domain=DOMAIN, unique_id="sensor.heat").add_to_hass(hass)
    await reconfigure("sensor.heat")
    assert entry.unique_id == "sensor.heat_new"


async def test_reconfigure_found_heat_pump_keeps_the_unique_id(
    hass: HomeAssistant,
) -> None:
    """A found heat pump is identified by its source, not by a counter."""
    for entity_id in ("sensor.heat", "sensor.elec"):
        hass.states.async_set(entity_id, "1.0", ENERGY)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        unique_id="ems_esp:boiler",
        data=entry_data(),
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        form_input(
            result,
            heating={"heat_heating": "sensor.heat", "elec_heating": "sensor.elec"},
        ),
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == "ems_esp:boiler"
