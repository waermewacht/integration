"""Actions performance_curve and heat_load on recorded statistics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.waermewacht.const import DOMAIN

from .conftest import ELEC_HEATING, ENERGY, FLOW, HEAT_HEATING, TEMPERATURE, entry_data

OUTDOOR = "sensor.boiler_outdoortemp"
# Three full local days (Berlin, winter time) ending yesterday.
FIRST_HOUR = datetime(2026, 1, 11, 23, tzinfo=UTC)
HOURS = 72
NOW = FIRST_HOUR + timedelta(hours=HOURS + 10)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


def import_series(hass: HomeAssistant, statistic_id: str, *, mean: bool) -> None:
    rows: list[StatisticData] = []
    for i in range(HOURS):
        start = FIRST_HOUR + timedelta(hours=i)
        if mean:
            rows.append(StatisticData(start=start, mean=1.0, min=0.5, max=1.5))
        elif statistic_id == HEAT_HEATING:
            rows.append(StatisticData(start=start, sum=1.0 * (i + 1)))
        else:
            rows.append(StatisticData(start=start, sum=0.25 * (i + 1)))
    async_import_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.ARITHMETIC if mean else StatisticMeanType.NONE,
            has_sum=not mean,
            name=None,
            source="recorder",
            statistic_id=statistic_id,
            unit_class="temperature" if mean else "energy",
            unit_of_measurement="°C" if mean else "kWh",
        ),
        rows,
    )


async def setup(hass: HomeAssistant, with_outdoor: bool) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(HEAT_HEATING, "72.0", ENERGY)
    hass.states.async_set(ELEC_HEATING, "18.0", ENERGY)
    hass.states.async_set(OUTDOOR, "1.0", TEMPERATURE)
    entities = {"heat_heating": HEAT_HEATING, "elec_heating": ELEC_HEATING}
    if with_outdoor:
        entities["outdoor_temp"] = OUTDOOR
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(entities=entities)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.freeze_time(NOW)
async def test_curve_and_heat_load(hass: HomeAssistant) -> None:
    import_series(hass, HEAT_HEATING, mean=False)
    import_series(hass, ELEC_HEATING, mean=False)
    import_series(hass, OUTDOOR, mean=True)
    await async_wait_recording_done(hass)
    entry = await setup(hass, with_outdoor=True)
    window = {
        "config_entry": entry.entry_id,
        "start": FIRST_HOUR.isoformat(),
        "end": (FIRST_HOUR + timedelta(hours=HOURS)).isoformat(),
    }

    curve = await hass.services.async_call(
        DOMAIN, "performance_curve", window, blocking=True, return_response=True
    )
    # Three days at 1 °C: one class, too few days for a ratio (7 needed).
    assert sum(row["days"] for row in curve["classes"]) == 3
    assert all(row["ratio"] is None for row in curve["classes"])

    load = await hass.services.async_call(
        DOMAIN, "heat_load", window, blocking=True, return_response=True
    )
    assert load["sufficient"] is False
    assert "too_few_weeks" in load["reasons"]

    # Three days at 1 °C: 19 K·d each (G20/15), 24 kWh of heating heat each.
    report = await hass.services.async_call(
        DOMAIN, "report", window, blocking=True, return_response=True
    )
    assert report["degree_days"]["degree_days"] == pytest.approx(57.0)
    assert report["degree_days"]["kwh_per_degree_day"] == pytest.approx(1.26)
    assert [m["degree_days"]["days_counted"] for m in report["months"]] == [3]


@pytest.mark.freeze_time(NOW)
async def test_needs_an_outdoor_temperature(hass: HomeAssistant) -> None:
    entry = await setup(hass, with_outdoor=False)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "performance_curve",
            {"config_entry": entry.entry_id},
            blocking=True,
            return_response=True,
        )


STARTS = "sensor.boiler_totalcompstarts"


@pytest.mark.freeze_time(NOW)
async def test_starts_season_from_the_statistics(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The counter's statistics reach back to 12 January only: the season
    count starts there and says so."""
    import_series(hass, HEAT_HEATING, mean=False)
    import_series(hass, ELEC_HEATING, mean=False)
    import_series(hass, OUTDOOR, mean=True)
    import_series(hass, FLOW, mean=True)
    async_import_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=None,
            source="recorder",
            statistic_id=STARTS,
            unit_class=None,
            unit_of_measurement=None,
        ),
        [
            StatisticData(
                start=FIRST_HOUR + timedelta(hours=i), state=2000 + i, sum=float(i)
            )
            for i in range(HOURS)
        ],
    )
    await async_wait_recording_done(hass)
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(HEAT_HEATING, "72.0", ENERGY)
    hass.states.async_set(ELEC_HEATING, "18.0", ENERGY)
    hass.states.async_set(OUTDOOR, "1.0", TEMPERATURE)
    hass.states.async_set(STARTS, "2090", {"state_class": "total_increasing"})
    hass.states.async_set(FLOW, "30.0", TEMPERATURE)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data=entry_data(
            entities={
                "heat_heating": HEAT_HEATING,
                "elec_heating": ELEC_HEATING,
                "outdoor_temp": OUTDOOR,
                "starts_total": STARTS,
                "flow_temp": FLOW,
            }
        ),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    await hass.async_block_till_done()

    found = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_starts_season"
    )
    state = hass.states.get(found)
    assert state.state == "90"
    assert state.attributes["since"] == FIRST_HOUR.isoformat()

    # Three days are too few for the heating curve: unknown, with reasons.
    flow = hass.states.get(
        er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_flow_at_zero"
        )
    )
    assert flow.state == "unknown"
    assert "too_few_days" in flow.attributes["reasons"]
