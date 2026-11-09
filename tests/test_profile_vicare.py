"""Viessmann ViCare template against fixtures derived from its source."""

from __future__ import annotations

from datetime import UTC, tzinfo

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
    Match,
    RegistryEntry,
    drop_foreign_activity,
    find,
)
from custom_components.waermewacht.profiles_viessmann import VICARE
from custom_components.waermewacht.templates import TEMPLATES

from .conftest import load_fixture

E3 = "vicare_vitocal250a.json"
REAL = "vicare_vitocal151a_real.json"
LEGACY = "vicare_vitocal333g.json"
SPLIT = "vicare_vitocal200a.json"


def entries(name: str, *, with_disabled: bool = True) -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], "vicare", e["unique_id"])
        for e in load_fixture(name)["entities"]
        if with_disabled or not e.get("disabled_by_default")
    ]


def on_gateway(found: list[RegistryEntry], gateway: str) -> list[RegistryEntry]:
    """The entries moved to another gateway (unique id up to the first "_")."""
    return [
        e._replace(unique_id=f"{gateway}_{e.unique_id.partition('_')[2]}")
        for e in found
    ]


def of_device(name: str, prefix: str) -> list[RegistryEntry]:
    return [e for e in entries(name) if e.unique_id.startswith(f"{prefix}-")]


def test_e3_finds_cycling_and_electricity() -> None:
    (match,) = find(VICARE, entries(E3))
    s, b = "sensor.e3_vitocal_", "binary_sensor.e3_vitocal_"
    assert match.prefix == "0000111122223333_0000444455556666"
    assert match.entities == {
        Signal.ELEC_HEATING: s + "heating_electricity_consumption_today",
        Signal.ELEC_DHW: s + "dhw_electricity_consumption_today",
        Signal.COMPRESSOR: b + "compressor",
        Signal.STARTS_TOTAL: s + "compressor_starts",
        Signal.OUTDOOR_TEMP: s + "outside_temperature",
        Signal.FLOW_TEMP: s + "secondary_circuit_supply_temperature",
        Signal.RETURN_TEMP: s + "return_temperature",
        Signal.DHW_TEMP: s + "dhw_storage_temperature",
    }
    # E3: the phase carries no activity (ready / not_ready).
    assert set(match.missing) == {Signal.ELEC_COOLING, Signal.DHW_FLAG, Signal.ACTIVITY}
    assert not any(s in match.entities for s in HEAT_SIGNALS.values())


def test_real_vitocal_151a() -> None:
    """A real E3 (Vitocal 151-A, French entity names, 2026-11-09): every
    signal the template knows for E3 is found, the phase is left out."""
    (match,) = find(VICARE, entries(REAL))
    s, b = "sensor.e3_vitocal_", "binary_sensor.e3_vitocal_"
    assert match.prefix == load_fixture(REAL)["prefix"]
    assert match.entities == {
        Signal.ELEC_HEATING: s + "consommation_electrique_du_chauffage_aujourd_hui",
        Signal.ELEC_DHW: s + "consommation_electrique_de_l_ecs_aujourd_hui",
        Signal.COMPRESSOR: b + "compresseur",
        Signal.STARTS_TOTAL: s + "demarrages_du_compresseur",
        Signal.OUTDOOR_TEMP: s + "temperature_exterieure",
        Signal.FLOW_TEMP: s + "temperature_de_depart_du_circuit_secondaire",
        Signal.RETURN_TEMP: s + "temperature_de_retour",
        Signal.DHW_TEMP: s + "temperature_du_ballon_d_eau_chaude_sanitaire",
    }
    # No cooling on this one; E3 has no hot water flag and no mode.
    assert set(match.missing) == {Signal.ELEC_COOLING, Signal.DHW_FLAG, Signal.ACTIVITY}
    rows = {e["entity_id"]: e for e in load_fixture(REAL)["entities"]}
    for signal, entity_id in match.entities.items():
        if signal in ENERGY_SIGNALS:
            assert rows[entity_id]["attributes"] == {
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "total_increasing",
            }, entity_id
    assert VICARE.is_foreign_activity(rows[s + "phase_du_compresseur"]["state"])


def test_e3_enabled_by_default_is_enough() -> None:
    (match,) = find(VICARE, entries(E3, with_disabled=False))
    assert set(match.missing) == {Signal.ELEC_COOLING, Signal.DHW_FLAG, Signal.ACTIVITY}


def test_e3_phase_is_foreign() -> None:
    states = {e["entity_id"]: e["state"] for e in load_fixture(E3)["entities"]}
    phase = "sensor.e3_vitocal_compressor_phase"
    assert VICARE.is_foreign_activity(states[phase])


def test_e3_phase_left_out_whatever_it_shows() -> None:
    """Vitocal 151-A (2026-11): the phase showed "off" at setup, so the flow
    kept it, and the entry then asked to remove it. Electricity tells E3."""
    (match,) = find(VICARE, entries(E3))
    assert Signal.ACTIVITY not in match.entities
    kept = drop_foreign_activity(match, lambda _: "off")
    assert Signal.ACTIVITY not in kept.entities
    assert Signal.COMPRESSOR in kept.entities


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
    for name in (E3, LEGACY, SPLIT):
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
    assert VICARE.day_values and VICARE.day_timezone is UTC


def test_day_timezones_are_zone_objects() -> None:
    # A zone name would be looked up from disk when the runtime is built on
    # the event loop (HACS review, hacs/default#12862).
    for template in TEMPLATES.values():
        assert template.day_timezone is None or isinstance(
            template.day_timezone, tzinfo
        )


def test_defrost_in_the_phase_beats_the_hot_water_flag() -> None:
    configured = {Signal.ACTIVITY, Signal.DHW_FLAG}
    states = {Signal.DHW_FLAG: "on"}
    assert combine(Activity.DEFROST, states, configured) is Activity.DEFROST
    assert combine(Activity.HEATING, states, configured) is Activity.DHW


# Split system (Vitocal 200-A): outdoor unit with the compressor, system
# controller with the electricity, two devices of one gateway.
SPLIT_EXPECTED = {
    Signal.ELEC_HEATING: "sensor.vitocal_200a_heating_electricity_consumption_today",
    Signal.ELEC_DHW: "sensor.vitocal_200a_dhw_electricity_consumption_today",
    Signal.COMPRESSOR: "binary_sensor.vitocal_200a_outdoor_compressor",
    Signal.STARTS_TOTAL: "sensor.vitocal_200a_outdoor_compressor_starts",
    Signal.FLOW_TEMP: "sensor.vitocal_200a_outdoor_secondary_circuit_supply_temperature",
    Signal.DHW_TEMP: "sensor.vitocal_200a_dhw_storage_temperature",
}
SPLIT_MISSING = {
    Signal.ELEC_COOLING,
    Signal.ACTIVITY,  # E3 (merged electricity)
    Signal.DHW_FLAG,
    Signal.OUTDOOR_TEMP,  # system.temperature.outside: no getter in PyViCare
    Signal.RETURN_TEMP,
}


@pytest.mark.parametrize("with_disabled", [True, False])
def test_split_system_is_one_heat_pump(with_disabled: bool) -> None:
    (match,) = find(VICARE, entries(SPLIT, with_disabled=with_disabled))
    fixture = load_fixture(SPLIT)
    assert match.prefix == fixture["prefix"] == fixture["devices"]["outdoor_unit"]
    assert match.entities == SPLIT_EXPECTED
    assert set(match.missing) == SPLIT_MISSING


def test_split_system_order_does_not_matter() -> None:
    (match,) = find(VICARE, list(reversed(entries(SPLIT))))
    assert match.entities == SPLIT_EXPECTED


def test_split_system_null_phase_is_unknown() -> None:
    states = {e["entity_id"]: e["state"] for e in load_fixture(SPLIT)["entities"]}
    phase = "sensor.vitocal_200a_outdoor_compressor_phase"
    assert VICARE.parse_activity(states[phase]) is None


def test_split_system_devices_alone() -> None:
    devices = load_fixture(SPLIT)["devices"]
    (outdoor,) = find(VICARE, of_device(SPLIT, devices["outdoor_unit"]))
    assert not any(s in outdoor.entities for s in ENERGY_SIGNALS)
    assert find(VICARE, of_device(SPLIT, devices["system_controller"])) == []


def test_split_system_on_two_gateways_is_not_merged() -> None:
    devices = load_fixture(SPLIT)["devices"]
    controller = on_gateway(
        of_device(SPLIT, devices["system_controller"]), "0000999999999999"
    )
    (match,) = find(VICARE, of_device(SPLIT, devices["outdoor_unit"]) + controller)
    assert not any(s in match.entities for s in ENERGY_SIGNALS)


def test_disabled_controller_energy_is_no_donor() -> None:
    found = [
        e._replace(usable=False) if "consumption" in e.unique_id else e
        for e in entries(SPLIT)
    ]
    (match,) = find(VICARE, found)
    assert not any(s in match.entities for s in ENERGY_SIGNALS)
    assert Signal.DHW_TEMP not in match.entities


def by_compressor(matches: list[Match]) -> dict[str, dict[Signal, str]]:
    return {m.entities[Signal.COMPRESSOR]: m.entities for m in matches}


def test_two_heat_pumps_on_one_gateway() -> None:
    gateway = load_fixture(E3)["gateway"]
    alone = find(VICARE, entries(E3)) + find(VICARE, entries(LEGACY))
    both = find(VICARE, entries(E3) + on_gateway(entries(LEGACY), gateway))
    assert len(both) == 2
    assert len({m.prefix for m in both}) == 2
    assert by_compressor(both) == by_compressor(alone)


def test_two_heat_pumps_and_a_controller_merge_nothing() -> None:
    # The Vitotronic lacks electricity, but which heat pump the controller
    # belongs to is unknown with two compressors on the gateway.
    devices = load_fixture(SPLIT)["devices"]
    found = on_gateway(
        entries(E3) + entries(LEGACY) + of_device(SPLIT, devices["system_controller"]),
        load_fixture(E3)["gateway"],
    )
    alone = find(VICARE, entries(E3)) + find(VICARE, entries(LEGACY))
    assert by_compressor(find(VICARE, found)) == by_compressor(alone)


def test_complete_heat_pump_takes_nothing() -> None:
    # The E3 device has its own electricity: the controller is no donor.
    gateway = load_fixture(E3)["gateway"]
    devices = load_fixture(SPLIT)["devices"]
    controller = on_gateway(of_device(SPLIT, devices["system_controller"]), gateway)
    (alone,) = find(VICARE, entries(E3))
    (match,) = find(VICARE, entries(E3) + controller)
    assert match == alone


def test_two_donors_merge_nothing() -> None:
    prefix = load_fixture(SPLIT)["devices"]["system_controller"]
    second = [
        e._replace(
            entity_id=f"{e.entity_id}_2",
            unique_id=e.unique_id.replace(prefix, f"{prefix}2"),
        )
        for e in of_device(SPLIT, prefix)
    ]
    (match,) = find(VICARE, entries(SPLIT) + second)
    assert not any(s in match.entities for s in ENERGY_SIGNALS)


def test_boiler_is_no_donor() -> None:
    # Vitotronic heat pump (no electricity) and a gas boiler on one gateway.
    gateway = load_fixture(LEGACY)["gateway"]
    boiler = f"{gateway}_0000313131313131"
    electricity = RegistryEntry(
        "sensor.boiler_heating_electricity_consumption_today",
        "vicare",
        f"{boiler}-energy_summary_consumption_heating_currentday",
    )
    burner = RegistryEntry(
        "binary_sensor.boiler_burner", "vicare", f"{boiler}-burner_active-0"
    )
    (alone,) = find(VICARE, entries(LEGACY))
    (match,) = find(VICARE, [*entries(LEGACY), electricity, burner])
    assert match == alone
    # Without the burner the same device would count as the controller.
    (merged,) = find(VICARE, [*entries(LEGACY), electricity])
    assert merged.entities[Signal.ELEC_HEATING] == electricity.entity_id


def test_split_system_found_by_its_template_only() -> None:
    for key, template in TEMPLATES.items():
        found = find(template, entries(SPLIT))
        assert bool(found) == (key == "vicare"), key
