"""Templates: unique id formats, activity values, compressor states."""

from __future__ import annotations

import pytest

from custom_components.waermewacht.model import Activity, Signal
from custom_components.waermewacht.profiles import (
    BOSCH_HOMECOM,
    EMS_ESP,
    RegistryEntry,
    find,
    parse_compressor,
)

from .conftest import load_fixture


def entries(prefix: str, names: dict[str, str]) -> list[RegistryEntry]:
    """Registry entries as EMS-ESP creates them via MQTT discovery."""
    base = f"{prefix}_" if prefix else ""
    return [
        RegistryEntry(
            f"{domain}.{base}boiler_{key}".replace("-", "_"),
            "mqtt",
            f"{base}boiler_{key}",
        )
        for key, domain in names.items()
    ]


CURRENT = {
    "nrgheat": "sensor",
    "nrgsuppheating": "sensor",
    "dhw_nrg": "sensor",
    "nrgcool": "sensor",
    "meterheat": "sensor",
    "dhw_meter": "sensor",
    "metercool": "sensor",
    "auxelecheatnrgconsheating": "sensor",
    "dhw_auxelecheatnrgcons": "sensor",
    "hpcompon": "binary_sensor",
    "hp4way": "binary_sensor",
    "hpactivity": "sensor",
    "totalcompstarts": "sensor",
    "outdoortemp": "sensor",
}


def test_single_instance_short_names() -> None:
    (match,) = find(EMS_ESP, entries("", CURRENT))
    assert match.prefix == ""
    assert (
        match.entities[Signal.HEAT_HEATING] == "sensor.boiler_nrgheat"
    )  # 0.01 kWh first
    assert match.entities[Signal.HEAT_DHW] == "sensor.boiler_dhw_nrg"
    assert match.entities[Signal.COMPRESSOR] == "binary_sensor.boiler_hpcompon"
    assert Signal.FLOW_TEMP in match.missing


def test_compatibility_names_of_3_6() -> None:
    names = {
        "nrgheat": "sensor",
        "nrgww": "sensor",
        "meterheat": "sensor",
        "wwmeter": "sensor",
        "hpcompon": "binary_sensor",
    }
    (match,) = find(EMS_ESP, entries("", names))
    assert match.entities[Signal.HEAT_DHW] == "sensor.boiler_nrgww"
    assert match.entities[Signal.ELEC_DHW] == "sensor.boiler_wwmeter"


def test_current_names_win_over_old_ones() -> None:
    """Both formats can exist side by side after a change of the setting."""
    names = {**CURRENT, "nrgww": "sensor", "wwmeter": "sensor"}
    (match,) = find(EMS_ESP, entries("", names))
    assert match.entities[Signal.HEAT_DHW] == "sensor.boiler_dhw_nrg"
    assert match.entities[Signal.ELEC_DHW] == "sensor.boiler_dhw_meter"


def test_multiple_instances_by_prefix() -> None:
    found = find(EMS_ESP, entries("ems-esp", CURRENT) + entries("ems-esp2", CURRENT))
    assert [m.prefix for m in found] == ["ems-esp", "ems-esp2"]
    assert found[0].entities[Signal.HEAT_HEATING] == "sensor.ems_esp_boiler_nrgheat"


def test_gas_boiler_is_no_heat_pump() -> None:
    """Gas boilers share short names like nrgheat but have no compressor."""
    names = {"nrgheat": "sensor", "meterheat": "sensor", "burnstarts": "sensor"}
    assert find(EMS_ESP, entries("", names)) == []


def test_other_platforms_are_ignored() -> None:
    other = [RegistryEntry("sensor.boiler_nrgheat", "template", "boiler_nrgheat")]
    assert find(EMS_ESP, other) == []


@pytest.mark.parametrize(
    ("state", "activity"),
    [
        ("Heizen", Activity.HEATING),
        ("heating", Activity.HEATING),
        ("Warmwasser", Activity.DHW),
        ("hot water", Activity.DHW),
        ("Abtauen", Activity.DEFROST),
        ("dégivrage", Activity.DEFROST),
        ("aus", Activity.OFF),
        ("Kühlen", Activity.COOLING),
        ("6", Activity.DEFROST),
        ("Pool beheizen", Activity.OTHER),
        ("something new", Activity.OTHER),
    ],
)
def test_activity_values(state: str, activity: Activity) -> None:
    assert EMS_ESP.parse_activity(state) is activity


@pytest.mark.parametrize("state", [None, "unknown", "unavailable"])
def test_unknown_activity(state: str | None) -> None:
    assert EMS_ESP.parse_activity(state) is None


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        ("101234567-heat_produced_ch", ("101234567", "heat_produced_ch")),
        ("101234567-dhw1-delta_t", ("101234567", "dhw1-delta_t")),  # first "-"
        ("101234567", None),
        ("-heat_produced_ch", None),
    ],
)
def test_homecom_unique_ids(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert BOSCH_HOMECOM.split(unique_id) == expected


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        ("boiler_nrgheat", ("", "nrgheat")),
        ("ems-esp_boiler_nrgheat", ("ems-esp", "nrgheat")),  # multiple instances
        ("ems-esp2_boiler_dhw_nrg", ("ems-esp2", "dhw_nrg")),
        ("boiler_x_boiler_y", ("", "x_boiler_y")),  # no prefix: the first "boiler_"
        ("_boiler_nrgheat", None),
        ("boiler_", None),
        ("thermostat_hc1_seltemp", None),
    ],
)
def test_ems_esp_unique_ids(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert EMS_ESP.split(unique_id) == expected


@pytest.mark.parametrize(
    ("state", "running"),
    [
        ("on", True),
        ("off", False),
        ("42", True),
        ("0", False),
        ("0.0", False),
        ("unavailable", None),
        ("unknown", None),
        (None, None),
    ],
)
def test_compressor_from_on_off_or_speed(
    state: str | None, running: bool | None
) -> None:
    assert parse_compressor(state) is running


def test_ems_esp_long_names_v34() -> None:
    """EMS-ESP format "single instance, long names (v3.4)": unique ids from
    the English full names (forum report: Buderus not found, English names)."""
    found = find(
        EMS_ESP,
        [
            RegistryEntry(e["entity_id"], "mqtt", e["unique_id"])
            for e in load_fixture("ems_esp_long_names.json")["entities"]
        ],
    )
    (match,) = found
    by_uid = {
        s: next(
            e["unique_id"]
            for e in load_fixture("ems_esp_long_names.json")["entities"]
            if e["entity_id"] == entity_id
        )
        for s, entity_id in match.entities.items()
    }
    assert by_uid[Signal.HEAT_HEATING] == "boiler_energy_heating"
    assert by_uid[Signal.ELEC_HEATING] == "boiler_meter_heating"
    assert by_uid[Signal.HEAT_DHW] == "boiler_dhw_energy"
    assert by_uid[Signal.ELEC_DHW] == "boiler_dhw_meter"
    assert by_uid[Signal.COMPRESSOR] == "boiler_hp_compressor"
    assert by_uid[Signal.ACTIVITY] == "boiler_compressor_activity"
    assert by_uid[Signal.FLOW_TEMP] == "boiler_heat_carrier_forward_(tc1)"
    assert by_uid[Signal.AUX_HEATING] == (
        "boiler_aux_elec._heater_energy_consumption_heating"
    )


def test_homecom_compressor_status_is_the_activity() -> None:
    """bosch_homecom from PR #217: "<gateway>-compressor_status", the words of
    the PointT cloud; before it, the template simply finds no activity."""
    rows = load_fixture("bosch_homecom_k40.json")["entities"]
    base = [
        RegistryEntry(r["entity_id"], "bosch_homecom", r["unique_id"]) for r in rows
    ]
    (without,) = find(BOSCH_HOMECOM, base)
    assert Signal.ACTIVITY not in without.entities
    status = RegistryEntry(
        "sensor.boschcom_k40_101234567_compressor_status",
        "bosch_homecom",
        "101234567-compressor_status",
    )
    (match,) = find(BOSCH_HOMECOM, [*base, status])
    assert match.entities[Signal.ACTIVITY] == status.entity_id
    assert BOSCH_HOMECOM.parse_activity("defrost") is Activity.DEFROST
    assert BOSCH_HOMECOM.parse_activity("dhw") is Activity.DHW
    assert BOSCH_HOMECOM.parse_activity("pool_heat") is Activity.OTHER
