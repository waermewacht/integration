"""Waterkotte template (`waterkotte_heatpump`) against its fixture.

The template maps the compressor electricity to Signal.ELEC_TOTAL; until the
core has that signal, every test here is skipped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from custom_components.waermewacht.activity import combine
from custom_components.waermewacht.counter import UNIT_FACTORS, Counter, CounterEvent
from custom_components.waermewacht.model import Activity, Signal
from custom_components.waermewacht.profiles import RegistryEntry, find

from .conftest import FIXTURES, load_fixture

if TYPE_CHECKING:
    from custom_components.waermewacht.profiles import Template

ELEC_TOTAL = getattr(Signal, "ELEC_TOTAL", None)
pytestmark = pytest.mark.skipif(
    ELEC_TOTAL is None, reason="core signal Signal.ELEC_TOTAL not there yet"
)

FIXTURE = "waterkotte_ecotouch.json"
PLATFORM = "waterkotte_heatpump"


@pytest.fixture(name="waterkotte")
def fixture_waterkotte() -> Template:
    from custom_components.waermewacht.profiles_waterkotte import WATERKOTTE

    return WATERKOTTE


def entries(platform: str = PLATFORM, usable_only: bool = False) -> list[RegistryEntry]:
    """Registry entries; `usable_only` drops entities disabled by default."""
    return [
        RegistryEntry(
            e["entity_id"],
            platform,
            e["unique_id"],
            usable=not (usable_only and e["disabled_by_default"]),
        )
        for e in load_fixture(FIXTURE)["entities"]
    ]


def states() -> dict[str, dict]:
    return {e["entity_id"]: e for e in load_fixture(FIXTURE)["entities"]}


def with_serial(serial: str) -> list[RegistryEntry]:
    """The fixture as the option "add_serial_as_id" names it."""
    return [
        RegistryEntry(
            e.entity_id.replace(".wkh_", f".wkh_{serial}_"),
            PLATFORM,
            f"{e.unique_id}_{serial}",
        )
        for e in entries()
    ]


EXPECTED = {
    Signal.HEAT_HEATING: "sensor.wkh_heating_energy_production_year",
    Signal.HEAT_DHW: "sensor.wkh_hot_water_energy_production_year",
    Signal.HEAT_COOLING: "sensor.wkh_cooling_energy_year",
    Signal.AUX_TOTAL: "sensor.wkh_electrical_heater_electric_consumption_year",
    Signal.COMPRESSOR: "binary_sensor.wkh_state_compressor",
    Signal.DHW_FLAG: "binary_sensor.wkh_state_water",
    Signal.COOLING_FLAG: "binary_sensor.wkh_state_cooling",
    Signal.OUTDOOR_TEMP: "sensor.wkh_temperature_outside",  # not _1h / _24h
    Signal.FLOW_TEMP: "sensor.wkh_temperature_flow",
    Signal.RETURN_TEMP: "sensor.wkh_temperature_return",
    Signal.DHW_TEMP: "sensor.wkh_temperature_water",
}


def test_template_finds_every_signal(waterkotte: Template) -> None:
    (match,) = find(waterkotte, entries())
    assert match.prefix == ""
    assert match.entities == {
        **EXPECTED,
        ELEC_TOTAL: "sensor.wkh_compressor_electric_consumption_year",
    }
    assert match.missing == []
    assert waterkotte.experimental
    assert waterkotte.required == (Signal.COMPRESSOR, Signal.HEAT_HEATING, ELEC_TOTAL)


def test_signals_the_source_does_not_have(waterkotte: Template) -> None:
    """No electricity per mode, no activity entity, no defrost, no starts, no
    flow rate; the backup heater only as a total."""
    absent = {
        Signal.ELEC_HEATING,
        Signal.ELEC_DHW,
        Signal.ELEC_COOLING,
        Signal.ELEC_DEFROST,
        Signal.ELEC_STANDBY,
        Signal.AUX_HEATING,
        Signal.AUX_DHW,
        Signal.ACTIVITY,
        Signal.DEFROST_FLAG,
        Signal.HEATING_FLAG,  # "status_heating" is the release
        Signal.COOLING_MODE,
        Signal.STARTS_TOTAL,
        Signal.FLOW_RATE,
    }
    assert not absent & set(waterkotte.signals)


def test_defaults_without_cooling_state(waterkotte: Template) -> None:
    """ "state_cooling" is disabled by default: cooling is not told apart."""
    (match,) = find(waterkotte, entries(usable_only=True))
    assert match.missing == [Signal.COOLING_FLAG]


def test_required_signals(waterkotte: Template) -> None:
    for key in (
        "state_compressor",
        "heating_energy_production_year",
        "compressor_electric_consumption_year",
    ):
        rest = [e for e in entries() if e.unique_id != f"{PLATFORM}.{key}"]
        assert find(waterkotte, rest) == [], key


def test_energy_entities_are_counters_in_kwh(waterkotte: Template) -> None:
    (match,) = find(waterkotte, entries())
    known = states()
    energy = {
        Signal.HEAT_HEATING,
        Signal.HEAT_DHW,
        Signal.HEAT_COOLING,
        ELEC_TOTAL,
        Signal.AUX_TOTAL,
    }
    for signal in energy:
        attributes = known[match.entities[signal]]["attributes"]
        assert attributes["unit_of_measurement"] in UNIT_FACTORS, signal
        assert attributes["device_class"] == "energy", signal
        assert attributes["state_class"] == "total_increasing", signal
        assert match.entities[signal].endswith("_year"), signal


def test_year_start_is_a_reset() -> None:
    """The yearly sums start anew on 1 January: a reset, nothing booked."""
    counter = Counter(max_kw=20.0)
    counter.update(1956.734, datetime(2026, 12, 31, 22, 59, tzinfo=UTC))
    update = counter.update(0.012, datetime(2026, 12, 31, 23, 0, tzinfo=UTC))
    assert update.event is CounterEvent.RESET
    assert update.delta == 0
    later = counter.update(0.112, datetime(2026, 12, 31, 23, 10, tzinfo=UTC))
    assert later.delta == pytest.approx(0.1)


@pytest.mark.parametrize(
    ("water", "cooling", "compressor", "activity"),
    [
        ("off", "off", True, Activity.HEATING),  # a run without a flag
        ("on", "off", True, Activity.DHW),
        ("off", "on", True, Activity.COOLING),
        ("on", "off", False, Activity.DHW),
        ("off", "off", False, Activity.OFF),
        ("off", "off", None, Activity.OFF),
        (None, "off", True, None),  # unknown flag that could still decide
    ],
)
def test_activity_from_flags(
    waterkotte: Template,
    water: str | None,
    cooling: str | None,
    compressor: bool | None,
    activity: Activity | None,
) -> None:
    (match,) = find(waterkotte, entries())
    flags = {Signal.DHW_FLAG: water, Signal.COOLING_FLAG: cooling}
    assert combine(None, flags, set(match.entities), compressor) is activity


def test_activity_without_cooling_state(waterkotte: Template) -> None:
    (match,) = find(waterkotte, entries(usable_only=True))
    flags = {Signal.DHW_FLAG: "off"}
    assert combine(None, flags, set(match.entities), True) is Activity.HEATING


def test_flag_states_are_on_off() -> None:
    known = states()
    for entity_id, entity in known.items():
        if entity_id.startswith("binary_sensor."):
            assert entity["state"] in ("on", "off"), entity_id


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        (f"{PLATFORM}.state_compressor", ("", "state_compressor")),
        (f"{PLATFORM}.state_compressor_we0612345", ("we0612345", "state_compressor")),
        (
            f"{PLATFORM}.temperature_outside_0123456789abcdef0123456789abcdef",
            ("0123456789abcdef0123456789abcdef", "temperature_outside"),
        ),
        (f"{PLATFORM}.state_compressor2", None),
        (f"{PLATFORM}.state_compressor2_we0612345", None),
        (f"{PLATFORM}.temperature_outside_1h", None),
        (f"{PLATFORM}.temperature_outside_24h", None),
        (f"{PLATFORM}.temperature_outside_24h_we0612345", None),
        (f"{PLATFORM}.temperature_water_setpoint", None),
        (f"{PLATFORM}.energy_consumption_total_year", None),
        ("state_compressor", None),  # before the prefix migration
        ("waterkotte_heatpump_state_compressor", None),
        (f"{PLATFORM}.", None),
    ],
)
def test_unique_ids(waterkotte: Template, unique_id: str, expected: object) -> None:
    assert waterkotte.split(unique_id) == expected


def test_one_match_per_serial(waterkotte: Template) -> None:
    """Several heat pumps need "add_serial_as_id"; one entry may lack it."""
    first, second = with_serial("we0612345"), with_serial("we0698765")
    plain, one, two = find(waterkotte, entries() + first + second)
    assert (plain.prefix, one.prefix, two.prefix) == ("", "we0612345", "we0698765")
    assert one.entities[ELEC_TOTAL] == (
        "sensor.wkh_we0612345_compressor_electric_consumption_year"
    )
    assert one.missing == []


def test_templates_do_not_claim_each_other(waterkotte: Template) -> None:
    from custom_components.waermewacht.templates import TEMPLATES

    others = {k: t for k, t in TEMPLATES.items() if k != waterkotte.key}
    assert waterkotte.platform not in {t.platform for t in others.values()}
    # Other templates on these entities (under their own platforms, too).
    for key, template in others.items():
        assert find(template, entries()) == [], key
        assert find(template, entries(template.platform)) == [], key
    # This template on every other fixture, under its platform and ours.
    names = {p.name for p in FIXTURES.glob("*.json")} - {"_index.json", FIXTURE}
    assert names
    for name in sorted(names):
        rows = load_fixture(name)["entities"]
        for platform in {PLATFORM, *(t.platform for t in others.values())}:
            found = [
                RegistryEntry(
                    e["entity_id"], platform, e["unique_id"], e.get("original_name")
                )
                for e in rows
            ]
            assert find(waterkotte, found) == [], (name, platform)
    # Same unique ids under a foreign platform (e.g. a template copy) do not count.
    assert find(waterkotte, entries("template")) == []
