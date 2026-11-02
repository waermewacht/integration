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
# The same 9 weeks, only mild (2 … 10 °C): no frost, spread 8 K.
MILD_WINTER = [
    (date(2025, 12, 1) + timedelta(days=n), 2.0 + (n // 7)) for n in range(63)
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


def import_statistics(
    hass: HomeAssistant, days: list[tuple[date, float]] | None = None
) -> None:
    tz = dt_util.get_default_time_zone()
    gas: list[StatisticData] = []
    outdoor: list[StatisticData] = []
    total = 0.0
    for day, mean in days if days is not None else [*SUMMER, *WINTER]:
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


@pytest.mark.freeze_time(NOW)
async def test_gas_boiler_mild_weeks_preliminary(hass: HomeAssistant) -> None:
    """Only mild weeks: the line as preliminary attributes, states unknown."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    import_statistics(hass, [*SUMMER, *MILD_WINTER])
    await async_wait_recording_done(hass)
    entry = await setup_gas(hass)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    per_kelvin = state(hass, entry, "gas_heat_load_per_kelvin")
    assert per_kelvin.state == "unknown"
    assert per_kelvin.attributes["reason"] == "spread_too_small"
    assert per_kelvin.attributes["preliminary"] is True
    assert per_kelvin.attributes["slope_kw_per_k"] == pytest.approx(-0.1, abs=0.002)
    assert per_kelvin.attributes["heating_limit"] == pytest.approx(15.0, abs=0.1)
    assert per_kelvin.attributes["standard_kw"] is None
    assert state(hass, entry, "gas_heat_load_design").state == "unknown"
    assert state(hass, entry, "gas_heating_limit").state == "unknown"

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


async def test_gas_reconfigure_keeps_prices(hass: HomeAssistant) -> None:
    kwh = {**VOLUME, "unit_of_measurement": "kWh", "device_class": "energy"}
    hass.states.async_set(GAS, "1234.5", kwh)
    hass.states.async_set("sensor.gas_dhw", "321.0", kwh)
    hass.states.async_set(OUTDOOR, "3.0", TEMPERATURE)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Gas",
        data={
            CONF_NAME: "Gas",
            CONF_KIND: "gas",
            CONF_ENTITIES: {"gas_total": GAS, "outdoor_temp": OUTDOOR},
        },
        options={CONF_GAS_PRICE: 12.0},
        unique_id=f"gas:{GAS}",
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "gas"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"gas_heating": GAS, "gas_dhw": "sensor.gas_dhw", "outdoor_temp": OUTDOOR},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_ENTITIES] == {
        "gas_heating": GAS,
        "gas_dhw": "sensor.gas_dhw",
        "outdoor_temp": OUTDOOR,
    }
    assert entry.options == {CONF_GAS_PRICE: 12.0}
    # The heating counter is the main counter now (same entity here).
    assert entry.unique_id == f"gas:{GAS}"

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"gas_heating": "sensor.gas_dhw", "outdoor_temp": OUTDOOR}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == "gas:sensor.gas_dhw"


FLOW = "sensor.boiler_flow"


@pytest.mark.freeze_time(NOW)
async def test_gas_boiler_flow_temperature(hass: HomeAssistant) -> None:
    """A heating counter and the boiler's flow: the flow at 0 °C and at the
    design temperature from the heating curve (35 °C - 0.8 K per K)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    import_statistics(hass)
    tz = dt_util.get_default_time_zone()
    rows = []
    for day, mean in WINTER:
        start = datetime.combine(day, datetime.min.time(), tzinfo=tz).astimezone(UTC)
        flow = 35.0 - 0.8 * mean
        rows.extend(
            StatisticData(
                start=start + timedelta(hours=h), mean=flow, min=flow, max=flow
            )
            for h in range(24)
        )
    async_import_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.ARITHMETIC,
            has_sum=False,
            name=None,
            source="recorder",
            statistic_id=FLOW,
            unit_class="temperature",
            unit_of_measurement="°C",
        ),
        rows,
    )
    await async_wait_recording_done(hass)
    hass.states.async_set(GAS, "1234.5", VOLUME)
    hass.states.async_set(OUTDOOR, "3.0", TEMPERATURE)
    hass.states.async_set(FLOW, "38.0", {**TEMPERATURE, "state_class": "measurement"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Gas",
        data={
            CONF_NAME: "Gas",
            CONF_KIND: "gas",
            CONF_ENTITIES: {
                "gas_heating": GAS,
                "outdoor_temp": OUTDOOR,
                "flow_temp": FLOW,
            },
        },
        options={CONF_CALORIFIC_VALUE: HS, CONF_Z_NUMBER: 1.0, CONF_DESIGN_TEMP: -12.0},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    at_zero = state(hass, entry, "gas_flow_at_zero")
    assert float(at_zero.state) == pytest.approx(35.0, abs=0.1)
    assert at_zero.attributes["reason"] is None
    assert at_zero.attributes["slope"] == pytest.approx(-0.8, abs=0.01)
    assert at_zero.attributes["days"] == 63
    assert at_zero.attributes["coldest_day"] == pytest.approx(-6.0)
    assert at_zero.attributes["dhw_method"] == "heating_only"
    design = state(hass, entry, "gas_flow_at_design")
    assert float(design.state) == pytest.approx(44.6, abs=0.1)
    assert design.attributes["design_temp"] == -12.0
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_gas_flow_without_statistics_is_refused(hass: HomeAssistant) -> None:
    hass.states.async_set(GAS, "1234.5", VOLUME)
    hass.states.async_set(OUTDOOR, "3.0", TEMPERATURE)
    hass.states.async_set(FLOW, "38.0", TEMPERATURE)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Gas", "source": "gas"}
    )
    assert result["step_id"] == "gas"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "gas_total": GAS,
            "outdoor_temp": OUTDOOR,
            "flow_temp": FLOW,
            CONF_CALORIFIC_VALUE: HS,
            CONF_Z_NUMBER: 1.0,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "gas_flow_no_statistics"}


def winter_and_summer_readings() -> list[tuple[datetime, float]]:
    """Gas meter (kWh) of the test house: summer from 1.7. to 21.7.2025, then
    weekly through the nine winter weeks from Monday 1.12.2025."""
    tz = dt_util.get_default_time_zone()
    days = dict([*SUMMER, *WINTER])
    total = 1000.0
    readings = []
    day = date(2025, 7, 1)
    end = date(2026, 2, 2)
    while day <= end:
        at = datetime.combine(day, datetime.min.time(), tzinfo=tz)
        if day in (date(2025, 7, 1), date(2025, 7, 21)) or (
            day >= date(2025, 12, 1) and (day - date(2025, 12, 1)).days % 7 == 0
        ):
            readings.append((at, total))
        if day in days:
            total += gas_kwh(days[day]) * 24
        day += timedelta(days=1)
    return readings


@pytest.mark.freeze_time(NOW)
async def test_gas_boiler_with_readings_by_hand(hass: HomeAssistant) -> None:
    """No counter: readings by hand through the number entity and the action;
    each period between two readings is a point of the signature."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    import_statistics(hass)  # the outdoor temperature (and an unused meter)
    await async_wait_recording_done(hass)
    hass.states.async_set(OUTDOOR, "3.0", TEMPERATURE)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Gas", "source": "gas"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"outdoor_temp": OUTDOOR, "manual_unit": "kwh", "gas_total": GAS},
    )
    assert result["errors"] == {"base": "gas_manual_and_counter"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"outdoor_temp": OUTDOOR, "manual_unit": "kwh"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["manual_unit"] == "kwh"
    assert result["data"][CONF_ENTITIES] == {"outdoor_temp": OUTDOOR}
    entry = result["result"]
    await hass.async_block_till_done()
    entry.runtime_data.design_temp = -12.0

    for at, value in winter_and_summer_readings():
        await hass.services.async_call(
            DOMAIN,
            "add_gas_reading",
            {"config_entry": entry.entry_id, "reading": value, "time": at.isoformat()},
            blocking=True,
        )
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    per_kelvin = state(hass, entry, "gas_heat_load_per_kelvin")
    assert per_kelvin.state != "unknown", per_kelvin.attributes
    assert float(per_kelvin.state) == pytest.approx(100, abs=2)
    assert per_kelvin.attributes["dhw_method"] == "summer_base"
    dhw = state(hass, entry, "gas_dhw_share")
    assert dhw.attributes["summer_base_kwh_per_day"] == pytest.approx(DHW_PER_DAY)

    # The number entity: the last reading; a lower one is refused.
    number = er.async_get(hass).async_get_entity_id(
        "number", DOMAIN, f"{entry.entry_id}_gas_reading"
    )
    assert number
    last = winter_and_summer_readings()[-1][1]
    assert float(hass.states.get(number).state) == pytest.approx(last)
    assert hass.states.get(number).attributes["readings"] == 12
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": number, "value": last - 1},
            blocking=True,
        )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": number, "value": last + 5}, blocking=True
    )
    assert hass.states.get(number).attributes["readings"] == 13

    # The action heat_load works on the readings too.
    load = await hass.services.async_call(
        DOMAIN,
        "heat_load",
        {"config_entry": entry.entry_id, "design_outdoor_temp": -10.0},
        blocking=True,
        return_response=True,
    )
    assert load["sufficient"] is True
    assert load["standard_kw"] == pytest.approx(3.0, abs=0.1)

    # Removing a reading; one that does not exist is an error.
    first = winter_and_summer_readings()[0][0]
    await hass.services.async_call(
        DOMAIN,
        "remove_gas_reading",
        {"config_entry": entry.entry_id, "time": first.isoformat()},
        blocking=True,
    )
    assert hass.states.get(number).attributes["readings"] == 12
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "remove_gas_reading",
            {"config_entry": entry.entry_id, "time": first.isoformat()},
            blocking=True,
        )
    assert await hass.config_entries.async_unload(entry.entry_id)
