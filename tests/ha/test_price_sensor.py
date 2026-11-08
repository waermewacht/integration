"""Costs with an electricity price sensor: each hour with the sensor's mean
of that hour (statistics, else recorded states), the look-back before the
setup included; the running hour at the current price."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.waermewacht.const import DOMAIN

from .conftest import ACTIVITY, COMPRESSOR, ELEC_HEATING, HEAT_HEATING, entry_data
from .test_import_history import SETUP_HOUR, source_statistics
from .test_init import START, entity_id, set_counters, tick, value

PRICE = "sensor.electricity_price"
CENT = {"unit_of_measurement": "ct/kWh", "state_class": "measurement"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


def price_statistics(hass: HomeAssistant, cents: list[float]) -> None:
    """Hourly means of the price sensor for the hours just before START."""
    first = SETUP_HOUR - timedelta(hours=len(cents))
    async_import_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.ARITHMETIC,
            has_sum=False,
            name=None,
            source="recorder",
            statistic_id=PRICE,
            unit_class=None,
            unit_of_measurement="ct/kWh",
        ),
        [
            StatisticData(start=first + timedelta(hours=i), mean=c, min=c, max=c)
            for i, c in enumerate(cents)
        ],
    )


async def setup_entry(hass: HomeAssistant, options: dict) -> MockConfigEntry:
    # 1, 2 and 3 kWh in the three hours before the setup (sums start at 0).
    source_statistics(
        hass, HEAT_HEATING, [0.0, 3.0, 9.0, 18.0], SETUP_HOUR - timedelta(hours=4)
    )
    source_statistics(
        hass, ELEC_HEATING, [0.0, 1.0, 3.0, 6.0], SETUP_HOUR - timedelta(hours=4)
    )
    await async_wait_recording_done(hass)
    set_counters(hass, 18.0, 6.0)
    hass.states.async_set(COMPRESSOR, "off")
    hass.states.async_set(ACTIVITY, "aus")
    entities = {
        "heat_heating": HEAT_HEATING,
        "elec_heating": ELEC_HEATING,
        "compressor": COMPRESSOR,
        "activity": ACTIVITY,
    }
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(entities=entities), options=options
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    await async_wait_recording_done(hass)
    return entry


async def run_two_kwh(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    hass.states.async_set(COMPRESSOR, "on")
    hass.states.async_set(ACTIVITY, "Heizen")
    await tick(hass, freezer, 1)
    set_counters(hass, 24.0, 8.0)  # 2 kWh in the running hour
    await tick(hass, freezer, 1)


@pytest.mark.freeze_time(START)
async def test_costs_from_price_statistics(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    price_statistics(hass, [20.0, 30.0, 40.0])
    hass.states.async_set(PRICE, "50.0", CENT)
    entry = await setup_entry(hass, {"electricity_price_entity": PRICE})
    await tick(hass, freezer, 1)  # the first tick reads the prices

    # Look-back: 1 x 0.20 + 2 x 0.30 + 3 x 0.40 = 2.00 €.
    assert value(hass, entry, "cost_month") == pytest.approx(2.0)
    await run_two_kwh(hass, freezer)
    # The running hour at the current price: + 2 x 0.50 €.
    assert value(hass, entry, "cost_month") == pytest.approx(3.0)
    assert value(hass, entry, "cost_season") == pytest.approx(3.0)
    attributes = hass.states.get(entity_id(hass, entry, "cost_month")).attributes
    assert attributes["price_source"] == "sensor"
    assert attributes["price_entity"] == PRICE
    assert attributes["hours_fixed_price"] == 0
    assert attributes["hours_without_price"] == 0
    assert attributes["average_price_eur_per_kwh"] == pytest.approx(0.375)


@pytest.mark.freeze_time(START)
async def test_hours_without_price_use_the_fixed_price(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    price_statistics(hass, [30.0, 40.0])  # the first look-back hour has none
    hass.states.async_set(PRICE, "unavailable", CENT)
    entry = await setup_entry(
        hass, {"electricity_price_entity": PRICE, "electricity_price": 40.0}
    )
    await tick(hass, freezer, 1)
    # 1 x 0.40 (fixed) + 2 x 0.30 + 3 x 0.40 = 2.20 €.
    assert value(hass, entry, "cost_month") == pytest.approx(2.2)
    attributes = hass.states.get(entity_id(hass, entry, "cost_month")).attributes
    assert attributes["price_source"] == "mixed"
    assert attributes["hours_fixed_price"] == 1


@pytest.mark.freeze_time(START)
async def test_without_any_price_the_cost_is_unknown(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(PRICE, "unavailable", CENT)
    entry = await setup_entry(hass, {"electricity_price_entity": PRICE})
    await tick(hass, freezer, 1)
    assert hass.states.get(entity_id(hass, entry, "cost_month")).state == "unknown"
    attributes = hass.states.get(entity_id(hass, entry, "cost_month")).attributes
    assert attributes["hours_without_price"] == 3


async def test_prices_from_recorded_states(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A price sensor without state class has no statistics: its recorded
    states give the hourly means."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    plain = {"unit_of_measurement": "ct/kWh"}
    for hours_before, cents in ((3, "20.0"), (2, "30.0"), (1, "40.0")):
        freezer.move_to(SETUP_HOUR - timedelta(hours=hours_before))
        hass.states.async_set(PRICE, cents, plain)
        await async_wait_recording_done(hass)
    freezer.move_to(START)
    entry = await setup_entry(hass, {"electricity_price_entity": PRICE})
    await tick(hass, freezer, 1)
    assert value(hass, entry, "cost_month") == pytest.approx(2.0)
    diagnostics = entry.runtime_data.prices
    assert diagnostics is not None and diagnostics.hours_from_states >= 3


@pytest.mark.freeze_time(START)
async def test_own_electricity_at_the_feed_in_tariff(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Only a grid import meter: the grid import goes to the heat pump first;
    the rest is own electricity at the feed-in tariff."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    # The heat pump uses 1, 2, 3 kWh; the house takes 0.5, 2, 0 from the grid.
    source_statistics(
        hass,
        "sensor.grid_import",
        [0.0, 0.5, 2.5, 2.5],
        SETUP_HOUR - timedelta(hours=4),
    )
    entry = await setup_entry(
        hass,
        {
            "electricity_price": 30.0,
            "grid_import_entity": "sensor.grid_import",
            "feed_in_tariff": 8.0,
        },
    )
    await tick(hass, freezer, 1)
    # 6 kWh x 0.30 = 1.80 €, own 0.5 + 0 + 3 = 3.5 kWh at 0.08 instead:
    # 1.80 - 3.5 x 0.22 = 1.03 €, in steps of 10 cents.
    assert value(hass, entry, "cost_month") == pytest.approx(1.0)
    attributes = hass.states.get(entity_id(hass, entry, "cost_month")).attributes
    assert attributes["allocation"] == "heat_pump_first"
    assert attributes["kwh_own"] == pytest.approx(3.5)
    assert attributes["kwh_from_grid"] == pytest.approx(2.5)
    assert attributes["grid_share"] == pytest.approx(0.417)
    assert attributes["hours_all_grid"] == 0
    assert attributes["price_source"] == "fixed"


@pytest.mark.freeze_time(START)
async def test_without_grid_meter_no_allocation(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    entry = await setup_entry(hass, {"electricity_price": 30.0})
    await tick(hass, freezer, 1)
    assert value(hass, entry, "cost_month") == pytest.approx(1.8)
    attributes = hass.states.get(entity_id(hass, entry, "cost_month")).attributes
    assert attributes["allocation"] == "none"


@pytest.mark.freeze_time(START)
async def test_house_meter_glitch_counts_as_grid(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The PV meter reports Wh as kWh for one reading (107 -> 109851.5 ->
    110.131): read as it is, the house would have used 110 MWh of PV in that
    hour and the heat pump's electricity would be own. Both hours are left
    out and count as grid electricity."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    first = SETUP_HOUR - timedelta(hours=4)
    # The house takes from the grid exactly what the heat pump uses.
    source_statistics(hass, "sensor.grid_import", [0.0, 1.0, 3.0, 6.0], first)
    source_statistics(hass, "sensor.feed_in", [0.0, 0.0, 0.0, 0.0], first)
    pv_states = [107.0, 107.0, 109851.5, 110.131]
    source_statistics(
        hass,
        "sensor.pv",
        [0.0, 0.0, 109744.5, 109854.631],
        first,
        pv_states,
    )
    entry = await setup_entry(
        hass,
        {
            "electricity_price": 30.0,
            "grid_import_entity": "sensor.grid_import",
            "feed_in_entity": "sensor.feed_in",
            "pv_entity": "sensor.pv",
            "feed_in_tariff": 8.0,
        },
    )
    await tick(hass, freezer, 1)
    attributes = hass.states.get(entity_id(hass, entry, "cost_month")).attributes
    assert attributes["allocation"] == "proportional"
    assert attributes["kwh_own"] == pytest.approx(0.0)
    assert attributes["kwh_from_grid"] == pytest.approx(6.0)
    assert attributes["hours_implausible"] == 2
    assert value(hass, entry, "cost_month") == pytest.approx(1.8)
