"""Renamed source entities: the entries follow without reconfiguring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.waermewacht.const import CONF_ENTITIES, CONF_HISTORY, DOMAIN
from custom_components.waermewacht.model import Signal

from .conftest import (
    ACTIVITY,
    COMPRESSOR,
    ELEC_DHW,
    ELEC_HEATING,
    ENERGY,
    ENTITIES,
    FLOW,
    HEAT_DHW,
    HEAT_HEATING,
    RETURN,
    TEMPERATURE,
    entry_data,
)

# 15.01.2026 07:00:30 CET.
START = datetime(2026, 1, 15, 6, 0, 30, tzinfo=UTC)
STATES = {
    HEAT_HEATING: ("1000.0", ENERGY),
    ELEC_HEATING: ("300.0", ENERGY),
    HEAT_DHW: ("500.0", ENERGY),
    ELEC_DHW: ("200.0", ENERGY),
    COMPRESSOR: ("off", {}),
    ACTIVITY: ("aus", {}),
    FLOW: ("28.0", TEMPERATURE),
    RETURN: ("24.0", TEMPERATURE),
}


async def wait(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def register(hass: HomeAssistant, entity_id: str) -> None:
    """A source in the entity registry (renaming needs one)."""
    domain, object_id = entity_id.split(".")
    found = er.async_get(hass).async_get_or_create(
        domain, "test", object_id, suggested_object_id=object_id
    )
    assert found.entity_id == entity_id


async def setup(hass: HomeAssistant, **data: object) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    for entity_id, (value, attributes) in STATES.items():
        if er.async_get(hass).async_get(entity_id) is None:
            register(hass, entity_id)
        hass.states.async_set(entity_id, value, attributes)
    entry = MockConfigEntry(domain=DOMAIN, title="WP", **data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def rename(hass: HomeAssistant, old: str, new: str) -> None:
    """As Home Assistant does it: the entity comes back under the new id."""
    state = hass.states.get(old)
    er.async_get(hass).async_update_entity(old, new_entity_id=new)
    hass.states.async_remove(old)
    if state is not None:
        hass.states.async_set(new, state.state, state.attributes)


@pytest.mark.freeze_time(START)
async def test_source_renamed(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(
        hass,
        data=entry_data(**{CONF_HISTORY: {HEAT_HEATING: ["sensor.boiler_nrgheat_v1"]}}),
    )
    before = entry.runtime_data
    # A verdict made for the flow and return sensors (books on unload).
    before._swapped = -3.0

    rename(hass, HEAT_HEATING, "sensor.wp_nrgheat")
    rename(hass, FLOW, "sensor.wp_flow")
    await hass.async_block_till_done()
    # The data follows at once, the reload waits for the end of the burst.
    assert entry.data[CONF_ENTITIES]["heat_heating"] == "sensor.wp_nrgheat"
    assert entry.data[CONF_ENTITIES]["flow_temp"] == "sensor.wp_flow"
    assert entry.data[CONF_HISTORY] == {
        "sensor.wp_nrgheat": ["sensor.boiler_nrgheat_v1"]
    }
    assert entry.runtime_data is before

    await wait(hass, freezer, 5)
    assert entry.state is ConfigEntryState.LOADED
    runtime = entry.runtime_data
    assert runtime is not before
    assert runtime.entities[Signal.HEAT_HEATING] == "sensor.wp_nrgheat"
    assert runtime._swapped == -3.0

    # No repair issue after the grace time.
    await wait(hass, freezer, 15 * 60)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"{entry.entry_id}_missing_entity") is None


@pytest.mark.freeze_time(START)
async def test_renamed_twice_and_shared(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Two entries with the same counter; renamed again before the reload."""
    first = await setup(hass, data=entry_data(), unique_id="ems_esp:boiler")
    manual = await setup(hass, data=entry_data(template=None), unique_id=HEAT_HEATING)

    rename(hass, HEAT_HEATING, "sensor.wp_nrgheat")
    await wait(hass, freezer, 1)
    rename(hass, "sensor.wp_nrgheat", "sensor.heat_pump_heat")
    await wait(hass, freezer, 5)

    for entry in (first, manual):
        assert entry.state is ConfigEntryState.LOADED
        assert entry.data[CONF_ENTITIES]["heat_heating"] == "sensor.heat_pump_heat"
        assert entry.runtime_data.entities[Signal.HEAT_HEATING] == (
            "sensor.heat_pump_heat"
        )
    # A template entry is known by template and prefix, a manual one by its
    # first energy entity.
    assert first.unique_id == "ems_esp:boiler"
    assert manual.unique_id == "sensor.heat_pump_heat"


@pytest.mark.freeze_time(START)
async def test_rename_onto_another_source(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The new id is already a source of the entry: nothing changes."""
    entry = await setup(hass, data=entry_data())
    er.async_get(hass).async_remove(ELEC_HEATING)
    hass.states.async_remove(ELEC_HEATING)

    rename(hass, HEAT_HEATING, ELEC_HEATING)
    await wait(hass, freezer, 5)
    assert entry.data[CONF_ENTITIES] == ENTITIES
    assert entry.state is ConfigEntryState.LOADED


@pytest.mark.freeze_time(START)
async def test_other_changes_ignored(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A new name or a removed entity is not a rename."""
    entry = await setup(hass, data=entry_data())
    before = entry.runtime_data
    er.async_get(hass).async_update_entity(HEAT_HEATING, name="Wärme Heizen")
    er.async_get(hass).async_remove(FLOW)
    await wait(hass, freezer, 5)
    assert entry.data[CONF_ENTITIES] == ENTITIES
    assert entry.runtime_data is before
