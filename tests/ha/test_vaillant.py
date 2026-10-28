"""Vaillant (mypyllant): booking hour by hour from the external statistics
the integration writes itself, in Wh."""

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
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.waermewacht.const import (
    CONF_ENTITIES,
    CONF_NAME,
    CONF_TEMPLATE,
    DOMAIN,
)

SYSTEM = "3f9a6c2e-81d4-4b7f-a5e0-9c2d7b14e6f8"
DEVICE = "a1c3e5f7091b2d4f6a8c0e2b4d6f8a0c1e3b5d7f"
NAME = "Zuhause Device 0 aroTHERM plus "
SERIES = {
    # key: (position in the cloud's list, English name, entity id)
    "heat": (6, "Heat Generated Heating", "sensor.wp_heat_generated_heating"),
    "elec": (2, "Consumed Electrical Energy Heating", "sensor.wp_consumed_heating"),
    "env": (5, "Earned Environment Energy Heating", "sensor.wp_earned_heating"),
}
NOW = datetime(2026, 1, 15, 6, 10, 30, tzinfo=UTC)
FIRST = datetime(2026, 1, 15, 3, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


def unique_id(key: str) -> str:
    return f"mypyllant_{SYSTEM}_{DEVICE}_{SERIES[key][0]}_0"


def statistic_id(key: str) -> str:
    return f"mypyllant:{unique_id(key)}".lower().replace("-", "_")


def write_hours(
    hass: HomeAssistant, key: str, wh: list[float], first: datetime
) -> None:
    """Hourly sums in Wh as mypyllant writes them (only completed hours)."""
    total = 0.0
    rows = []
    for n, value in enumerate(wh):
        total += value
        rows.append(StatisticData(start=first + timedelta(hours=n), sum=total))
    async_add_external_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=None,
            source="mypyllant",
            statistic_id=statistic_id(key),
            unit_class="energy",
            unit_of_measurement="Wh",
        ),
        rows,
    )


def register(hass: HomeAssistant) -> None:
    registry = er.async_get(hass)
    for key, (_, name, entity_id) in SERIES.items():
        registry.async_get_or_create(
            "sensor",
            "mypyllant",
            unique_id(key),
            suggested_object_id=entity_id.removeprefix("sensor."),
            original_name=NAME + name,
        )
        hass.states.async_set(
            entity_id,
            "0",
            {
                "unit_of_measurement": "Wh",
                "device_class": "energy",
                "state_class": "total_increasing",
            },
        )


def value(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> float:
    found = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert found, key
    return float(hass.states.get(found).state)


@pytest.mark.freeze_time(NOW)
async def test_hours_from_the_source_statistics(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    # 03:00 to 06:00 UTC: 3 kWh heat for 1 kWh electricity per hour.
    write_hours(hass, "heat", [3000.0] * 3, FIRST)
    write_hours(hass, "elec", [1000.0] * 3, FIRST)
    await async_wait_recording_done(hass)
    register(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data={
            CONF_NAME: "WP",
            CONF_TEMPLATE: "mypyllant",
            CONF_ENTITIES: {
                "heat_heating": SERIES["heat"][2],
                "elec_heating": SERIES["elec"][2],
                # Chosen by hand, not mapped by the template (a series of
                # environmental yield, without statistics): no reason to stop.
                "aux_dhw": SERIES["env"][2],
            },
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = entry.runtime_data

    # The past hours are in the month (backfill), and booking goes on at 06:00.
    assert runtime.booked_until == FIRST + timedelta(hours=3)
    assert value(hass, entry, "ratio_heating_month") == pytest.approx(3.0)

    # The next fetch of mypyllant writes the hour 06:00-07:00 (in Wh).
    write_hours(hass, "heat", [3000.0] * 3 + [4000.0], FIRST)
    write_hours(hass, "elec", [1000.0] * 4, FIRST)
    await async_wait_recording_done(hass)
    freezer.move_to(datetime(2026, 1, 15, 7, 2, 0, tzinfo=UTC))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    await hass.async_block_till_done()

    assert runtime.booked_until == FIRST + timedelta(hours=4)
    assert value(hass, entry, "heat_heating") == pytest.approx(4.0)  # kWh, not Wh
    assert value(hass, entry, "electricity_heating") == pytest.approx(1.0)
    assert value(hass, entry, "ratio_heating_month") == pytest.approx(13 / 4)
    # No compressor: no cycling.
    found = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_starts_today"
    )
    assert found is None

    # mypyllant starts its sum anew after a week without a fetch: the first
    # row has a huge negative change. It is passed over, nothing is booked.
    write_hours(hass, "heat", [3000.0] * 4 + [-40_000_000.0, 3000.0], FIRST)
    write_hours(hass, "elec", [1000.0] * 4 + [-12_000_000.0, 1000.0], FIRST)
    await async_wait_recording_done(hass)
    freezer.move_to(datetime(2026, 1, 15, 9, 2, 0, tzinfo=UTC))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    await hass.async_block_till_done()
    assert runtime.booked_until == FIRST + timedelta(hours=6)
    assert value(hass, entry, "heat_heating") == pytest.approx(7.0)
    assert value(hass, entry, "electricity_heating") == pytest.approx(2.0)
    assert value(hass, entry, "standby") == 0
