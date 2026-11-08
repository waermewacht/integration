"""One heat meter for heating and hot water (heat_total): live booking by the
running mode, the setup form and its check, the diagnostics."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.const import (
    CONF_ENTITIES,
    CONF_NAME,
    CONF_TEMPLATE,
    DOMAIN,
)
from custom_components.waermewacht.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.waermewacht.energy import Kind
from custom_components.waermewacht.model import Mode

from .conftest import ENERGY
from .test_config_flow import EMPTY_SECTIONS
from .test_init import START, entity_id, tick, value

HEAT = "sensor.wmz_energy"
ELEC_HEATING = "sensor.wp_elec_heating"
ELEC_DHW = "sensor.wp_elec_dhw"
COMPRESSOR = "binary_sensor.wp_compressor"
ACTIVITY = "sensor.wp_activity"


@pytest.mark.freeze_time(START)
async def test_heat_total_follows_the_running_mode(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(HEAT, "1000.0", ENERGY)
    hass.states.async_set(ELEC_HEATING, "500.0", ENERGY)
    hass.states.async_set(ELEC_DHW, "300.0", ENERGY)
    hass.states.async_set(COMPRESSOR, "on")
    hass.states.async_set(ACTIVITY, "Heizen")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data={
            CONF_NAME: "WP",
            CONF_TEMPLATE: None,
            CONF_ENTITIES: {
                "heat_total": HEAT,
                "elec_heating": ELEC_HEATING,
                "elec_dhw": ELEC_DHW,
                "compressor": COMPRESSOR,
                "activity": ACTIVITY,
            },
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # Heat sensors for heating and hot water, none for cooling.
    entity_id(hass, entry, "heat_heating")
    entity_id(hass, entry, "heat_dhw")
    await tick(hass, freezer, 11)

    # Heating.
    hass.states.async_set(HEAT, "1002.0", ENERGY)
    hass.states.async_set(ELEC_HEATING, "500.5", ENERGY)
    await tick(hass, freezer, 30)
    assert value(hass, entry, "heat_heating") == pytest.approx(2.0)

    # Hot water: the same meter, now hot water.
    hass.states.async_set(ACTIVITY, "Warmwasser")
    await tick(hass, freezer, 5)
    hass.states.async_set(HEAT, "1003.5", ENERGY)
    hass.states.async_set(ELEC_DHW, "300.6", ENERGY)
    await tick(hass, freezer, 30)
    assert value(hass, entry, "heat_dhw") == pytest.approx(1.5)
    assert value(hass, entry, "heat_heating") == pytest.approx(2.0)

    # A defrost and the pump overrun after the stop: the mode that ran.
    hass.states.async_set(ACTIVITY, "Abtauen")
    await tick(hass, freezer, 1)
    hass.states.async_set(HEAT, "1003.6", ENERGY)
    await tick(hass, freezer, 3)
    hass.states.async_set(ACTIVITY, "aus")
    hass.states.async_set(COMPRESSOR, "off")
    await tick(hass, freezer, 1)
    hass.states.async_set(HEAT, "1003.8", ENERGY)
    await tick(hass, freezer, 1)
    totals = entry.runtime_data.totals
    assert totals.get(Kind.HEAT, Mode.DHW) == pytest.approx(1.8)

    # Cooling: a heat meter counts no heat then; what it counts is not booked.
    hass.states.async_set(COMPRESSOR, "on")
    hass.states.async_set(ACTIVITY, "Kühlen")
    await tick(hass, freezer, 5)
    hass.states.async_set(HEAT, "1004.1", ENERGY)
    await tick(hass, freezer, 5)
    assert totals.get(Kind.HEAT, Mode.HEATING) == pytest.approx(2.0)
    assert totals.get(Kind.HEAT, Mode.DHW) == pytest.approx(1.8)
    assert totals.get(Kind.HEAT, Mode.COOLING) == 0

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["events"]["heat_total_not_booked:cooling"] == 1
    assert "heat_total" in diagnostics["config"]["entities"]
    assert diagnostics["states"]["heat_total"]["state"] == "1004.1"
    assert diagnostics["booking"]["heat_modes"] == ["dhw", "heating"]


async def test_heat_total_in_the_form(hass: HomeAssistant) -> None:
    """Either one heat meter for all or per mode; with it a mode is complete."""
    for entity_id_ in ("sensor.heat", "sensor.heat_heating", "sensor.elec"):
        hass.states.async_set(entity_id_, "1.0", ENERGY)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "manual"}
    )
    # The field is in the form.
    fields = {
        str(key)
        for section in result["data_schema"].schema.values()
        for key in section.schema.schema
    }
    assert "heat_total" in fields
    totals_input = {"heat_total": "sensor.heat", "elec_total": "sensor.elec"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **EMPTY_SECTIONS,
            "heating": {"heat_heating": "sensor.heat_heating"},
            **_with(totals_input),
        },
    )
    assert result["errors"] == {"base": "heat_twice"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**EMPTY_SECTIONS, **_with(totals_input)}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ENTITIES] == {
        "heat_total": "sensor.heat",
        "elec_total": "sensor.elec",
    }


def _with(fields: dict[str, str]) -> dict[str, dict[str, str]]:
    """The fields in the section of the form that holds them."""
    from custom_components.waermewacht.config_flow import SECTIONS

    result: dict[str, dict[str, str]] = {}
    for name, signals in SECTIONS.items():
        for signal in signals:
            if signal.value in fields:
                result.setdefault(name, {})[signal.value] = fields[signal.value]
    return result
