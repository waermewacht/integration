"""Source template for Lambda heat pumps (HACS integration lambda_heat_pumps).

Pure Python, no Home Assistant imports. Derived from the source code of
GuidoJeuken-6512/lambda_heat_pumps 2.8.6 (commit 5ad6cd0, 2026-10-17) on
2026-10-27, not from a real installation: experimental until a recorded
fixture exists.

Unique ids (utils.py, `generate_sensor_names`): "<name>_hp<N>_<key>" for the
sensors of heat pump N and "<name>_<key>" for those of the main device
(outdoor temperature) with the default "use_legacy_modbus_names"; without it
"hp<N>_<key>" and "<key>". <name> is the name of the config entry, lower case
without spaces (`normalize_name_prefix`, default "EU08L"); it may contain "_".
Names set in "sensors_names_override" (lambda_wp_config.yaml) replace
"hp<N>_<key>" by a free name and are not recognized. `Template.split` has no
such format; `LambdaTemplate` adds it here until the core does.

Energy: the Modbus registers 1020/1022 (+100 per heat pump) are lifetime
totals in Wh of electricity and heat, but not split by mode. Lambda splits
their increments itself by the operating state at each poll (coordinator.py,
`_track_hp_energy_type_consumption`: CH heating, DHW hot water, CC cooling,
DEFROST defrost, everything else "stby") into restored lifetime sensors
"<mode>_energy_total" (electricity, total_increasing) and
"<mode>_thermal_energy_total" (heat, state class total) in kWh that never
step back (`set_energy_value`). Those are the counters used here. Defrost
and standby have counters of their own that no signal takes yet: the
electricity of defrosts is missing in heating, and Wärmewacht's standby only
sees what Lambda booked to a mode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Activity, Signal
from .profiles import Template

# Sensors of the main device (no "hp<N>_"); they join heat pump 1.
GENERAL_KEYS = frozenset({"ambient_temperature", "ambient_temperature_calculated"})

# The rest before a heat pump key: "[<name>_]hp<N>".
_HEAT_PUMP = re.compile(r"(?:(?P<name>.*)_)?(?P<hp>hp\d+)")
# The rest before a key of the main device must not name a sub-device.
_SUB_DEVICE = re.compile(r"(?:.*_)?(?:hp|boil|buff|sol|hc)\d+")


def _group(name: str, heat_pump: str) -> str:
    return f"{name}_{heat_pump}" if name else heat_pump


def split_lambda(unique_id: str, keys: frozenset[str]) -> tuple[str, str] | None:
    """(prefix, key) of a Lambda unique id, None if no known key fits.

    The prefix is "[<name>_]hp<N>", one group per heat pump; keys of the main
    device get the group of heat pump 1. Keys are tried longest first; an id
    that merely ends in a known key ("…_hp1_requested_flow_line_temperature",
    "…_hc1_flow_line_temperature") does not fit and is skipped.
    """
    for key in sorted(keys, key=len, reverse=True):
        if unique_id == key:
            rest = ""
        elif unique_id.endswith(f"_{key}"):
            rest = unique_id[: -len(key) - 1]
        else:
            continue
        if key in GENERAL_KEYS:
            if _SUB_DEVICE.fullmatch(rest):
                continue
            return _group(rest, "hp1"), key
        if match := _HEAT_PUMP.fullmatch(rest):
            return _group(match["name"] or "", match["hp"]), key
    return None


@dataclass(frozen=True)
class LambdaTemplate(Template):
    """A template whose unique ids are "[<name>_][hp<N>_]<key>"."""

    def split(self, unique_id: str) -> tuple[str, str] | None:
        return split_lambda(
            unique_id, frozenset(k for cs in self.signals.values() for _, k in cs)
        )


# Operating state (register 1003, HP_OPERATING_STATE in const_mapping.py): a
# text sensor in English, the same in every language. Utility and time locks,
# summer and holiday are standstill; frost protection, errors and messages are
# OTHER (the compressor may run, Lambda books its energy to "stby").
LAMBDA_ACTIVITY: dict[str, Activity] = {
    "stby": Activity.OFF,
    "ch": Activity.HEATING,
    "dhw": Activity.DHW,
    "cc": Activity.COOLING,
    "circulate": Activity.OFF,
    "defrost": Activity.DEFROST,
    "off": Activity.OFF,
    "frost": Activity.OTHER,
    "stby-frost": Activity.OFF,
    "not used": Activity.OTHER,
    "summer": Activity.OFF,
    "holiday": Activity.OFF,
    "error": Activity.OTHER,
    "warning": Activity.OTHER,
    "info-message": Activity.OTHER,
    "time-block": Activity.OFF,
    "release-block": Activity.OFF,
    "mintemp-block": Activity.OFF,
    "firmware-download": Activity.OTHER,
}

_S = "sensor"
LAMBDA = LambdaTemplate(
    experimental=True,
    key="lambda",
    label="Lambda",
    platform="lambda_heat_pumps",
    device=None,
    signals={
        Signal.HEAT_HEATING: ((_S, "heating_thermal_energy_total"),),
        Signal.HEAT_DHW: ((_S, "hot_water_thermal_energy_total"),),
        Signal.HEAT_COOLING: ((_S, "cooling_thermal_energy_total"),),
        Signal.ELEC_HEATING: ((_S, "heating_energy_total"),),
        Signal.ELEC_DHW: ((_S, "hot_water_energy_total"),),
        Signal.ELEC_COOLING: ((_S, "cooling_energy_total"),),
        # No backup heater energy (only the relay state of the 2nd stage).
        # Compressor unit rating in % (register 1010), 0 while it stands.
        Signal.COMPRESSOR: ((_S, "compressor_unit_rating"),),
        Signal.ACTIVITY: ((_S, "operating_state"),),
        # Counted by Lambda: changes of the HP state to "START COMPRESSOR".
        Signal.STARTS_TOTAL: ((_S, "compressor_start_cycling_total"),),
        # Main device; the direct value is readable up to firmware 9 only.
        Signal.OUTDOOR_TEMP: (
            (_S, "ambient_temperature"),
            (_S, "ambient_temperature_calculated"),
        ),
        Signal.FLOW_TEMP: ((_S, "flow_line_temperature"),),
        Signal.RETURN_TEMP: ((_S, "return_line_temperature"),),
        # The heat sink flow ("l/h") has no device class volume_flow_rate, the
        # entity form would not offer it: left out.
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING),
    activity_values=LAMBDA_ACTIVITY,
)
