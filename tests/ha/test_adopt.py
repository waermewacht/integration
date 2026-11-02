"""Signals a template learned after setup: taken over once the source has
them; counters moved to the form the template prefers (adopt.py)."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waermewacht.const import (
    CONF_ENTITIES,
    CONF_HISTORY,
    CONF_KNOWN_SIGNALS,
    CONF_NAME,
    CONF_TEMPLATE,
    DOMAIN,
)
from custom_components.waermewacht.energy import Kind
from custom_components.waermewacht.model import Mode
from custom_components.waermewacht.profiles import BOSCH_HOMECOM

from .conftest import ENERGY

GATEWAY = "101234567"


def add(
    hass: HomeAssistant, platform: str, unique_id: str, state: str, **attrs: Any
) -> str:
    """A registry entry with a state; returns its entity id."""
    entry = er.async_get(hass).async_get_or_create(
        "binary_sensor" if unique_id.endswith("hpcompon") else "sensor",
        platform,
        unique_id,
        suggested_object_id=unique_id.replace("-", "_"),
    )
    hass.states.async_set(entry.entity_id, state, attrs)
    return entry.entity_id


def homecom(hass: HomeAssistant) -> dict[str, str]:
    return {
        "heat_heating": add(
            hass, "bosch_homecom", f"{GATEWAY}-heat_produced_ch", "8.0", **ENERGY
        ),
        "elec_heating": add(
            hass, "bosch_homecom", f"{GATEWAY}-energy_compressor_ch", "2.0", **ENERGY
        ),
        "compressor": add(
            hass, "bosch_homecom", f"{GATEWAY}-local_compressor_speed", "0"
        ),
    }


def status(hass: HomeAssistant) -> str:
    return add(hass, "bosch_homecom", f"{GATEWAY}-compressor_status", "off")


async def set_up(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_homecom_entry_from_0_2_5_takes_over_the_status(
    hass: HomeAssistant,
) -> None:
    """Up to 0.2.5 an entry counted the compressor status as known although
    bosch_homecom had none yet; the migration to 1.2 forgets it again."""
    entities = homecom(hass)
    found = status(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        minor_version=1,
        data={
            CONF_NAME: "WP",
            CONF_TEMPLATE: "bosch_homecom",
            CONF_ENTITIES: entities,
            CONF_KNOWN_SIGNALS: sorted(s.value for s in BOSCH_HOMECOM.signals),
        },
    )
    await set_up(hass, entry)
    assert entry.minor_version == 2
    assert entry.data[CONF_ENTITIES]["activity"] == found


async def test_a_signal_the_source_adds_later_is_taken_over(
    hass: HomeAssistant,
) -> None:
    entities = homecom(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        minor_version=2,
        data={
            CONF_NAME: "WP",
            CONF_TEMPLATE: "bosch_homecom",
            CONF_ENTITIES: entities,
            CONF_KNOWN_SIGNALS: sorted(entities),
        },
    )
    await set_up(hass, entry)
    assert "activity" not in entry.data[CONF_ENTITIES]
    assert "activity" not in entry.data[CONF_KNOWN_SIGNALS]

    found = status(hass)  # bosch_homecom 1.6.1
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.data[CONF_ENTITIES]["activity"] == found
    assert "activity" in entry.data[CONF_KNOWN_SIGNALS]


def ems_esp(hass: HomeAssistant) -> dict[str, str]:
    return {
        "heat_heating": add(hass, "mqtt", "boiler_nrgheat", "1000.0", **ENERGY),
        "elec_heating": add(hass, "mqtt", "boiler_meterheat", "300.0", **ENERGY),
        "compressor": add(hass, "mqtt", "boiler_hpcompon", "off"),
        "activity": add(hass, "mqtt", "boiler_hpactivity", "aus"),
        "aux_heating": add(
            hass, "mqtt", "boiler_auxelecheatnrgconsheating", "10", **ENERGY
        ),
    }


async def test_backup_heater_moves_to_the_counter_in_hundredths(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """EMS-ESP 3.9.0-dev.23: the entry moves from the whole-kWh counter to
    the 0.01 kWh one. The last whole-kWh reading is no baseline for it
    (10 → 10.4 would book 0.4 kWh of backup heater); the books of 0.2.5 do
    not name the counter's entity yet."""
    entities = ems_esp(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WP",
        data={CONF_NAME: "WP", CONF_TEMPLATE: "ems_esp", CONF_ENTITIES: entities},
    )
    await set_up(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    books = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    assert books["counter_entities"]["aux_heating"] == entities["aux_heating"]
    assert books["counters"]["aux_heating"]["last_value"] == 10
    del books["counter_entities"]

    hundredths = add(hass, "mqtt", "boiler_metereheatheat", "10.4", **ENERGY)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.data[CONF_ENTITIES]["aux_heating"] == hundredths
    assert entry.data[CONF_HISTORY][hundredths] == [entities["aux_heating"]]
    runtime = entry.runtime_data
    assert runtime.totals.get(Kind.AUX, Mode.HEATING) == 0

    hass.states.async_set(hundredths, "10.6", ENERGY)
    await hass.async_block_till_done()
    assert runtime.totals.get(Kind.AUX, Mode.HEATING) == pytest.approx(0.2)
