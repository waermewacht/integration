"""Health check: repair issues for stuck counters and unreachable sources,
the problem sensors with their reason, the restart button and the diary."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    ENTITIES,
    FLOW,
    HEAT_DHW,
    HEAT_HEATING,
    RETURN,
    TEMPERATURE,
    entry_data,
)
from .test_init import set_counters, tick

# 15.01.2026 07:00:30 CET.
START = datetime(2026, 1, 15, 6, 0, 30, tzinfo=UTC)
OUTDOOR = "sensor.boiler_outdoortemp"
AUX = "sensor.boiler_nrgsuppheating"


async def setup(hass: HomeAssistant, **entities: str) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    # Decimal counters: a standstill counts after one hour of running.
    set_counters(hass, 1000.5, 300.5)
    hass.states.async_set(HEAT_DHW, "500.5", ENERGY)
    hass.states.async_set(ELEC_DHW, "200.5", ENERGY)
    hass.states.async_set(COMPRESSOR, "off")
    hass.states.async_set(ACTIVITY, "aus")
    hass.states.async_set(FLOW, "28.0", TEMPERATURE)
    hass.states.async_set(RETURN, "24.0", TEMPERATURE)
    hass.states.async_set(OUTDOOR, "3.0", TEMPERATURE)
    hass.states.async_set(AUX, "12.0", ENERGY)
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(entities={**ENTITIES, **entities})
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str):
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{key}"
    )


def issue(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> ir.IssueEntry:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{entry.entry_id}_{key}")


@pytest.mark.freeze_time(START)
async def test_counter_standing_still_while_running(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    hass.states.async_set(COMPRESSOR, "on")
    hass.states.async_set(ACTIVITY, "Heizen")
    await tick(hass, freezer, 11)  # grace time over, the clock starts
    await tick(hass, freezer, 30)
    assert issue(hass, entry, "counter_stuck") is None
    await tick(hass, freezer, 31)
    found = issue(hass, entry, "counter_stuck")
    assert found is not None
    assert set(found.translation_placeholders["entities"].split(", ")) == {
        HEAT_HEATING,
        ELEC_HEATING,
    }
    # Only the heat rises: the electricity meter still stands still.
    hass.states.async_set(HEAT_HEATING, "1001.5", ENERGY)
    await tick(hass, freezer, 1)
    assert issue(hass, entry, "counter_stuck").translation_placeholders["entities"] == (
        ELEC_HEATING
    )
    hass.states.async_set(ELEC_HEATING, "300.8", ENERGY)
    await tick(hass, freezer, 1)
    assert issue(hass, entry, "counter_stuck") is None


@pytest.mark.freeze_time(START)
async def test_no_standstill_while_the_compressor_is_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    await tick(hass, freezer, 11)
    await tick(hass, freezer, 240)
    assert issue(hass, entry, "counter_stuck") is None


@pytest.mark.freeze_time(START)
async def test_source_unavailable_for_an_hour(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    hass.states.async_set(FLOW, "unavailable")
    await tick(hass, freezer, 11)
    await tick(hass, freezer, 40)
    assert issue(hass, entry, "source_unavailable") is None
    await tick(hass, freezer, 10)
    found = issue(hass, entry, "source_unavailable")
    assert found is not None
    assert found.translation_placeholders["entities"] == FLOW
    assert found.translation_placeholders["minutes"] == "60"
    hass.states.async_set(FLOW, "29.0", TEMPERATURE)
    await tick(hass, freezer, 1)
    assert issue(hass, entry, "source_unavailable") is None


@pytest.mark.freeze_time(START)
async def test_health_sensors_need_outdoor_and_backup_heater(
    hass: HomeAssistant,
) -> None:
    entry = await setup(hass)
    assert entity_id(hass, entry, "binary_sensor", "efficiency_drop") is None
    assert entity_id(hass, entry, "button", "restart_comparison") is None

    other = await setup(hass, outdoor_temp=OUTDOOR)
    assert entity_id(hass, other, "binary_sensor", "efficiency_drop")
    assert entity_id(hass, other, "button", "restart_comparison")
    assert entity_id(hass, other, "binary_sensor", "aux_mild_weather") is None


@pytest.mark.freeze_time(START)
async def test_unknown_with_reason_and_restart(hass: HomeAssistant) -> None:
    """Without a recorder there is no analysis: unknown, with the reason."""
    entry = await setup(hass, outdoor_temp=OUTDOOR, aux_heating=AUX)
    drop = entity_id(hass, entry, "binary_sensor", "efficiency_drop")
    aux = entity_id(hass, entry, "binary_sensor", "aux_mild_weather")
    for found in (drop, aux):
        state = hass.states.get(found)
        assert state.state == "unknown"
        assert state.attributes["reason"] == "not_analysed_yet"

    button = entity_id(hass, entry, "button", "restart_comparison")
    await hass.services.async_call(
        "button", "press", {"entity_id": button}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(drop).attributes["reason"] == "comparison_restarted"
    assert entry.runtime_data.comparison_reset_at is not None


@pytest.mark.freeze_time(START)
async def test_diary_entry_at_midnight(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass, outdoor_temp=OUTDOOR)
    hass.states.async_set(COMPRESSOR, "on")
    hass.states.async_set(ACTIVITY, "Heizen")
    await tick(hass, freezer, 30)
    set_counters(hass, 1003.5, 301.5)
    hass.states.async_set(COMPRESSOR, "off")
    hass.states.async_set(ACTIVITY, "aus")
    await tick(hass, freezer, 1)
    # From 07:31 to just after midnight local time.
    await tick(hass, freezer, 16 * 60 + 30)
    diary = entry.runtime_data.diary
    assert [d["day"] for d in diary] == ["2026-01-15"]
    assert diary[0]["starts"] == 1
    assert diary[0]["outdoor"] == pytest.approx(3.0)
    assert diary[0]["energy"]["heat_heating"] == pytest.approx(3.0)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["diary_days"] == 1
