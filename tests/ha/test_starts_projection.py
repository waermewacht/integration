"""Starts per year projected from 7 days, against the Fraunhofer field test:
attributes of "Starts today", never a reason for "cycling"."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.waermewacht.const import DOMAIN
from custom_components.waermewacht.runs import Run

from .test_init import START, entity_id, setup, state, tick


def attributes(hass: HomeAssistant, entry) -> dict:
    current = hass.states.get(entity_id(hass, entry, "starts_today"))
    assert current is not None
    return dict(current.attributes)


def runs_per_day(first_day: datetime, days: int, per_day: int) -> list[dict]:
    """Runs of 15 minutes (neither short nor critical), `per_day` a day."""
    result = []
    for day in range(days):
        midnight = first_day + timedelta(days=day)
        for i in range(per_day):
            start = midnight + timedelta(minutes=30 + i * 1440 // per_day)
            run = Run(start=start, end=start + timedelta(minutes=15))
            result.append(run.as_dict())
    return result


@pytest.mark.freeze_time(START)
async def test_projection_needs_seven_days(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    await tick(hass, freezer, 1)
    found = attributes(hass, entry)
    assert found["starts_per_year_projected"] is None
    assert found["starts_field_class"] is None
    assert found["starts_7d_reason"] == "too_few_days"
    assert found["starts_7d_days"] == 0


@pytest.mark.freeze_time(START)
async def test_projection_from_stored_runs(
    hass: HomeAssistant, hass_storage: dict, freezer: FrozenDateTimeFactory
) -> None:
    """Books of 0.4.5 (no observation start): the earliest run stands in."""
    entry = await setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    live = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    live["tracker"].pop("observed_since", None)
    local_today = dt_util.as_local(START).replace(hour=0, minute=0, second=0)
    first = dt_util.as_utc(local_today - timedelta(days=8))
    # 8 days before today with 20 starts a day: 7 of them in the window.
    hass_storage[f"{DOMAIN}.{entry.entry_id}.history"]["data"]["runs"] = runs_per_day(
        first, 8, 20
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass, freezer, 1)
    found = attributes(hass, entry)
    assert found["starts_per_day_7d"] == 20.0
    assert found["starts_per_year_projected"] == 7300
    assert found["starts_field_class"] == "top_10_percent"
    assert found["starts_7d_days"] == 7
    assert found["starts_7d_reason"] is None
    # An orientation only: the cycling check stays as it was.
    assert state(hass, entry, "cycling_problem") == "off"

    assert await hass.config_entries.async_unload(entry.entry_id)
    live = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    assert live["tracker"]["observed_since"] is not None
