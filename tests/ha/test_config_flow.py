"""Config flow: detection (EMS-ESP, Bosch HomeCom), manual mapping, errors, options."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.const import CONF_ENTITIES, CONF_TEMPLATE, DOMAIN

from .conftest import ENERGY, entry_data

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
    assert result["description_placeholders"] == {"found": "1", "disabled": "–"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "ems_esp:"}
    )
    assert result["step_id"] == "entities"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **EMPTY_SECTIONS,
            "heating": {
                "heat_heating": "sensor.boiler_nrgheat",
                "elec_heating": "sensor.boiler_meterheat",
            },
            "operation": {"compressor": "binary_sensor.boiler_hpcompon"},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "WP"
    assert result["data"][CONF_TEMPLATE] == "ems_esp"
    assert (
        result["data"][CONF_ENTITIES]["compressor"] == "binary_sensor.boiler_hpcompon"
    )
    assert result["result"].unique_id == "ems_esp:"


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
    assert result["description_placeholders"] == {
        "found": "0",
        "disabled": "sensor.boschcom_k40_101234567_energy_compressor_ch, "
        "sensor.boschcom_k40_101234567_heat_produced_ch",
    }


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
        {
            **EMPTY_SECTIONS,
            "heating": {
                "heat_heating": "sensor.boschcom_k40_101234567_heat_produced_ch",
                "elec_heating": "sensor.boschcom_k40_101234567_energy_compressor_ch",
            },
            "operation": {
                "compressor": "sensor.boschcom_k40_101234567_local_compressor_speed"
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TEMPLATE] == "bosch_homecom"


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


async def test_options(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="WP", data=entry_data())
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "min_electricity": 1.0,
            "short_run_minutes": 12,
            "critical_run_minutes": 5,
            "starts_per_hour": 4,
            "season_start_month": "9",
            # Optional: a gas price without base price.
            "costs": {"electricity_price": 27.75, "gas_price": 11.5},
            "heat_load": {"design_outdoor_temp": -12.0},
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
