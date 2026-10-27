"""Templates against the recorded registry of real installations."""

from __future__ import annotations

from custom_components.waermewacht.counter import UNIT_FACTORS
from custom_components.waermewacht.model import ENERGY_SIGNALS, Activity, Signal
from custom_components.waermewacht.profiles import (
    BOSCH_HOMECOM,
    EMS_ESP,
    RegistryEntry,
    find,
)

from .conftest import FIXTURES, load_fixture

FIXTURE = "ems_esp_cs6800i.json"


def entries() -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], "mqtt", e["unique_id"])
        for e in load_fixture(FIXTURE)["entities"]
    ]


def test_every_fixture_is_documented() -> None:
    index = load_fixture("_index.json")
    files = {p.name for p in FIXTURES.glob("*.json")} - {"_index.json"}
    assert files == set(index)


def test_template_finds_every_signal() -> None:
    (match,) = find(EMS_ESP, entries())
    assert match.missing == []
    expected = {
        Signal.HEAT_HEATING: "sensor.boiler_nrgheat",
        Signal.HEAT_DHW: "sensor.boiler_dhw_nrg",  # current name, not nrgww
        Signal.HEAT_COOLING: "sensor.boiler_nrgcool",
        Signal.ELEC_HEATING: "sensor.boiler_meterheat",
        Signal.ELEC_DHW: "sensor.boiler_dhw_meter",
        Signal.ELEC_COOLING: "sensor.boiler_metercool",
        Signal.AUX_HEATING: "sensor.boiler_auxelecheatnrgconsheating",
        Signal.AUX_DHW: "sensor.boiler_dhw_auxelecheatnrgcons",
        Signal.COMPRESSOR: "binary_sensor.boiler_hpcompon",
        Signal.ACTIVITY: "sensor.boiler_hpactivity",
        Signal.STARTS_TOTAL: "sensor.boiler_totalcompstarts",
        Signal.OUTDOOR_TEMP: "sensor.boiler_outdoortemp",
        Signal.FLOW_TEMP: "sensor.boiler_hptc1",
        Signal.RETURN_TEMP: "sensor.boiler_hptc0",
        Signal.FLOW_RATE: "sensor.boiler_pc0flow",
        Signal.HEAT_POWER: "sensor.boiler_hppower",
        Signal.ELEC_POWER: "sensor.boiler_hpcurrpower",
    }
    assert match.entities == expected


def test_energy_entities_have_usable_units() -> None:
    (match,) = find(EMS_ESP, entries())
    states = {e["entity_id"]: e for e in load_fixture(FIXTURE)["entities"]}
    for signal, entity_id in match.entities.items():
        if signal in ENERGY_SIGNALS:
            attributes = states[entity_id]["attributes"]
            assert attributes["unit_of_measurement"] in UNIT_FACTORS, entity_id
            assert attributes["state_class"] == "total_increasing", entity_id


def test_seen_activity_values_are_known() -> None:
    seen = load_fixture(FIXTURE)["activity_values_seen"]
    parsed = [EMS_ESP.parse_activity(value) for value in seen]
    assert parsed == [Activity.OFF, Activity.HEATING, Activity.DHW, Activity.DEFROST]


def test_older_names_kept_for_the_backfill() -> None:
    """The real installation has both formats; the older ids carry the longer
    statistics and are remembered as history of the chosen entity."""
    (match,) = find(EMS_ESP, entries())
    assert match.history[Signal.HEAT_DHW] == ["sensor.boiler_nrgww"]
    assert match.history[Signal.ELEC_DHW] == ["sensor.boiler_wwmeter"]
    assert match.history[Signal.AUX_DHW] == ["sensor.boiler_auxelecheatnrgconsww"]
    assert Signal.HEAT_HEATING not in match.history


HOMECOM = "bosch_homecom_k40.json"


def homecom_entries(*, with_disabled: bool = True) -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], "bosch_homecom", e["unique_id"])
        for e in load_fixture(HOMECOM)["entities"]
        if with_disabled or not e["disabled_by_default"]
    ]


def test_homecom_template_finds_every_signal() -> None:
    (match,) = find(BOSCH_HOMECOM, homecom_entries())
    gateway = load_fixture(HOMECOM)["gateway"]
    base = f"sensor.boschcom_k40_{gateway}_"
    assert match.prefix == gateway
    assert match.entities == {
        Signal.HEAT_HEATING: base + "warme_erzeugt_heizung",
        Signal.HEAT_DHW: base + "warme_erzeugt_warmwasser",
        Signal.HEAT_COOLING: base + "warme_erzeugt_kuhlung",
        Signal.ELEC_HEATING: base + "strom_kompressor_heizung",
        Signal.ELEC_DHW: base + "strom_kompressor_warmwasser",
        Signal.ELEC_COOLING: base + "strom_kompressor_kuhlung",
        Signal.AUX_HEATING: base + "strom_heizstab_heizung",
        Signal.AUX_DHW: base + "strom_heizstab_warmwasser",
        Signal.COMPRESSOR: base + "kompressordrehzahl",
        Signal.STARTS_TOTAL: base + "kompressor_starts",
        Signal.OUTDOOR_TEMP: base + "outdoor_temp_sensor",
        Signal.FLOW_TEMP: base + "vorlauftemperatur",
        Signal.RETURN_TEMP: base + "rucklauftemperatur",
        Signal.ELEC_POWER: base + "kompressorleistung",
    }
    # No activity: no defrosts, no mode of a run. Volume flow left out (unit).
    assert match.missing == []
    assert Signal.FLOW_RATE not in match.entities


def test_homecom_energy_units_are_usable() -> None:
    units = {
        e["entity_id"]: e["attributes"].get("unit_of_measurement")
        for e in load_fixture(HOMECOM)["entities"]
    }
    (match,) = find(BOSCH_HOMECOM, homecom_entries())
    for signal, entity_id in match.entities.items():
        if signal in ENERGY_SIGNALS:
            assert units[entity_id] in UNIT_FACTORS, entity_id


def test_homecom_needs_the_disabled_energy_per_mode() -> None:
    """bosch_homecom disables the energy per mode by default: no match."""
    assert find(BOSCH_HOMECOM, homecom_entries(with_disabled=False)) == []


def test_templates_do_not_claim_each_other() -> None:
    assert find(EMS_ESP, homecom_entries()) == []
    assert find(BOSCH_HOMECOM, entries()) == []
