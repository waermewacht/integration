"""Mitsubishi Ecodan via MELCloud: template against a fixture from its source."""

from __future__ import annotations

import pytest

from custom_components.waermewacht.counter import UNIT_FACTORS
from custom_components.waermewacht.model import ENERGY_SIGNALS, Signal
from custom_components.waermewacht.profiles import RegistryEntry, find
from custom_components.waermewacht.profiles_melcloud import MELCLOUD

from .conftest import load_fixture

FIXTURE = "melcloud_ecodan.json"
PREFIX = "9900000001-02:00:00:00:00:01"


def entries(*, with_disabled: bool = True) -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], "melcloud", e["unique_id"])
        for e in load_fixture(FIXTURE)["entities"]
        if with_disabled or not e["disabled_by_default"]
    ]


def test_template_finds_every_signal() -> None:
    (match,) = find(MELCLOUD, entries())  # the air conditioner is no match
    assert match.prefix == PREFIX
    s = "sensor.ecodan_"
    assert match.entities == {
        Signal.HEAT_HEATING: s + "daily_heating_energy_produced",
        Signal.HEAT_DHW: s + "daily_hot_water_energy_produced",
        Signal.HEAT_COOLING: s + "daily_cooling_energy_produced",
        Signal.ELEC_HEATING: s + "daily_heating_energy_consumed",
        Signal.ELEC_DHW: s + "daily_hot_water_energy_consumed",
        Signal.ELEC_COOLING: s + "daily_cooling_energy_consumed",
        Signal.OUTDOOR_TEMP: s + "outside_temperature",
        Signal.FLOW_TEMP: s + "flow_temperature",  # system, not zone_1_
        Signal.RETURN_TEMP: s + "return_temperature",  # system, not zone_1_
        Signal.DHW_TEMP: s + "tank_temperature",
    }
    assert match.missing == []
    assert Signal.COMPRESSOR not in match.entities  # 30-min snapshot, left out


def test_needs_the_heat_disabled_by_default() -> None:
    assert find(MELCLOUD, entries(with_disabled=False)) == []


def test_energy_entities_have_usable_units() -> None:
    attributes = {
        e["entity_id"]: e["attributes"] for e in load_fixture(FIXTURE)["entities"]
    }
    (match,) = find(MELCLOUD, entries())
    for signal, entity_id in match.entities.items():
        if signal in ENERGY_SIGNALS:
            assert attributes[entity_id]["unit_of_measurement"] in UNIT_FACTORS
            assert attributes[entity_id]["state_class"] == "total_increasing"


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        (
            f"{PREFIX}-daily_heating_energy_consumed",
            (PREFIX, "daily_heating_energy_consumed"),
        ),
        (f"{PREFIX}-system_flow_temperature", (PREFIX, "system_flow_temperature")),
        (f"{PREFIX}-flow_temperature-zone-2", None),
        ("9900000001", None),
        ("9900000001-1", None),
        ("101234567-heat_produced_ch", None),
        ("-daily_heating_energy_consumed", None),
    ],
)
def test_unique_ids(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert MELCLOUD.split(unique_id) == expected


def test_day_values_without_compressor() -> None:
    assert MELCLOUD.day_values and MELCLOUD.experimental
    assert MELCLOUD.required == (Signal.HEAT_HEATING, Signal.ELEC_HEATING)
