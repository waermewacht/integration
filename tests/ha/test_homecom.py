"""Bosch HomeCom: day values of a cloud, standby per fetch, compressor speed."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.const import (
    CONF_ENTITIES,
    CONF_NAME,
    CONF_TEMPLATE,
    DOMAIN,
)

from .conftest import ENERGY
from .test_init import START, state, tick, value

BASE = "sensor.boschcom_k40_101234567_"
HEAT = BASE + "warme_erzeugt_heizung"
ELEC = BASE + "strom_kompressor_heizung"
HEAT_DHW = BASE + "warme_erzeugt_warmwasser"
ELEC_DHW = BASE + "strom_kompressor_warmwasser"
SPEED = BASE + "kompressordrehzahl"


def fetch(hass: HomeAssistant, elec: float, heat: float) -> None:
    """One cloud fetch: the electricity entity happens to update first."""
    hass.states.async_set(ELEC, str(elec), ENERGY)
    hass.states.async_set(HEAT, str(heat), ENERGY)


async def setup(hass: HomeAssistant) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    fetch(hass, 2.0, 8.0)
    hass.states.async_set(HEAT_DHW, "4.0", ENERGY)
    hass.states.async_set(ELEC_DHW, "1.5", ENERGY)
    hass.states.async_set(SPEED, "0", {"unit_of_measurement": "%"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data={
            CONF_NAME: "WP",
            CONF_TEMPLATE: "bosch_homecom",
            CONF_ENTITIES: {
                "heat_heating": HEAT,
                "elec_heating": ELEC,
                "heat_dhw": HEAT_DHW,
                "elec_dhw": ELEC_DHW,
                "compressor": SPEED,
            },
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.freeze_time(START)
async def test_standby_per_fetch_and_new_day(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)

    # A fetch with heat: the electricity came from a run, although the
    # compressor is off by now (the values are up to two hours late).
    fetch(hass, 2.5, 10.0)
    await tick(hass, freezer, 1)
    assert value(hass, entry, "electricity_heating") == pytest.approx(0.5)
    assert value(hass, entry, "heat_heating") == pytest.approx(2.0)
    assert value(hass, entry, "standby") == 0

    # An hour later only electricity: standby.
    await tick(hass, freezer, 60)
    hass.states.async_set(ELEC, "2.6", ENERGY)
    await tick(hass, freezer, 1)
    assert value(hass, entry, "electricity_heating") == pytest.approx(0.5)
    assert value(hass, entry, "standby") == pytest.approx(0.1)

    # First fetch after midnight: the day values start anew, and the new
    # day's value is energy, not a drop.
    freezer.move_to(START.replace(hour=23, minute=20))  # 00:20 local
    fetch(hass, 0.3, 1.2)
    await tick(hass, freezer, 1)
    assert value(hass, entry, "electricity_heating") == pytest.approx(0.8)
    assert value(hass, entry, "heat_heating") == pytest.approx(3.2)


@pytest.mark.freeze_time(START)
async def test_compressor_speed_counts_runs(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    hass.states.async_set(SPEED, "42")
    await tick(hass, freezer, 30)
    hass.states.async_set(SPEED, "unavailable")  # Home Assistant restart
    await tick(hass, freezer, 1)
    hass.states.async_set(SPEED, "38")
    await tick(hass, freezer, 20)
    hass.states.async_set(SPEED, "0")
    await tick(hass, freezer, 1)
    assert value(hass, entry, "starts_today") == 1
    assert value(hass, entry, "run_minutes_today") == pytest.approx(51, abs=0.1)
    # No activity: no defrost and no flow temperature sensors.
    for key in ("defrosts_today", "flow_temp_today", "spread_today"):
        with pytest.raises(AssertionError):
            state(hass, entry, key)
