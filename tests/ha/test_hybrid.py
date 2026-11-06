"""Hybrid systems in Home Assistant: the boiler's counters are booked apart,
the heat pump's share follows, the form and the options know the boiler."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.config_flow import validate
from custom_components.waermewacht.const import DOMAIN
from custom_components.waermewacht.energy import Kind
from custom_components.waermewacht.model import Mode

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
from .test_init import entity_id, tick, value

START = datetime(2026, 1, 15, 6, 0, 30, tzinfo=UTC)
BOILER_HEAT = "sensor.boiler_nrgheat2"
FUEL = "sensor.boiler_gasmeterheat"
FUEL_DHW = "sensor.boiler_dhw_gasmeter"


async def setup(hass: HomeAssistant, **boiler: str) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(HEAT_HEATING, "1000.0", ENERGY)
    hass.states.async_set(ELEC_HEATING, "300.0", ENERGY)
    hass.states.async_set(HEAT_DHW, "500.0", ENERGY)
    hass.states.async_set(ELEC_DHW, "200.0", ENERGY)
    hass.states.async_set(BOILER_HEAT, "15000.0", ENERGY)
    hass.states.async_set(FUEL, "16000.0", ENERGY)
    hass.states.async_set(FUEL_DHW, "1900.0", ENERGY)
    hass.states.async_set(COMPRESSOR, "off")
    hass.states.async_set(ACTIVITY, "aus")
    hass.states.async_set(FLOW, "35.0", TEMPERATURE)
    hass.states.async_set(RETURN, "30.0", TEMPERATURE)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data=entry_data(entities={**ENTITIES, **boiler}),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.freeze_time(START)
async def test_boiler_booked_apart_and_share(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(
        hass,
        boiler_heat_heating=BOILER_HEAT,
        fuel_heating=FUEL,
        fuel_dhw=FUEL_DHW,
    )
    runtime = entry.runtime_data
    # A heating run of the heat pump, the boiler helping meanwhile.
    hass.states.async_set(COMPRESSOR, "on")
    hass.states.async_set(ACTIVITY, "Heizen")
    # Half an hour later (the jump check allows at most 50 kW per counter).
    await tick(hass, freezer, 30)
    hass.states.async_set(HEAT_HEATING, "1003.0", ENERGY)
    hass.states.async_set(ELEC_HEATING, "301.0", ENERGY)
    hass.states.async_set(BOILER_HEAT, "15002.0", ENERGY)
    hass.states.async_set(FUEL, "16002.2", ENERGY)
    hass.states.async_set(FUEL_DHW, "1900.5", ENERGY)
    await tick(hass, freezer, 30)

    totals = runtime.totals
    assert totals.get(Kind.HEAT, Mode.HEATING) == pytest.approx(3.0)
    assert totals.get(Kind.ELEC, Mode.HEATING) == pytest.approx(1.0)
    assert totals.get(Kind.AUX, Mode.HEATING) == 0.0  # never the backup heater
    assert totals.get(Kind.BOILER, Mode.HEATING) == pytest.approx(2.0)
    assert totals.get(Kind.FUEL, Mode.HEATING) == pytest.approx(2.2)
    assert totals.get(Kind.FUEL, Mode.DHW) == pytest.approx(0.5)

    assert value(hass, entry, "boiler_heat_heating") == pytest.approx(2.0)
    assert value(hass, entry, "fuel_heating") == pytest.approx(2.2)
    assert value(hass, entry, "ratio_heating_month") == pytest.approx(3.0)
    share = hass.states.get(entity_id(hass, entry, "heat_pump_share_month"))
    assert float(share.state) == pytest.approx(60.0)  # 3 of 3 + 2 kWh
    # Hot water: heat pump nothing, boiler 0.5 kWh fuel x 0.87 (no counter).
    assert share.attributes["boiler_heat_dhw_kwh"] == pytest.approx(0.4, abs=0.05)
    assert share.attributes["boiler_heat_from_fuel"] == ["dhw"]
    assert share.attributes["boiler_efficiency"] == pytest.approx(0.87)


@pytest.mark.freeze_time(START)
async def test_no_boiler_sensors_without_a_boiler(hass: HomeAssistant) -> None:
    entry = await setup(hass)
    registry = er.async_get(hass)
    for key in ("heat_pump_share_month", "boiler_heat_heating", "fuel_heating"):
        unique_id = f"{entry.entry_id}_{key}"
        assert registry.async_get_entity_id("sensor", DOMAIN, unique_id) is None


async def test_boiler_needs_the_heat_pumps_heating_meter(hass: HomeAssistant) -> None:
    hass.states.async_set(FUEL, "16000.0", ENERGY)
    assert validate(hass, {"compressor": COMPRESSOR, "fuel_heating": FUEL}) == (
        "boiler_without_heat_pump"
    )
    assert validate(hass, {**ENTITIES, "fuel_heating": FUEL}) is None


async def test_boiler_efficiency_only_for_heat_from_fuel(hass: HomeAssistant) -> None:
    fuel_only = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data=entry_data(entities={**ENTITIES, "fuel_heating": FUEL}),
    )
    fuel_only.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(fuel_only.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert "boiler_efficiency" in {str(k) for k in result["data_schema"].schema}

    with_heat = MockConfigEntry(
        domain=DOMAIN,
        title="WP 2",
        data=entry_data(
            entities={
                **ENTITIES,
                "fuel_heating": FUEL,
                "boiler_heat_heating": BOILER_HEAT,
            }
        ),
    )
    with_heat.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(with_heat.entry_id)
    assert "boiler_efficiency" not in {str(k) for k in result["data_schema"].schema}
