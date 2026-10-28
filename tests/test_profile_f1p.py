"""Mitsubishi Ecodan via the F1p bridge: template against a fixture from its source."""

from __future__ import annotations

import pytest

from custom_components.waermewacht.counter import UNIT_FACTORS
from custom_components.waermewacht.model import ENERGY_SIGNALS, Activity, Signal
from custom_components.waermewacht.profiles import EMS_ESP, RegistryEntry, find
from custom_components.waermewacht.profiles_f1p import F1P, F1P_KEYS
from custom_components.waermewacht.templates import TEMPLATES

from .conftest import FIXTURES, load_fixture

FIXTURE = "f1p_ecodan.json"
DEVICE = "abcdef123456"


def entries(fixture: str = FIXTURE, platform: str = "mqtt") -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], platform, e["unique_id"], e.get("original_name"))
        for e in load_fixture(fixture)["entities"]
    ]


def test_template_finds_every_signal() -> None:
    (match,) = find(F1P, entries())
    assert match.prefix == DEVICE
    s = "sensor.ecodan_ashp_"
    assert match.entities == {
        Signal.HEAT_HEATING: s + "delivered_heating_yesterday",
        Signal.HEAT_DHW: s + "delivered_dhw_yesterday",
        Signal.HEAT_COOLING: s + "delivered_cooling_yesterday",
        Signal.ELEC_HEATING: s + "consumed_heating_yesterday",
        Signal.ELEC_DHW: s + "consumed_dhw_yesterday",
        Signal.ELEC_COOLING: s + "consumed_cooling_yesterday",
        Signal.COMPRESSOR: s + "compressor_frequency",
        Signal.ACTIVITY: s + "system_operation_mode",
        Signal.OUTDOOR_TEMP: s + "outside_temperature",
        Signal.FLOW_TEMP: s + "heater_flow_temperature",  # not boiler, not zone 1
        Signal.RETURN_TEMP: s + "heater_return_temperature",
        Signal.FLOW_RATE: s + "flow_rate",
        Signal.DHW_TEMP: s + "dhw_temperature",  # not the upper sensor
    }
    assert match.missing == []
    assert match.history == {}


def test_missing_signals_and_required() -> None:
    keep = [e for e in entries() if not e.unique_id.startswith("ashp_delivered_cool_")]
    (match,) = find(F1P, keep)
    assert match.missing == [Signal.HEAT_COOLING]
    without_compressor = [
        e for e in entries() if not e.unique_id.startswith("ashp_compressor_freq_")
    ]
    assert find(F1P, without_compressor) == []
    unusable = [e._replace(usable=False) for e in entries()]
    assert find(F1P, unusable) == []


def test_energy_entities_have_usable_units() -> None:
    attributes = {
        e["entity_id"]: e["attributes"] for e in load_fixture(FIXTURE)["entities"]
    }
    (match,) = find(F1P, entries())
    for signal, entity_id in match.entities.items():
        if signal in ENERGY_SIGNALS:
            assert attributes[entity_id]["unit_of_measurement"] in UNIT_FACTORS
            assert attributes[entity_id]["device_class"] == "energy"
            # F1p sets a state class only on units other than kWh.
            assert "state_class" not in attributes[entity_id]


def test_previous_day_values_with_compressor() -> None:
    assert F1P.day_values and F1P.previous_day and F1P.experimental
    assert F1P.day_timezone is None
    assert F1P.platform == "mqtt"
    assert F1P.required == (Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING)


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        (f"ashp_consumed_heat_{DEVICE}", (DEVICE, "ashp_consumed_heat_")),
        # No "_" between key and deviceId.
        (f"ashp_comp_op_times{DEVICE}", (DEVICE, "ashp_comp_op_times")),
        ("ashp_op_mode_1a2b3c", ("1a2b3c", "ashp_op_mode_")),  # ESP8266 chip id
        # A key that starts with another key: the longest wins.
        (f"ashp_dhw_temp_thw5a_{DEVICE}", (DEVICE, "ashp_dhw_temp_thw5a_")),
        (f"ashp_dhw_temp_{DEVICE}", (DEVICE, "ashp_dhw_temp_")),
        (f"ashp_dhw_mode_{DEVICE}", (DEVICE, "ashp_dhw_mode_")),  # sensor
        (f"ashp_dhw_mode{DEVICE}", (DEVICE, "ashp_dhw_mode")),  # select
        (f"ashp_heat_cool_mode_z2{DEVICE}", (DEVICE, "ashp_heat_cool_mode_z2")),
        (f"gshp_brine_in_{DEVICE}", (DEVICE, "gshp_brine_in_")),
        ("ashp_consumed_heat_", None),  # no deviceId
        ("ashp_unknown_key_abc", None),
        (f"aa{DEVICE}", None),  # air-to-air bridge
        ("boiler_nrgheat", None),  # EMS-ESP
        ("ems-esp_boiler_meterheat", None),
        ("9900000001-02:00:00:00:00:01-daily_heating_energy_consumed", None),
    ],
)
def test_unique_ids(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert F1P.split(unique_id) == expected


def test_signal_keys_are_firmware_keys() -> None:
    assert len(F1P_KEYS) == len(set(F1P_KEYS)) == 129
    for candidates in F1P.signals.values():
        for _, key in candidates:
            assert key in F1P_KEYS


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("Off", Activity.OFF),
        ("Hot Water", Activity.DHW),
        ("Legionella", Activity.DHW),
        ("Heating", Activity.HEATING),
        ("Heating Eco", Activity.HEATING),
        ("Cooling", Activity.COOLING),
        ("Defrosting", Activity.DEFROST),
        ("Zero V", Activity.OTHER),
        ("Frost Protect", Activity.OTHER),
        ("Something new", Activity.OTHER),
        ("unknown", None),
        ("unavailable", None),
    ],
)
def test_activity_values(state: str, expected: Activity | None) -> None:
    assert F1P.parse_activity(state) is expected


def test_every_operation_mode_is_mapped() -> None:
    for value in load_fixture(FIXTURE)["operation_mode_values"]:
        assert value.casefold() in F1P.activity_values


def test_no_other_template_claims_f1p() -> None:
    for key, template in TEMPLATES.items():
        if template is F1P:
            continue
        # As if the F1p unique ids came from the template's own platform.
        assert find(template, entries(platform=template.platform)) == [], key
    assert EMS_ESP.platform == F1P.platform  # the case that matters
    assert find(EMS_ESP, entries()) == []


def _fixtures() -> list[str]:
    return sorted(
        p.name
        for p in FIXTURES.glob("*.json")
        if p.name not in ("_index.json", FIXTURE)
    )


@pytest.mark.parametrize("fixture", _fixtures())
def test_f1p_claims_no_other_fixture(fixture: str) -> None:
    # Any platform: not even the unique ids alone may look like F1p's.
    assert find(F1P, entries(fixture, F1P.platform)) == []
    for entity in load_fixture(fixture)["entities"]:
        assert F1P.split(entity["unique_id"]) is None, entity["unique_id"]
