"""Day counters (energy today) taken for lifetime counters: refused in the
setup, a repair issue for older entries."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.waermewacht.const import DOMAIN

from .conftest import ELEC_HEATING, ENERGY, HEAT_HEATING, entry_data

EMPTY_SECTIONS = {
    "heating": {},
    "dhw": {},
    "cooling": {},
    "operation": {},
    "measurements": {},
    "activity_parts": {},
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


def import_counters(hass: HomeAssistant, days: int) -> None:
    """Heat as energy today (0.5 … 12 kWh, restarting at 0 UTC), electricity
    as a lifetime counter."""
    now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    hour, heat_sum, elec = now - timedelta(days=days), 0.0, 100.0
    heat, electricity = [], []
    while hour < now:
        heat_sum += 0.5
        elec += 0.125
        heat.append(
            StatisticData(start=hour, state=(hour.hour + 1) * 0.5, sum=heat_sum)
        )
        electricity.append(StatisticData(start=hour, state=elec, sum=elec - 100.0))
        hour += timedelta(hours=1)
    for statistic_id, rows in ((HEAT_HEATING, heat), (ELEC_HEATING, electricity)):
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
            rows,
        )


async def test_day_counter_is_refused_in_the_setup(hass: HomeAssistant) -> None:
    import_counters(hass, 4)
    await async_wait_recording_done(hass)
    hass.states.async_set(HEAT_HEATING, "3.0", ENERGY)
    hass.states.async_set(ELEC_HEATING, "112.0", ENERGY)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "manual"}
    )
    mapping = {
        **EMPTY_SECTIONS,
        "heating": {"heat_heating": HEAT_HEATING, "elec_heating": ELEC_HEATING},
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], mapping)
    assert result["errors"] == {"base": "day_counter"}


async def test_lifetime_counters_pass_the_setup(hass: HomeAssistant) -> None:
    import_counters(hass, 1)  # one day: no second restart
    await async_wait_recording_done(hass)
    hass.states.async_set(HEAT_HEATING, "3.0", ENERGY)
    hass.states.async_set(ELEC_HEATING, "112.0", ENERGY)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "manual"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **EMPTY_SECTIONS,
            "heating": {"heat_heating": HEAT_HEATING, "elec_heating": ELEC_HEATING},
        },
    )
    assert result["type"] == "create_entry"


async def test_day_counter_gives_a_repair_issue(hass: HomeAssistant) -> None:
    """An entry made before the check: the daily analysis finds it."""
    import_counters(hass, 4)
    await async_wait_recording_done(hass)
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(HEAT_HEATING, "3.0", ENERGY)
    hass.states.async_set(ELEC_HEATING, "112.0", ENERGY)
    entities = {"heat_heating": HEAT_HEATING, "elec_heating": ELEC_HEATING}
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(entities=entities)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data._async_check_day_counters()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"{entry.entry_id}_day_counter")
    assert issue is not None
    assert issue.translation_placeholders["entities"] == HEAT_HEATING
