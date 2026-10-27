"""Luxtronik template (luxtronik2) against its fixture, derived from source."""

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
from custom_components.waermewacht.profiles_luxtronik import LUXTRONIK, split_suffix

from .conftest import load_fixture

FIXTURE = "luxtronik_lwd70a.json"


def entities() -> list[dict]:
    return load_fixture(FIXTURE)["entities"]


def lux_entries(
    *, with_disabled: bool = True, platform: str = "luxtronik2"
) -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], platform, e["unique_id"])
        for e in entities()
        if with_disabled or not e["disabled_by_default"]
    ]


def renamed(prefix: str, entries: list[RegistryEntry]) -> list[RegistryEntry]:
    """The same entities under another prefix (second pump, legacy entry)."""
    old = load_fixture(FIXTURE)["prefix"]
    return [
        RegistryEntry(
            e.entity_id.replace(old, prefix),
            e.platform,
            e.unique_id.replace(old, prefix),
        )
        for e in entries
    ]


def test_template_finds_every_signal() -> None:
    (match,) = find(LUXTRONIK, lux_entries())
    prefix = load_fixture(FIXTURE)["prefix"]
    s, b = f"sensor.{prefix}_", f"binary_sensor.{prefix}_"
    assert match.prefix == prefix
    assert match.entities == {
        Signal.HEAT_HEATING: s + "heat_amount_heating",
        Signal.HEAT_DHW: s + "dhw_heat_amount",
        Signal.HEAT_COOLING: s + "cooling_heat_amount",
        Signal.ELEC_HEATING: s + "heat_energy_input",
        Signal.ELEC_DHW: s + "dhw_energy_input",
        Signal.ELEC_COOLING: s + "cooling_energy_input",
        Signal.AUX_TOTAL: s + "additional_heat_generator_energy",  # not _p1059
        Signal.COMPRESSOR: b + "compressor",  # not compressor2/_heater
        Signal.ACTIVITY: s + "status",  # not smart_grid_status/status_line_*
        Signal.STARTS_TOTAL: s + "compressor1_impulses",
        Signal.OUTDOOR_TEMP: s + "outdoor_temperature",  # not _average
        Signal.FLOW_TEMP: s + "flow_in_temperature",
        Signal.RETURN_TEMP: s + "flow_out_temperature",  # not _target
        Signal.FLOW_RATE: s + "heat_amount_flow_rate",  # not heat_source_
        Signal.DHW_TEMP: s + "dhw_temperature",
        Signal.HEAT_POWER: s + "current_heat_output",
        Signal.ELEC_POWER: s + "current_power_consumption",
    }
    assert match.missing == []
    # No backup heater per mode: the total is attributed to the current mode.
    assert Signal.AUX_HEATING not in match.entities
    assert Signal.AUX_DHW not in match.entities


def test_energy_entities_have_usable_units() -> None:
    attributes = {e["entity_id"]: e["attributes"] for e in entities()}
    (match,) = find(LUXTRONIK, lux_entries())
    for signal, entity_id in match.entities.items():
        if signal in ENERGY_SIGNALS:
            assert attributes[entity_id]["unit_of_measurement"] in UNIT_FACTORS
            assert attributes[entity_id]["state_class"] == "total_increasing"


def test_enabled_by_default_is_enough() -> None:
    """Starts and powers are disabled in luxtronik2, the energy is not."""
    (match,) = find(LUXTRONIK, lux_entries(with_disabled=False))
    assert set(match.missing) == {
        Signal.STARTS_TOTAL,
        Signal.HEAT_POWER,
        Signal.ELEC_POWER,
    }


@pytest.mark.parametrize(
    ("state", "activity"),
    [
        ("heating", Activity.HEATING),
        ("hot_water", Activity.DHW),
        ("cooling", Activity.COOLING),
        ("defrost", Activity.DEFROST),
        ("no_request", Activity.OFF),
        ("evu", Activity.OFF),
        ("swimming_pool_solar", Activity.OTHER),
        ("heating_external_source", Activity.OTHER),
        ("something new", Activity.OTHER),
    ],
)
def test_activity_values(state: str, activity: Activity) -> None:
    assert LUXTRONIK.parse_activity(state) is activity


@pytest.mark.parametrize("state", [None, "unknown", "unavailable"])
def test_unknown_activity(state: str | None) -> None:
    assert LUXTRONIK.parse_activity(state) is None


def test_every_status_option_is_mapped() -> None:
    """The enum options of the status sensor, as luxtronik2 declares them."""
    options = load_fixture(FIXTURE)["activity_options"]
    assert set(options) == set(LUXTRONIK.activity_values)
    (match,) = find(LUXTRONIK, lux_entries())
    (status,) = [
        e for e in entities() if e["entity_id"] == match.entities[Signal.ACTIVITY]
    ]
    assert status["attributes"]["options"] == options


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        (
            "sensor.luxtronik_2113_01267_heat_amount_heating",
            ("luxtronik_2113_01267", "heat_amount_heating"),
        ),
        ("sensor.luxtronik_status", ("luxtronik", "status")),  # migrated v1
        ("sensor.luxtronik2_status", ("luxtronik2", "status")),  # migrated v3
        ("binary_sensor.luxtronik_compressor", ("luxtronik", "compressor")),
        ("binary_sensor.luxtronik_compressor2", None),
        ("sensor.luxtronik_compressor", None),  # key of another domain
        ("sensor.status", None),  # no prefix
        ("sensor._status", None),
        ("luxtronik_status", None),  # no domain
        ("sensor.luxtronik_heat_amount_heating_compressor_2", None),  # twin
    ],
)
def test_unique_ids(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert LUXTRONIK.split(unique_id) == expected


def test_longest_key_wins() -> None:
    candidates = [("sensor", "energy"), ("sensor", "generator_energy")]
    assert split_suffix("sensor.lux_generator_energy", candidates) == (
        "lux",
        "generator_energy",
    )


def test_old_firmware_without_electricity_per_mode_is_not_found() -> None:
    """Parameters 1136/1137 exist only on newer controllers."""
    without = [e for e in lux_entries() if not e.unique_id.endswith("energy_input")]
    assert find(LUXTRONIK, without) == []


def test_no_compressor_no_heat_pump() -> None:
    without = [e for e in lux_entries() if not e.unique_id.endswith("_compressor")]
    assert len(without) == len(lux_entries()) - 1
    assert find(LUXTRONIK, without) == []


def test_two_heat_pumps_and_a_legacy_prefix() -> None:
    entries = lux_entries() + renamed("luxtronik", lux_entries())
    found = find(LUXTRONIK, entries)
    assert [m.prefix for m in found] == ["luxtronik", "luxtronik_2113_01267"]
    assert found[0].entities[Signal.ACTIVITY] == "sensor.luxtronik_status"
    assert found[1].entities[Signal.ACTIVITY] == ("sensor.luxtronik_2113_01267_status")


def test_user_renamed_entity_is_still_found() -> None:
    """Detection uses the unique id; the entity id may be anything."""
    entries = [
        e._replace(entity_id="sensor.wp_waerme_heizen")
        if e.unique_id.endswith("_heat_amount_heating")
        else e
        for e in lux_entries()
    ]
    (match,) = find(LUXTRONIK, entries)
    assert match.entities[Signal.HEAT_HEATING] == "sensor.wp_waerme_heizen"


def ems_entries() -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], "mqtt", e["unique_id"])
        for e in load_fixture("ems_esp_cs6800i.json")["entities"]
    ]


def homecom_entries() -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], "bosch_homecom", e["unique_id"])
        for e in load_fixture("bosch_homecom_k40.json")["entities"]
    ]


def test_templates_do_not_claim_each_other() -> None:
    assert find(LUXTRONIK, ems_entries()) == []
    assert find(LUXTRONIK, homecom_entries()) == []
    assert find(EMS_ESP, lux_entries()) == []
    assert find(BOSCH_HOMECOM, lux_entries()) == []


def test_unique_id_formats_do_not_overlap() -> None:
    """Even on a shared platform name no template splits another's ids."""
    assert (
        find(LUXTRONIK, [e._replace(platform="luxtronik2") for e in ems_entries()])
        == []
    )
    homecom = [e._replace(platform="luxtronik2") for e in homecom_entries()]
    assert find(LUXTRONIK, homecom) == []
    assert find(EMS_ESP, lux_entries(platform="mqtt")) == []
    assert find(BOSCH_HOMECOM, lux_entries(platform="bosch_homecom")) == []
