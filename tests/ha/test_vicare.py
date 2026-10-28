"""Viessmann ViCare: cycling and electricity without heat, days in UTC,
the E3 phase that carries no activity, and the Vitotronic defrost."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.const import (
    CONF_ENTITIES,
    CONF_NAME,
    CONF_TEMPLATE,
    DOMAIN,
)

from .conftest import ENERGY
from .test_init import tick

# 15.01.2026 07:00:30 CET.
START = datetime(2026, 1, 15, 6, 0, 30, tzinfo=UTC)
S, B = "sensor.e3_vitocal_", "binary_sensor.e3_vitocal_"
ELEC = S + "heating_electricity_consumption_today"
ELEC_DHW = S + "dhw_electricity_consumption_today"
COMPRESSOR = B + "compressor"
PHASE = S + "compressor_phase"
STARTS = S + "compressor_starts"


async def setup(
    hass: HomeAssistant, entities: dict[str, str], options: dict | None = None
) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data={CONF_NAME: "WP", CONF_TEMPLATE: "vicare", CONF_ENTITIES: entities},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def keys(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    prefix = f"{entry.entry_id}_"
    return {
        e.unique_id.removeprefix(prefix)
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


def value(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> float:
    found = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert found, key
    return float(hass.states.get(found).state)


@pytest.mark.freeze_time(START)
async def test_e3_cycling_and_electricity_without_heat(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set(ELEC, "6.3", ENERGY)
    hass.states.async_set(ELEC_DHW, "1.9", ENERGY)
    hass.states.async_set(COMPRESSOR, "off")
    hass.states.async_set(STARTS, "2140", {"state_class": "total_increasing"})
    entry = await setup(
        hass,
        {
            "elec_heating": ELEC,
            "elec_dhw": ELEC_DHW,
            "compressor": COMPRESSOR,
            "starts_total": STARTS,
        },
        {"electricity_price": 30.0},
    )
    found = keys(hass, entry)
    assert {"electricity_heating", "starts_today", "cycling_problem"} <= found
    assert {"cost_month", "cost_season"} <= found
    for absent in (
        "standby",
        "heat_heating",
        "ratio_heating_month",
        "heat_cost_season",
    ):
        assert absent not in found, absent

    # A run, then the cloud's next value: running electricity, no standby.
    hass.states.async_set(COMPRESSOR, "on")
    await tick(hass, freezer, 40)
    hass.states.async_set(COMPRESSOR, "off")
    await tick(hass, freezer, 20)
    hass.states.async_set(ELEC, "6.8", ENERGY)
    await tick(hass, freezer, 1)
    await tick(hass, freezer, 150)  # past the wait for heat of the same fetch
    assert value(hass, entry, "electricity_heating") == pytest.approx(0.5)
    assert value(hass, entry, "starts_today") == 1

    # The cloud starts its day at midnight UTC (01:00 here): the drop is a
    # new day, its first value counts in full.
    freezer.move_to(datetime(2026, 1, 16, 0, 0, 30, tzinfo=UTC))
    hass.states.async_set(ELEC, "0.4", ENERGY)
    await tick(hass, freezer, 1)
    await tick(hass, freezer, 150)
    assert value(hass, entry, "electricity_heating") == pytest.approx(0.9)


@pytest.mark.freeze_time(START)
async def test_e3_phase_without_activity_raises_an_issue(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set(COMPRESSOR, "off")
    hass.states.async_set(PHASE, "off")
    entry = await setup(hass, {"compressor": COMPRESSOR, "activity": PHASE})
    hass.states.async_set(PHASE, "ready")
    await tick(hass, freezer, 11)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{entry.entry_id}_activity_foreign"
    )
    assert issue is not None
    assert issue.translation_placeholders["entities"] == PHASE


@pytest.mark.freeze_time(START)
async def test_vitotronic_defrost_from_the_phase(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    compressor = "binary_sensor.vitocal_333g_compressor"
    phase = "sensor.vitocal_333g_compressor_phase"
    charging = "binary_sensor.vitocal_333g_dhw_charging"
    hass.states.async_set(compressor, "off")
    hass.states.async_set(phase, "pause")
    hass.states.async_set(charging, "off")
    entry = await setup(
        hass, {"compressor": compressor, "activity": phase, "dhw_flag": charging}
    )
    assert "electricity_heating" not in keys(hass, entry)
    hass.states.async_set(compressor, "on")
    hass.states.async_set(phase, "heating")
    await tick(hass, freezer, 30)
    hass.states.async_set(phase, "preparing_defrost")
    hass.states.async_set(charging, "on")  # a defrost beats the charging flag
    await tick(hass, freezer, 1)
    hass.states.async_set(phase, "defrost")
    await tick(hass, freezer, 4)
    hass.states.async_set(phase, "heating")
    hass.states.async_set(charging, "off")
    await tick(hass, freezer, 10)
    assert value(hass, entry, "defrosts_today") == 1
