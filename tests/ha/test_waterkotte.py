"""Waterkotte: compressor electricity as one meter for all modes (ELEC_TOTAL)."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.const import (
    CONF_ENTITIES,
    CONF_NAME,
    CONF_TEMPLATE,
    DOMAIN,
)
from custom_components.waermewacht.energy import Kind
from custom_components.waermewacht.model import Mode

from .conftest import ENERGY
from .test_init import START, tick, value

HEAT = "sensor.wkh_heating_energy_production_year"
HEAT_DHW = "sensor.wkh_hot_water_energy_production_year"
ELEC = "sensor.wkh_compressor_electric_consumption_year"
COMPRESSOR = "binary_sensor.wkh_state_compressor"
WATER = "binary_sensor.wkh_state_water"
HEATING = "binary_sensor.wkh_status_heating"


@pytest.mark.freeze_time(START)
async def test_elec_total_follows_the_running_mode(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(HEAT, "6000.0", ENERGY)
    hass.states.async_set(HEAT_DHW, "1000.0", ENERGY)
    hass.states.async_set(ELEC, "2000.0", ENERGY)
    hass.states.async_set(COMPRESSOR, "on")
    hass.states.async_set(WATER, "off")
    hass.states.async_set(HEATING, "on")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data={
            CONF_NAME: "WP",
            CONF_TEMPLATE: "waterkotte",
            CONF_ENTITIES: {
                "heat_heating": HEAT,
                "heat_dhw": HEAT_DHW,
                "elec_total": ELEC,
                "compressor": COMPRESSOR,
                "dhw_flag": WATER,
                "heating_flag": HEATING,
            },
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass, freezer, 11)

    # Heating runs.
    hass.states.async_set(HEAT, "6002.0", ENERGY)
    hass.states.async_set(ELEC, "2000.5", ENERGY)
    await tick(hass, freezer, 30)
    assert value(hass, entry, "electricity_heating") == pytest.approx(0.5)

    # Hot water runs.
    hass.states.async_set(WATER, "on")
    await tick(hass, freezer, 5)
    hass.states.async_set(HEAT_DHW, "1001.0", ENERGY)
    hass.states.async_set(ELEC, "2000.8", ENERGY)
    await tick(hass, freezer, 30)
    assert value(hass, entry, "electricity_dhw") == pytest.approx(0.3)
    assert value(hass, entry, "electricity_heating") == pytest.approx(0.5)

    # Standstill: electricity without a run and without heat is standby.
    hass.states.async_set(WATER, "off")
    hass.states.async_set(COMPRESSOR, "off")
    await tick(hass, freezer, 60)
    hass.states.async_set(ELEC, "2000.9", ENERGY)
    await tick(hass, freezer, 60)
    hass.states.async_set(ELEC, "2000.92", ENERGY)
    await tick(hass, freezer, 1)
    totals = entry.runtime_data.totals
    # The first rise after the stop still belongs to the run.
    assert totals.get(Kind.ELEC, Mode.HEATING) == pytest.approx(0.6)
    assert totals.get(Kind.STANDBY, Mode.HEATING) == pytest.approx(0.02)
