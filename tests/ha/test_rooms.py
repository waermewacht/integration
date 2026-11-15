"""Heating curve check: rooms from areas, sampled each minute, in the diary
(made-up values)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.const import (
    CONF_ROOM_ENTITIES,
    CONF_VALVE_ENTITIES,
    DOMAIN,
)

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
CLIMATE = "climate.living"
THERMO = "sensor.hall_temperature"
VALVE = "sensor.hall_valve"
LOOSE = "sensor.loose_valve"


def make_rooms(hass: HomeAssistant) -> tuple[str, str]:
    areas = ar.async_get(hass)
    living = areas.async_create("Wohnzimmer").id
    hall = areas.async_create("Flur").id
    registry = er.async_get(hass)
    for entity_id, area in (
        (CLIMATE, living),
        (THERMO, hall),
        (VALVE, hall),
        (LOOSE, None),
    ):
        domain, object_id = entity_id.split(".")
        entry = registry.async_get_or_create(
            domain, "test", object_id, suggested_object_id=object_id
        )
        if area:
            registry.async_update_entity(entry.entity_id, area_id=area)
    hass.states.async_set(
        CLIMATE,
        "heat",
        {"current_temperature": 22.8, "temperature": 22.5, "valve_position": 12},
    )
    hass.states.async_set(THERMO, "20.6", TEMPERATURE)
    hass.states.async_set(VALVE, "40", {"unit_of_measurement": "%"})
    hass.states.async_set(LOOSE, "10", {"unit_of_measurement": "%"})
    return living, hall


async def setup(hass: HomeAssistant, **options) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    set_counters(hass, 1000.5, 300.5)
    hass.states.async_set(HEAT_DHW, "500.5", ENERGY)
    hass.states.async_set(ELEC_DHW, "200.5", ENERGY)
    hass.states.async_set(COMPRESSOR, "off")
    hass.states.async_set(ACTIVITY, "aus")
    hass.states.async_set(FLOW, "28.0", TEMPERATURE)
    hass.states.async_set(RETURN, "24.0", TEMPERATURE)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data=entry_data(entities=dict(ENTITIES)),
        options=options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str):
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{key}"
    )


@pytest.mark.freeze_time(START)
async def test_no_check_without_rooms(hass: HomeAssistant) -> None:
    entry = await setup(hass)
    assert entity_id(hass, entry, "binary_sensor", "heating_curve_high") is None


@pytest.mark.freeze_time(START)
async def test_rooms_from_areas_into_the_diary(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    living, hall = make_rooms(hass)
    entry = await setup(
        hass,
        **{
            CONF_ROOM_ENTITIES: [CLIMATE, THERMO],
            CONF_VALVE_ENTITIES: [VALVE, LOOSE],
            "room_target": 21.0,
        },
    )
    runtime = entry.runtime_data
    assert set(runtime.room_map.rooms) == {living, hall}
    assert runtime.room_map.no_area == [LOOSE]
    assert runtime.room_map.rooms[hall].valves == [VALVE]

    # The check exists, without a verdict before the days.
    found = entity_id(hass, entry, "binary_sensor", "heating_curve_high")
    state = hass.states.get(found)
    assert state.state == "unknown"
    assert state.attributes["reason"] == "too_few_days"
    assert sorted(state.attributes["rooms_set"]) == ["Flur", "Wohnzimmer"]
    assert state.attributes["without_area"] == [LOOSE]
    status = entity_id(hass, entry, "sensor", "heating_curve_high_status")
    assert hass.states.get(status).state == "too_few_days"

    # Sampled once a minute: the wish temperature replaces the setpoint.
    await tick(hass, freezer, 1)
    await tick(hass, freezer, 1)
    await tick(hass, freezer, 1)
    log = runtime.room_log.rooms
    assert log[living].delta.value == pytest.approx(1.8)
    assert log[living].valve.value == pytest.approx(12)
    assert log[hall].delta.value == pytest.approx(-0.4)
    assert log[hall].valve.value == pytest.approx(40)

    # At midnight the day goes into the diary and the means start again.
    await tick(hass, freezer, 18 * 60)
    entry_day = runtime.diary[-1]
    assert entry_day["rooms"][living]["delta"] == pytest.approx(1.8)
    assert entry_day["rooms"][hall]["valve_max"] == pytest.approx(40)
    assert runtime.room_log.rooms.get(living) is None or (
        runtime.room_log.rooms[living].delta.seconds < 3600
    )


@pytest.mark.freeze_time(START)
async def test_thermostat_off_takes_the_room_out(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    living, _hall = make_rooms(hass)
    hass.states.async_set(CLIMATE, "off", {"current_temperature": 18.0})
    entry = await setup(hass, **{CONF_ROOM_ENTITIES: [CLIMATE]})
    await tick(hass, freezer, 1)
    await tick(hass, freezer, 1)
    assert living not in entry.runtime_data.room_log.rooms
