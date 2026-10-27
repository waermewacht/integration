"""Source template: Stiebel Eltron / Tecalor heat pumps via the ISG.

Integration stiebel_eltron_isg (HACS, pail23/stiebel_eltron_isg_component),
read at tag 2026.10-beta4 (commit 15b8b30) with pystiebeleltron 0.8.0, the
version its manifest pins. Derived from source code only, not from a real
installation: experimental until a fixture of a real registry exists.

Unique ids are "<config entry id>_<key>" since 2026.7 (entity.py,
build_unique_id; older "stiebel_eltron_isg_<name>_<key>" ids are migrated in
place). The keys are the same for all controller families (WPM 3, WPM 3i,
WPMsystem, LWZ R290, LWZ, LWZ x04 SOL); which entities exist differs.

Energy: every heat and compressor electricity counter is a register pair in
whole kWh (low word kWh, high word MWh). The "..._total" entity changes only
when the controller moves the day register into the total at midnight; the
day-and-total entity (key without suffix) is day + total, held monotonic by
the library, so it rises in 1 kWh steps during the day. That one is used.
The electric booster and the LWZ cooling heat exist as totals only.

Activity: there is no single activity entity, but four binary sensors from
bits of the operating status register (is_heating, is_heating_water,
is_cooling, evaporator_defrost). The core reads one activity entity, so
ACTIVITY is not among the signals; ACTIVITY_FLAGS and activity_from_flags()
describe the mapping for a core extension.
"""

from __future__ import annotations

from collections.abc import Mapping

from .model import Activity, Signal
from .profiles import Template

# Config entry ids: ULID (26 characters) or, for old entries, a uuid4 in hex
# (32). Neither contains "_", so the first "_" ends the prefix; keys contain
# more of them ("produced_heating_total").
_ENTRY_ID_MIN_LENGTH = 26


def split_entry_id(unique_id: str) -> tuple[str, str] | None:
    """(config entry id, key) of a "<entry id>_<key>" unique id, else None."""
    prefix, separator, key = unique_id.partition("_")
    if not separator or not key:
        return None
    if len(prefix) < _ENTRY_ID_MIN_LENGTH or not (
        prefix.isascii() and prefix.isalnum()
    ):
        return None  # e.g. a leftover "stiebel_eltron_isg_<name>_<key>" id
    return prefix, key


class EntryIdTemplate(Template):
    """Template for "<config entry id>_<key>" unique ids.

    Stopgap until Template itself can be told the separator ("-" for Bosch
    HomeCom, "_" here) and a pattern for the prefix.
    """

    def split(self, unique_id: str) -> tuple[str, str] | None:
        return split_entry_id(unique_id)


_S, _B = "sensor", "binary_sensor"
STIEBEL_ISG = EntryIdTemplate(
    experimental=True,
    key="stiebel_isg",
    label="Stiebel Eltron / Tecalor ISG",
    platform="stiebel_eltron_isg",
    device=None,
    signals={
        # Day-and-total counters (sensor.py ENERGY_SENSOR_TYPES and
        # LWZ_ENERGY_SENSOR_TYPES), kWh, total_increasing, enabled by default.
        Signal.HEAT_HEATING: ((_S, "produced_heating"),),
        Signal.HEAT_DHW: ((_S, "produced_water_heating"),),
        Signal.ELEC_HEATING: ((_S, "consumed_heating"),),
        Signal.ELEC_DHW: ((_S, "consumed_water_heating"),),
        # LWZ only: thermal cooling energy (hm_cooling_total), total only.
        # No electricity for cooling exists as a counter, so no EER.
        Signal.HEAT_COOLING: ((_S, "produced_cooling_total"),),
        # Heat of the electric booster (NHZ), total only; for a resistance
        # heater heat equals electricity.
        Signal.AUX_HEATING: ((_S, "produced_electrical_booster_heating_total"),),
        Signal.AUX_DHW: ((_S, "produced_electrical_booster_water_heating_total"),),
        # Bit "compressor in operation" of the operating status (WPM bit 6,
        # LWZ bit 1); the LWZ compressor frequency as a fallback.
        Signal.COMPRESSOR: ((_B, "compressor_on"), (_S, "compressor_speed")),
        # LWZ only; WPM controllers expose no start counter.
        Signal.STARTS_TOTAL: ((_S, "compressor_starts"),),
        Signal.OUTDOOR_TEMP: ((_S, "outdoor_temperature"),),
        # WPM: flow of the heat pump before the booster; LWZ has only the one.
        Signal.FLOW_TEMP: ((_S, "flow_temperature_wp"), (_S, "flow_temperature")),
        Signal.RETURN_TEMP: ((_S, "return_temperature"),),
        Signal.FLOW_RATE: ((_S, "volume_stream"),),
        # WPMsystem only: inverter input power of compressor 1 (kW).
        Signal.ELEC_POWER: ((_S, "current_power_consumption"),),
        # Operating status bits (see ACTIVITY_FLAGS below).
        Signal.DEFROST_FLAG: ((_B, "evaporator_defrost"),),
        Signal.DHW_FLAG: ((_B, "is_heating_water"),),
        Signal.COOLING_FLAG: ((_B, "is_cooling"),),
        Signal.HEATING_FLAG: ((_B, "is_heating"),),
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING),
)

# Operating status bits as binary sensors, first match wins: a defrost runs
# while heating is requested, hot water has priority over heating. Bits per
# family in binary_sensor.py (WPM: 4 heating, 5 hot water, 8 cooling,
# 9 defrost of at least one inverter; LWZ: 2, 4, 3, 11).
ACTIVITY_FLAGS: tuple[tuple[str, Activity], ...] = (
    ("evaporator_defrost", Activity.DEFROST),
    ("is_heating_water", Activity.DHW),
    ("is_cooling", Activity.COOLING),
    ("is_heating", Activity.HEATING),
)


def activity_from_flags(states: Mapping[str, str | None]) -> Activity | None:
    """Activity from the states of the flag entities, by key.

    Keys without an entity are left out of `states`. None while a flag that
    could still decide is unknown or without any flag; OFF when all are off.
    """
    if not any(key in states for key, _ in ACTIVITY_FLAGS):
        return None
    for key, activity in ACTIVITY_FLAGS:
        if key not in states:
            continue
        match states[key]:
            case "on":
                return activity
            case "off":
                continue
            case _:
                return None  # unknown, unavailable
    return Activity.OFF
