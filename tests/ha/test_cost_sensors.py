"""Costs, savings against a gas boiler and CO₂ from the prices of the options."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.const import DOMAIN

from .conftest import (
    ACTIVITY,
    COMPRESSOR,
    ELEC_DHW,
    ENERGY,
    HEAT_DHW,
    entry_data,
)
from .test_init import START, set_counters, tick, value


async def setup(hass: HomeAssistant, options: dict) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    set_counters(hass, 1000.0, 300.0)
    hass.states.async_set(HEAT_DHW, "500.0", ENERGY)
    hass.states.async_set(ELEC_DHW, "200.0", ENERGY)
    hass.states.async_set(COMPRESSOR, "off")
    hass.states.async_set(ACTIVITY, "aus")
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(), options=options
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.freeze_time(START)
async def test_costs_and_gas_comparison(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    # Prices in ct/kWh as entered; no gas base price (optional).
    entry = await setup(hass, {"electricity_price": 30.0, "gas_price": 10.0})
    hass.states.async_set(COMPRESSOR, "on")
    hass.states.async_set(ACTIVITY, "Heizen")
    await tick(hass, freezer, 30)
    set_counters(hass, 1010.0, 302.5)  # 10 kWh heat for 2.5 kWh electricity
    await tick(hass, freezer, 1)

    # 2.5 kWh x 0.30 €/kWh.
    assert value(hass, entry, "cost_month") == pytest.approx(0.75)
    assert value(hass, entry, "cost_season") == pytest.approx(0.75)
    assert value(hass, entry, "heat_cost_season") == pytest.approx(0.075)
    # Gas: 10 kWh / 0.87 = 11.49 kWh x 0.10 € = 1.15 €; saving 0.40 €.
    assert value(hass, entry, "gas_savings_season") == pytest.approx(0.40)
    # CO₂: 2.5 x 406 g = 1.0 kg against 11.49 x 240 x 0.906 g = 2.5 kg.
    assert value(hass, entry, "co2_savings_season") == pytest.approx(1.0)


@pytest.mark.freeze_time(START)
async def test_without_prices_only_co2(hass: HomeAssistant) -> None:
    entry = await setup(hass, {})
    registry = er.async_get(hass)

    def exists(key: str) -> bool:
        return (
            registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
            is not None
        )

    assert exists("co2_savings_season")
    for key in ("cost_month", "cost_season", "heat_cost_season", "gas_savings_season"):
        assert not exists(key), key
