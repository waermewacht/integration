"""Vaillant template (mypyllant) against its fixture, derived from source."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise

import pytest

from custom_components.waermewacht.backfill import bookable_hours, by_hour
from custom_components.waermewacht.counter import UNIT_FACTORS
from custom_components.waermewacht.energy import Kind
from custom_components.waermewacht.model import ENERGY_SIGNALS, Activity, Mode, Signal
from custom_components.waermewacht.profiles import (
    BOSCH_HOMECOM,
    EMS_ESP,
    RegistryEntry,
    find,
)
from custom_components.waermewacht.profiles_vaillant import (
    VAILLANT,
    data_key,
    split_data_sensor,
)

from .conftest import load_fixture

FIXTURE = "vaillant_mypyllant_arotherm.json"


def entities() -> list[dict]:
    return load_fixture(FIXTURE)["entities"]


def entries(*, platform: str = "mypyllant") -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], platform, e["unique_id"], e["original_name"])
        for e in entities()
    ]


S = "sensor.zuhause_"
HP = S + "device_0_arotherm_plus_"
AUX = S + "device_1_hydraulic_station_"
EXPECTED = {
    Signal.HEAT_HEATING: HP + "heat_generated_heating",
    Signal.HEAT_DHW: HP + "heat_generated_domestic_hot_water",
    Signal.HEAT_COOLING: HP + "heat_generated_cooling",
    Signal.ELEC_HEATING: HP + "consumed_electrical_energy_heating",
    Signal.ELEC_DHW: HP + "consumed_electrical_energy_domestic_hot_water",
    Signal.ELEC_COOLING: HP + "consumed_electrical_energy_cooling",
    Signal.AUX_HEATING: AUX + "consumed_electrical_energy_heating",
    Signal.AUX_DHW: AUX + "consumed_electrical_energy_domestic_hot_water",
    Signal.ACTIVITY: S + "energy_manager_state",  # not circuit_0_state
    Signal.OUTDOOR_TEMP: S + "outdoor_temperature",
    Signal.FLOW_TEMP: S + "system_flow_temperature",  # not circuit_0_current_…
    Signal.DHW_TEMP: S + "domestic_hot_water_0_tank_temperature",  # not top_dhw
}


def test_template_finds_every_signal() -> None:
    (match,) = find(VAILLANT, entries())
    assert match.prefix == load_fixture(FIXTURE)["prefix"]
    assert match.entities == EXPECTED
    assert match.missing == []
    assert Signal.COMPRESSOR not in VAILLANT.signals  # no compressor signal


def test_energy_entities_have_usable_units() -> None:
    attributes = {e["entity_id"]: e["attributes"] for e in entities()}
    for signal, entity_id in EXPECTED.items():
        if signal in ENERGY_SIGNALS:
            assert attributes[entity_id]["unit_of_measurement"] in UNIT_FACTORS
            assert attributes[entity_id]["state_class"] == "total_increasing"


def test_position_in_the_api_list_does_not_matter() -> None:
    """flexoTHERM test data lists 'heat generated' heating before hot water,
    aroTHERM the other way round: only the name tells."""

    def swap(entry: RegistryEntry) -> RegistryEntry:
        for a, b in (("_6_0", "_7_0"), ("_7_0", "_6_0")):
            if entry.unique_id.endswith(a):
                return entry._replace(unique_id=entry.unique_id[: -len(a)] + b)
        return entry

    (match,) = find(VAILLANT, [swap(e) for e in entries()])
    assert match.entities == EXPECTED


def test_disabled_yield_sensors_still_mark_the_heat_pump() -> None:
    """Users disable unneeded series against the API quota."""
    disabled = [
        e._replace(usable=False) if "earned_environment" in e.entity_id else e
        for e in entries()
    ]
    (match,) = find(VAILLANT, disabled)
    assert match.entities == EXPECTED


def test_without_yield_series_there_is_no_heat_pump() -> None:
    without = [e for e in entries() if "earned_environment" not in e.entity_id]
    assert find(VAILLANT, without) == []


def test_backup_heater_heat_is_not_taken() -> None:
    (match,) = find(VAILLANT, entries())
    assert AUX + "heat_generated_heating" not in match.entities.values()


def test_two_heat_pumps_share_the_system_but_not_the_backup_heater() -> None:
    fx = load_fixture(FIXTURE)
    second = "f" * 40
    extra = [
        e._replace(
            entity_id=e.entity_id.replace("device_0", "device_2"),
            unique_id=e.unique_id.replace(fx["heat_pump"], second)[:-1] + "2",
        )
        for e in entries()
        if fx["heat_pump"] in e.unique_id and split_data_sensor(e.unique_id)
    ]
    found = find(VAILLANT, entries() + extra)
    assert len(found) == 2
    assert all(Signal.AUX_HEATING not in m.entities for m in found)  # ambiguous
    assert {m.entities[Signal.OUTDOOR_TEMP] for m in found} == {
        S + "outdoor_temperature"
    }


def test_user_renamed_entity_is_still_found() -> None:
    renamed = [
        e._replace(entity_id="sensor.wp_waerme_heizen")
        if e.entity_id == EXPECTED[Signal.HEAT_HEATING]
        else e
        for e in entries()
    ]
    (match,) = find(VAILLANT, renamed)
    assert match.entities[Signal.HEAT_HEATING] == "sensor.wp_waerme_heizen"


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Zuhause Device 0 aroTHERM plus Heat Generated Heating", "heat_heating"),
        (
            "X Device 1 Hydraulic Station Consumed Electrical Energy Domestic Hot Water",
            "elec_dhw",
        ),
        ("X Device 0 aroTHERM plus Earned Environment Energy Cooling", "env_cooling"),
        ("X Device 0 aroTHERM plus Heating", None),  # disabled at creation
        ("X Device 0 aroTHERM plus Heating Energy Efficiency", None),
        (None, None),
    ],
)
def test_data_key(name: str | None, key: str | None) -> None:
    assert data_key(name) == key


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        ("mypyllant_sys-1_abc_6_0", ("sys-1", "abc")),
        ("mypyllant_sys-1_device_abc_on_off_cycles", None),
        ("mypyllant_sys-1_device_abc_heating_energy_efficiency", None),
        ("mypyllant_sys-1_domestic_hot_water_0_tank_temperature", None),
        ("mypyllant_api_request_count", None),
        ("other_sys_abc_6_0", None),
    ],
)
def test_split_data_sensor(unique_id: str, expected: tuple[str, str] | None) -> None:
    assert split_data_sensor(unique_id) == expected


def test_statistic_id() -> None:
    fx = load_fixture(FIXTURE)
    uid = f"mypyllant_{fx['system']}_{fx['heat_pump']}_6_0"
    assert VAILLANT.statistic_id(uid) == ("mypyllant:" + uid.replace("-", "_"))
    assert uid.replace("-", "_") != uid  # the system id has hyphens
    assert VAILLANT.statistic_id(f"mypyllant_{fx['system']}_home_base") is None


@pytest.mark.parametrize(
    ("state", "activity"),
    [
        ("STANDBY", Activity.OFF),
        ("HEATING", Activity.HEATING),
        ("DHW", Activity.DHW),
        ("COOLING", Activity.COOLING),
        ("SOMETHING_NEW", Activity.OTHER),
        ("unavailable", None),
    ],
)
def test_activity_values(state: str, activity: Activity | None) -> None:
    assert VAILLANT.parse_activity(state) is activity


def test_every_energy_manager_state_is_mapped() -> None:
    options = load_fixture(FIXTURE)["activity_options"]
    assert {o.casefold() for o in options} == set(VAILLANT.activity_values)


def hourly_from_fixture() -> dict[Signal, dict[datetime, float]]:
    fx = load_fixture(FIXTURE)
    uid = {e["entity_id"]: e["unique_id"] for e in entities()}
    hourly: dict[Signal, dict[datetime, float]] = {}
    for signal, entity_id in EXPECTED.items():
        rows = fx["statistics"].get(VAILLANT.statistic_id(uid[entity_id]) or "")
        if not rows:
            continue
        changes = {}
        for before, row in pairwise(rows):
            changes[datetime.fromisoformat(row["start"])] = (
                row["sum"] - before["sum"]
            ) / 1000  # Wh -> kWh, as the recorder converts
        hourly[signal] = changes
    return hourly


def test_hour_without_yield_is_standby() -> None:
    hours = by_hour(hourly_from_fixture(), heat_includes_electricity=True)
    standby = hours[datetime(2026, 1, 14, 22, tzinfo=UTC)]
    assert standby.get(Kind.STANDBY, Mode.HEATING) == pytest.approx(0.025)
    assert standby.get(Kind.ELEC, Mode.HEATING) == 0
    assert standby.get(Kind.HEAT, Mode.HEATING) == 0  # heat = electricity only
    run = hours[datetime(2026, 1, 14, 23, tzinfo=UTC)]
    assert run.get(Kind.HEAT, Mode.HEATING) == pytest.approx(4.0)
    assert run.get(Kind.ELEC, Mode.HEATING) == pytest.approx(1.1)
    assert run.get(Kind.STANDBY, Mode.HEATING) == 0


def test_bookable_hours_wait_for_every_series() -> None:
    hourly = hourly_from_fixture()
    start, end = (
        datetime(2026, 1, 14, 22, tzinfo=UTC),
        datetime(2026, 1, 15, 1, tzinfo=UTC),
    )
    hours, next_start = bookable_hours(hourly, start, end)
    assert next_start == end and len(hours) == 3
    hourly[Signal.HEAT_HEATING].pop(datetime(2026, 1, 15, 0, tzinfo=UTC))
    hours, next_start = bookable_hours(hourly, start, end)
    assert next_start == datetime(2026, 1, 15, 0, tzinfo=UTC)


def test_templates_do_not_claim_each_other() -> None:
    assert find(EMS_ESP, entries(platform="mqtt")) == []
    assert find(BOSCH_HOMECOM, entries(platform="bosch_homecom")) == []
    assert find(VAILLANT, entries(platform="bosch_homecom")) == []
