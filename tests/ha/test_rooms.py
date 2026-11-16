"""Heating curve check: rooms from areas, sampled each minute, in the diary
(made-up values)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.const import (
    CONF_ROOM_ENTITIES,
    CONF_VALVE_ENTITIES,
    DOMAIN,
)
from custom_components.waermewacht.room_sources import (
    KIND_VALVES,
    level_number,
    target_entities,
    valve_value,
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
        {
            CONF_ROOM_ENTITIES: {"entity_id": [CLIMATE, THERMO]},
            CONF_VALVE_ENTITIES: {"entity_id": [VALVE, LOOSE]},
        }
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
    assert suggested[CONF_ROOM_ENTITIES] == {"entity_id": [CLIMATE, THERMO]}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "electricity_price": 30.0,
            "design_outdoor_temp": -12.0,
            "rooms": {CONF_ROOM_ENTITIES: {"entity_id": [CLIMATE]}},
        },
    )
    assert result["step_id"] == "rooms_check"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "rooms_ok"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ROOM_ENTITIES] == {"entity_id": [CLIMATE]}
    assert entry.options["electricity_price"] == 30.0
    await hass.async_block_till_done()

    # Unchanged rooms: saved without the check.
    result = await submit({CONF_ROOM_ENTITIES: {"entity_id": [CLIMATE]}})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


@pytest.mark.freeze_time(START)
async def test_other_valve_sources_and_found_valves(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Netatmo's heating_power_request on the climate, a Bosch Smart Home
    valve with its position; the check names a disabled valve sensor found in
    a room without a valve."""
    living, hall = make_rooms(hass)
    registry = er.async_get(hass)
    hass.states.async_set(
        CLIMATE,
        "heat",
        {"current_temperature": 21.0, "temperature": 21.0, "heating_power_request": 30},
    )
    bosch = registry.async_get_or_create("valve", "bosch_shc", "hall_valve")
    registry.async_update_entity(bosch.entity_id, area_id=hall)
    hass.states.async_set(bosch.entity_id, "open", {"current_position": 65})
    hidden = registry.async_get_or_create(
        "sensor",
        "homematicip_local",
        "bath_level",
        suggested_object_id="bath_valve_opening",
        original_name="Valve opening",
        unit_of_measurement="%",
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    bath = ar.async_get(hass).async_create("Bad").id
    registry.async_update_entity(hidden.entity_id, area_id=bath)
    thermo_bath = registry.async_get_or_create(
        "sensor", "test", "bath_temperature", suggested_object_id="bath_temperature"
    )
    registry.async_update_entity(thermo_bath.entity_id, area_id=bath)
    hass.states.async_set(thermo_bath.entity_id, "22.0", TEMPERATURE)

    entry = await setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "electricity_price": 30.0,
            "design_outdoor_temp": -12.0,
            "rooms": {
                CONF_ROOM_ENTITIES: {
                    "entity_id": [CLIMATE, THERMO, thermo_bath.entity_id]
                },
                "room_target": 21.0,
                CONF_VALVE_ENTITIES: {"entity_id": [bosch.entity_id]},
            },
        },
    )
    assert result["step_id"] == "rooms_check"
    check = result["description_placeholders"]["check"]
    assert "valve 30 % (from climate.living)" in check
    assert f"valve 65 % (from {bosch.entity_id})" in check
    assert f"found in the area, not chosen: {hidden.entity_id} (disabled)" in check
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "rooms_ok"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    runtime = entry.runtime_data
    await tick(hass, freezer, 1)
    await tick(hass, freezer, 1)
    assert runtime.room_log.rooms[living].valve.value == pytest.approx(30)
    assert runtime.room_log.rooms[hall].valve.value == pytest.approx(65)


def test_zwave_valve_level_in_percent() -> None:
    """Z-Wave "Valve control": a number 0-99 without a unit, 99 = open."""
    level = State("number.spirit_valve_control", "99", {"min": 0, "max": 99})
    assert valve_value(level) == pytest.approx(100)
    half = State("number.spirit_valve_control", "33", {"min": 0, "max": 99})
    assert valve_value(half) == pytest.approx(33.33, abs=0.01)
    # A number in % stays as it is; another number without a unit too.
    percent = State(
        "number.x", "40", {"min": 0, "max": 100, "unit_of_measurement": "%"}
    )
    assert valve_value(percent) == 40
    assert not level_number(State("number.y", "200", {"min": 0, "max": 255}))


@pytest.mark.freeze_time(START)
async def test_heating_share_without_valve(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A thermostat that reports only whether it heats (TP-Link Kasa KE100):
    the share of minutes it heats stands in for the valve opening."""
    living, _hall = make_rooms(hass)
    hass.states.async_set(
        CLIMATE,
        "heat",
        {"current_temperature": 21.0, "temperature": 21.0, "hvac_action": "heating"},
    )
    entry = await setup(hass, **{CONF_ROOM_ENTITIES: [CLIMATE]})
    log = entry.runtime_data.room_log
    await tick(hass, freezer, 1)
    await tick(hass, freezer, 1)
    hass.states.async_set(
        CLIMATE,
        "heat",
        {"current_temperature": 21.0, "temperature": 21.0, "hvac_action": "idle"},
    )
    await tick(hass, freezer, 1)
    await tick(hass, freezer, 1)
    share = log.rooms[living].valve.value
    assert 0 < share < 100


@pytest.mark.freeze_time(START)
async def test_setpoint_entity_of_its_own(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A thermostat reporting actual and target temperature as two sensors
    (simon42 95035 #250): the setpoint entity of the area counts."""
    _living, hall = make_rooms(hass)
    registry = er.async_get(hass)
    target = registry.async_get_or_create(
        "sensor", "test", "hall_setpoint", suggested_object_id="hall_setpoint"
    )
    registry.async_update_entity(target.entity_id, area_id=hall)
    hass.states.async_set(target.entity_id, "21.5", TEMPERATURE)
    entry = await setup(
        hass,
        **{CONF_ROOM_ENTITIES: [THERMO], "target_entities": [target.entity_id]},
    )
    await tick(hass, freezer, 1)
    await tick(hass, freezer, 1)
    # Thermometer 20.6 °C against the setpoint 21.5 °C.
    assert entry.runtime_data.room_log.rooms[hall].delta.value == pytest.approx(-0.9)


@pytest.mark.freeze_time(START)
async def test_valves_by_device_and_rooms_by_area(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A floor heating controller chosen as a device gives all its valve
    channels at once, an area all its thermostats (simon42 95035 #255);
    other % sensors of the device do not count."""
    living, hall = make_rooms(hass)
    devices = dr.async_get(hass)
    entry_for_device = MockConfigEntry(domain="test")
    entry_for_device.add_to_hass(hass)
    controller = devices.async_get_or_create(
        config_entry_id=entry_for_device.entry_id, identifiers={("test", "falmot")}
    )
    registry = er.async_get(hass)
    channels = []
    for n, area in ((1, living), (2, hall)):
        channel = registry.async_get_or_create(
            "sensor",
            "test",
            f"falmot_valve_position_{n}",
            suggested_object_id=f"falmot_valve_position_{n}",
            device_id=controller.id,
            unit_of_measurement="%",
            translation_key="valve_position",
            # Channels have a name of their own (e.g. "Heizkreislauf 1"):
            # only then may an entity have an area of its own.
            original_name=f"Valve position {n}",
        )
        registry.async_update_entity(channel.entity_id, area_id=area)
        hass.states.async_set(
            channel.entity_id, str(30 * n), {"unit_of_measurement": "%"}
        )
        channels.append(channel.entity_id)
    battery = registry.async_get_or_create(
        "sensor",
        "test",
        "falmot_battery",
        device_id=controller.id,
        unit_of_measurement="%",
        translation_key="battery",
    )
    entry = await setup(
        hass,
        **{
            CONF_ROOM_ENTITIES: {"area_id": [living], "entity_id": [THERMO]},
            CONF_VALVE_ENTITIES: {"device_id": [controller.id]},
        },
    )
    room_map = entry.runtime_data.room_map
    assert room_map.rooms[living].climates == [CLIMATE]
    assert room_map.rooms[hall].thermometers == [THERMO]
    assert sorted(
        room_map.rooms[living].valves + room_map.rooms[hall].valves
    ) == sorted(channels)
    assert battery.entity_id not in room_map.no_room + room_map.no_area


@pytest.mark.freeze_time(START)
async def test_homematic_ip_local_channels_by_device(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Homematic IP Local: the valve channel of a FALMOT has the translation
    key "pipe_level", no word "valve" in its unique id, and the user may have
    renamed its entity id (simon42 95035 #259)."""
    living, _hall = make_rooms(hass)
    entry_for_device = MockConfigEntry(domain="homematicip_local")
    entry_for_device.add_to_hass(hass)
    controller = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry_for_device.entry_id, identifiers={("hmip", "falmot2")}
    )
    registry = er.async_get(hass)
    channel = registry.async_get_or_create(
        "sensor",
        "homematicip_local",
        "001234567890ab_3_LEVEL",
        suggested_object_id="e_4_fbh_kanal_3",
        device_id=controller.id,
        unit_of_measurement="%",
        translation_key="pipe_level",
        original_name="Kanal 3",
    )
    registry.async_update_entity(channel.entity_id, area_id=living)
    hass.states.async_set(channel.entity_id, "42", {"unit_of_measurement": "%"})
    entry = await setup(
        hass,
        **{
            CONF_ROOM_ENTITIES: [CLIMATE],
            CONF_VALVE_ENTITIES: {"device_id": [controller.id]},
        },
    )
    assert entry.runtime_data.room_map.rooms[living].valves == [channel.entity_id]


@pytest.mark.freeze_time(START)
async def test_level_numbers_of_a_heating_actuator(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Homematic IP Local may show a FALMOT channel as a number "Level ch1"
    in % without a translation key (simon42 95035 #265): it counts when the
    device is chosen, or in an area on a heating actuator; a blind's level in
    the same area does not."""
    living, _hall = make_rooms(hass)
    entry_for_device = MockConfigEntry(domain="homematicip_local")
    entry_for_device.add_to_hass(hass)
    devices = dr.async_get(hass)
    falmot = devices.async_get_or_create(
        config_entry_id=entry_for_device.entry_id,
        identifiers={("hmip", "falmot3")},
        model="HmIPW-FALMOT-C12",
    )
    blind = devices.async_get_or_create(
        config_entry_id=entry_for_device.entry_id,
        identifiers={("hmip", "broll")},
        model="HmIP-BROLL",
    )
    registry = er.async_get(hass)

    def level(device: dr.DeviceEntry, uid: str, name: str) -> str:
        made = registry.async_get_or_create(
            "number",
            "homematicip_local",
            uid,
            suggested_object_id=uid.lower(),
            device_id=device.id,
            unit_of_measurement="%",
            original_name=name,
        )
        registry.async_update_entity(made.entity_id, area_id=living)
        hass.states.async_set(made.entity_id, "33.5", {"unit_of_measurement": "%"})
        return made.entity_id

    channel = level(falmot, "002CA4099D587E_1_LEVEL", "Level ch1")
    shutter = level(blind, "00AA_4_LEVEL", "Level ch4")
    # By device.
    entry = await setup(
        hass,
        **{
            CONF_ROOM_ENTITIES: [CLIMATE],
            CONF_VALVE_ENTITIES: {"device_id": [falmot.id]},
        },
    )
    assert entry.runtime_data.room_map.rooms[living].valves == [channel]
    # By area: the actuator's level, not the blind's.
    found = target_entities(hass, {"area_id": [living]}, KIND_VALVES)
    assert channel in found
    assert shutter not in found
