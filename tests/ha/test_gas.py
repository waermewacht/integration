"""Gas boiler entry: setup, analysis from recorded statistics, actions, options."""

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
    CONF_CALORIFIC_VALUE,
    CONF_DESIGN_TEMP,
    CONF_ENTITIES,
    CONF_GAS_PRICE,
    CONF_KIND,
    CONF_NAME,
    CONF_Z_NUMBER,
    DOMAIN,
)

from .conftest import TEMPERATURE

GAS = "sensor.gas_meter"
OUTDOOR = "sensor.outdoor"
VOLUME = {
    "unit_of_measurement": "m³",
    "device_class": "gas",
    "state_class": "total_increasing",
}
ETA = 0.87
HS = 10.0  # kWh/m³, so 1 m³ = 10 kWh with Z = 1
DHW_PER_DAY = 6.0  # kWh gas
# 20 summer days at 20 °C, then 9 winter weeks from Monday 1.12.2025 at
# -6, -4, … 10 °C (a week each); now is 1.3.2026 (window 1.3.2025 - 28.2.2026).
SUMMER = [(date(2025, 7, 1) + timedelta(days=n), 20.0) for n in range(20)]
WINTER = [
    (date(2025, 12, 1) + timedelta(days=n), -6.0 + 2 * (n // 7)) for n in range(63)
]
NOW = datetime(2026, 3, 1, 11, tzinfo=UTC)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


def gas_kwh(mean: float) -> float:
    """Gas per hour of a house with 100 W/K and a heating limit of 15 °C."""
    return max(0.0, 0.1 * (15.0 - mean)) / ETA + DHW_PER_DAY / 24


def import_statistics(hass: HomeAssistant) -> None:
    tz = dt_util.get_default_time_zone()
    gas: list[StatisticData] = []
    outdoor: list[StatisticData] = []
    total = 0.0
    for day, mean in [*SUMMER, *WINTER]:
        start = datetime.combine(day, datetime.min.time(), tzinfo=tz).astimezone(UTC)
        for hour in range(24):
            at = start + timedelta(hours=hour)
            total += gas_kwh(mean) / HS
            gas.append(StatisticData(start=at, state=total, sum=total))
            outdoor.append(StatisticData(start=at, mean=mean, min=mean, max=mean))
    async_import_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=None,
            source="recorder",
            statistic_id=GAS,
            unit_class="volume",
            unit_of_measurement="m³",
        ),
        gas,
    )
    async_import_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.ARITHMETIC,
            has_sum=False,
            name=None,
            source="recorder",
            statistic_id=OUTDOOR,
            unit_class="temperature",
            unit_of_measurement="°C",
        ),
        outdoor,
    )


async def setup_gas(hass: HomeAssistant) -> MockConfigEntry:
    hass.states.async_set(GAS, "1234.5", VOLUME)
    hass.states.async_set(OUTDOOR, "3.0", TEMPERATURE)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Gas",
        data={
            CONF_NAME: "Gas",
            CONF_KIND: "gas",
            CONF_ENTITIES: {"gas_total": GAS, "outdoor_temp": OUTDOOR},
        },
        options={
            CONF_CALORIFIC_VALUE: HS,
            CONF_Z_NUMBER: 1.0,
            CONF_DESIGN_TEMP: -12.0,
            CONF_GAS_PRICE: 12.0,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def state(hass: HomeAssistant, entry: MockConfigEntry, key: str):
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id, key
    return hass.states.get(entity_id)


@pytest.mark.freeze_time(NOW)
async def test_gas_boiler_from_statistics(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    import_statistics(hass)
    await async_wait_recording_done(hass)
    entry = await setup_gas(hass)
    # Before the first analysis (2 minutes after the start): unknown.
    first = state(hass, entry, "gas_heat_load_per_kelvin")
    assert first.state == "unknown"
    assert first.attributes["reason"] == "not_analysed_yet"

    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    per_kelvin = state(hass, entry, "gas_heat_load_per_kelvin")
    assert float(per_kelvin.state) == pytest.approx(100, abs=1)
    assert per_kelvin.attributes["dhw_method"] == "summer_base"
    assert per_kelvin.attributes["reason"] is None
    assert float(state(hass, entry, "gas_heat_load_design").state) == pytest.approx(
        3.2, abs=0.05
    )
    assert float(state(hass, entry, "gas_heating_limit").state) == pytest.approx(
        15.0, abs=0.1
    )
    dhw = state(hass, entry, "gas_dhw_share")
    assert dhw.attributes["summer_days"] == 20
    assert dhw.attributes["summer_base_kwh_per_day"] == pytest.approx(DHW_PER_DAY)
    gas = sum(gas_kwh(mean) * 24 for _, mean in [*SUMMER, *WINTER])
    assert float(dhw.state) == pytest.approx(100 * DHW_PER_DAY * 83 / gas, abs=0.1)
    year = state(hass, entry, "gas_consumption_year")
    assert float(year.state) == pytest.approx(gas, rel=1e-3)
    assert year.attributes["days"] == 83
    assert year.attributes["complete"] is False
    cost = state(hass, entry, "gas_cost_year")
    assert float(cost.state) == pytest.approx(gas * 0.12, rel=1e-3)
    # A gas boiler has no heat pump entities.
    assert state(hass, entry, "gas_heat_per_degree_day") is not None
    assert not [
        e
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain in ("binary_sensor", "button")
    ]

    # The action heat_load: by default the last 365 days.
    load = await hass.services.async_call(
        DOMAIN,
        "heat_load",
        {"config_entry": entry.entry_id, "design_outdoor_temp": -10.0},
        blocking=True,
        return_response=True,
    )
    assert load["sufficient"] is True
    assert load["standard_kw"] == pytest.approx(3.0, abs=0.05)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "report",
            {"config_entry": entry.entry_id},
            blocking=True,
            return_response=True,
        )

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_gas_setup_flow(hass: HomeAssistant) -> None:
    hass.states.async_set(GAS, "1234.5", VOLUME)
    hass.states.async_set(OUTDOOR, "3.0", TEMPERATURE)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Wärmepumpe", "source": "gas"}
    )
    assert result["step_id"] == "gas"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"outdoor_temp": OUTDOOR}
    )
    assert result["errors"] == {"base": "gas_none"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"gas_total": GAS, "outdoor_temp": OUTDOOR}
    )
    assert result["errors"] == {"base": "gas_calorific_value"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "gas_total": GAS,
            "outdoor_temp": OUTDOOR,
            "calorific_value": 11.2,
            "z_number": 0.95,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Gasheizung"
    assert result["data"] == {
        CONF_NAME: "Gasheizung",
        CONF_KIND: "gas",
        CONF_ENTITIES: {"gas_total": GAS, "outdoor_temp": OUTDOOR},
    }
    assert result["options"] == {CONF_CALORIFIC_VALUE: 11.2, CONF_Z_NUMBER: 0.95}
    assert result["result"].unique_id == f"gas:{GAS}"
    await hass.async_block_till_done()

    # Options: efficiency and prices, the conversion stays editable.
    entry = result["result"]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "gas"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"boiler_efficiency": 0.8, "gas_price": 11.5, "calorific_value": 11.0},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "boiler_efficiency": 0.8,
        "gas_price": 11.5,
        "calorific_value": 11.0,
    }
    await hass.async_block_till_done()
    assert entry.runtime_data.efficiency == 0.8
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_gas_counter_without_statistics_is_refused(hass: HomeAssistant) -> None:
    hass.states.async_set(GAS, "12.0", {**VOLUME, "state_class": "measurement"})
    hass.states.async_set(OUTDOOR, "3.0", TEMPERATURE)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Gas", "source": "gas"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"gas_heating": GAS, "outdoor_temp": OUTDOOR, "gas_total": GAS},
    )
    assert result["errors"] == {"base": "gas_twice"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"gas_heating": GAS, "outdoor_temp": OUTDOOR}
    )
    assert result["errors"] == {"base": "gas_no_statistics"}
