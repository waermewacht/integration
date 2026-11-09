"""Vendor-neutral signals of a heat pump. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from collections.abc import Collection
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
    # Compressor electricity of all modes in one meter (Waterkotte): booked
    # to the mode running, like AUX_TOTAL.
    ELEC_TOTAL = "elec_total"
    # Heat of heating and hot water in one meter (a heat meter between the
    # heat pump and a buffer that also makes the hot water): booked to the
    # mode running, like ELEC_TOTAL (TOTAL_HEAT_MODES).
    HEAT_TOTAL = "heat_total"
    # Electricity a source books apart (Lambda, iDM): defrosts belong to the
    # mode running (mostly heating), standby is standby.
    ELEC_DEFROST = "elec_defrost"
    ELEC_STANDBY = "elec_standby"
    # Boiler of a hybrid system, never heat pump energy. Its heat enters the
    # building's figures (heat load, signature, degree days, flow curve) and
    # the heat pump's share: the heat the boiler reports (Buderus "Abgegebene
    # Energie", EMS-ESP "nrgheat2"/"nrg2"), else its fuel (EMS-ESP
    # "gasmeterheat"/"gasmeter", also for oil, on Hs) times the efficiency.
    BOILER_HEAT_HEATING = "boiler_heat_heating"
    BOILER_HEAT_DHW = "boiler_heat_dhw"
    FUEL_HEATING = "fuel_heating"
    FUEL_DHW = "fuel_dhw"
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
    # Counters of the heat pump for heating only (run time, starts): the
    # look-back of run time per outdoor class (duty.py).
    RUNTIME_HEATING = "runtime_heating"
    STARTS_HEATING = "starts_heating"
    # Measurements.
    OUTDOOR_TEMP = "outdoor_temp"
    FLOW_TEMP = "flow_temp"
    RETURN_TEMP = "return_temp"
    FLOW_RATE = "flow_rate"
    DHW_TEMP = "dhw_temp"  # hot water storage, for charges and disinfection
    # No longer mapped (never evaluated); kept so entries that stored them
    # before 0.1.1 still load.
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
BOILER_HEAT_SIGNALS: dict[Mode, Signal] = {
    Mode.HEATING: Signal.BOILER_HEAT_HEATING,
    Mode.DHW: Signal.BOILER_HEAT_DHW,
}
FUEL_SIGNALS: dict[Mode, Signal] = {
    Mode.HEATING: Signal.FUEL_HEATING,
    Mode.DHW: Signal.FUEL_DHW,
}
ENERGY_SIGNALS: frozenset[Signal] = frozenset(
    {*HEAT_SIGNALS.values(), *ELEC_SIGNALS.values(), *AUX_SIGNALS.values()}
    | {Signal.AUX_TOTAL, Signal.ELEC_TOTAL, Signal.ELEC_DEFROST, Signal.ELEC_STANDBY}
    | {Signal.HEAT_TOTAL}
    | set(BOILER_HEAT_SIGNALS.values())
    | set(FUEL_SIGNALS.values())
)


BOILER_SIGNALS: frozenset[Signal] = frozenset(
    {*BOILER_HEAT_SIGNALS.values(), *FUEL_SIGNALS.values()}
)


def fuel_modes(entities: Collection[Signal]) -> frozenset[Mode]:
    """Modes whose boiler heat comes from the fuel (no boiler heat counter)."""
    return frozenset(
        m
        for m, s in FUEL_SIGNALS.items()
        if s in entities and BOILER_HEAT_SIGNALS[m] not in entities
    )


def has_boiler(entities: Collection[Signal]) -> bool:
    """A hybrid system: boiler heat or boiler fuel mapped."""
    return any(
        s in entities for s in (*BOILER_HEAT_SIGNALS.values(), *FUEL_SIGNALS.values())
    )


# Modes the common heat meter (HEAT_TOTAL) is split to. Hot water only with
# an activity, which tells it from heating. Cooling needs a meter of its own:
# a heat meter counts no heat while the heat pump cools (or counts the cold
# in a register of its own).
TOTAL_HEAT_MODES: tuple[Mode, ...] = (Mode.HEATING, Mode.DHW)


def has_activity(entities: Collection[Signal]) -> bool:
    """An activity: the activity entity or flags (activity.py)."""
    return any(s in entities for s in (Signal.ACTIVITY, *ACTIVITY_PARTS))


def total_heat_modes(entities: Collection[Signal]) -> tuple[Mode, ...]:
    """Modes whose heat comes from the common heat meter: heating, and hot
    water with an activity; none without the meter."""
    if Signal.HEAT_TOTAL not in entities:
        return ()
    return tuple(
        m
        for m in TOTAL_HEAT_MODES
        if HEAT_SIGNALS[m] not in entities
        and (m is Mode.HEATING or has_activity(entities))
    )


def has_heat(entities: Collection[Signal], mode: Mode) -> bool:
    """Whether `mode` gets heat: its own meter, or the common one."""
    return HEAT_SIGNALS[mode] in entities or mode in total_heat_modes(entities)


def heat_signal(entities: Collection[Signal], mode: Mode) -> Signal:
    """The meter that counts the heat of `mode` (its own if not mapped)."""
    if mode in total_heat_modes(entities):
        return Signal.HEAT_TOTAL
    return HEAT_SIGNALS[mode]


def has_elec(entities: Collection[Signal], mode: Mode) -> bool:
    """Whether `mode` gets electricity: its own meter, or the common one
    for the modes with heat (heating always)."""
    if ELEC_SIGNALS[mode] in entities:
        return True
    return Signal.ELEC_TOTAL in entities and (
        mode is Mode.HEATING or has_heat(entities, mode)
    )


# Signals that make up the activity, besides the activity entity itself.
ACTIVITY_PARTS: tuple[Signal, ...] = (
    Signal.DEFROST_FLAG,
    Signal.DHW_FLAG,
    Signal.COOLING_FLAG,
    Signal.HEATING_FLAG,
    Signal.COOLING_MODE,
)
