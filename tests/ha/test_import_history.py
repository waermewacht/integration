"""The hours before the setup go into the statistics of the own energy sensors."""

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
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.waermewacht.const import DOMAIN

from .conftest import ELEC_HEATING, ENERGY, HEAT_HEATING, entry_data
from .test_init import START, entity_id


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


def source_statistics(
    hass: HomeAssistant, statistic_id: str, sums: list[float]
) -> None:
    """Hourly sums of a source counter for the three hours before START."""
    first = START.replace(minute=0, second=0) - timedelta(hours=len(sums))
    async_import_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=None,
            source="recorder",
            statistic_id=statistic_id,
            unit_class="energy",
            unit_of_measurement="kWh",
        ),
        [
            StatisticData(start=first + timedelta(hours=i), sum=value, state=value)
            for i, value in enumerate(sums)
        ],
    )


async def sums(hass: HomeAssistant, statistic_id: str) -> list[float]:
    rows = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        START - timedelta(days=1),
        START + timedelta(hours=1),
        {statistic_id},
        "hour",
        None,
        {"sum"},
    )
    return [row["sum"] for row in rows.get(statistic_id, [])]


@pytest.mark.freeze_time(START)
async def test_hours_before_setup_are_imported(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    # Heat 1, 2, 3 kWh with electricity in the same hours (not standby).
    source_statistics(hass, HEAT_HEATING, [1.0, 3.0, 6.0])
    source_statistics(hass, ELEC_HEATING, [0.25, 0.75, 1.5])
    await async_wait_recording_done(hass)
    hass.states.async_set(HEAT_HEATING, "6.0", ENERGY)
    hass.states.async_set(ELEC_HEATING, "1.5", ENERGY)

    entities = {"heat_heating": HEAT_HEATING, "elec_heating": ELEC_HEATING}
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(entities=entities)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    # The sums end at 0, where the sensor's own recorded sum starts.
    assert await sums(hass, entity_id(hass, entry, "heat_heating")) == [-5.0, -3.0, 0.0]
    assert await sums(hass, entity_id(hass, entry, "electricity_heating")) == [
        -1.25,
        -0.75,
        0.0,
    ]
    assert entry.runtime_data.history_imported

    # Once only: a reload does not import again.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    assert await sums(hass, entity_id(hass, entry, "heat_heating")) == [-5.0, -3.0, 0.0]
