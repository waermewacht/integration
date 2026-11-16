"""Heating curve check: rooms from areas, sampled each minute, in the diary
(made-up values)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
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


@pytest.mark.freeze_time(START)
async def test_widest_valve_of_a_room_counts(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A heating group's valve_position and a valve sensor in one area: the
    widest counts (Homematic IP reports its widest channel the same way)."""
    living, _hall = make_rooms(hass)
    areas = ar.async_get(hass)
    registry = er.async_get(hass)
    registry.async_update_entity(LOOSE, area_id=living)
    hass.states.async_set(LOOSE, "55", {"unit_of_measurement": "%"})
    entry = await setup(
        hass, **{CONF_ROOM_ENTITIES: [CLIMATE], CONF_VALVE_ENTITIES: [LOOSE]}
    )
    assert areas.async_get_area(living) is not None
    await tick(hass, freezer, 1)
    await tick(hass, freezer, 1)
    assert entry.runtime_data.room_log.rooms[living].valve.value == pytest.approx(55)


@pytest.mark.freeze_time(START)
async def test_options_show_the_rooms_before_saving(hass: HomeAssistant) -> None:
    """Changed rooms: a check step lists each room with its values and
    sources; "Change" goes back to the form with the rooms open, "Right"
    saves. Unchanged rooms save directly."""
    make_rooms(hass)
    entry = await setup(hass)

    async def submit(rooms: dict) -> dict:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        return await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"electricity_price": 30.0, "design_outdoor_temp": -12.0, "rooms": rooms},
        )

    result = await submit(
        {CONF_ROOM_ENTITIES: [CLIMATE, THERMO], CONF_VALVE_ENTITIES: [VALVE, LOOSE]}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "rooms_check"
    check = result["description_placeholders"]["check"]
    assert (
        "- **Wohnzimmer:** 22.8 °C, target 22.5 °C, valve 12 % · from climate.living"
        in check
    )
    assert "- **Flur:** 20.6 °C (from sensor.hall_temperature)" in check
    assert "- **Without an area, not counted:** sensor.loose_valve" in check
    assert CONF_ROOM_ENTITIES not in entry.options

    # Change: the form again, with what was entered and the rooms open.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "rooms_change"}
    )
    assert result["type"] is FlowResultType.FORM
    rooms_section = next(
        v for k, v in result["data_schema"].schema.items() if str(k) == "rooms"
    )
    assert rooms_section.options["collapsed"] is False
    suggested = {
        str(k): (k.description or {}).get("suggested_value")
        for k in rooms_section.schema.schema
    }
    assert suggested[CONF_ROOM_ENTITIES] == [CLIMATE, THERMO]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "electricity_price": 30.0,
            "design_outdoor_temp": -12.0,
            "rooms": {CONF_ROOM_ENTITIES: [CLIMATE]},
        },
    )
    assert result["step_id"] == "rooms_check"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "rooms_ok"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ROOM_ENTITIES] == [CLIMATE]
    assert entry.options["electricity_price"] == 30.0
    await hass.async_block_till_done()

    # Unchanged rooms: saved without the check.
    result = await submit({CONF_ROOM_ENTITIES: [CLIMATE]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
