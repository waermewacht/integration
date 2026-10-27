"""HeishaMon template (`aquarea` integration) against its fixture."""

from __future__ import annotations

import pytest

from custom_components.waermewacht.counter import UNIT_FACTORS
from custom_components.waermewacht.model import ENERGY_SIGNALS, Activity, Signal
from custom_components.waermewacht.profiles import (
    BOSCH_HOMECOM,
    EMS_ESP,
    RegistryEntry,
    find,
    parse_compressor,
)
from custom_components.waermewacht.profiles_heishamon import (
    ACTIVITY_PARTS,
    HEISHAMON,
    heishamon_activity,
)

from .conftest import load_fixture

FIXTURE = "heishamon_wh_mdc07j3e5.json"


def entries(*, with_disabled: bool = True) -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], "aquarea", e["unique_id"])
        for e in load_fixture(FIXTURE)["entities"]
        if with_disabled or not e["disabled_by_default"]
    ]


def states() -> dict[str, dict]:
    return {e["entity_id"]: e for e in load_fixture(FIXTURE)["entities"]}


def test_template_finds_every_signal() -> None:
    (match,) = find(HEISHAMON, entries())
    assert match.prefix == load_fixture(FIXTURE)["entry_id"]
    assert match.missing == []
    main = "sensor.panasonic_heat_pump_main_"
    assert match.entities == {
        Signal.HEAT_HEATING: "sensor.aquarea_heat_power_produced_total",
        Signal.HEAT_DHW: "sensor.aquarea_dhw_power_produced_total",
        Signal.HEAT_COOLING: "sensor.aquarea_thermal_cooling_power_production_total",
        Signal.ELEC_HEATING: "sensor.aquarea_heat_power_consumed_total",
        Signal.ELEC_DHW: "sensor.aquarea_dhw_power_consumed_total",
        Signal.ELEC_COOLING: "sensor.aquarea_thermal_cooling_power_consumption_total",
        Signal.COMPRESSOR: main + "compressor_freq",
        Signal.ACTIVITY: main + "threeway_valve_state",
        Signal.STARTS_TOTAL: main + "operations_counter",
        Signal.OUTDOOR_TEMP: main + "outside_temp",
        Signal.FLOW_TEMP: main + "main_outlet_temp",
        Signal.RETURN_TEMP: main + "main_inlet_temp",
        Signal.FLOW_RATE: main + "pump_flow",
        Signal.HEAT_POWER: "sensor.panasonic_heat_pump_production",
        Signal.ELEC_POWER: "sensor.panasonic_heat_pump_consumption",
    }
    # No energy of the backup heater in HeishaMon.
    assert not {Signal.AUX_HEATING, Signal.AUX_DHW, Signal.AUX_TOTAL} & set(
        match.entities
    )


def test_energy_entities_are_riemann_sums_in_kwh() -> None:
    (match,) = find(HEISHAMON, entries())
    known = states()
    for signal, entity_id in match.entities.items():
        if signal not in ENERGY_SIGNALS:
            continue
        entity = known[entity_id]
        attributes = entity["attributes"]
        assert attributes["device_class"] == "energy", entity_id
        assert attributes["state_class"] == "total", entity_id  # not ..._increasing
        assert known[attributes["source"]]["attributes"]["unit_of_measurement"] == "W"
        if entity["state"] != "unknown":  # the unit comes with the first power
            assert attributes["unit_of_measurement"] in UNIT_FACTORS, entity_id


def test_works_with_the_defaults_of_aquarea() -> None:
    """Cooling power is disabled by default, its sums exist anyway."""
    (match,) = find(HEISHAMON, entries(with_disabled=False))
    assert match.missing == []


def test_compressor_from_frequency() -> None:
    (match,) = find(HEISHAMON, entries())
    state = states()[match.entities[Signal.COMPRESSOR]]["state"]
    assert parse_compressor(state) is True
    assert parse_compressor("0") is False


@pytest.mark.parametrize(
    ("state", "activity"),
    [
        ("Room", Activity.HEATING),
        ("Tank", Activity.DHW),
        ("something new", Activity.OTHER),
        ("unavailable", None),
    ],
)
def test_valve_values(state: str, activity: Activity | None) -> None:
    assert HEISHAMON.parse_activity(state) is activity


def test_fixture_valve_options_are_known() -> None:
    (match,) = find(HEISHAMON, entries())
    options = states()[match.entities[Signal.ACTIVITY]]["attributes"]["options"]
    assert [HEISHAMON.parse_activity(o) for o in options] == [
        Activity.HEATING,
        Activity.DHW,
    ]


def test_activity_parts_exist_in_the_fixture() -> None:
    found = {
        (e.entity_id.split(".", 1)[0], HEISHAMON.split(e.unique_id)[1])
        for e in entries()
    }
    for part, candidates in ACTIVITY_PARTS.items():
        assert any(c in found for c in candidates), part


@pytest.mark.parametrize(
    ("valve", "defrost", "mode", "activity"),
    [
        ("Room", "off", "Heat+DHW", Activity.HEATING),
        ("Tank", "off", "Heat+DHW", Activity.DHW),
        ("Room", "on", "Heat+DHW", Activity.DEFROST),
        ("Tank", "on", "DHW only", Activity.DEFROST),
        ("Room", "off", "Cool only", Activity.COOLING),
        ("Room", "off", "Auto(Cool)+DHW", Activity.COOLING),
        ("Room", "off", "Auto(Heat)", Activity.HEATING),
        ("Room", "unknown", None, Activity.HEATING),
        ("unknown", "off", "Heat only", None),
        (None, "on", None, Activity.DEFROST),
        ("Pool", "off", "Heat only", Activity.OTHER),
    ],
)
def test_full_activity(
    valve: str | None, defrost: str | None, mode: str | None, activity: Activity
) -> None:
    assert heishamon_activity(valve, defrost, mode) is activity


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        ("01JQ7K3M9X4V2B8N6T5R1W0Y3Z-TOP15", ("01JQ7K3M9X4V2B8N6T5R1W0Y3Z", "TOP15")),
        (
            "01JQ7K3M9X4V2B8N6T5R1W0Y3Z-TOP15_integration",
            ("01JQ7K3M9X4V2B8N6T5R1W0Y3Z", "TOP15_integration"),
        ),
        (
            "0123456789abcdef0123456789abcdef-s0-1-watthour",  # UUID hex entry
            ("0123456789abcdef0123456789abcdef", "s0-1-watthour"),
        ),
    ],
)
def test_unique_ids(unique_id: str, expected: tuple[str, str]) -> None:
    assert HEISHAMON.split(unique_id) == expected


def test_templates_do_not_claim_each_other() -> None:
    assert find(EMS_ESP, entries()) == []
    assert find(BOSCH_HOMECOM, entries()) == []
    ems = [
        RegistryEntry(e["entity_id"], "mqtt", e["unique_id"])
        for e in load_fixture("ems_esp_cs6800i.json")["entities"]
    ]
    homecom = [
        RegistryEntry(e["entity_id"], "bosch_homecom", e["unique_id"])
        for e in load_fixture("bosch_homecom_k40.json")["entities"]
    ]
    assert find(HEISHAMON, ems) == []
    assert find(HEISHAMON, homecom) == []
    # Same unique ids under a foreign platform (e.g. a template copy) do not count.
    copied = [RegistryEntry(e.entity_id, "template", e.unique_id) for e in entries()]
    assert find(HEISHAMON, copied) == []


def test_other_aquarea_integration_is_no_match() -> None:
    """The Panasonic cloud integration uses the same domain `aquarea` (its
    unique id format is not checked; without HeishaMon keys there is no match)."""
    cloud = [
        RegistryEntry("sensor.aquarea_outdoor", "aquarea", "B123456789-outdoor"),
        RegistryEntry("sensor.aquarea_power", "aquarea", "B123456789_power"),
    ]
    assert find(HEISHAMON, cloud) == []
