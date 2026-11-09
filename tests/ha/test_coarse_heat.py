"""Live standby without a compressor state next to a heat meter in whole kWh:
electricity within COARSE_WINDOW after a heat step of its mode is running
(the same window as the look-back). Fine meters and a compressor state keep
the rule from before. All values are made up."""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.const import (
    CONF_ENTITIES,
    CONF_NAME,
    CONF_TEMPLATE,
    DOMAIN,
)
from custom_components.waermewacht.energy import Kind
from custom_components.waermewacht.model import Mode

from .conftest import ENERGY
from .test_init import START, tick

HEAT = "sensor.wmz_energy"
ELEC = "sensor.wp_elec_heating"
ELEC_DHW = "sensor.wp_elec_dhw"
COMPRESSOR = "binary_sensor.wp_compressor"
ACTIVITY = "sensor.wp_activity"
STEP = 0.05  # electricity per report (5 min, 600 W)


async def _setup(
    hass: HomeAssistant, entities: dict[str, str], states: dict[str, str]
) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    for entity, state in states.items():
        hass.states.async_set(entity, state, _attributes(entity))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data={CONF_NAME: "WP", CONF_TEMPLATE: None, CONF_ENTITIES: entities},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _play(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    events: Iterable[tuple[int, str, str]],
) -> None:
    """Set states at minutes after the setup: (minute, entity, state)."""
    now = 0
    for minute, entity, state in sorted(events, key=lambda e: e[0]):
        if minute > now:
            await tick(hass, freezer, minute - now)
            now = minute
        hass.states.async_set(entity, state, _attributes(entity))
    await tick(hass, freezer, 1)


def _attributes(entity: str) -> dict[str, str]:
    return ENERGY if entity in (HEAT, ELEC, ELEC_DHW) else {}


def _electricity(
    entity: str, minutes: Iterable[int], start: float
) -> list[tuple[int, str, str]]:
    """A report every given minute, STEP each."""
    return [
        (minute, entity, f"{start + STEP * (i + 1):.2f}")
        for i, minute in enumerate(minutes)
    ]


def _run(heat_states: tuple[str, str, str]) -> list[tuple[int, str, str]]:
    """3 h of a run: electricity every 5 min, heat steps at 42 and 142 min;
    then at 270 min (over 2 h after the last step) 0.1 kWh more electricity."""
    events = _electricity(ELEC, range(5, 181, 5), 300.0)
    events += [(42, HEAT, heat_states[1]), (142, HEAT, heat_states[2])]
    events.append((270, ELEC, f"{300.0 + STEP * 36 + 0.1:.2f}"))
    return events


@pytest.mark.freeze_time(START)
async def test_whole_kwh_heat_meter_keeps_a_run_running(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await _setup(
        hass,
        {"heat_heating": HEAT, "elec_heating": ELEC},
        {HEAT: "1000", ELEC: "300.00"},
    )
    await _play(hass, freezer, _run(("1000", "1001", "1002")))
    totals = entry.runtime_data.totals
    assert totals.get(Kind.HEAT, Mode.HEATING) == pytest.approx(2.0)
    # Before the first heat step standby (8 reports), from it on running
    # (28 reports), beyond the window standby again.
    assert totals.get(Kind.ELEC, Mode.HEATING) == pytest.approx(28 * STEP)
    assert totals.get(Kind.STANDBY, Mode.HEATING) == pytest.approx(8 * STEP + 0.1)
    assert entry.runtime_data.coarse_heat_modes() == [Mode.HEATING]

    # The settings summary says what is missing.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    summary = result["description_placeholders"]["summary"]
    assert (
        "- Without a compressor, part of the running electricity counts as standby"
        " with a heat meter in whole kWh – map the compressor if there is one."
        in summary
    )


@pytest.mark.freeze_time(START)
async def test_decimal_heat_meter_as_before(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await _setup(
        hass,
        {"heat_heating": HEAT, "elec_heating": ELEC},
        {HEAT: "1000.25", ELEC: "300.00"},
    )
    await _play(hass, freezer, _run(("1000.25", "1001.25", "1002.25")))
    totals = entry.runtime_data.totals
    # Running only for the report right after each heat step.
    assert totals.get(Kind.ELEC, Mode.HEATING) == pytest.approx(2 * STEP)
    assert totals.get(Kind.STANDBY, Mode.HEATING) == pytest.approx(34 * STEP + 0.1)
    assert entry.runtime_data.coarse_heat_modes() == []
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "whole kWh" not in result["description_placeholders"]["summary"]


@pytest.mark.freeze_time(START)
async def test_with_compressor_as_before(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await _setup(
        hass,
        {"heat_heating": HEAT, "elec_heating": ELEC, "compressor": COMPRESSOR},
        {HEAT: "1000", ELEC: "300.00", COMPRESSOR: "on"},
    )
    events = _electricity(ELEC, range(5, 181, 5), 300.0)
    events += [(42, HEAT, "1001"), (142, HEAT, "1002"), (181, COMPRESSOR, "off")]
    # Still within the run's last interval, then standby although within
    # 2 h of the last heat step: the compressor decides.
    events += [(190, ELEC, "301.85"), (200, ELEC, "301.95")]
    await _play(hass, freezer, events)
    totals = entry.runtime_data.totals
    assert totals.get(Kind.ELEC, Mode.HEATING) == pytest.approx(37 * STEP)
    assert totals.get(Kind.STANDBY, Mode.HEATING) == pytest.approx(0.1)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "whole kWh" not in result["description_placeholders"]["summary"]


@pytest.mark.freeze_time(START)
async def test_heat_total_window_per_mode(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The common heat meter marks the mode it books to: a heating step does
    not make hot water electricity running, and back in heating the window
    of the heating step still holds."""
    entry = await _setup(
        hass,
        {
            "heat_total": HEAT,
            "elec_heating": ELEC,
            "elec_dhw": ELEC_DHW,
            "activity": ACTIVITY,
        },
        {HEAT: "1000", ELEC: "300.00", ELEC_DHW: "200.00", ACTIVITY: "Heizen"},
    )
    events = _electricity(ELEC, range(5, 61, 5), 300.0)  # 12 reports
    events.append((42, HEAT, "1001"))
    events.append((62, ACTIVITY, "Warmwasser"))
    events += _electricity(ELEC_DHW, range(65, 121, 5), 200.0)  # 12 reports
    events.append((92, HEAT, "1002"))
    events.append((122, ACTIVITY, "Heizen"))
    events += _electricity(ELEC, range(125, 151, 5), 300.0 + 12 * STEP)  # 6
    events.append((170, ELEC, f"{300.0 + 18 * STEP + 0.1:.2f}"))
    await _play(hass, freezer, events)
    totals = entry.runtime_data.totals
    assert totals.get(Kind.HEAT, Mode.HEATING) == pytest.approx(1.0)
    assert totals.get(Kind.HEAT, Mode.DHW) == pytest.approx(1.0)
    # Heating: 5–40 min standby, 45–60 and 125–150 running (42 + 2 h),
    # 170 min beyond the window.
    assert totals.get(Kind.ELEC, Mode.HEATING) == pytest.approx(10 * STEP)
    assert totals.get(Kind.STANDBY, Mode.HEATING) == pytest.approx(8 * STEP + 0.1)
    # Hot water: until its first own step standby, then running.
    assert totals.get(Kind.STANDBY, Mode.DHW) == pytest.approx(6 * STEP)
    assert totals.get(Kind.ELEC, Mode.DHW) == pytest.approx(6 * STEP)
    assert set(entry.runtime_data.coarse_heat_modes()) == {Mode.HEATING, Mode.DHW}
