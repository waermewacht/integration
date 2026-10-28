"""iDM template (idm_heatpump) against a fixture derived from its source code."""

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
from custom_components.waermewacht.profiles_idm import IDM

from .conftest import load_fixture

FIXTURE = "idm_navigator20.json"


def entries(*, web: bool = True) -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], "idm_heatpump", e["unique_id"])
        for e in load_fixture(FIXTURE)["entities"]
        if web or e["source"] == "modbus"
    ]


def other_entries() -> list[RegistryEntry]:
    """EMS-ESP and Bosch HomeCom fixtures with their real platforms."""
    ems = [
        RegistryEntry(e["entity_id"], "mqtt", e["unique_id"])
        for e in load_fixture("ems_esp_cs6800i.json")["entities"]
    ]
    homecom = [
        RegistryEntry(e["entity_id"], "bosch_homecom", e["unique_id"])
        for e in load_fixture("bosch_homecom_k40.json")["entities"]
    ]
    return ems + homecom


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        (
            "01JR4T8Q2M6W9X3K5B7N1V0C8D_web_stat_elcons_total_heating",
            ("01JR4T8Q2M6W9X3K5B7N1V0C8D", "web_stat_elcons_total_heating"),
        ),
        (
            "0123456789abcdef0123456789abcdef_hp_operating_mode",  # old UUID hex
            ("0123456789abcdef0123456789abcdef", "hp_operating_mode"),
        ),
        ("01JR4T8Q2M6W9X3K5B7N1V0C8D", None),
        ("_energy_heating", None),
        ("01JR4T8Q2M6W9X3K5B7N1V0C8D_", None),
    ],
)
def test_unique_ids(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert IDM.split(unique_id) == expected


def test_template_finds_every_signal() -> None:
    (match,) = find(IDM, entries())
    assert match.prefix == load_fixture(FIXTURE)["entry_id"]
    assert match.entities == {
        Signal.HEAT_HEATING: "sensor.idm_warmemenge_heizen_gesamt_web_2_0",
        Signal.HEAT_DHW: "sensor.idm_warmemenge_warmwasser_gesamt_web_2_0",
        Signal.HEAT_COOLING: "sensor.idm_warmemenge_kuhlen_gesamt_web_2_0",
        Signal.ELEC_HEATING: "sensor.idm_elektrische_energie_heizen_gesamt_web_2_0",
        Signal.ELEC_DHW: "sensor.idm_elektrische_energie_warmwasser_gesamt_web_2_0",
        Signal.ELEC_COOLING: "sensor.idm_elektrische_energie_kuhlen_gesamt_web_2_0",
        Signal.COMPRESSOR: "binary_sensor.idm_verdichter_1",  # Modbus before web
        Signal.ACTIVITY: "sensor.idm_warmepumpen_betriebsart",
        Signal.STARTS_TOTAL: "sensor.idm_schaltzyklen_stufe_1_web",
        Signal.OUTDOOR_TEMP: "sensor.idm_aussentemperatur",
        Signal.FLOW_TEMP: "sensor.idm_warmepumpe_vorlauf",
        Signal.RETURN_TEMP: "sensor.idm_warmepumpe_rucklauf",
    }
    assert match.missing == []


def test_energy_entities_have_usable_units() -> None:
    (match,) = find(IDM, entries())
    states = {e["entity_id"]: e for e in load_fixture(FIXTURE)["entities"]}
    for signal, entity_id in match.entities.items():
        if signal in ENERGY_SIGNALS:
            attributes = states[entity_id]["attributes"]
            assert attributes["unit_of_measurement"] in UNIT_FACTORS, entity_id
            assert attributes["state_class"] == "total_increasing", entity_id


def test_without_web_statistics_no_heat_pump() -> None:
    """Modbus alone has heat quantities but no electricity per mode
    (Navigator 10, or Navigator 2.0 without web PIN): no match."""
    assert find(IDM, entries(web=False)) == []


def test_web_compressor_when_modbus_hides_it() -> None:
    without = [e for e in entries() if not e.unique_id.endswith("compressor_status_1")]
    (match,) = find(IDM, without)
    assert match.entities[Signal.COMPRESSOR] == "binary_sensor.idm_verdichter_1_web"


@pytest.mark.parametrize(
    ("state", "activity"),
    [
        ("Standby", Activity.OFF),
        ("Heating", Activity.HEATING),
        ("Cooling", Activity.COOLING),
        ("DHW", Activity.DHW),
        ("Defrost", Activity.DEFROST),
        ("Abtauen", Activity.DEFROST),
        ("Heizbetrieb", Activity.HEATING),
        ("Heizbetrieb|Warmwasser", Activity.OTHER),
        ("unknown", None),
        ("unavailable", None),
    ],
)
def test_activity_values(state: str, activity: Activity | None) -> None:
    assert IDM.parse_activity(state) is activity


def test_fixture_activity_values_are_known() -> None:
    values = load_fixture(FIXTURE)["activity_values"]
    assert Activity.OTHER not in [IDM.parse_activity(v) for v in values]


def test_no_cross_matching() -> None:
    assert find(IDM, other_entries()) == []
    # Same entries under a foreign platform name: the formats do not match
    # either (EMS-ESP needs "boiler_", HomeCom splits at "-").
    foreign = [RegistryEntry(e.entity_id, "mqtt", e.unique_id) for e in entries()]
    assert find(EMS_ESP, foreign) == []
    foreign = [
        RegistryEntry(e.entity_id, "bosch_homecom", e.unique_id) for e in entries()
    ]
    assert find(BOSCH_HOMECOM, foreign) == []
    disguised = [
        RegistryEntry(e.entity_id, "idm_heatpump", e.unique_id) for e in other_entries()
    ]
    assert find(IDM, disguised) == []
