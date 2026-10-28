"""Source template for Luxtronik 2.x controllers (HACS integration luxtronik2).

alpha innotec, Novelan and older Buderus/Bosch heat pumps. Derived from the
source code of BenPru/luxtronik 2026.10.18 (custom_components/luxtronik2) on
2026-10-27, not from a real installation: experimental until a recorded
fixture exists.

Unique ids are the entity id the integration assigned at creation,
"<domain>.<prefix>_<key>" (sensor.py, binary_sensor.py: `self.entity_id =
ENTITY_ID_FORMAT.format(f"{prefix}_{description.key}")`, `_attr_unique_id =
self.entity_id`). The prefix is "luxtronik_<serial>" for new entries
(config_flow.py), "luxtronik" or "luxtronik2" for entries migrated from config
entry versions 1 and 3 (__init__.py). Prefix and key both contain "_", so the
id is split at a known key at its end (`id_format` with "{key}").
"""

from __future__ import annotations

from .model import Activity, Signal
from .profiles import Template

# Status sensor (key "status", register C0080): an enum whose state is the
# option key (LuxOperationMode in const.py, normalized in common.py: spaces and
# "/" to "_", lower case), the same in every language. Utility lock (evu) and
# no request are standstill. Pool/solar and heating by an external source are
# OTHER: no Wärmewacht mode, and the compressor may not be the heat source.
LUXTRONIK_ACTIVITY: dict[str, Activity] = {
    "heating": Activity.HEATING,
    "hot_water": Activity.DHW,
    "cooling": Activity.COOLING,
    "defrost": Activity.DEFROST,
    "no_request": Activity.OFF,
    "evu": Activity.OFF,
    "swimming_pool_solar": Activity.OTHER,
    "heating_external_source": Activity.OTHER,
}

# Keys from SensorKey (const.py) and sensor_entities_predefined.py /
# binary_sensor_entities_predefined.py. Heat per mode: calculations 151/152 in
# 0.1 kWh (compressor 1 only on twin units); cooling heat: parameter 1135 in
# 0.01 kWh. Electricity per mode: parameters 1136/1137/1139 in 0.01 kWh, only
# on controllers whose parameter block reaches them (newer firmware; V1.73
# ends at 1021). Cooling counters exist only while not 0. The backup heater
# has a lifetime total only (sum of parameters 1059 and 1140, 0.1 kWh).
# Disabled by default in luxtronik2: compressor1_impulses,
# current_heat_output, current_power_consumption.
_S, _B = "sensor", "binary_sensor"
LUXTRONIK = Template(
    experimental=True,
    key="luxtronik",
    label="Luxtronik",
    platform="luxtronik2",
    # "<domain>.<prefix>_<key>", only keys of the id's own domain. Keys of
    # the integration that merely end in one ("smart_grid_status" ends in
    # "_status") give a longer prefix, a group that never holds the
    # required signals.
    id_format=r"(?P<domain>[^.]+)\.(?P<prefix>.+)_(?P<key>{key})",
    signals={
        Signal.HEAT_HEATING: ((_S, "heat_amount_heating"),),
        Signal.HEAT_DHW: ((_S, "dhw_heat_amount"),),
        Signal.HEAT_COOLING: ((_S, "cooling_heat_amount"),),
        Signal.ELEC_HEATING: ((_S, "heat_energy_input"),),
        Signal.ELEC_DHW: ((_S, "dhw_energy_input"),),
        Signal.ELEC_COOLING: ((_S, "cooling_energy_input"),),
        Signal.AUX_TOTAL: ((_S, "additional_heat_generator_energy"),),
        Signal.COMPRESSOR: ((_B, "compressor"),),
        Signal.ACTIVITY: ((_S, "status"),),
        Signal.STARTS_TOTAL: ((_S, "compressor1_impulses"),),
        Signal.OUTDOOR_TEMP: ((_S, "outdoor_temperature"),),
        Signal.DHW_TEMP: ((_S, "dhw_temperature"),),
        # Luxtronik calls the return "flow out" (TRL), the flow "flow in" (TVL).
        Signal.FLOW_TEMP: ((_S, "flow_in_temperature"),),
        Signal.RETURN_TEMP: ((_S, "flow_out_temperature"),),
        # Heat meter flow (C0155) in "L/h"; not the heat source (brine) flow.
        Signal.FLOW_RATE: ((_S, "heat_amount_flow_rate"),),
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING),
    activity_values=LUXTRONIK_ACTIVITY,
)
