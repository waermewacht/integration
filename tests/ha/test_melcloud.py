"""Mitsubishi Ecodan via MELCloud: day values without a compressor."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.const import (
    CONF_ENTITIES,
    CONF_NAME,
    CONF_TEMPLATE,
    DOMAIN,
)

from .conftest import ENERGY
from .test_init import START, tick, value

S = "sensor.ecodan_"
HEAT = S + "daily_heating_energy_produced"
ELEC = S + "daily_heating_energy_consumed"


@pytest.mark.freeze_time(START)
async def test_ratio_from_day_values_without_compressor(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(HEAT, "10.0", ENERGY)
    hass.states.async_set(ELEC, "3.0", ENERGY)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data={
            CONF_NAME: "WP",
            CONF_TEMPLATE: "melcloud",
            CONF_ENTITIES: {"heat_heating": HEAT, "elec_heating": ELEC},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    keys = {
        e.unique_id.removeprefix(f"{entry.entry_id}_")
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    assert "ratio_heating_month" in keys
    assert "starts_today" not in keys and "cycling_problem" not in keys

    await tick(hass, freezer, 60)
    hass.states.async_set(ELEC, "4.0", ENERGY)
    hass.states.async_set(HEAT, "14.0", ENERGY)
    await tick(hass, freezer, 1)
    await tick(hass, freezer, 150)  # past the wait for heat of the same fetch
    assert value(hass, entry, "electricity_heating") == pytest.approx(1.0)
    assert value(hass, entry, "standby") == 0
    assert value(hass, entry, "ratio_heating_month") == pytest.approx(4.0)
