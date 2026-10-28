"""Viessmann ViCare template against fixtures derived from its source."""

from __future__ import annotations

import pytest

from custom_components.waermewacht.activity import combine
from custom_components.waermewacht.counter import UNIT_FACTORS
from custom_components.waermewacht.model import (
    ENERGY_SIGNALS,
    HEAT_SIGNALS,
    Activity,
    Signal,
)
from custom_components.waermewacht.profiles import (
    RegistryEntry,
    drop_foreign_activity,
    find,
)
from custom_components.waermewacht.profiles_viessmann import VICARE

from .conftest import load_fixture

E3 = "vicare_vitocal250a.json"
LEGACY = "vicare_vitocal333g.json"


def entries(name: str, *, with_disabled: bool = True) -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], "vicare", e["unique_id"])
        for e in load_fixture(name)["entities"]
        if with_disabled or not e.get("disabled_by_default")
    ]


def test_e3_finds_cycling_and_electricity() -> None:
    (match,) = find(VICARE, entries(E3))
    s, b = "sensor.e3_vitocal_", "binary_sensor.e3_vitocal_"
    assert match.prefix == "0000111122223333_0000444455556666"
    assert match.entities == {
        Signal.ELEC_HEATING: s + "heating_electricity_consumption_today",
        Signal.ELEC_DHW: s + "dhw_electricity_consumption_today",
        Signal.COMPRESSOR: b + "compressor",
        Signal.ACTIVITY: s + "compressor_phase",  # dropped by the flow: "ready"
        Signal.STARTS_TOTAL: s + "compressor_starts",
        Signal.OUTDOOR_TEMP: s + "outside_temperature",
        Signal.FLOW_TEMP: s + "secondary_circuit_supply_temperature",
        Signal.RETURN_TEMP: s + "return_temperature",
        Signal.DHW_TEMP: s + "dhw_storage_temperature",
    }
    assert set(match.missing) == {Signal.ELEC_COOLING, Signal.DHW_FLAG}
    assert not any(s in match.entities for s in HEAT_SIGNALS.values())


def test_e3_enabled_by_default_is_enough() -> None:
    (match,) = find(VICARE, entries(E3, with_disabled=False))
    assert set(match.missing) == {Signal.ELEC_COOLING, Signal.DHW_FLAG}


def test_e3_phase_is_foreign() -> None:
    (match,) = find(VICARE, entries(E3))
    states = {e["entity_id"]: e["state"] for e in load_fixture(E3)["entities"]}
    dropped = drop_foreign_activity(match, states.get)
    assert Signal.ACTIVITY not in dropped.entities
    assert Signal.COMPRESSOR in dropped.entities
    # A phase that happens to be "off" at setup keeps it (repair issue later).
    kept = drop_foreign_activity(match, lambda _: "off")
    assert Signal.ACTIVITY in kept.entities


def test_vitotronic_finds_cycling_and_defrost() -> None:
    (match,) = find(VICARE, entries(LEGACY))
    s, b = "sensor.vitocal_333g_", "binary_sensor.vitocal_333g_"
    assert match.entities == {
        Signal.COMPRESSOR: b + "compressor",
        Signal.ACTIVITY: s + "compressor_phase",
        Signal.DHW_FLAG: b + "dhw_charging",
        Signal.STARTS_TOTAL: s + "compressor_starts",
        Signal.OUTDOOR_TEMP: s + "outside_temperature",
        Signal.FLOW_TEMP: s + "secondary_circuit_supply_temperature",
        Signal.RETURN_TEMP: s + "return_temperature",
        Signal.DHW_TEMP: s + "dhw_storage_temperature",
    }
    assert set(match.missing) == {
        Signal.ELEC_HEATING,
        Signal.ELEC_DHW,
        Signal.ELEC_COOLING,
    }


@pytest.mark.parametrize(
    ("state", "activity"),
    [
        ("heating", Activity.HEATING),
        ("cooling", Activity.COOLING),
        ("defrost", Activity.DEFROST),
        ("preparing_defrost", Activity.DEFROST),
        ("passive_defrost", Activity.DEFROST),
        ("preparing", Activity.OFF),
        ("pause", Activity.OFF),
        ("off", Activity.OFF),
        ("null", None),
        ("ready", None),
        ("not_ready", None),
        ("something new", Activity.OTHER),
    ],
)
def test_phase_values(state: str, activity: Activity | None) -> None:
    assert VICARE.parse_activity(state) is activity


def test_every_phase_option_is_mapped() -> None:
    for name in (E3, LEGACY):
        for value in load_fixture(name)["phase_options"]:
            assert value in VICARE.activity_values or value in VICARE.activity_foreign


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        (
            "0000111122223333_0000444455556666-compressor_active-0",
            ("0000111122223333_0000444455556666", "compressor_active-0"),
        ),
        (
            "0000111122223333_0-power consumption today",
            ("0000111122223333_0", "power consumption today"),
        ),
        ("nodash", None),
    ],
)
def test_unique_ids(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert VICARE.split(unique_id) == expected


def test_only_compressor_one_is_not_followed() -> None:
    prefix = "0000111122223333_0000444455556666"
    found = find(
        VICARE,
        [RegistryEntry("binary_sensor.x", "vicare", f"{prefix}-compressor_active-1")],
    )
    assert found == []


def test_energy_entities_have_usable_units() -> None:
    attributes = {e["entity_id"]: e["attributes"] for e in load_fixture(E3)["entities"]}
    (match,) = find(VICARE, entries(E3))
    for signal, entity_id in match.entities.items():
        if signal in ENERGY_SIGNALS:
            assert attributes[entity_id]["unit_of_measurement"] in UNIT_FACTORS


def test_day_values_counted_in_utc() -> None:
    assert VICARE.day_values and VICARE.day_timezone == "UTC"


def test_defrost_in_the_phase_beats_the_hot_water_flag() -> None:
    configured = {Signal.ACTIVITY, Signal.DHW_FLAG}
    states = {Signal.DHW_FLAG: "on"}
    assert combine(Activity.DEFROST, states, configured) is Activity.DEFROST
    assert combine(Activity.HEATING, states, configured) is Activity.DHW
