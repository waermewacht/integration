"""Oil boiler (a gas boiler entry with fuel oil): litres, boiler type, price,
tank levels with refills."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

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
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.waermewacht.const import (
    CONF_BOILER_TYPE,
    CONF_DESIGN_TEMP,
    CONF_ENTITIES,
    CONF_FUEL,
    CONF_KIND,
    CONF_NAME,
    CONF_OIL_PRICE,
    DOMAIN,
)
from custom_components.waermewacht.oil import KWH_PER_LITRE_HS

from .conftest import TEMPERATURE
from .test_gas import NOW, OUTDOOR, SUMMER, WINTER, gas_kwh, winter_and_summer_readings

OIL = "sensor.oil_meter"
LITRES = {
    "unit_of_measurement": "L",
    "device_class": "volume",
    "state_class": "total_increasing",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


def import_statistics(hass: HomeAssistant) -> None:
    """The house of test_gas (100 W/K, η 0.87) with an oil meter in litres."""
    tz = dt_util.get_default_time_zone()
    oil: list[StatisticData] = []
    outdoor: list[StatisticData] = []
    total = 0.0
    for day, mean in [*SUMMER, *WINTER]:
        start = datetime.combine(day, datetime.min.time(), tzinfo=tz).astimezone(UTC)
        for hour in range(24):
            at = start + timedelta(hours=hour)
            total += gas_kwh(mean) / KWH_PER_LITRE_HS
            oil.append(StatisticData(start=at, state=total, sum=total))
            outdoor.append(StatisticData(start=at, mean=mean, min=mean, max=mean))
    for statistic_id, unit_class, unit, rows, mean_type in (
        (OIL, "volume", "L", oil, StatisticMeanType.NONE),
        (OUTDOOR, "temperature", "°C", outdoor, StatisticMeanType.ARITHMETIC),
    ):
        async_import_statistics(
            hass,
            StatisticMetaData(
                mean_type=mean_type,
                has_sum=mean_type is StatisticMeanType.NONE,
                name=None,
                source="recorder",
                statistic_id=statistic_id,
                unit_class=unit_class,
                unit_of_measurement=unit,
            ),
            rows,
        )


def entity(hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str):
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id, key
    return er.async_get(hass).async_get(entity_id), hass.states.get(entity_id)


@pytest.mark.freeze_time(NOW)
async def test_oil_boiler_from_litres(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    import_statistics(hass)
    await async_wait_recording_done(hass)
    hass.states.async_set(OIL, "4321", LITRES)
    hass.states.async_set(OUTDOOR, "3.0", TEMPERATURE)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Öl",
        data={
            CONF_NAME: "Öl",
            CONF_KIND: "gas",
            CONF_FUEL: "oil",
            CONF_ENTITIES: {"gas_total": OIL, "outdoor_temp": OUTDOOR},
        },
        options={
            CONF_BOILER_TYPE: "condensing",  # 0.87, as the house of test_gas
            CONF_DESIGN_TEMP: -12.0,
            CONF_OIL_PRICE: 106.6,  # €/100 l = 0.10 €/kWh
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    _, per_kelvin = entity(hass, entry, "sensor", "gas_heat_load_per_kelvin")
    assert float(per_kelvin.state) == pytest.approx(100, abs=1)
    assert per_kelvin.attributes["boiler_efficiency"] == 0.87
    kwh = sum(gas_kwh(mean) * 24 for _, mean in [*SUMMER, *WINTER])
    registry, year = entity(hass, entry, "sensor", "gas_consumption_year")
    assert registry.translation_key == "oil_consumption_year"
    assert float(year.state) == pytest.approx(kwh, rel=1e-3)
    assert year.attributes["litres"] == round(kwh / KWH_PER_LITRE_HS)
    registry, cost = entity(hass, entry, "sensor", "gas_cost_year")
    assert registry.translation_key == "oil_cost_year"
    assert float(cost.state) == pytest.approx(kwh * 0.10, rel=1e-3)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_oil_setup_options_reconfigure(hass: HomeAssistant) -> None:
    hass.states.async_set(OIL, "4321", LITRES)
    hass.states.async_set("sensor.gas", "12", {**LITRES, "unit_of_measurement": "m³"})
    hass.states.async_set(OUTDOOR, "3.0", TEMPERATURE)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Wärmepumpe", "source": "oil"}
    )
    assert result["step_id"] == "oil"
    for values, error in (
        ({"boiler_type": "condensing"}, "oil_none"),
        ({"gas_total": "sensor.gas", "boiler_type": "condensing"}, "oil_unit"),
        ({"gas_total": OIL, "boiler_type": "custom"}, "boiler_efficiency_missing"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"outdoor_temp": OUTDOOR, **values}
        )
        assert result["errors"] == {"base": error}, values
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"gas_total": OIL, "outdoor_temp": OUTDOOR, "boiler_type": "low_temperature"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Ölheizung"
    assert result["data"] == {
        CONF_NAME: "Ölheizung",
        CONF_KIND: "gas",
        CONF_FUEL: "oil",
        CONF_ENTITIES: {"gas_total": OIL, "outdoor_temp": OUTDOOR},
    }
    assert result["options"] == {CONF_BOILER_TYPE: "low_temperature"}
    entry = result["result"]
    await hass.async_block_till_done()
    assert entry.runtime_data.efficiency == 0.79
    assert entry.runtime_data.kwh_per_litre == KWH_PER_LITRE_HS

    # Options: an own value needs the efficiency.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "oil"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"boiler_type": "custom", "kwh_per_litre": 10.5}
    )
    assert result["errors"] == {"base": "boiler_efficiency_missing"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "boiler_type": "custom",
            "boiler_efficiency": 0.82,
            "kwh_per_litre": 10.5,
            "oil_price": 105.0,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    runtime = entry.runtime_data
    assert runtime.efficiency == 0.82
    assert runtime.kwh_per_litre == 10.5
    assert runtime.gas_price == pytest.approx(1.05 / 10.5)

    # Reconfigure: the oil form again; the options stay.
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "oil"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"gas_heating": OIL, "outdoor_temp": OUTDOOR, "boiler_type": "condensing"},
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_FUEL] == "oil"
    assert entry.data[CONF_ENTITIES] == {"gas_heating": OIL, "outdoor_temp": OUTDOOR}
    assert entry.options[CONF_BOILER_TYPE] == "condensing"
    assert entry.options[CONF_OIL_PRICE] == 105.0
    await hass.async_block_till_done()

    # The same meter again: the oil text.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Öl 2", "source": "oil"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"gas_heating": OIL, "outdoor_temp": OUTDOOR, "boiler_type": "condensing"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "oil_already_configured"
    assert await hass.config_entries.async_unload(entry.entry_id)


REFILL_DAY = date(2025, 12, 17)  # between the readings of 15.12. and 22.12.
REFILL = 2000.0


@pytest.mark.freeze_time(NOW)
async def test_oil_tank_levels_with_refill(hass: HomeAssistant) -> None:
    """Tank levels by hand: the level drops with the oil used and jumps by a
    refill; the refill must come in before the level after it."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    import_statistics(hass)  # the outdoor temperature (and an unused meter)
    await async_wait_recording_done(hass)
    hass.states.async_set(OUTDOOR, "3.0", TEMPERATURE)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Öl", "source": "oil"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"outdoor_temp": OUTDOOR, "manual_unit": "tank", "boiler_type": "condensing"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    await hass.async_block_till_done()
    entry.runtime_data.design_temp = -12.0

    tz = dt_util.get_default_time_zone()
    refill_at = datetime.combine(REFILL_DAY, datetime.min.time(), tzinfo=tz)
    readings = winter_and_summer_readings()  # a gas meter in kWh from 1000
    levels = [
        (
            at,
            3000.0
            - (kwh - 1000.0) / KWH_PER_LITRE_HS
            + (REFILL if at > refill_at else 0),
        )
        for at, kwh in readings
    ]

    async def add_level(at: datetime, level: float) -> None:
        await hass.services.async_call(
            DOMAIN,
            "add_gas_reading",
            {"config_entry": entry.entry_id, "reading": level, "time": at.isoformat()},
            blocking=True,
        )

    before = [(at, v) for at, v in levels if at < refill_at]
    after = [(at, v) for at, v in levels if at > refill_at]
    for at, level in before:
        await add_level(at, level)
    # The level after the refill, before the refill is known: refused.
    with pytest.raises(ServiceValidationError) as err:
        await add_level(*after[0])
    assert err.value.translation_key == "tank_rising"
    await hass.services.async_call(
        DOMAIN,
        "add_oil_refill",
        {
            "config_entry": entry.entry_id,
            "litres": REFILL,
            "time": refill_at.isoformat(),
        },
        blocking=True,
    )
    for at, level in after:
        await add_level(at, level)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    _, per_kelvin = entity(hass, entry, "sensor", "gas_heat_load_per_kelvin")
    assert per_kelvin.state != "unknown", per_kelvin.attributes
    assert float(per_kelvin.state) == pytest.approx(100, abs=2)
    _, dhw = entity(hass, entry, "sensor", "gas_dhw_share")
    assert dhw.attributes["summer_base_kwh_per_day"] == pytest.approx(6.0, rel=1e-3)

    # The numbers: tank level (last level) and refill (last refill).
    registry, level = entity(hass, entry, "number", "gas_reading")
    assert registry.translation_key == "tank_level"
    assert float(level.state) == pytest.approx(levels[-1][1], abs=0.6)
    assert level.attributes["unit_of_measurement"] == "L"
    _, refill = entity(hass, entry, "number", "oil_refill")
    assert float(refill.state) == REFILL
    assert refill.attributes["refills"] == 1

    # Removing the refill would leave the levels rising: refused.
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "remove_oil_refill",
            {"config_entry": entry.entry_id, "time": refill_at.isoformat()},
            blocking=True,
        )
    assert err.value.translation_key == "tank_rising"
    assert await hass.config_entries.async_unload(entry.entry_id)
