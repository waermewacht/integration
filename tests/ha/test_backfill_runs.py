"""Runs and defrosts before the setup come from the recorded state history."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.waermewacht.const import DOMAIN

from .conftest import (
    ACTIVITY,
    COMPRESSOR,
    ELEC_DHW,
    ELEC_HEATING,
    ENERGY,
    HEAT_DHW,
    HEAT_HEATING,
    entry_data,
)
from .test_init import START, value


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


async def at_minute(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, minute: float, **states: str
) -> None:
    freezer.move_to(START + timedelta(minutes=minute))
    for entity_id, state in states.items():
        hass.states.async_set(entity_id, state)
    await hass.async_block_till_done()


@pytest.mark.freeze_time(START)
async def test_runs_before_setup_are_counted(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    for entity_id in (HEAT_HEATING, ELEC_HEATING, HEAT_DHW, ELEC_DHW):
        hass.states.async_set(entity_id, "100.0", ENERGY)
    c, a = COMPRESSOR, ACTIVITY
    await at_minute(hass, freezer, 0, **{c: "off", a: "aus"})
    await at_minute(hass, freezer, 10, **{c: "on", a: "Heizen"})
    await at_minute(hass, freezer, 40, **{a: "Abtauen"})
    await at_minute(hass, freezer, 44, **{a: "Heizen"})
    await at_minute(hass, freezer, 55, **{c: "off", a: "aus"})
    await at_minute(hass, freezer, 70, **{c: "on", a: "Warmwasser"})
    await async_wait_recording_done(hass)

    # Set up while the second run is still going.
    freezer.move_to(START + timedelta(minutes=80))
    entry = MockConfigEntry(domain=DOMAIN, title="WP", data=entry_data())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert value(hass, entry, "starts_today") == 2
    assert value(hass, entry, "defrosts_today") == 1
    assert value(hass, entry, "run_minutes_today") == pytest.approx(45)

    # The running run continues after the setup: no extra start.
    await at_minute(hass, freezer, 90, **{c: "off", a: "aus"})
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert value(hass, entry, "starts_today") == 2
