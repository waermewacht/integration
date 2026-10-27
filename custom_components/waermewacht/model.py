"""Vendor-neutral signals of a heat pump. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from enum import StrEnum


class Mode(StrEnum):
    """Operating mode an amount of energy belongs to."""

    HEATING = "heating"
    DHW = "dhw"
    COOLING = "cooling"


class Activity(StrEnum):
    """What the heat pump is doing right now."""

    OFF = "off"
    HEATING = "heating"
    DHW = "dhw"
    COOLING = "cooling"
    DEFROST = "defrost"
    OTHER = "other"  # pool, alarm, unknown values

    @property
    def mode(self) -> Mode | None:
        """The operating mode of this activity, if it is one."""
        try:
            return Mode(self.value)
        except ValueError:
            return None


class Signal(StrEnum):
    """An input Wärmewacht can read from an entity."""

    # Cumulative energy (kWh after unit conversion).
    HEAT_HEATING = "heat_heating"
    HEAT_DHW = "heat_dhw"
    HEAT_COOLING = "heat_cooling"
    ELEC_HEATING = "elec_heating"
    ELEC_DHW = "elec_dhw"
    ELEC_COOLING = "elec_cooling"
    AUX_HEATING = "aux_heating"
    AUX_DHW = "aux_dhw"
    AUX_TOTAL = "aux_total"
    # Operation.
    COMPRESSOR = "compressor"
    ACTIVITY = "activity"
    # Activity from several entities (activity.py): on/off flags, and the set
    # operating mode telling cooling from heating behind one valve position.
    DEFROST_FLAG = "defrost_flag"
    DHW_FLAG = "dhw_flag"
    COOLING_FLAG = "cooling_flag"
    HEATING_FLAG = "heating_flag"
    COOLING_MODE = "cooling_mode"
    STARTS_TOTAL = "starts_total"
    # Measurements.
    OUTDOOR_TEMP = "outdoor_temp"
    FLOW_TEMP = "flow_temp"
    RETURN_TEMP = "return_temp"
    FLOW_RATE = "flow_rate"
    DHW_TEMP = "dhw_temp"  # hot water storage, for charges and disinfection
    HEAT_POWER = "heat_power"
    ELEC_POWER = "elec_power"


HEAT_SIGNALS: dict[Mode, Signal] = {
    Mode.HEATING: Signal.HEAT_HEATING,
    Mode.DHW: Signal.HEAT_DHW,
    Mode.COOLING: Signal.HEAT_COOLING,
}
ELEC_SIGNALS: dict[Mode, Signal] = {
    Mode.HEATING: Signal.ELEC_HEATING,
    Mode.DHW: Signal.ELEC_DHW,
    Mode.COOLING: Signal.ELEC_COOLING,
}
AUX_SIGNALS: dict[Mode, Signal] = {
    Mode.HEATING: Signal.AUX_HEATING,
    Mode.DHW: Signal.AUX_DHW,
}
ENERGY_SIGNALS: frozenset[Signal] = frozenset(
    {*HEAT_SIGNALS.values(), *ELEC_SIGNALS.values(), *AUX_SIGNALS.values()}
    | {Signal.AUX_TOTAL}
)

# Signals that make up the activity, besides the activity entity itself.
ACTIVITY_PARTS: tuple[Signal, ...] = (
    Signal.DEFROST_FLAG,
    Signal.DHW_FLAG,
    Signal.COOLING_FLAG,
    Signal.HEATING_FLAG,
    Signal.COOLING_MODE,
)
