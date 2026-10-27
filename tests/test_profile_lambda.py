"""Lambda template (`lambda_heat_pumps`) against its fixture."""

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
from custom_components.waermewacht.profiles_lambda import LAMBDA

from .conftest import load_fixture

FIXTURE = "lambda_eu08l.json"
PLATFORM = "lambda_heat_pumps"


def entries() -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], PLATFORM, e["unique_id"])
        for e in load_fixture(FIXTURE)["entities"]
    ]


def states() -> dict[str, dict]:
    return {e["entity_id"]: e for e in load_fixture(FIXTURE)["entities"]}


def test_template_finds_every_signal() -> None:
    (match,) = find(LAMBDA, entries())
    assert match.prefix == "eu08l_hp1"
    hp = "sensor.eu08l_hp1_"
    assert match.entities == {
        Signal.HEAT_HEATING: hp + "heating_thermal_energy_total",
        Signal.HEAT_DHW: hp + "hot_water_thermal_energy_total",
        Signal.HEAT_COOLING: hp + "cooling_thermal_energy_total",
        Signal.ELEC_HEATING: hp + "heating_energy_total",
        Signal.ELEC_DHW: hp + "hot_water_energy_total",
        Signal.ELEC_COOLING: hp + "cooling_energy_total",
        Signal.COMPRESSOR: hp + "compressor_unit_rating",
        Signal.ACTIVITY: hp + "operating_state",
        Signal.STARTS_TOTAL: hp + "compressor_start_cycling_total",
        Signal.OUTDOOR_TEMP: "sensor.eu08l_ambient_temperature",
        Signal.FLOW_TEMP: hp + "flow_line_temperature",  # not hc1_…
        Signal.RETURN_TEMP: hp + "return_line_temperature",
        Signal.HEAT_POWER: hp + "actual_heating_capacity",
        Signal.ELEC_POWER: hp + "inverter_power_consumption",
    }
    assert match.missing == []
    # No backup heater energy, flow rate left out (no volume_flow_rate class).
    assert not {
        Signal.AUX_HEATING,
        Signal.AUX_DHW,
        Signal.AUX_TOTAL,
        Signal.FLOW_RATE,
    } & set(LAMBDA.signals)


def test_energy_entities_are_lifetime_counters_in_kwh() -> None:
    (match,) = find(LAMBDA, entries())
    known = states()
    for signal, entity_id in match.entities.items():
        if signal not in ENERGY_SIGNALS:
            continue
        attributes = known[entity_id]["attributes"]
        assert attributes["unit_of_measurement"] in UNIT_FACTORS, entity_id
        assert attributes["device_class"] == "energy", entity_id
        # Heat totals are "total", electricity totals "total_increasing".
        assert attributes["state_class"] in ("total", "total_increasing"), entity_id
        assert entity_id.endswith("_total"), entity_id  # not daily/monthly/yearly


def test_compressor_from_unit_rating() -> None:
    (match,) = find(LAMBDA, entries())
    assert parse_compressor(states()[match.entities[Signal.COMPRESSOR]]["state"])
    assert parse_compressor("0.0") is False


def test_every_operating_state_is_mapped() -> None:
    (match,) = find(LAMBDA, entries())
    options = states()[match.entities[Signal.ACTIVITY]]["attributes"]["options"]
    assert {o.casefold() for o in options} == set(LAMBDA.activity_values)


@pytest.mark.parametrize(
    ("state", "activity"),
    [
        ("CH", Activity.HEATING),
        ("DHW", Activity.DHW),
        ("CC", Activity.COOLING),
        ("DEFROST", Activity.DEFROST),
        ("STBY", Activity.OFF),
        ("OFF", Activity.OFF),
        ("TIME-BLOCK", Activity.OFF),
        ("FROST", Activity.OTHER),
        ("ERROR", Activity.OTHER),
        ("Unknown state (42)", Activity.OTHER),
        ("unavailable", None),
    ],
)
def test_activity_values(state: str, activity: Activity | None) -> None:
    assert LAMBDA.parse_activity(state) is activity


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        ("eu08l_hp1_heating_energy_total", ("eu08l_hp1", "heating_energy_total")),
        ("eu08l_hp2_heating_energy_total", ("eu08l_hp2", "heating_energy_total")),
        ("hp1_heating_energy_total", ("hp1", "heating_energy_total")),  # standard
        ("lambda_eu10l_hp1_operating_state", ("lambda_eu10l_hp1", "operating_state")),
        ("my_hp1_hp1_operating_state", ("my_hp1_hp1", "operating_state")),
        ("eu08l_ambient_temperature", ("eu08l_hp1", "ambient_temperature")),
        ("ambient_temperature", ("hp1", "ambient_temperature")),
        ("eu08l_hc1_flow_line_temperature", None),  # heating circuit
        ("eu08l_hp1_requested_flow_line_temperature", None),
        ("eu08l_ambient_operating_state", None),
        ("eu08l_boil1_operating_state", None),
        ("eu08l_hp1_heating_energy_daily", None),
        ("eu08l_hp1_", None),
    ],
)
def test_unique_ids(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert LAMBDA.split(unique_id) == expected


def test_one_match_per_heat_pump() -> None:
    """A cascade has hp1..hp3; the outdoor temperature goes to heat pump 1."""
    second = [
        RegistryEntry(
            e.entity_id.replace("_hp1_", "_hp2_"),
            PLATFORM,
            e.unique_id.replace("_hp1_", "_hp2_"),
        )
        for e in entries()
        if "_hp1_" in e.unique_id
    ]
    first, other = find(LAMBDA, entries() + second)
    assert (first.prefix, other.prefix) == ("eu08l_hp1", "eu08l_hp2")
    assert other.entities[Signal.HEAT_HEATING] == (
        "sensor.eu08l_hp2_heating_thermal_energy_total"
    )
    assert Signal.OUTDOOR_TEMP in first.entities
    assert Signal.OUTDOOR_TEMP not in other.entities


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
    assert find(LAMBDA, ems) == []
    assert find(LAMBDA, homecom) == []
    # Same unique ids under a foreign platform (e.g. a template copy) do not count.
    copied = [RegistryEntry(e.entity_id, "template", e.unique_id) for e in entries()]
    assert find(LAMBDA, copied) == []
