"""Stiebel Eltron ISG template against fixtures derived from its source."""

from __future__ import annotations

import pytest

from custom_components.waermewacht.counter import UNIT_FACTORS
from custom_components.waermewacht.model import ENERGY_SIGNALS, Activity, Signal
from custom_components.waermewacht.profiles import (
    BOSCH_HOMECOM,
    EMS_ESP,
    RegistryEntry,
    find,
)
from custom_components.waermewacht.profiles_stiebel import (
    ACTIVITY_FLAGS,
    STIEBEL_ISG,
    activity_from_flags,
    split_entry_id,
)

from .conftest import load_fixture

PLATFORM = "stiebel_eltron_isg"
WPMSYSTEM = "stiebel_isg_wpmsystem.json"
LWZ = "stiebel_isg_lwz.json"


def entries(name: str, platform: str = PLATFORM) -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], platform, e["unique_id"])
        for e in load_fixture(name)["entities"]
    ]


def by_key(name: str) -> dict[str, str]:
    """Entity id per key of a fixture (binary sensors prefixed "b:")."""
    found = {}
    for e in load_fixture(name)["entities"]:
        _, key = split_entry_id(e["unique_id"]) or ("", "")
        prefix = "b:" if e["entity_id"].startswith("binary_sensor.") else ""
        found[prefix + key] = e["entity_id"]
    return found


def test_wpmsystem_finds_every_signal() -> None:
    (match,) = find(STIEBEL_ISG, entries(WPMSYSTEM))
    ids = by_key(WPMSYSTEM)
    assert match.prefix == load_fixture(WPMSYSTEM)["entry_id"]
    assert match.entities == {
        Signal.HEAT_HEATING: ids["produced_heating"],  # day and total
        Signal.HEAT_DHW: ids["produced_water_heating"],
        Signal.ELEC_HEATING: ids["consumed_heating"],
        Signal.ELEC_DHW: ids["consumed_water_heating"],
        Signal.AUX_HEATING: ids["produced_electrical_booster_heating_total"],
        Signal.AUX_DHW: ids["produced_electrical_booster_water_heating_total"],
        Signal.COMPRESSOR: ids["b:compressor_on"],
        Signal.OUTDOOR_TEMP: ids["outdoor_temperature"],
        Signal.FLOW_TEMP: ids["flow_temperature_wp"],
        Signal.RETURN_TEMP: ids["return_temperature"],
        Signal.FLOW_RATE: ids["volume_stream"],
        Signal.DHW_TEMP: ids["actual_temperature_water"],
        Signal.DEFROST_FLAG: ids["b:evaporator_defrost"],
        Signal.DHW_FLAG: ids["b:is_heating_water"],
        Signal.COOLING_FLAG: ids["b:is_cooling"],
        Signal.HEATING_FLAG: ids["b:is_heating"],
    }
    # WPM: no start counter, no cooling counters (windows only).
    assert set(match.missing) == {
        Signal.HEAT_COOLING,
        Signal.STARTS_TOTAL,
    }
    assert match.history == {}


def test_lwz_finds_every_signal() -> None:
    (match,) = find(STIEBEL_ISG, entries(LWZ))
    ids = by_key(LWZ)
    assert match.entities == {
        Signal.HEAT_HEATING: ids["produced_heating"],
        Signal.HEAT_DHW: ids["produced_water_heating"],
        Signal.HEAT_COOLING: ids["produced_cooling_total"],
        Signal.ELEC_HEATING: ids["consumed_heating"],
        Signal.ELEC_DHW: ids["consumed_water_heating"],
        Signal.AUX_HEATING: ids["produced_electrical_booster_heating_total"],
        Signal.AUX_DHW: ids["produced_electrical_booster_water_heating_total"],
        Signal.COMPRESSOR: ids["b:compressor_on"],
        Signal.STARTS_TOTAL: ids["compressor_starts"],
        Signal.OUTDOOR_TEMP: ids["outdoor_temperature"],
        Signal.FLOW_TEMP: ids["flow_temperature"],
        Signal.RETURN_TEMP: ids["return_temperature"],
        Signal.FLOW_RATE: ids["volume_stream"],
        Signal.DHW_TEMP: ids["actual_temperature_water"],
        Signal.DEFROST_FLAG: ids["b:evaporator_defrost"],
        Signal.DHW_FLAG: ids["b:is_heating_water"],
        Signal.COOLING_FLAG: ids["b:is_cooling"],
        Signal.HEATING_FLAG: ids["b:is_heating"],
    }
    assert match.missing == []


@pytest.mark.parametrize("name", [WPMSYSTEM, LWZ])
def test_energy_entities_are_lifetime_counters(name: str) -> None:
    states = {e["entity_id"]: e for e in load_fixture(name)["entities"]}
    (match,) = find(STIEBEL_ISG, entries(name))
    for signal, entity_id in match.entities.items():
        if signal in ENERGY_SIGNALS:
            entity = states[entity_id]
            assert entity["attributes"]["unit_of_measurement"] in UNIT_FACTORS
            assert entity["attributes"]["state_class"] == "total_increasing"
            assert not entity["disabled_by_default"], entity_id


@pytest.mark.parametrize("name", [WPMSYSTEM, LWZ])
def test_day_registers_and_windows_are_never_chosen(name: str) -> None:
    (match,) = find(STIEBEL_ISG, entries(name))
    ids = by_key(name)
    rejected = {
        ids[key]
        for key in ids
        if key.endswith(("_today", "_24h", "_12m"))
        or key in ("produced_heating_total", "consumed_heating_total")
    }
    assert rejected
    assert not rejected & set(match.entities.values())


def test_compressor_frequency_when_the_flag_is_missing() -> None:
    names = [e for e in entries(LWZ) if not e.entity_id.startswith("binary_sensor.")]
    (match,) = find(STIEBEL_ISG, names)
    assert match.entities[Signal.COMPRESSOR] == by_key(LWZ)["compressor_speed"]


def test_without_compressor_no_heat_pump() -> None:
    names = [
        e for e in entries(WPMSYSTEM) if not e.unique_id.endswith("_compressor_on")
    ]
    assert find(STIEBEL_ISG, names) == []


def test_two_controllers_by_entry_id() -> None:
    found = find(STIEBEL_ISG, entries(WPMSYSTEM) + entries(LWZ))
    assert [m.prefix for m in found] == sorted(
        [load_fixture(WPMSYSTEM)["entry_id"], load_fixture(LWZ)["entry_id"]]
    )


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        (
            "01JZK3W8Q5N2V7C4X9B6M1T0RS_produced_heating_total",
            ("01JZK3W8Q5N2V7C4X9B6M1T0RS", "produced_heating_total"),
        ),
        (
            "0123456789abcdef0123456789abcdef_compressor_on",  # uuid4 hex entry id
            ("0123456789abcdef0123456789abcdef", "compressor_on"),
        ),
        # Legacy id of a duplicate the migration left orphaned (< 2026.7).
        ("stiebel_eltron_isg_Stiebel Eltron WPM_produced_heating", None),
        ("01JZK3W8Q5N2V7C4X9B6M1T0RS", None),
        ("01JZK3W8Q5N2V7C4X9B6M1T0RS_", None),
        ("_produced_heating", None),
        ("101234567-heat_produced_ch", None),  # Bosch HomeCom format
    ],
)
def test_unique_ids(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert STIEBEL_ISG.split(unique_id) == expected


def test_templates_do_not_claim_each_other() -> None:
    stiebel = entries(WPMSYSTEM) + entries(LWZ)
    ems = [
        RegistryEntry(e["entity_id"], "mqtt", e["unique_id"])
        for e in load_fixture("ems_esp_cs6800i.json")["entities"]
    ]
    homecom = [
        RegistryEntry(e["entity_id"], "bosch_homecom", e["unique_id"])
        for e in load_fixture("bosch_homecom_k40.json")["entities"]
    ]
    assert find(STIEBEL_ISG, ems + homecom) == []
    assert find(EMS_ESP, stiebel) == []
    assert find(BOSCH_HOMECOM, stiebel) == []


def test_ids_do_not_match_under_a_foreign_platform() -> None:
    """Even with the platform swapped, the id formats keep the templates apart."""
    assert find(EMS_ESP, entries(WPMSYSTEM, "mqtt")) == []
    assert find(BOSCH_HOMECOM, entries(LWZ, "bosch_homecom")) == []


def test_activity_flags_exist_in_both_families() -> None:
    for name in (WPMSYSTEM, LWZ):
        keys = by_key(name)
        assert all(f"b:{key}" in keys for key, _ in ACTIVITY_FLAGS), name


def _flags(**on: str) -> dict[str, str | None]:
    states: dict[str, str | None] = dict.fromkeys(
        (key for key, _ in ACTIVITY_FLAGS), "off"
    )
    states.update(on)
    return states


@pytest.mark.parametrize(
    ("states", "activity"),
    [
        (_flags(), Activity.OFF),
        (_flags(is_heating="on"), Activity.HEATING),
        (_flags(is_heating_water="on"), Activity.DHW),
        (_flags(is_cooling="on"), Activity.COOLING),
        # A defrost while heating is requested is a defrost.
        (_flags(is_heating="on", evaporator_defrost="on"), Activity.DEFROST),
        (_flags(is_heating="on", is_heating_water="on"), Activity.DHW),
        # Unknown flag of higher priority: undecided.
        (_flags(is_heating="on", evaporator_defrost="unavailable"), None),
        # Unknown flag of lower priority does not matter.
        (_flags(is_heating_water="on", is_heating="unknown"), Activity.DHW),
        (_flags(is_heating=None), None),
        ({"is_heating": "on"}, Activity.HEATING),  # other flags absent
        ({}, None),
    ],
)
def test_activity_from_flags(
    states: dict[str, str | None], activity: Activity | None
) -> None:
    assert activity_from_flags(states) is activity


@pytest.mark.parametrize("name", [WPMSYSTEM, LWZ])
def test_activity_of_the_fixture(name: str) -> None:
    states = {}
    for e in load_fixture(name)["entities"]:
        _, key = split_entry_id(e["unique_id"]) or ("", "")
        if e["entity_id"].startswith("binary_sensor."):
            states[key] = e["state"]
    flags = {key: states[key] for key, _ in ACTIVITY_FLAGS}
    assert activity_from_flags(flags) is Activity.HEATING
