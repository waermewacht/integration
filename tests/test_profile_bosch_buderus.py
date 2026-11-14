"""Bosch/Buderus Home Comfort (`bosch_buderus_heating`): template against its fixture."""

from __future__ import annotations

import pytest

from custom_components.waermewacht.counter import UNIT_FACTORS
from custom_components.waermewacht.model import ENERGY_SIGNALS, Activity, Signal
from custom_components.waermewacht.profiles import (
    RegistryEntry,
    find,
    parse_compressor,
)
from custom_components.waermewacht.profiles_bosch_buderus import (
    BOSCH_BUDERUS,
    PLATFORM,
)

from .conftest import load_fixture

FIXTURE = "bosch_buderus_heating_k40.json"
GATEWAY = "101987654"
S = "sensor.heat_pump_"


def rows() -> list[dict]:
    return load_fixture(FIXTURE)["entities"]


def entries(platform: str = PLATFORM) -> list[RegistryEntry]:
    return [
        RegistryEntry(
            e["entity_id"],
            platform,
            e["unique_id"],
            e["original_name"],
            usable=not e["disabled_by_default"],
        )
        for e in rows()
    ]


def without(*keys: str) -> list[RegistryEntry]:
    ids = {f"{GATEWAY}:{key}" for key in keys}
    return [e for e in entries() if e.unique_id not in ids]


def enabled(key: str) -> list[RegistryEntry]:
    return [
        e._replace(usable=True) if e.unique_id == f"{GATEWAY}:{key}" else e
        for e in entries()
    ]


HP1 = "local_only:signals:SRC.CUHP.HP1.CompressorStatus"
HMI = "local_only:signals:SRC.CUHP.HMI.CompressorActive"
TC1 = "local_only:heatSources:additionalHeater:flowTemp"

EXPECTED = {
    Signal.HEAT_HEATING: S + "heating_heat_produced",
    Signal.HEAT_DHW: S + "hot_water_heat_produced",
    Signal.HEAT_COOLING: S + "cooling_cooling_energy_produced",
    Signal.ELEC_HEATING: S + "heating_heat_pump_electricity_consumption",
    Signal.ELEC_DHW: S + "hot_water_heat_pump_electricity_consumption",
    Signal.ELEC_COOLING: S + "cooling_heat_pump_electricity_consumption",
    Signal.AUX_HEATING: S + "heating_electric_auxiliary_heater_consumption",
    Signal.AUX_DHW: S + "hot_water_electric_auxiliary_heater_consumption",
    # HP1 is disabled by default: the enabled display signal.
    Signal.COMPRESSOR: "sensor.compressor_running_display_signal",
    Signal.ACTIVITY: S + "compressor_status",
    Signal.STARTS_TOTAL: S + "number_of_starts_total",
    Signal.RUNTIME_HEATING: S + "operating_time_heating",
    Signal.STARTS_HEATING: S + "number_of_starts_heating",
    Signal.OUTDOOR_TEMP: "sensor.system_outdoor_temperature",
    Signal.FLOW_TEMP: "sensor.primary_supply_temperature_tc1",
    Signal.RETURN_TEMP: S + "return_to_the_heat_source",
    Signal.DHW_TEMP: "sensor.hot_water_1_hot_water_temperature",
    Signal.SYSTEM_PRESSURE: S + "system_pressure",
}


def test_template_finds_every_signal() -> None:
    (match,) = find(BOSCH_BUDERUS, entries())
    assert match.prefix == GATEWAY
    assert match.entities == EXPECTED
    assert match.missing == []
    assert BOSCH_BUDERUS.experimental
    assert not BOSCH_BUDERUS.day_values  # lifetime counters
    assert not BOSCH_BUDERUS.previous_day
    assert BOSCH_BUDERUS.min_system_pressure is None  # not only one model


def test_compressor_prefers_the_heat_pump_signal() -> None:
    (match,) = find(BOSCH_BUDERUS, enabled(HP1))
    assert match.entities[Signal.COMPRESSOR] == (
        "sensor.compressor_running_heat_pump_signal"
    )


def test_cloud_only() -> None:
    """Without the local access: modulation and the system supply."""
    (match,) = find(BOSCH_BUDERUS, without(HP1, HMI, TC1))
    assert match.entities[Signal.COMPRESSOR] == S + "current_modulation"
    assert match.entities[Signal.FLOW_TEMP] == S + "system_supply_temperature"
    assert match.missing == []


@pytest.mark.parametrize(
    "keys",
    [
        ("gateway:heating_heat_produced",),
        ("heatSources:emon:chConsumption:compressor",),
        (HP1, HMI, "gateway:modulation"),
    ],
)
def test_required_signals(keys: tuple[str, ...]) -> None:
    assert find(BOSCH_BUDERUS, without(*keys)) == []


def test_energy_entities_are_lifetime_counters_in_kwh() -> None:
    known = {e["entity_id"]: e["attributes"] for e in rows()}
    (match,) = find(BOSCH_BUDERUS, entries())
    energy = [s for s in match.entities if s in ENERGY_SIGNALS]
    assert len(energy) == 8
    for signal in energy:
        attributes = known[match.entities[signal]]
        assert attributes["unit_of_measurement"] in UNIT_FACTORS, signal
        assert attributes["device_class"] == "energy", signal
        # Heat is "total": it dips during a defrost (counter.py keeps the
        # maximum); electricity only rises.
        heat = signal in (Signal.HEAT_HEATING, Signal.HEAT_DHW, Signal.HEAT_COOLING)
        expected = "total" if heat else "total_increasing"
        assert attributes["state_class"] == expected, signal


def test_run_time_and_pressure_units() -> None:
    known = {e["entity_id"]: e["attributes"] for e in rows()}
    (match,) = find(BOSCH_BUDERUS, entries())
    assert known[match.entities[Signal.RUNTIME_HEATING]]["unit_of_measurement"] == "h"
    pressure = known[match.entities[Signal.SYSTEM_PRESSURE]]
    assert pressure["unit_of_measurement"] == "bar"
    assert pressure["device_class"] == "pressure"


def test_every_compressor_status_option_is_mapped() -> None:
    (status,) = [
        e
        for e in rows()
        if e["unique_id"] == f"{GATEWAY}:heatSources:compressor:status"
    ]
    assert set(status["attributes"]["options"]) == set(BOSCH_BUDERUS.activity_values)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("off", Activity.OFF),
        ("heating", Activity.HEATING),
        ("dhw", Activity.DHW),
        ("defrost", Activity.DEFROST),
        ("alarm", Activity.OTHER),
        ("unknown", None),
    ],
)
def test_activity_values(state: str, expected: Activity | None) -> None:
    assert BOSCH_BUDERUS.parse_activity(state) is expected


@pytest.mark.parametrize(
    ("state", "running"),
    [("on", True), ("off", False), ("34", True), ("0", False), ("unknown", None)],
)
def test_compressor_states(state: str, running: bool | None) -> None:
    """The local signals report on/off, the cloud a modulation in %."""
    assert parse_compressor(state) is running


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        (f"{GATEWAY}:gateway:modulation", (GATEWAY, "gateway:modulation")),
        (f"{GATEWAY}:{HMI}", (GATEWAY, HMI)),
        ("gateway-one:gateway:modulation", ("gateway-one", "gateway:modulation")),
        ("gateway:modulation", ("gateway", "modulation")),  # an unknown key
        (f"{GATEWAY}_gateway:modulation", (f"{GATEWAY}_gateway", "modulation")),
        ("no-colon-at-all", None),
    ],
)
def test_unique_ids(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert BOSCH_BUDERUS.split(unique_id) == expected


def test_one_match_per_gateway() -> None:
    second = [
        e._replace(
            entity_id=e.entity_id + "_2",
            unique_id=e.unique_id.replace(GATEWAY, "101000001"),
        )
        for e in entries()
    ]
    first, other = find(BOSCH_BUDERUS, entries() + second)
    assert (first.prefix, other.prefix) == ("101000001", GATEWAY)
    assert other.entities == EXPECTED


def test_foreign_platform_does_not_count() -> None:
    assert find(BOSCH_BUDERUS, entries("bosch_homecom")) == []
