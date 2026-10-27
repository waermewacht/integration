"""Hot water charges through real state changes: a charge with late heat,
the thermal disinfection and the backup heater check."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.const import DOMAIN

from .conftest import (
    ACTIVITY,
    COMPRESSOR,
    ELEC_DHW,
    ENERGY,
    ENTITIES,
    FLOW,
    HEAT_DHW,
    RETURN,
    TEMPERATURE,
    entry_data,
)
from .test_init import set_counters, tick

# 15.01.2026 07:00:30 CET.
START = datetime(2026, 1, 15, 6, 0, 30, tzinfo=UTC)
DHW_TEMP = "sensor.boiler_dhw_curtemp"
AUX_DHW = "sensor.boiler_dhw_auxelecheatnrgcons"


async def setup(hass: HomeAssistant) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    set_counters(hass, 1000.5, 300.5)
    hass.states.async_set(HEAT_DHW, "500.5", ENERGY)
    hass.states.async_set(ELEC_DHW, "200.5", ENERGY)
    hass.states.async_set(AUX_DHW, "10", ENERGY)
    hass.states.async_set(COMPRESSOR, "off")
    hass.states.async_set(ACTIVITY, "aus")
    hass.states.async_set(FLOW, "28.0", TEMPERATURE)
    hass.states.async_set(RETURN, "24.0", TEMPERATURE)
    hass.states.async_set(DHW_TEMP, "45.0", TEMPERATURE)
    entities = {**ENTITIES, "dhw_temp": DHW_TEMP, "aux_dhw": AUX_DHW}
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(entities=entities)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str):
    found = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert found, key
    return found


@pytest.mark.freeze_time(START)
async def test_charge_disinfection_and_backup_heater_check(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    last = entity_id(hass, entry, "sensor", "ratio_dhw_last_charge")
    disinfection = entity_id(hass, entry, "sensor", "last_disinfection")
    check = entity_id(hass, entry, "binary_sensor", "aux_dhw_charges")
    assert hass.states.get(last).state == "unknown"
    assert hass.states.get(disinfection).state == "unknown"

    hass.states.async_set(COMPRESSOR, "on")
    hass.states.async_set(ACTIVITY, "Warmwasser")
    await tick(hass, freezer, 1)
    hass.states.async_set(DHW_TEMP, "52.0", TEMPERATURE)
    hass.states.async_set(HEAT_DHW, "502.5", ENERGY)
    hass.states.async_set(ELEC_DHW, "201.1", ENERGY)
    await tick(hass, freezer, 20)
    hass.states.async_set(COMPRESSOR, "off")
    hass.states.async_set(ACTIVITY, "aus")
    await tick(hass, freezer, 1)
    hass.states.async_set(HEAT_DHW, "502.8", ENERGY)  # reported late
    await tick(hass, freezer, 1)
    assert hass.states.get(last).state == "unknown"  # still taking late energy
    await tick(hass, freezer, 5)

    state = hass.states.get(last)
    assert float(state.state) == pytest.approx(2.3 / 0.6, abs=0.01)
    assert state.attributes["start_temp"] == 45.0
    assert state.attributes["max_temp"] == 52.0
    assert state.attributes["disinfection"] is False
    assert entry.runtime_data.charges[0].heat_kwh == pytest.approx(2.3)

    check_state = hass.states.get(check)
    assert check_state.state == "unknown"
    assert check_state.attributes["reason"] == "too_few_charges"
    assert check_state.attributes["charges"] == 1

    hass.states.async_set(DHW_TEMP, "61.0", TEMPERATURE)
    await tick(hass, freezer, 1)
    assert hass.states.get(disinfection).state != "unknown"
    first = entry.runtime_data.last_disinfection
    # Staying hot or dipping a little is the same disinfection.
    hass.states.async_set(DHW_TEMP, "58.0", TEMPERATURE)
    hass.states.async_set(DHW_TEMP, "60.5", TEMPERATURE)
    await tick(hass, freezer, 1)
    assert entry.runtime_data.last_disinfection == first
