"""The hours before the setup go into the statistics of the own energy
sensors, once per sensor: also for a sensor that appears later."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

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
    statistic_during_period,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.waermewacht.const import DOMAIN

from .conftest import ELEC_HEATING, ENERGY, HEAT_DHW, HEAT_HEATING, entry_data
from .test_init import START, entity_id


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


SETUP_HOUR = START.replace(minute=0, second=0)
HEATING = {"heat_heating": HEAT_HEATING, "elec_heating": ELEC_HEATING}


def source_statistics(
    hass: HomeAssistant,
    statistic_id: str,
    sums: list[float],
    first: datetime | None = None,
    states: list[float] | None = None,
) -> None:
    """Hourly sums of a source counter from `first`, by default for the
    hours just before START; the states are the sums unless given."""
    if states is None:
        states = sums
    if first is None:
        first = SETUP_HOUR - timedelta(hours=len(sums))
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
            StatisticData(start=first + timedelta(hours=i), sum=value, state=state)
            for i, (value, state) in enumerate(zip(sums, states, strict=True))
        ],
    )


async def sums(hass: HomeAssistant, statistic_id: str, hours: int = 1) -> list[float]:
    """Hourly sums from a day before START to `hours` after it."""
    rows = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        START - timedelta(days=1),
        START + timedelta(hours=hours),
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
    # The import is a background task: wait for it, then for the recorder.
    await hass.async_block_till_done(wait_background_tasks=True)
    await async_wait_recording_done(hass)

    # The sums end at 0, where the sensor's own recorded sum starts.
    assert await sums(hass, entity_id(hass, entry, "heat_heating")) == [-5.0, -3.0, 0.0]
    assert await sums(hass, entity_id(hass, entry, "electricity_heating")) == [
        -1.25,
        -0.75,
        0.0,
    ]
    assert entry.runtime_data.history_imported

    # 15 minutes later the sums are shifted to start at 0: Home Assistant
    # takes the change of the earliest row against 0.
    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    await async_wait_recording_done(hass)
    assert await sums(hass, entity_id(hass, entry, "heat_heating")) == [1.0, 3.0, 6.0]
    assert await sums(hass, entity_id(hass, entry, "electricity_heating")) == [
        0.25,
        0.75,
        1.5,
    ]
    assert entry.runtime_data.history_adjusted

    # Once only: a reload neither imports nor shifts again.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    await async_wait_recording_done(hass)
    assert await sums(hass, entity_id(hass, entry, "heat_heating")) == [1.0, 3.0, 6.0]


async def settle(hass: HomeAssistant) -> None:
    """Wait for the import (a background task), then for the recorder."""
    await hass.async_block_till_done(wait_background_tasks=True)
    await async_wait_recording_done(hass)


async def set_up_heating(hass: HomeAssistant) -> MockConfigEntry:
    """An entry with heat and electricity of heating, whose source has the
    three hours before START."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    source_statistics(hass, HEAT_HEATING, [1.0, 3.0, 6.0])
    source_statistics(hass, ELEC_HEATING, [0.25, 0.75, 1.5])
    await async_wait_recording_done(hass)
    hass.states.async_set(HEAT_HEATING, "6.0", ENERGY)
    hass.states.async_set(ELEC_HEATING, "1.5", ENERGY)
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(entities=HEATING)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    return entry


async def shift(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """16 minutes on: the imported sums are shifted."""
    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await settle(hass)


@pytest.mark.freeze_time(START)
async def test_sensor_added_later_gets_its_past(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A heat meter for hot water added three hours after the setup: its
    sensor counts from then on, its statistics get the hours before the
    setup and those between the setup and Reconfigure, once."""
    entry = await set_up_heating(hass)
    heat_heating = entity_id(hass, entry, "heat_heating")
    assert (await sums(hass, heat_heating))[:3] == [-5.0, -3.0, 0.0]
    freezer.tick(timedelta(hours=3))
    async_fire_time_changed(hass)
    await settle(hass)
    # Two hours before the setup, three after it (2, 1, 2, 1, 2 kWh).
    source_statistics(
        hass,
        HEAT_DHW,
        [2.0, 3.0, 5.0, 6.0, 8.0],
        first=SETUP_HOUR - timedelta(hours=2),
    )
    await async_wait_recording_done(hass)
    hass.states.async_set(HEAT_DHW, "8.0", ENERGY)

    hass.config_entries.async_update_entry(
        entry, data=entry_data(entities={**HEATING, "heat_dhw": HEAT_DHW})
    )
    await settle(hass)
    runtime = entry.runtime_data
    heat_dhw = entity_id(hass, entry, "heat_dhw")
    assert hass.states.get(heat_dhw).state == "0.0"  # counts from now on
    # Up to the hour of Reconfigure, ending at 0 where its own sum starts.
    assert (await sums(hass, heat_dhw, hours=4))[:5] == [-6.0, -5.0, -3.0, -2.0, 0.0]
    assert "heat_dhw" in runtime.history_done
    assert set(runtime.history_shift) == {"heat_dhw"}
    # The sensors of the setup are left as they are.
    assert (await sums(hass, heat_heating))[:3] == [1.0, 3.0, 6.0]

    await shift(hass, freezer)
    assert (await sums(hass, heat_dhw, hours=4))[:5] == [2.0, 3.0, 5.0, 6.0, 8.0]
    assert runtime.history_adjusted

    # Once only: the next load neither imports nor shifts again.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await settle(hass)
    assert not entry.runtime_data.history_shift
    await shift(hass, freezer)
    assert (await sums(hass, heat_dhw, hours=4))[:5] == [2.0, 3.0, 5.0, 6.0, 8.0]
    assert (await sums(hass, heat_heating))[:3] == [1.0, 3.0, 6.0]


@pytest.mark.freeze_time(START)
async def test_update_from_one_flag_imports_only_the_new_sensor(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    """0.4.4 and older kept one flag for the entry. The sensors of the setup
    are not imported again (a pending shift still happens); a sensor that
    appears now gets its past."""
    entry = await set_up_heating(hass)
    heat_heating = entity_id(hass, entry, "heat_heating")
    assert await hass.config_entries.async_unload(entry.entry_id)
    books = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    assert set(books["history_shift"]) == {"heat_heating", "electricity_heating"}
    # The books of 0.4.4, saved before the shift.
    del books["history_done"], books["history_shift"]
    assert books["history_imported"]
    assert not books["history_adjusted"]

    source_statistics(hass, HEAT_DHW, [2.0, 3.0])
    await async_wait_recording_done(hass)
    hass.states.async_set(HEAT_DHW, "3.0", ENERGY)
    hass.config_entries.async_update_entry(
        entry, data=entry_data(entities={**HEATING, "heat_dhw": HEAT_DHW})
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    runtime = entry.runtime_data
    heat_dhw = entity_id(hass, entry, "heat_dhw")
    assert await sums(hass, heat_heating) == [-5.0, -3.0, 0.0]  # not again
    assert await sums(hass, heat_dhw) == [-1.0, 0.0]
    assert {"heat_heating", "electricity_heating", "heat_dhw"} <= runtime.history_done
    assert set(runtime.history_shift) == {
        "heat_heating",
        "electricity_heating",
        "heat_dhw",
    }

    await shift(hass, freezer)
    assert await sums(hass, heat_heating) == [1.0, 3.0, 6.0]
    assert await sums(hass, heat_dhw) == [2.0, 3.0]
    assert runtime.history_adjusted
    assert await hass.config_entries.async_unload(entry.entry_id)
    books = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    assert {"heat_heating", "heat_dhw"} <= set(books["history_done"])
    assert books["history_shift"] == {}


# Midnight of 01.01.2026 in Berlin (23:00 UTC) and of 01.02.2026.
JANUARY = datetime(2025, 12, 31, 23, 0, tzinfo=UTC)
FEBRUARY = datetime(2026, 1, 31, 23, 0, tzinfo=UTC)
DEC_31 = datetime(2025, 12, 31, 4, 0, tzinfo=UTC)
JAN_1 = datetime(2026, 1, 1, 4, 0, tzinfo=UTC)


async def month_change(hass: HomeAssistant, statistic_id: str) -> float | None:
    """Change of January as Home Assistant's statistics cards ask for it."""
    found = await hass.async_add_executor_job(
        statistic_during_period, hass, JANUARY, FEBRUARY, statistic_id, {"change"}, None
    )
    return found.get("change")


async def hourly_rows(hass: HomeAssistant, statistic_id: str) -> dict[datetime, float]:
    rows = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        DEC_31 - timedelta(days=1),
        START,
        {statistic_id},
        "hour",
        None,
        {"sum"},
    )
    return {
        datetime.fromtimestamp(r["start"], UTC)
        if not isinstance(r["start"], datetime)
        else r["start"]: r["sum"]
        for r in rows.get(statistic_id, [])
    }


@pytest.mark.freeze_time(START)
async def test_imported_hours_are_dense(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Energy on 31.12. and 01.01. only (as found in a real system): the
    import writes every hour up to the setup, so January's change in Home
    Assistant's own period sum keeps the first hour of January."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    first = DEC_31 - timedelta(hours=2)
    count = int((SETUP_HOUR - first) / timedelta(hours=1))
    hours = [first + timedelta(hours=i) for i in range(count)]

    def sums_of(kwh_31: float, kwh_1: float) -> list[float]:
        return [
            (kwh_31 if h >= DEC_31 else 0.0) + (kwh_1 if h >= JAN_1 else 0.0)
            for h in hours
        ]

    source_statistics(hass, HEAT_HEATING, sums_of(6.08, 6.60), first)
    source_statistics(hass, ELEC_HEATING, sums_of(2.0, 2.2), first)
    await async_wait_recording_done(hass)
    hass.states.async_set(HEAT_HEATING, "12.68", ENERGY)
    hass.states.async_set(ELEC_HEATING, "4.2", ENERGY)
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(entities=HEATING)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)

    heat = entity_id(hass, entry, "heat_heating")
    rows = await hourly_rows(hass, heat)
    # From the first hour with energy up to the setup hour, every hour.
    assert min(rows) == DEC_31
    assert len(rows) == int((SETUP_HOUR - DEC_31) / timedelta(hours=1))
    assert rows[JANUARY - timedelta(hours=1)] == pytest.approx(-6.60)
    assert await month_change(hass, heat) == pytest.approx(6.60)


@pytest.mark.freeze_time(START)
async def test_gaps_of_older_imports_are_filled_once(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Rows an import before 0.4.6 left out are added once, with the sum of
    the row before; existing sums stay as they are."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(HEAT_HEATING, "12.68", ENERGY)
    hass.states.async_set(ELEC_HEATING, "4.2", ENERGY)
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(entities=HEATING)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    heat = entity_id(hass, entry, "heat_heating")
    # As 0.4.5 imported it: hours with energy only.
    async_import_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=None,
            source="recorder",
            statistic_id=heat,
            unit_class="energy",
            unit_of_measurement="kWh",
        ),
        [
            StatisticData(start=DEC_31, sum=-6.60),
            StatisticData(start=JAN_1, sum=0.0),
        ],
    )
    await async_wait_recording_done(hass)
    runtime = entry.runtime_data
    assert not runtime.history_dense

    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await settle(hass)
    assert runtime.history_dense
    assert runtime.history_gaps_filled == {"heat_heating": 23}
    rows = await hourly_rows(hass, heat)
    assert rows[DEC_31] == pytest.approx(-6.60)  # unchanged
    assert rows[JAN_1] == pytest.approx(0.0)
    # Every hour from 31.12. 04:00 to 01.01. 04:00 (Home Assistant may
    # have compiled rows of its own after the setup: not counted here).
    between = {h: v for h, v in rows.items() if DEC_31 <= h <= JAN_1}
    assert len(between) == 25, sorted(rows)
    assert all(v == pytest.approx(-6.60) for h, v in between.items() if h < JAN_1)
    assert rows[JANUARY - timedelta(hours=1)] == pytest.approx(-6.60)
    assert await month_change(hass, heat) == pytest.approx(6.60)

    # A second run finds nothing to add.
    await runtime._async_fill_history_gaps()
    await settle(hass)
    assert runtime.history_gaps_filled == {}
    assert len(await hourly_rows(hass, heat)) == len(rows)


def ha_sums(states: list[float], first_sum: float) -> list[float]:
    """Sums as Home Assistant books a total_increasing meter: a fall by more
    than 10 % is a new cycle and adds the whole new reading."""
    result = [first_sum]
    for before, after in pairwise(states):
        result.append(result[-1] + (after if after < before * 0.9 else after - before))
    return result


@pytest.mark.freeze_time(START)
@pytest.mark.parametrize(
    ("states", "kept"),
    [
        # A real meter: Wh as kWh for one reading, back as a "new cycle" of
        # 110 kWh (above the bound of 75 kWh per hour).
        ([107.0, 107.5, 109851.5, 110.131, 110.6], 0.25 + 0.5 + 0.469),
        # The same with a small reading: the fall back adds 7.9 kWh only.
        ([7.0, 7.5, 7500.0, 7.9, 8.2], 0.25 + 0.5 + 0.3),
    ],
)
async def test_look_back_leaves_out_a_unit_glitch(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    states: list[float],
    kept: float,
) -> None:
    """The jump and the hour falling back are left out of the history."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    first = SETUP_HOUR - timedelta(hours=5)
    source_statistics(hass, HEAT_HEATING, [1.0, 3.0, 6.0, 9.0, 12.0], first)
    source_statistics(hass, ELEC_HEATING, ha_sums(states, 0.25), first, states)
    await async_wait_recording_done(hass)
    hass.states.async_set(HEAT_HEATING, "12.0", ENERGY)
    hass.states.async_set(ELEC_HEATING, str(states[-1]), ENERGY)
    entry = MockConfigEntry(
        domain=DOMAIN, title="WP", data=entry_data(entities=HEATING)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    await shift(hass, freezer)
    electricity = await sums(hass, entity_id(hass, entry, "electricity_heating"))
    assert electricity[-1] == pytest.approx(kept)
    heat = await sums(hass, entity_id(hass, entry, "heat_heating"))
    assert heat[-1] == pytest.approx(12.0)
