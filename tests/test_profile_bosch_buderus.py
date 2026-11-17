"""Bosch/Buderus Home Comfort (`bosch_buderus_heating`): template against its fixture."""

from __future__ import annotations

import pytest

from custom_components.waermewacht.activity import combine
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
COOLING = "local_only:signals:SRC.CUHP.Cooling.Active"
PC1 = "local_only:signals:SRC.HC1.FlowCtrl.PumpVolumeFlow"
PC0 = "local_only:heatSources:hs1:pumpVolumeFlow"
PC0_SIGNAL = "local_only:signals:SRC.SystemPumpVolumeFlow"

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
    # An enum sensor on/off, not a binary sensor (issue #7).
    Signal.COOLING_FLAG: "sensor.cooling_active",
    Signal.COOLING_MODE: "sensor.heating_circuit_1_heating_cooling_mode",
    Signal.STARTS_TOTAL: S + "number_of_starts_total",
    Signal.RUNTIME_HEATING: S + "operating_time_heating",
    Signal.STARTS_HEATING: S + "number_of_starts_heating",
    Signal.OUTDOOR_TEMP: "sensor.system_outdoor_temperature",
    Signal.FLOW_TEMP: "sensor.primary_supply_temperature_tc1",
    Signal.RETURN_TEMP: S + "return_to_the_heat_source",
    # The primary circuit at the heat pump, as the spread TC1/TC0 (issue #7).
    Signal.FLOW_RATE: "sensor.primary_flow_rate",
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
    """Without the local access: modulation and the system supply; no
    cooling flag (the set mode stands in) and no flow."""
    (match,) = find(
        BOSCH_BUDERUS, without(HP1, HMI, TC1, COOLING, PC0, PC0_SIGNAL, PC1)
    )
    assert match.entities[Signal.COMPRESSOR] == S + "current_modulation"
    assert match.entities[Signal.FLOW_TEMP] == S + "system_supply_temperature"
    assert Signal.COOLING_MODE in match.entities
    assert sorted(match.missing) == sorted([Signal.COOLING_FLAG, Signal.FLOW_RATE])


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


def test_cooling_signal_is_an_enum_sensor_on_off() -> None:
    """The local cooling signal says "on"/"off" like a binary sensor; it
    beats the heating the activity entity reports."""
    configured = {Signal.ACTIVITY, Signal.COOLING_FLAG, Signal.COOLING_MODE}
    states = {Signal.COOLING_FLAG: "on", Signal.COOLING_MODE: "heat"}
    assert combine(Activity.HEATING, states, configured) is Activity.COOLING
    states[Signal.COOLING_FLAG] = "off"
    assert combine(Activity.HEATING, states, configured) is Activity.HEATING
    states[Signal.COOLING_FLAG] = "unavailable"  # cloud only, local gone
    assert combine(Activity.HEATING, states, configured) is Activity.HEATING


def test_flow_rate_falls_back_from_the_primary_circuit() -> None:
    """PC0 first, then its second source (disabled by default), then PC1."""
    (match,) = find(BOSCH_BUDERUS, without(PC0))
    assert match.entities[Signal.FLOW_RATE] == "sensor.flow_rate_hc1_pc1"
    signal = [
        e._replace(usable=True) if e.unique_id == f"{GATEWAY}:{PC0_SIGNAL}" else e
        for e in without(PC0)
    ]
    (match,) = find(BOSCH_BUDERUS, signal)
    assert match.entities[Signal.FLOW_RATE] == "sensor.primary_flow_rate_pc0_signal"


REAL = "bosch_buderus_heating_k40_real.json"
R = "sensor.heating_"

REAL_EXPECTED = {
    Signal.HEAT_HEATING: R + "warmepumpe_heizung_erzeugte_warme",
    Signal.HEAT_DHW: R + "warmepumpe_warmwasser_erzeugte_warme",
    Signal.HEAT_COOLING: R + "warmepumpe_kuhlung_erzeugte_kuhlenergie",
    Signal.ELEC_HEATING: R + "warmepumpe_heizung_stromverbrauch_warmepumpe",
    Signal.ELEC_DHW: R + "warmepumpe_warmwasser_stromverbrauch_warmepumpe",
    Signal.ELEC_COOLING: R + "warmepumpe_kuhlung_stromverbrauch_warmepumpe",
    Signal.AUX_HEATING: R + "warmepumpe_heizung_stromverbrauch_elektrischer_zuheizer",
    Signal.AUX_DHW: R + "warmepumpe_warmwasser_stromverbrauch_elektrischer_zuheizer",
    # HP1 disabled by default at the real installation too.
    Signal.COMPRESSOR: R + "anlage_kompressor_lauft_anzeigesignal",
    Signal.ACTIVITY: R + "warmepumpe_status_kompressor",
    Signal.COOLING_FLAG: R + "anlage_kuhlung_aktiv",
    Signal.COOLING_MODE: R + "heizkreis_1_heiz_kuhlbetrieb",
    Signal.STARTS_TOTAL: R + "warmepumpe_anzahl_der_starts_gesamt",
    Signal.RUNTIME_HEATING: R + "warmepumpe_betriebszeit_heizung",
    Signal.STARTS_HEATING: R + "warmepumpe_anzahl_der_starts_heizung",
    Signal.OUTDOOR_TEMP: R + "anlage_aussentemperatur",
    Signal.FLOW_TEMP: R + "warmepumpe_vorlauftemperatur_primar_tc1",
    Signal.RETURN_TEMP: R + "warmepumpe_rucklauf_zum_warmeerzeuger",
    Signal.FLOW_RATE: R + "warmepumpe_volumenstrom_primar",
    Signal.DHW_TEMP: R + "warmwasser_warmwasser_isttemperatur",
    Signal.SYSTEM_PRESSURE: R + "warmepumpe_systemdruck",
}


def real_rows() -> list[dict]:
    return load_fixture(REAL)["entities"]


def test_real_installation_finds_every_signal() -> None:
    """A real Bosch Compress 5800i AW with K40RF (German names, local
    access): every signal, the energy as lifetime counters in kWh."""
    rows_ = real_rows()
    (match,) = find(
        BOSCH_BUDERUS,
        [
            RegistryEntry(
                e["entity_id"],
                PLATFORM,
                e["unique_id"],
                e["original_name"],
                usable=not e["disabled_by_default"],
            )
            for e in rows_
        ],
    )
    assert match.prefix == GATEWAY
    assert match.entities == REAL_EXPECTED
    assert match.missing == []
    known = {e["entity_id"]: e["attributes"] for e in rows_}
    for signal in ENERGY_SIGNALS:
        if signal in match.entities:
            attributes = known[match.entities[signal]]
            assert attributes["unit_of_measurement"] == "kWh", signal
            assert attributes["device_class"] == "energy", signal


def test_real_compressor_status_options_are_mapped() -> None:
    (status,) = [
        e
        for e in real_rows()
        if e["unique_id"] == f"{GATEWAY}:heatSources:compressor:status"
    ]
    assert set(status["attributes"]["options"]) == set(BOSCH_BUDERUS.activity_values)
