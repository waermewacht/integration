"""Buderus/Bosch MX300/MX400/K30 (`buderus_ha`): template against its fixture."""

from __future__ import annotations

import pytest

from custom_components.waermewacht.counter import UNIT_FACTORS
from custom_components.waermewacht.model import ENERGY_SIGNALS, Activity, Signal
from custom_components.waermewacht.profiles import (
    RegistryEntry,
    find,
    parse_compressor,
)
from custom_components.waermewacht.profiles_buderus import BUDERUS, PLATFORM
from custom_components.waermewacht.templates import TEMPLATES

from .conftest import FIXTURES, load_fixture

FIXTURE = "buderus_mx300.json"
GATEWAY = "1029876543"
S = f"sensor.buderus_gateway_{GATEWAY}_"


def rows() -> list[dict]:
    return load_fixture(FIXTURE)["entities"]


def entries(platform: str = PLATFORM) -> list[RegistryEntry]:
    return [RegistryEntry(e["entity_id"], platform, e["unique_id"]) for e in rows()]


def without(key: str) -> list[RegistryEntry]:
    return [e for e in entries() if e.unique_id != f"{GATEWAY}_{key}"]


EXPECTED = {
    Signal.HEAT_HEATING: S + "erzeugte_warme_heizen",
    Signal.HEAT_DHW: S + "erzeugte_warme_warmwasser",
    Signal.HEAT_COOLING: S + "erzeugte_kuhlenergie",
    Signal.ELEC_HEATING: S + "stromverbrauch_warmepumpe_heizen",
    Signal.ELEC_DHW: S + "stromverbrauch_warmepumpe_warmwasser",
    Signal.ELEC_COOLING: S + "stromverbrauch_warmepumpe_kuhlen",
    Signal.AUX_HEATING: S + "stromverbrauch_elektrischer_zuheizer_heizen",
    Signal.AUX_DHW: S + "stromverbrauch_elektrischer_zuheizer_warmwasser",
    Signal.COMPRESSOR: S + "aktuelle_modulation",
    Signal.ACTIVITY: S + "kompressorstatus",
    Signal.STARTS_TOTAL: S + "anzahl_starts",
    Signal.OUTDOOR_TEMP: S + "aussentemperatur",
    Signal.FLOW_TEMP: S + "vorlauftemperatur",
    Signal.RETURN_TEMP: S + "rucklauftemperatur",
    Signal.DHW_TEMP: S + "warmwasser_ist_temperatur",
}


def test_template_finds_every_signal() -> None:
    (match,) = find(BUDERUS, entries())
    assert match.prefix == GATEWAY
    assert match.entities == EXPECTED
    assert match.missing == []
    assert BUDERUS.experimental
    assert not BUDERUS.day_values  # lifetime counters
    assert not BUDERUS.previous_day


def test_signals_the_source_does_not_have() -> None:
    absent = {
        Signal.FLOW_RATE,
        Signal.AUX_TOTAL,
        Signal.ELEC_TOTAL,
        Signal.ELEC_DEFROST,
        Signal.ELEC_STANDBY,
        Signal.DEFROST_FLAG,
        Signal.DHW_FLAG,
    }
    assert not absent & set(BUDERUS.signals)


def test_nothing_disabled_by_default() -> None:
    assert not any(e["disabled_by_default"] for e in rows())


@pytest.mark.parametrize(
    "key",
    ["actual_modulation", "emon_heating_heat_produced", "emon_heating_compressor"],
)
def test_required_signals(key: str) -> None:
    assert find(BUDERUS, without(key)) == []


def test_activity_is_optional() -> None:
    """compressor_status is not confirmed for every gateway."""
    (match,) = find(BUDERUS, without("compressor_status"))
    assert match.missing == [Signal.ACTIVITY]


def test_unusable_energy_is_not_found() -> None:
    """A gateway without EMON leaves the energy sensors unavailable."""
    found = [
        e._replace(usable=not e.unique_id.endswith("_heat_produced")) for e in entries()
    ]
    assert find(BUDERUS, found) == []


def test_energy_entities_are_lifetime_counters_in_kwh() -> None:
    known = {e["entity_id"]: e["attributes"] for e in rows()}
    (match,) = find(BUDERUS, entries())
    energy = [s for s in match.entities if s in ENERGY_SIGNALS]
    assert len(energy) == 8
    for signal in energy:
        attributes = known[match.entities[signal]]
        assert attributes["unit_of_measurement"] in UNIT_FACTORS, signal
        assert attributes["device_class"] == "energy", signal
        assert attributes["state_class"] == "total_increasing", signal
        assert attributes["resource_id"].startswith("/heatSources/emon/"), signal


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("off", Activity.OFF),
        ("heating", Activity.HEATING),
        ("cooling", Activity.COOLING),
        ("dhw", Activity.DHW),
        ("defrost", Activity.DEFROST),
        ("pool", Activity.OTHER),
        ("pool_heat", Activity.OTHER),
        ("alarm", Activity.OTHER),
        ("something_new", Activity.OTHER),
        ("unknown", None),  # also an undeclared value of the API
        ("unavailable", None),
    ],
)
def test_activity_values(state: str, expected: Activity | None) -> None:
    assert BUDERUS.parse_activity(state) is expected


def test_every_compressor_status_option_is_mapped() -> None:
    (status,) = [e for e in rows() if e["unique_id"] == f"{GATEWAY}_compressor_status"]
    assert set(status["attributes"]["options"]) == set(BUDERUS.activity_values)


@pytest.mark.parametrize(
    ("state", "running"),
    [("46.0", True), ("0", False), ("0.0", False), ("unknown", None)],
)
def test_compressor_from_modulation(state: str, running: bool | None) -> None:
    assert parse_compressor(state) is running


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        (f"{GATEWAY}_emon_heating_compressor", (GATEWAY, "emon_heating_compressor")),
        (f"{GATEWAY}_actual_modulation", (GATEWAY, "actual_modulation")),
        (f"{GATEWAY}_number_of_starts", (GATEWAY, "number_of_starts")),
        (f"{GATEWAY}_number_of_starts_heating", None),
        (f"{GATEWAY}_emon_total_compressor", None),
        (f"{GATEWAY}_dhw_charge_switch", None),
        (f"{GATEWAY}_dhw_charge_duration_number", None),
        (f"{GATEWAY}-emon_heating_compressor", None),
        ("emon_heating_compressor", None),
        ("_emon_heating_compressor", None),
    ],
)
def test_unique_ids(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert BUDERUS.split(unique_id) == expected


def test_one_match_per_gateway() -> None:
    second = [
        RegistryEntry(
            e.entity_id.replace(GATEWAY, "1020000001"),
            PLATFORM,
            e.unique_id.replace(GATEWAY, "1020000001"),
        )
        for e in entries()
    ]
    first, other = find(BUDERUS, entries() + second)
    assert (first.prefix, other.prefix) == ("1020000001", GATEWAY)
    assert other.entities == EXPECTED


def test_templates_do_not_claim_each_other() -> None:
    others = {k: t for k, t in TEMPLATES.items() if k != BUDERUS.key}
    assert PLATFORM not in {t.platform for t in others.values()}
    # Other templates on these entities, under their platforms and ours.
    for key, template in others.items():
        assert find(template, entries()) == [], key
        assert find(template, entries(template.platform)) == [], key
    # This template on every other fixture, under its platform and ours.
    own = {FIXTURE, "buderus_k40_real.json"}
    names = {p.name for p in FIXTURES.glob("*.json")} - {"_index.json", *own}
    assert names
    for name in sorted(names):
        fixture_rows = load_fixture(name)["entities"]
        for platform in {PLATFORM, *(t.platform for t in others.values())}:
            found = [
                RegistryEntry(
                    e["entity_id"], platform, e["unique_id"], e.get("original_name")
                )
                for e in fixture_rows
            ]
            assert find(BUDERUS, found) == [], (name, platform)
    # Same unique ids under a foreign platform do not count.
    assert find(BUDERUS, entries("template")) == []


def test_real_installation() -> None:
    """Registry of a real installation (forum user, K40RF gateway): every
    signal of the template is found, including activity and starts."""
    rows = load_fixture("buderus_k40_real.json")["entities"]
    found = find(
        BUDERUS,
        [
            RegistryEntry(
                r["entity_id"],
                PLATFORM,
                r["unique_id"],
                usable=r.get("disabled_by") is None,
            )
            for r in rows
        ],
    )
    (match,) = found
    by_entity = {r["entity_id"]: r["unique_id"] for r in rows}
    keys = {s: by_entity[e].split("_", 1)[1] for s, e in match.entities.items()}
    assert keys[Signal.HEAT_HEATING] == "emon_heating_heat_produced"
    assert keys[Signal.ELEC_HEATING] == "emon_heating_compressor"
    assert keys[Signal.COMPRESSOR] == "actual_modulation"
    assert keys[Signal.ACTIVITY] == "compressor_status"
    assert keys[Signal.STARTS_TOTAL] == "number_of_starts"
    assert keys[Signal.FLOW_TEMP] == "actual_supply_temperature"
    assert Signal.FLOW_RATE not in keys
    assert BUDERUS.parse_activity("off") is Activity.OFF
