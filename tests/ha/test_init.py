"""Setup, booking through real state changes, standby, restart, removal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
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
    """Let pending state changes be handled, then advance to the next minute tick.

    The test harness of HA 2026.4 fires time listeners before queued state
    events: without waiting, the tick would come before the booking.
    """
    await hass.async_block_till_done()
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

    # Standing still: the heating counter grows, the heat does not.
    await tick(hass, freezer, 120)
    set_counters(hass, 1003.0, 301.5)
    await tick(hass, freezer, 1)
    assert value(hass, entry, "standby") == pytest.approx(0.5)
    assert value(hass, entry, "ratio_heating_month") == pytest.approx(3.0)
    assert value(hass, entry, "ratio_combined_month") == pytest.approx(2.0)
    assert state(hass, entry, "cycling_problem") == "off"

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["runs_kept"] == 1
    assert "WP" not in str(diagnostics["config"])
    # The test states have no registry entries: nothing to list.
    assert diagnostics["source"] == {"devices": [], "entities": []}


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


@pytest.mark.freeze_time(START)
async def test_report_checks_its_input(hass: HomeAssistant) -> None:
    entry = await setup(hass)

    async def report(**data: str) -> None:
        await hass.services.async_call(
            DOMAIN,
            "report",
            {"config_entry": entry.entry_id, **data},
            blocking=True,
            return_response=True,
        )

    with pytest.raises(ServiceValidationError):
        await report(start="2026-01-15 08:00:00", end="2026-01-15 07:00:00")
    # The test instance has no recorder: the report says so instead of 0.
    with pytest.raises(HomeAssistantError):
        await report(start="2026-01-01 00:00:00")


@pytest.mark.freeze_time(START)
async def test_repair_issue_for_missing_entity(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    issues = ir.async_get(hass)
    issue_id = f"{entry.entry_id}_missing_entity"
    hass.states.async_remove(FLOW)
    await tick(hass, freezer, 5)
    assert issues.async_get_issue(DOMAIN, issue_id) is None  # grace time
    await tick(hass, freezer, 6)
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders["entities"] == FLOW
    hass.states.async_set(FLOW, "28.0", TEMPERATURE)
    await tick(hass, freezer, 1)
    assert issues.async_get_issue(DOMAIN, issue_id) is None


@pytest.mark.freeze_time(START)
async def test_runs_are_kept_in_their_own_file(
    hass: HomeAssistant, hass_storage: dict, freezer: FrozenDateTimeFactory
) -> None:
    """SD cards: the live file stays small; the run history is written when
    a run ends, not with every save."""
    entry = await setup(hass)
    await heating_run(hass, freezer, 30)
    await tick(hass, freezer, 1)
    assert await hass.config_entries.async_unload(entry.entry_id)
    live = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    history = hass_storage[f"{DOMAIN}.{entry.entry_id}.history"]["data"]
    assert "runs" not in live
    assert len(history["runs"]) == 1

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass, freezer, 1)
    assert value(hass, entry, "starts_today") == 1
