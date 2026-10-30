"""Day counters (energy today) taken for lifetime counters: a warning in the
setup, a repair issue for older entries."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

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
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.waermewacht.const import DOMAIN

from .conftest import ELEC_HEATING, ENERGY, HEAT_HEATING, entry_data

HEAT_TOTAL = "sensor.boiler_nrgheat_total"
RESTARTING = "sensor.esphome_heat"
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


def import_counters(hass: HomeAssistant, days: int = 4) -> None:
    """Heat as energy today (0.5 … 12 kWh, restarting at 0 UTC); electricity
    and a second heat counter as lifetime counters; a lifetime counter whose
    device restarted at 0 twice, at different hours."""
    now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=days)
    hour, total = start, 0.0
    series: dict[str, list[StatisticData]] = {
        HEAT_HEATING: [],
        ELEC_HEATING: [],
        HEAT_TOTAL: [],
        RESTARTING: [],
    }
    restart_at = {start + timedelta(hours=10), start + timedelta(hours=63)}
    restarting = 100.0
    while hour < now:
        total += 0.5
        restarting = 0.5 if hour in restart_at else restarting + 0.5
        for statistic_id, state in (
            (HEAT_HEATING, (hour.hour + 1) * 0.5),
            (ELEC_HEATING, 100.0 + total / 4),
            (HEAT_TOTAL, 1000.0 + total),
            (RESTARTING, restarting),
        ):
            series[statistic_id].append(
                StatisticData(start=hour, state=state, sum=total)
            )
        hour += timedelta(hours=1)
    for statistic_id, rows in series.items():
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


async def prepared(hass: HomeAssistant) -> None:
    import_counters(hass)
    await async_wait_recording_done(hass)
    await hass.config.async_set_time_zone("Europe/Berlin")
    for entity_id in (HEAT_HEATING, ELEC_HEATING, HEAT_TOTAL, RESTARTING):
        hass.states.async_set(entity_id, "3.0", ENERGY)


async def manual_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "WP", "source": "manual"}
    )
    return result["flow_id"]


def heating(heat: str) -> dict:
    return {
        **EMPTY_SECTIONS,
        "heating": {"heat_heating": heat, "elec_heating": ELEC_HEATING},
    }


async def test_day_counter_warning_can_be_overridden(hass: HomeAssistant) -> None:
    """A warning: sent again unchanged, the mapping is kept."""
    await prepared(hass)
    flow_id = await manual_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, heating(HEAT_HEATING)
    )
    assert result["errors"] == {"base": "day_counter"}
    result = await hass.config_entries.flow.async_configure(
        flow_id, heating(HEAT_HEATING)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_restarting_lifetime_counter_passes(hass: HomeAssistant) -> None:
    """Restarts at 0 at different hours are no day counter."""
    await prepared(hass)
    flow_id = await manual_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, heating(RESTARTING)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_failed_statistics_query_does_not_block(hass: HomeAssistant) -> None:
    await prepared(hass)
    flow_id = await manual_flow(hass)
    with patch(
        "custom_components.waermewacht.day_counters.statistics_during_period",
        side_effect=RuntimeError("database locked"),
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id, heating(HEAT_HEATING)
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def setup_day_counter_entry(hass: HomeAssistant) -> MockConfigEntry:
    """An entry made before the check, without outdoor temperature."""
    entities = {"heat_heating": HEAT_HEATING, "elec_heating": ELEC_HEATING}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        unique_id=HEAT_HEATING,
        data=entry_data(template=None, entities=entities),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_reconfigure_checks_only_changed_counters(hass: HomeAssistant) -> None:
    await prepared(hass)
    entry = await setup_day_counter_entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    # The day counter stays, only the hot water is added: no warning.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **heating(HEAT_HEATING),
            "dhw": {"heat_dhw": HEAT_TOTAL, "elec_dhw": RESTARTING},
        },
    )
    assert result["reason"] == "reconfigure_successful"


async def test_repair_issue_goes_after_reconfigure(hass: HomeAssistant) -> None:
    """The daily check (also without outdoor temperature) raises the issue;
    after Reconfigure with a total counter the reloaded entry drops it."""
    await prepared(hass)
    entry = await setup_day_counter_entry(hass)
    runtime = entry.runtime_data
    assert runtime._counter_check_due(dt_util.utcnow() + timedelta(minutes=3))
    await runtime._async_check_counters()
    issue_id = f"{entry.entry_id}_day_counter"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders["entities"] == HEAT_HEATING

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], heating(HEAT_TOTAL)
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.runtime_data is not runtime  # reloaded
    await entry.runtime_data._async_check_counters()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


def homecom_data(heat: str) -> dict:
    """A template with day values (Bosch HomeCom)."""
    return entry_data(
        template="bosch_homecom",
        entities={"heat_heating": heat, "elec_heating": HEAT_HEATING},
    )


async def test_lifetime_counter_in_day_values_gives_a_repair_issue(
    hass: HomeAssistant,
) -> None:
    await prepared(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="WP", data=homecom_data(HEAT_TOTAL))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data._async_check_counters()
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, f"{entry.entry_id}_lifetime_counter")
    assert issue is not None
    # The day counter in the electricity place is right for day values.
    assert issue.translation_placeholders["entities"] == HEAT_TOTAL
    assert registry.async_get_issue(DOMAIN, f"{entry.entry_id}_day_counter") is None


async def test_lifetime_counter_warning_on_reconfigure(hass: HomeAssistant) -> None:
    await prepared(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        unique_id="bosch_homecom:k40",
        data=homecom_data(HEAT_HEATING),
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    mapping = {
        **EMPTY_SECTIONS,
        "heating": {"heat_heating": HEAT_TOTAL, "elec_heating": HEAT_HEATING},
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], mapping)
    assert result["errors"] == {"base": "lifetime_counter"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], mapping)
    assert result["reason"] == "reconfigure_successful"
