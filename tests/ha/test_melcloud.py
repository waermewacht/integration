"""Mitsubishi Ecodan via MELCloud: day values without a compressor."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.const import (
    CONF_ENTITIES,
    CONF_NAME,
    CONF_TEMPLATE,
    DOMAIN,
)
from custom_components.waermewacht.periods import Period

from .conftest import ENERGY
from .test_init import START, tick, value

S = "sensor.ecodan_"
HEAT = S + "daily_heating_energy_produced"
ELEC = S + "daily_heating_energy_consumed"


@pytest.mark.freeze_time(START)
async def test_ratio_from_day_values_without_compressor(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(HEAT, "10.0", ENERGY)
    hass.states.async_set(ELEC, "3.0", ENERGY)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data={
            CONF_NAME: "WP",
            CONF_TEMPLATE: "melcloud",
            CONF_ENTITIES: {"heat_heating": HEAT, "elec_heating": ELEC},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    keys = {
        e.unique_id.removeprefix(f"{entry.entry_id}_")
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    assert "ratio_heating_month" in keys
    assert "starts_today" not in keys and "cycling_problem" not in keys

    await tick(hass, freezer, 60)
    hass.states.async_set(ELEC, "4.0", ENERGY)
    hass.states.async_set(HEAT, "14.0", ENERGY)
    await tick(hass, freezer, 1)
    await tick(hass, freezer, 150)  # past the wait for heat of the same fetch
    assert value(hass, entry, "electricity_heating") == pytest.approx(1.0)
    assert value(hass, entry, "standby") == 0
    assert value(hass, entry, "ratio_heating_month") == pytest.approx(4.0)


@pytest.mark.freeze_time(START)
async def test_previous_day_values_go_into_yesterday(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The value arriving just after midnight is yesterday's total."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(HEAT, "10.0", ENERGY)
    hass.states.async_set(ELEC, "3.0", ENERGY)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data={
            CONF_NAME: "WP",
            CONF_TEMPLATE: "melcloud",
            CONF_ENTITIES: {"heat_heating": HEAT, "elec_heating": ELEC},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = entry.runtime_data

    # 16.01. 00:21 local: the totals of 15.01. arrive at once.
    freezer.move_to(datetime(2026, 1, 15, 23, 21, tzinfo=UTC))
    await tick(hass, freezer, 1)
    hass.states.async_set(HEAT, "30.0", ENERGY)
    hass.states.async_set(ELEC, "8.0", ENERGY)
    await tick(hass, freezer, 1)
    await tick(hass, freezer, 150)  # past the wait for heat of the same fetch
    yesterday = runtime.energy(Period.YESTERDAY)
    today = runtime.energy(Period.TODAY)
    assert yesterday is not None and today is not None
    assert yesterday.values["heat_heating"] == pytest.approx(30.0)
    assert yesterday.values["elec_heating"] == pytest.approx(8.0)
    assert today.values.get("heat_heating", 0.0) == 0
