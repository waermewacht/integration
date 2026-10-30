"""Sensors of a gas boiler entry (gas.py): figures of the last 365 days.

Set up from sensor.py. All values come from the daily analysis; unknown
until it has run, with a `reason` where the data do not allow a value.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower, UnitOfTemperature
from homeassistant.helpers.typing import StateType

from .entity import HeatPumpEntity
from .gas import GasAnalysis
from .heat_load import heat_load_as_dict

if TYPE_CHECKING:
    from . import GasConfigEntry
    from .gas_runtime import GasRuntime

EURO = "EUR"


@dataclass(frozen=True, kw_only=True)
class GasSensorDescription(SensorEntityDescription):
    """A figure computed from the gas analysis."""

    value: Callable[[GasAnalysis], float | None]
    needs: Callable[[GasRuntime], bool] = lambda runtime: True
    attributes: Callable[[GasRuntime, GasAnalysis], dict[str, Any]] | None = None


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _load(analysis: GasAnalysis, key: str, digits: int) -> float | None:
    result = analysis.heat_load
    return _round(getattr(result, key), digits) if result.sufficient else None


def _heat_load_attributes(runtime: GasRuntime, analysis: GasAnalysis) -> dict[str, Any]:
    return {
        "start": analysis.start.isoformat(),
        "end": analysis.end.isoformat(),
        "boiler_efficiency": analysis.efficiency,
        "dhw_method": analysis.split.method,
        **heat_load_as_dict(analysis.heat_load),
    }


def _degree_day_attributes(
    runtime: GasRuntime, analysis: GasAnalysis
) -> dict[str, Any]:
    result = analysis.degree_days
    return {
        "base": "G20/15",
        "degree_days": round(result.degree_days, 1),
        "days_counted": result.days_counted,
        "days_missing": result.days_missing,
        "heating_kwh": round(result.heating_kwh, 1),
    }


def _dhw_attributes(runtime: GasRuntime, analysis: GasAnalysis) -> dict[str, Any]:
    split = analysis.split
    return {
        "method": split.method,
        "summer_days": split.summer_days,
        "summer_base_kwh_per_day": _round(split.summer_base_kwh, 2),
        "dhw_gas_kwh": round(analysis.dhw_kwh, 1),
        "heating_gas_kwh": round(analysis.heating_kwh, 1),
    }


def _gas_attributes(runtime: GasRuntime, analysis: GasAnalysis) -> dict[str, Any]:
    return {
        "start": analysis.start.isoformat(),
        "end": analysis.end.isoformat(),
        "days": analysis.gas_days,
        "complete": analysis.gas_days >= (analysis.end - analysis.start).days,
        "heat_kwh": round(analysis.heat_kwh, 1),
        "boiler_efficiency": analysis.efficiency,
    }


def _cost_attributes(runtime: GasRuntime, analysis: GasAnalysis) -> dict[str, Any]:
    return {
        **_gas_attributes(runtime, analysis),
        "gas_kwh": round(analysis.gas_kwh, 1),
        "base_cost_eur": _round(analysis.base_cost_eur, 2),
    }


GAS_DESCRIPTIONS: list[GasSensorDescription] = [
    GasSensorDescription(
        key="gas_heat_load_per_kelvin",
        native_unit_of_measurement="W/K",
        suggested_display_precision=0,
        value=lambda a: (
            None if (v := _load(a, "slope_kw_per_k", 4)) is None else round(-v * 1000)
        ),
        attributes=_heat_load_attributes,
    ),
    GasSensorDescription(
        key="gas_heat_load_design",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=1,
        value=lambda a: _load(a, "standard_kw", 2),
        needs=lambda r: r.design_temp is not None,
    ),
    GasSensorDescription(
        key="gas_heating_limit",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value=lambda a: _load(a, "heating_limit", 1),
    ),
    GasSensorDescription(
        key="gas_heat_per_degree_day",
        native_unit_of_measurement="kWh/K·d",
        suggested_display_precision=2,
        value=lambda a: _round(a.degree_days.kwh_per_degree_day, 2),
        attributes=_degree_day_attributes,
    ),
    GasSensorDescription(
        key="gas_dhw_share",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value=lambda a: _round(a.dhw_share, 1),
        attributes=_dhw_attributes,
    ),
    GasSensorDescription(
        key="gas_consumption_year",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=0,
        value=lambda a: round(a.gas_kwh, 1),
        attributes=_gas_attributes,
    ),
    GasSensorDescription(
        key="gas_cost_year",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=EURO,
        suggested_display_precision=0,
        value=lambda a: _round(a.cost_eur, 2),
        needs=lambda r: r.gas_price is not None,
        attributes=_cost_attributes,
    ),
]


class GasSensor(HeatPumpEntity, SensorEntity):
    """A figure of the gas boiler."""

    # Weeks of the signature: shown, not recorded.
    _unrecorded_attributes = frozenset({"weeks"})

    entity_description: GasSensorDescription
    runtime: GasRuntime  # type: ignore[assignment]

    def __init__(
        self, entry: GasConfigEntry, description: GasSensorDescription
    ) -> None:
        super().__init__(entry, description.key)  # type: ignore[arg-type]
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        if (analysis := self.runtime.analysis) is None:
            return None
        return self.entity_description.value(analysis)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        analysis = self.runtime.analysis
        if analysis is None:
            return {"reason": self.runtime.problem}
        attributes = {"reason": self._reason(analysis)}
        if self.entity_description.attributes is not None:
            attributes.update(
                self.entity_description.attributes(self.runtime, analysis)
            )
        return attributes

    def _reason(self, analysis: GasAnalysis) -> str | None:
        """Why the value is unknown, if it is."""
        key = self.entity_description.key
        if key in (
            "gas_heat_load_per_kelvin",
            "gas_heat_load_design",
            "gas_heating_limit",
        ):
            reasons = analysis.heat_load.reasons
            return reasons[0] if reasons else None
        if key == "gas_dhw_share" and analysis.dhw_share is None:
            return analysis.split.method
        return None


def gas_sensors(entry: GasConfigEntry) -> list[GasSensor]:
    runtime = entry.runtime_data
    return [GasSensor(entry, d) for d in GAS_DESCRIPTIONS if d.needs(runtime)]
