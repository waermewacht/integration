"""Mitsubishi Ecodan via ESPHome (esphome-ecodan-hp): template against a
fixture from its source."""

from __future__ import annotations

import re

import pytest

from custom_components.waermewacht.activity import combine
from custom_components.waermewacht.counter import UNIT_FACTORS
from custom_components.waermewacht.model import ENERGY_SIGNALS, Activity, Signal
from custom_components.waermewacht.profiles import EMS_ESP, RegistryEntry, find
from custom_components.waermewacht.profiles_esphome_ecodan import (
    ESPHOME_ECODAN,
    LABELS,
    LANGUAGES,
    OPERATION_LABELS,
    label_key,
    parse_unique_id,
)
from custom_components.waermewacht.profiles_f1p import F1P
from custom_components.waermewacht.templates import TEMPLATES

from .conftest import FIXTURES, load_fixture

FIXTURE = "esphome_ecodan.json"
MAC = "A0:B1:C2:D3:E4:F5"
EN = LANGUAGES.index("en")


def entries(fixture: str = FIXTURE, platform: str = "esphome") -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], platform, e["unique_id"], e.get("original_name"))
        for e in load_fixture(fixture)["entities"]
    ]


S = "sensor.ecodan_heatpump_"
EXPECTED = {
    Signal.HEAT_HEATING: S + "heating_delivered",
    Signal.HEAT_DHW: S + "dhw_delivered",
    Signal.HEAT_COOLING: S + "cool_delivered",
    Signal.ELEC_HEATING: S + "heating_consumed",
    Signal.ELEC_DHW: S + "dhw_consumed",
    Signal.ELEC_COOLING: S + "cool_consumed",
    Signal.COMPRESSOR: S + "compressor_frequency",  # not binary_sensor.…_compressor
    Signal.ACTIVITY: S + "operation_mode",  # not the select
    Signal.DEFROST_FLAG: "binary_sensor.ecodan_heatpump_defrost",
    Signal.OUTDOOR_TEMP: S + "outside_temp",
    Signal.FLOW_TEMP: S + "feed_temp",  # not Z1 Feed Temp, not the boiler's
    Signal.RETURN_TEMP: S + "return_temp",
    Signal.FLOW_RATE: S + "flow_rate",
    Signal.DHW_TEMP: S + "dhw_current_temp",  # not the secondary sensor
}


def test_template_finds_every_signal() -> None:
    (match,) = find(ESPHOME_ECODAN, entries())
    assert match.prefix == MAC == load_fixture(FIXTURE)["prefix"]
    assert match.entities == EXPECTED
    assert match.missing == []
    assert match.history == {}


def test_previous_day_values_with_compressor() -> None:
    t = ESPHOME_ECODAN
    assert t.day_values and t.previous_day and t.experimental
    assert t.day_timezone is None
    assert t.platform == "esphome"
    assert t.required == (Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING)
    # Starts are counted in hundreds: Wärmewacht counts them itself.
    assert Signal.STARTS_TOTAL not in t.signals


def test_lifetime_counters_are_not_taken() -> None:
    (match,) = find(ESPHOME_ECODAN, entries())
    assert not any("total" in e for e in match.entities.values())


def test_energy_entities_have_usable_units() -> None:
    attributes = {
        e["entity_id"]: e["attributes"] for e in load_fixture(FIXTURE)["entities"]
    }
    for signal, entity_id in EXPECTED.items():
        if signal in ENERGY_SIGNALS:
            assert attributes[entity_id]["unit_of_measurement"] in UNIT_FACTORS
            assert attributes[entity_id]["device_class"] == "energy"
            assert attributes[entity_id]["state_class"] == "total"


def _slug(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", name.lower())).strip("_")


def translated(language: str) -> list[RegistryEntry]:
    """The fixture as built with another label file: the signals' names,
    unique ids and entity ids in that language, everything else English."""
    english = {
        labels[EN]: labels[LANGUAGES.index(language)] for labels in LABELS.values()
    }
    result = []
    for entry in entries():
        name = entry.original_name or ""
        if name not in english:
            result.append(entry)
            continue
        new = english[name]
        domain = entry.entity_id.split(".", 1)[0]
        result.append(
            entry._replace(
                entity_id=f"{domain}.ecodan_heatpump_{_slug(new)}",
                unique_id=entry.unique_id.removesuffix(name) + new,
                original_name=new,
            )
        )
    return result


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_language_is_found(language: str) -> None:
    (match,) = find(ESPHOME_ECODAN, translated(language))
    assert set(match.entities) == set(EXPECTED)
    english = {e.entity_id: e.original_name for e in entries()}
    by_entity = {e.entity_id: e.original_name for e in translated(language)}
    for signal, entity_id in match.entities.items():
        key = next(k for _, k in ESPHOME_ECODAN.signals[signal])
        assert by_entity[entity_id] == LABELS[key][LANGUAGES.index(language)]
        assert english[EXPECTED[signal]] == LABELS[key][EN]


def test_german_operation_mode_is_not_the_select() -> None:
    """German labels name the text sensor and the select "Betriebsmodus"."""
    german = [
        e._replace(
            entity_id="select.ecodan_heatpump_betriebsmodus",
            unique_id=f"{MAC}/0/select/Betriebsmodus",
            original_name="Betriebsmodus",
        )
        if e.entity_id.startswith("select.")
        else e
        for e in translated("de")
    ]
    (match,) = find(ESPHOME_ECODAN, german)
    assert match.entities[Signal.ACTIVITY] == "sensor.ecodan_heatpump_betriebsmodus"
    assert (
        match.entities[Signal.OUTDOOR_TEMP] == "sensor.ecodan_heatpump_au_entemperatur"
    )
    assert match.entities[Signal.ELEC_HEATING] == (
        "sensor.ecodan_heatpump_heizung_verbraucht"
    )


def test_user_renamed_entity_is_still_found() -> None:
    """A rename in Home Assistant changes the entity id and the name shown,
    not original_name or the unique id."""
    renamed = [
        e._replace(entity_id="sensor.wp_strom_heizen")
        if e.entity_id == EXPECTED[Signal.ELEC_HEATING]
        else e
        for e in entries()
    ]
    (match,) = find(ESPHOME_ECODAN, renamed)
    assert match.entities[Signal.ELEC_HEATING] == "sensor.wp_strom_heizen"


def test_original_name_wins_over_the_unique_id() -> None:
    """A version 1 id whose object_id no label fits: the firmware's name decides."""
    odd = [
        e._replace(unique_id=f"{MAC}-sensor-something_else")
        if e.entity_id == EXPECTED[Signal.HEAT_HEATING]
        else e
        for e in entries()
    ]
    (match,) = find(ESPHOME_ECODAN, odd)
    assert match.entities[Signal.HEAT_HEATING] == EXPECTED[Signal.HEAT_HEATING]


def test_label_changed_in_the_firmware_is_not_found() -> None:
    """Custom labels: the user chooses the entities by hand."""
    custom = [
        e._replace(
            unique_id=f"{MAC}/0/sensor/WP Strom Heizen", original_name="WP Strom Heizen"
        )
        if e.entity_id == EXPECTED[Signal.ELEC_HEATING]
        else e
        for e in entries()
    ]
    assert find(ESPHOME_ECODAN, custom) == []


def test_legacy_unique_ids_without_original_name() -> None:
    """Version 1 ids ("<MAC>-<type>-<object_id>") before HA migrated them."""
    legacy = []
    for entry in entries():
        mac, _, kind, name = entry.unique_id.split("/", 3)
        legacy.append(
            entry._replace(unique_id=f"{mac}-{kind}-{_slug(name)}", original_name=None)
        )
    (match,) = find(ESPHOME_ECODAN, legacy)
    assert match.prefix == MAC
    assert match.entities == EXPECTED


def test_unusable_entities_are_left_out() -> None:
    assert find(ESPHOME_ECODAN, [e._replace(usable=False) for e in entries()]) == []
    without_compressor = [
        e for e in entries() if e.entity_id != EXPECTED[Signal.COMPRESSOR]
    ]
    assert find(ESPHOME_ECODAN, without_compressor) == []


def test_two_heat_pumps_by_mac() -> None:
    other = "02:00:00:00:00:01"
    second = [
        e._replace(
            entity_id=e.entity_id.replace("ecodan_heatpump", "ecodan_heatpump_2"),
            unique_id=e.unique_id.replace(MAC, other),
        )
        for e in entries()
    ]
    found = find(ESPHOME_ECODAN, entries() + second)
    assert [m.prefix for m in found] == [other, MAC]


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        (f"{MAC}/0/sensor/Heating Consumed", (MAC, "Heating Consumed")),
        (f"{MAC}/0/text_sensor/Operation Mode", (MAC, "Operation Mode")),
        (f"{MAC}/0/binary_sensor/Defrost", (MAC, "Defrost")),
        (f"{MAC}/22222222/sensor/Feed Temp", (f"{MAC}/22222222", "Feed Temp")),
        ("a0:b1:c2:d3:e4:f5/0/sensor/Feed Temp", (MAC, "Feed Temp")),
        (f"{MAC}/0/sensor/A/B", (MAC, "A/B")),  # a "/" in the name
        (f"{MAC}-sensor-heating_consumed", (MAC, "heating_consumed")),  # version 1
        (f"{MAC}-sensor-Heating Consumed", (MAC, "Heating Consumed")),  # version 2
        (f"{MAC}-sensor-kompressor-frequenz", (MAC, "kompressor-frequenz")),
        (f"{MAC}-sensor-feed_temp@22222222", (f"{MAC}/22222222", "feed_temp")),
        (f"{MAC}/0/select/Betriebsmodus", None),
        (f"{MAC}/0/climate/DHW Climate", None),
        (f"{MAC}-ble-presence", None),  # Bluetooth proxy entities
        (f"{MAC}/0/sensor/", None),
        ("ecodan/0/sensor/Feed Temp", None),
        ("9900000001-02:00:00:00:00:01-daily_heating_energy_consumed", None),
        ("ashp_consumed_heat_abcdef123456", None),
        ("boiler_nrgheat", None),
    ],
)
def test_parse_unique_id(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert parse_unique_id(unique_id) == expected


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Heating Consumed", "heating_consumed"),
        ("heating consumed ", "heating_consumed"),
        ("Heizung Verbraucht", "heating_consumed"),
        ("En. Risc. Prod. Ieri", "heating_delivered"),  # Italian: "yesterday"
        ("Außentemperatur", "outside_temp"),
        ("au_entemperatur", "outside_temp"),  # object_id, one "_" per character
        ("au__entemperatur", "outside_temp"),  # object_id, one "_" per byte
        ("kompressor-frequenz", "compressor_frequency"),
        ("Total Heating Consumed", None),
        ("Selected operating mode", None),
        ("", None),
        (None, None),
    ],
)
def test_label_key(name: str | None, key: str | None) -> None:
    assert label_key(name) == key


def test_label_tables_are_complete_and_unambiguous() -> None:
    assert len(LANGUAGES) == len(set(LANGUAGES)) == 14
    for labels in (*LABELS.values(), *OPERATION_LABELS.values()):
        assert len(labels) == len(LANGUAGES)
        assert all(label.strip() == label and label for label in labels)
    for key, labels in LABELS.items():
        assert all(label_key(label) == key for label in labels), key
    for _, candidates in ESPHOME_ECODAN.signals.items():
        assert all(k in LABELS for _, k in candidates)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("Off", Activity.OFF),
        ("Heating Water", Activity.DHW),
        ("Space Heating", Activity.HEATING),
        ("Space Cooling", Activity.COOLING),
        ("Legionella Prevention", Activity.DHW),
        ("Frost Protection", Activity.OTHER),
        ("Raumheizung", Activity.HEATING),
        ("Warmwasser", Activity.DHW),
        ("Aus", Activity.OFF),
        ("Unknown", None),
        ("Something new", Activity.OTHER),
        ("unavailable", None),
    ],
)
def test_activity_values(state: str, expected: Activity | None) -> None:
    assert ESPHOME_ECODAN.parse_activity(state) is expected


def test_every_operation_word_is_mapped() -> None:
    for value in load_fixture(FIXTURE)["operation_mode_values"]:
        assert value.casefold() in ESPHOME_ECODAN.activity_values
    for key, words in OPERATION_LABELS.items():
        values = {ESPHOME_ECODAN.parse_activity(w) for w in words}
        assert len(values) == 1, key  # no word means two things


def test_defrost_flag_beats_the_operation_mode() -> None:
    configured = {Signal.ACTIVITY, Signal.DEFROST_FLAG}
    heating = ESPHOME_ECODAN.parse_activity("Space Heating")
    on = {Signal.DEFROST_FLAG: "on"}
    assert combine(heating, on, configured) is Activity.DEFROST
    off = {Signal.DEFROST_FLAG: "off"}
    assert combine(heating, off, configured) is Activity.HEATING


def test_no_other_template_claims_esphome_ecodan() -> None:
    for key, template in TEMPLATES.items():
        if template is ESPHOME_ECODAN:
            continue
        # As if the ESPHome unique ids came from the template's own platform.
        assert find(template, entries(platform=template.platform)) == [], key
    assert find(EMS_ESP, entries(platform="mqtt")) == []
    assert find(F1P, entries(platform="mqtt")) == []


def _fixtures() -> list[str]:
    return sorted(
        p.name
        for p in FIXTURES.glob("*.json")
        if p.name not in ("_index.json", FIXTURE)
    )


@pytest.mark.parametrize("fixture", _fixtures())
def test_esphome_ecodan_claims_no_other_fixture(fixture: str) -> None:
    # Any platform: not even the unique ids alone may look like ESPHome's.
    assert find(ESPHOME_ECODAN, entries(fixture, ESPHOME_ECODAN.platform)) == []
    for entity in load_fixture(fixture)["entities"]:
        assert parse_unique_id(entity["unique_id"]) is None, entity["unique_id"]
