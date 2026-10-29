"""Daikin Altherma via the P1P2MQTT bridge: template against a fixture from its source."""

from __future__ import annotations

import pytest

from custom_components.waermewacht.activity import combine
from custom_components.waermewacht.counter import UNIT_FACTORS
from custom_components.waermewacht.model import (
    ENERGY_SIGNALS,
    Activity,
    Mode,
    Signal,
    has_elec,
)
from custom_components.waermewacht.profiles import (
    EMS_ESP,
    RegistryEntry,
    find,
    parse_compressor,
)
from custom_components.waermewacht.profiles_f1p import F1P
from custom_components.waermewacht.profiles_p1p2mqtt import P1P2MQTT
from custom_components.waermewacht.templates import TEMPLATES

from .conftest import FIXTURES, load_fixture

FIXTURE = "p1p2mqtt_altherma3.json"
PREFIX = "P1P2MQTT_bridge0"


def entries(fixture: str = FIXTURE, platform: str = "mqtt") -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], platform, e["unique_id"], e.get("original_name"))
        for e in load_fixture(fixture)["entities"]
    ]


M, S, B = "sensor.bridge0_meters_", "sensor.bridge0_sensors_", "binary_sensor.bridge0_"
EXPECTED = {
    Signal.HEAT_HEATING: M + "energy_produced_compressor_heating",
    Signal.HEAT_DHW: M + "energy_produced_compressor_dhw",
    Signal.HEAT_COOLING: M + "energy_produced_compressor_cooling",
    Signal.ELEC_HEATING: M + "electricity_consumed_compressor_heating",
    Signal.ELEC_DHW: M + "electricity_consumed_compressor_dhw",
    Signal.ELEC_COOLING: M + "electricity_consumed_compressor_cooling",
    Signal.AUX_HEATING: M + "electricity_consumed_backup_heating",
    Signal.AUX_DHW: M + "electricity_consumed_backup_dhw",
    Signal.COMPRESSOR: B + "mode_compressor",  # on/off before the frequency
    Signal.DEFROST_FLAG: B + "mode_defrost_active",  # not the param15 one
    Signal.DHW_FLAG: B + "dhw_dhw_demand",  # not "DHW" (function on/off)
    Signal.COOLING_FLAG: B + "mode_climate_cooling",
    Signal.HEATING_FLAG: B + "mode_climate_heating",  # not the request
    Signal.STARTS_TOTAL: M + "starts_compressor",
    Signal.OUTDOOR_TEMP: S + "temperature_outside",  # not the outdoor unit's
    Signal.FLOW_TEMP: S + "temperature_r1t_hp2gas_water",  # before the BUH
    Signal.RETURN_TEMP: S + "temperature_r4t_return_water",  # not R9T
    Signal.FLOW_RATE: S + "flow",
    Signal.DHW_TEMP: "sensor.bridge0_dhw_temperature_r5t_dhw_tank",
}


def test_template_finds_every_signal() -> None:
    (match,) = find(P1P2MQTT, entries())
    assert match.prefix == PREFIX == load_fixture(FIXTURE)["prefix"]
    assert match.entities == EXPECTED
    assert match.missing == []
    assert match.history == {}


def test_lifetime_counters_per_mode() -> None:
    t = P1P2MQTT
    assert t.experimental and t.platform == "mqtt"
    assert not t.day_values and not t.previous_day and not t.hourly_statistics
    assert t.required == (Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING)
    # Per-mode meters: no common meter, no activity entity (flags only).
    assert Signal.ELEC_TOTAL not in t.signals
    assert Signal.ACTIVITY not in t.signals
    (match,) = find(P1P2MQTT, entries())
    assert all(has_elec(match.entities, mode) for mode in Mode)
    assert not any("total" in e for e in match.entities.values())


def test_energy_entities_have_usable_units() -> None:
    attributes = {
        e["entity_id"]: e["attributes"] for e in load_fixture(FIXTURE)["entities"]
    }
    for signal, entity_id in EXPECTED.items():
        if signal in ENERGY_SIGNALS:
            assert attributes[entity_id]["unit_of_measurement"] in UNIT_FACTORS
            assert attributes[entity_id]["device_class"] == "energy"
            assert attributes[entity_id]["state_class"] == "total_increasing"
    # Flow in L/min without a device class (selectable since 0.1.3).
    assert attributes[EXPECTED[Signal.FLOW_RATE]] == {
        "unit_of_measurement": "L/min",
        "state_class": "measurement",
    }


def test_compressor_frequency_when_no_binary_sensor() -> None:
    without = [e for e in entries() if e.entity_id != EXPECTED[Signal.COMPRESSOR]]
    (match,) = find(P1P2MQTT, without)
    assert match.entities[Signal.COMPRESSOR] == "sensor.bridge0_mode_compressor_rpm"
    assert parse_compressor("42") is True
    assert parse_compressor("0") is False


def test_r1t_named_as_leaving_water() -> None:
    """With "use R1T" the bridge names R1T the leaving water and drops R2T."""
    r1t = "_T1_Temperature_R1T_HP2Gas_Water_1"
    switched = [
        e._replace(
            entity_id="sensor.bridge0_sensors_temperature_r1t_leaving_water",
            unique_id=PREFIX + "_T1_Temperature_R1T_Leaving_Water_1",
        )
        if e.unique_id.endswith(r1t)
        else e
        for e in entries()
        if "R2T" not in e.unique_id
    ]
    (match,) = find(P1P2MQTT, switched)
    assert match.entities[Signal.FLOW_TEMP] == (
        "sensor.bridge0_sensors_temperature_r1t_leaving_water"
    )
    only_r2t = [e for e in entries() if not e.unique_id.endswith(r1t)]
    (match,) = find(P1P2MQTT, only_r2t)
    assert match.entities[Signal.FLOW_TEMP] == S + "temperature_r2t_leaving_water"


def test_missing_signals_and_required() -> None:
    no_dhw = [e for e in entries() if "DHW" not in e.unique_id]
    (match,) = find(P1P2MQTT, no_dhw)
    assert match.missing == [
        Signal.HEAT_DHW,
        Signal.ELEC_DHW,
        Signal.AUX_DHW,
        Signal.DHW_FLAG,
        Signal.DHW_TEMP,
    ]
    compressor = ("_S1_Compressor_1", "_M1_Compressor_RPM_1")
    no_compressor = [e for e in entries() if not e.unique_id.endswith(compressor)]
    assert find(P1P2MQTT, no_compressor) == []
    # Counters never requested (Counter_Request_Function off): not found.
    no_counters = [e for e in entries() if "_C1_" not in e.unique_id]
    assert find(P1P2MQTT, no_counters) == []
    assert find(P1P2MQTT, [e._replace(usable=False) for e in entries()]) == []


def test_two_bridges_and_other_names() -> None:
    second = [
        e._replace(
            entity_id=e.entity_id.replace("bridge0", "bridge1"),
            unique_id=e.unique_id.replace("_bridge0_", "_bridge1_"),
        )
        for e in entries()
    ]
    found = find(P1P2MQTT, entries() + second)
    assert [m.prefix for m in found] == [PREFIX, "P1P2MQTT_bridge1"]
    # Names changed by the user, with "_" in them.
    renamed = [
        e._replace(unique_id=e.unique_id.replace(PREFIX, "wp_haus_br_0"))
        for e in entries()
    ]
    (match,) = find(P1P2MQTT, renamed)
    assert match.prefix == "wp_haus_br_0"
    assert match.entities == EXPECTED


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        (f"{PREFIX}_S1_Compressor_1", (PREFIX, "S1_Compressor_1")),
        (f"{PREFIX}_M1_Compressor_RPM_1", (PREFIX, "M1_Compressor_RPM_1")),
        # A name that ends like a shorter one: the longest key wins.
        (
            f"{PREFIX}_T1_Temperature_Outside_Unit_1",
            (PREFIX, "T1_Temperature_Outside_Unit_1"),
        ),
        (f"{PREFIX}_T1_Temperature_Outside_1", (PREFIX, "T1_Temperature_Outside_1")),
        (
            f"{PREFIX}_C1_Electricity_Consumed_Compressor_DHW_1",
            (PREFIX, "C1_Electricity_Consumed_Compressor_DHW_1"),
        ),
        # Same name from another source or category: not the heat pump's reply.
        (f"{PREFIX}_TF_Temperature_Outside_F", None),
        (f"{PREFIX}_S0_Climate_Heating_Request_0", None),
        (f"{PREFIX}_T1_Defrost_Active_param15_1", None),
        (f"{PREFIX}_S1_Valve_DHW_Tank_1", None),
        (f"{PREFIX}_C1_Electricity_Consumed_Total_1", None),
        ("S1_Compressor_1", None),  # no prefix
        ("boiler_nrgheat", None),  # EMS-ESP
        ("ashp_compressor_freq_abcdef123456", None),  # F1p
    ],
)
def test_unique_ids(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert P1P2MQTT.split(unique_id) == expected


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({}, Activity.OFF),
        ({Signal.HEATING_FLAG: "on"}, Activity.HEATING),
        ({Signal.HEATING_FLAG: "on", Signal.DHW_FLAG: "on"}, Activity.DHW),
        (
            {
                Signal.HEATING_FLAG: "on",
                Signal.DHW_FLAG: "on",
                Signal.DEFROST_FLAG: "on",
            },
            Activity.DEFROST,
        ),
        ({Signal.COOLING_FLAG: "on"}, Activity.COOLING),
        ({Signal.HEATING_FLAG: "unavailable"}, None),
    ],
)
def test_activity_from_flags(
    flags: dict[Signal, str], expected: Activity | None
) -> None:
    configured = {s for s in EXPECTED if s in P1P2MQTT.signals}
    parts = (
        Signal.DEFROST_FLAG,
        Signal.DHW_FLAG,
        Signal.COOLING_FLAG,
        Signal.HEATING_FLAG,
    )
    states = {s: flags.get(s, "off") for s in parts}
    assert combine(None, states, configured) is expected


def test_no_other_template_claims_p1p2mqtt() -> None:
    for key, template in TEMPLATES.items():
        if template is P1P2MQTT:
            continue
        # As if the P1P2MQTT unique ids came from the template's own platform.
        assert find(template, entries(platform=template.platform)) == [], key
    assert EMS_ESP.platform == F1P.platform == P1P2MQTT.platform  # all MQTT
    assert find(EMS_ESP, entries()) == []
    assert find(F1P, entries()) == []
    for entry in entries():
        assert F1P.split(entry.unique_id) is None, entry.unique_id


def _fixtures() -> list[str]:
    return sorted(
        p.name
        for p in FIXTURES.glob("*.json")
        if p.name not in ("_index.json", FIXTURE)
    )


@pytest.mark.parametrize("fixture", _fixtures())
def test_p1p2mqtt_claims_no_other_fixture(fixture: str) -> None:
    # Any platform: not even the unique ids alone may look like P1P2MQTT's.
    assert find(P1P2MQTT, entries(fixture, P1P2MQTT.platform)) == []
    for entity in load_fixture(fixture)["entities"]:
        assert P1P2MQTT.split(entity["unique_id"]) is None, entity["unique_id"]
