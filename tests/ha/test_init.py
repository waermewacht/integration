"""Setup, booking through real state changes, standby, restart, removal."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.waermewacht.const import DOMAIN
from custom_components.waermewacht.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import (
    ACTIVITY,
    COMPRESSOR,
    ELEC_DHW,
    ELEC_HEATING,
    ENERGY,
    FLOW,
    HEAT_DHW,
    HEAT_HEATING,
    RETURN,
    TEMPERATURE,
    entry_data,
)

# 15.01.2026 07:00:30 CET.
START = datetime(2026, 1, 15, 6, 0, 30, tzinfo=UTC)


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    platform = "binary_sensor" if key == "cycling_problem" else "sensor"
    found = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert found, key
    return found


def state(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    current = hass.states.get(entity_id(hass, entry, key))
    assert current is not None, key
    return current.state


def value(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> float:
    return float(state(hass, entry, key))


async def tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: float
) -> None:
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def set_counters(hass: HomeAssistant, heat: float, elec: float) -> None:
    hass.states.async_set(HEAT_HEATING, str(heat), ENERGY)
    hass.states.async_set(ELEC_HEATING, str(elec), ENERGY)


async def setup(hass: HomeAssistant) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    set_counters(hass, 1000.0, 300.0)
    hass.states.async_set(HEAT_DHW, "500.0", ENERGY)
    hass.states.async_set(ELEC_DHW, "200.0", ENERGY)
    hass.states.async_set(COMPRESSOR, "off")
    hass.states.async_set(ACTIVITY, "aus")
    hass.states.async_set(FLOW, "28.0", TEMPERATURE)
    hass.states.async_set(RETURN, "24.0", TEMPERATURE)
    entry = MockConfigEntry(domain=DOMAIN, title="WP", data=entry_data())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def heating_run(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: float
) -> None:
    """A heating run of `minutes`: 3 kWh heat for 1 kWh electricity."""
    hass.states.async_set(COMPRESSOR, "on")
    hass.states.async_set(ACTIVITY, "Heizen")
    await hass.async_block_till_done()
    await tick(hass, freezer, minutes)
    set_counters(hass, 1003.0, 301.0)
    await hass.async_block_till_done()
    hass.states.async_set(COMPRESSOR, "off")
    hass.states.async_set(ACTIVITY, "aus")
    await hass.async_block_till_done()


@pytest.mark.freeze_time(START)
async def test_ratio_standby_and_cycling(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert state(hass, entry, "ratio_heating_month") == "unknown"

    await heating_run(hass, freezer, 30)
    await tick(hass, freezer, 1)
    assert value(hass, entry, "ratio_heating_month") == pytest.approx(3.0)
    assert value(hass, entry, "starts_today") == 1
    assert value(hass, entry, "run_minutes_today") == pytest.approx(30, abs=0.1)
    assert value(hass, entry, "spread_today") == pytest.approx(4.0)
    assert value(hass, entry, "flow_temp_today") == pytest.approx(28.0)

    # A reading after the run ended (same value): from here on the compressor
    # stands still. Readings in the same instant as the stop would still
    # belong to the run (HA 2026.4 gives them microseconds apart).
    hass.states.async_set(ELEC_HEATING, "301.00", ENERGY)
    await hass.async_block_till_done()

    # Standing still: the heating counter grows, the heat does not.
    await tick(hass, freezer, 120)
    set_counters(hass, 1003.0, 301.05)
    await tick(hass, freezer, 1)
    runtime = entry.runtime_data
    debug = {
        "totals": runtime.totals.as_dict(),
        "counters": {s.value: c.as_dict() for s, c in runtime.counters.items()},
        "tracker": runtime.tracker.as_dict(),
        "heat_at": {m.value: t.isoformat() for m, t in runtime._heat_at.items()},
        "mode_seen": {m.value: t.isoformat() for m, t in runtime._mode_seen.items()},
        "events": runtime.events,
        "listeners": len(runtime._listeners),
        "standby_state": hass.states.get(entity_id(hass, entry, "standby")).as_dict(),
        "now": freezer().isoformat() if callable(freezer) else None,
    }
    runtime._notify()
    debug["after_notify"] = state(hass, entry, "standby")
    assert value(hass, entry, "standby") == pytest.approx(0.05), json.dumps(debug)
    assert value(hass, entry, "ratio_heating_month") == pytest.approx(3.0)
    assert value(hass, entry, "ratio_combined_month") == pytest.approx(3 / 1.05)
    assert state(hass, entry, "cycling_problem") == "off"

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["runs_kept"] == 1
    assert "WP" not in str(diagnostics["config"])


@pytest.mark.freeze_time(START)
async def test_restart_during_run_is_no_new_start(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    hass.states.async_set(COMPRESSOR, "on")
    hass.states.async_set(ACTIVITY, "Heizen")
    await hass.async_block_till_done()
    await tick(hass, freezer, 10)
    assert value(hass, entry, "starts_today") == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.states.async_set(COMPRESSOR, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=20))
    hass.states.async_set(COMPRESSOR, "on")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass, freezer, 1)
    assert value(hass, entry, "starts_today") == 1
    assert value(hass, entry, "starts_total") == 1


@pytest.mark.freeze_time(START)
async def test_unavailable_counter_is_not_zero(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    hass.states.async_set(ELEC_HEATING, "unavailable", ENERGY)
    await tick(hass, freezer, 1)
    hass.states.async_set(ELEC_HEATING, "300.0", ENERGY)
    await tick(hass, freezer, 1)
    assert value(hass, entry, "electricity_heating") == 0
    assert value(hass, entry, "standby") == 0


@pytest.mark.freeze_time(START)
async def test_remove_entry(hass: HomeAssistant) -> None:
    entry = await setup(hass)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.config_entries.async_entries(DOMAIN) == []
