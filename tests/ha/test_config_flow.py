"""Config flow: EMS-ESP detection, manual mapping, errors, options."""

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
    assert result["description_placeholders"] == {"found": "1"}
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
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["season_start_month"] == "9"
