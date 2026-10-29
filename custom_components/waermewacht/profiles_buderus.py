"""Source template: Buderus/Bosch gateways MX300, MX400, K30 (HACS `buderus_ha`).

Pure Python, no Home Assistant imports. Derived from the source code of
BassXT/buderus v0.2.0 (commit 9d3eb02, 2026-08-27) on 2026-10-29 (const.py,
coordinator.py, emon.py, sensor.py, enum_helpers.py, config_flow.py,
translations/de.json), the discussion of its PR #15 and issue #8 (EMON
payloads of a WLW186i with MX400 and a K40/MX400), the Bosch PointT
specification bosch-home-comfort/api-docs k-40-rf.yaml (78e36b3) and
homecom_alt (a6924f2) for the paths bosch_homecom reads. Not from a real
installation: experimental until a recorded fixture exists.

Platform "buderus_ha", sensors only (no binary sensors), none disabled by
default. Unique ids "<gateway id>_<key>" (sensor.py, `BuderusSensor`); the
gateway id is the PointT deviceId (digits on known gateways, config_flow.py).
Number, select and switch entities append "_number", "_select", "_switch".
The code does not tell MX300, MX400 and K30 apart: every gateway gets the
same entities; a resource the gateway does not serve leaves an ordinary
sensor "unknown" and an energy sensor "unavailable".

Energy: the "emon" sensors read /heatSources/emon/{ch,dhw,cooling,total}
Consumption: lifetime counters per mode (PR #15: "lifetime counters only";
the total equals the EMS-ESP sum of all modes on the owner's K40RF, where
bosch_homecom shows it as attributes of "Wärmequelle"). kWh as the
integration declares it (the payload's "unit" is not read), 0.01 kWh,
energy, total_increasing. Fetched every 10 minutes (EMON_UPDATE_INTERVAL,
the rest every 60 s), so a value is up to about 11 minutes late; the cloud
total itself moved every minute in bosch_homecom on the owner's K40RF. On a
failed fetch the last value stays. Not day values: no reset at midnight,
no `day_values`; standby is told from the compressor and the heat counter
between two values as for EMS-ESP. "compressor" is all heat pump
electricity of the mode including standby (PR #15: ~21 W rise of the
heating value without heat), the backup heater is "eheater" apart, heat is
"outputProduced". Cooling has no backup heater. An unused mode may report
zeros (HTTP 200) instead of being absent.

Compressor: "actual_modulation" (/heatSources/actualModulation, %), the path
behind bosch_homecom's "compressor_modulation", above 0 while running.
Activity: "compressor_status" (/heatSources/compressor/status), an enum with
the values of EMS-ESP's hpactivity (off, heating, cooling, dhw, pool,
pool_heat, defrost, alarm), states as slugs; values the integration does
not declare become "unknown". Not in the K40 specification and not among
the README's confirmed resources: whether an MX300 serves it is open (it
stays "unknown" on a hybrid, issue #22), hence not required.

Left out: no flow rate entity exists; "number_of_starts_heating/dhw/cooling"
(per mode, the total suffices); "emon_total_*" (sums of the modes);
"central_heating_status" and "actual_heat_demand" (demand, not activity).
"""

from __future__ import annotations

from .model import Activity, Signal
from .profiles import Template

PLATFORM = "buderus_ha"
_S = "sensor"
BUDERUS = Template(
    experimental=True,
    key="buderus",
    label="Buderus/Bosch (MX300/MX400, buderus)",
    platform=PLATFORM,
    # "<gateway id>_<key>": keys contain "_", so only the known ones count
    # (number/select/switch ids carry a suffix and fall out).
    id_format=r"(?P<prefix>[^_]+)_(?P<key>{key})",
    signals={
        Signal.HEAT_HEATING: ((_S, "emon_heating_heat_produced"),),
        Signal.HEAT_DHW: ((_S, "emon_dhw_heat_produced"),),
        Signal.HEAT_COOLING: ((_S, "emon_cooling_heat_produced"),),
        Signal.ELEC_HEATING: ((_S, "emon_heating_compressor"),),
        Signal.ELEC_DHW: ((_S, "emon_dhw_compressor"),),
        Signal.ELEC_COOLING: ((_S, "emon_cooling_compressor"),),
        Signal.AUX_HEATING: ((_S, "emon_heating_electric_heater"),),
        Signal.AUX_DHW: ((_S, "emon_dhw_electric_heater"),),
        Signal.COMPRESSOR: ((_S, "actual_modulation"),),
        Signal.ACTIVITY: ((_S, "compressor_status"),),
        # /heatSources/numberOfStarts: starts of the heat source since
        # installation (specification); compressor starts on a heat pump.
        Signal.STARTS_TOTAL: ((_S, "number_of_starts"),),
        Signal.OUTDOOR_TEMP: ((_S, "outdoor_temperature"),),
        # System flow (as bosch_homecom's supply_temperature), heat pump return.
        Signal.FLOW_TEMP: ((_S, "actual_supply_temperature"),),
        Signal.RETURN_TEMP: ((_S, "return_temperature"),),
        Signal.DHW_TEMP: ((_S, "dhw_actual_temperature"),),
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING),
    activity_values={
        "off": Activity.OFF,
        "heating": Activity.HEATING,
        "cooling": Activity.COOLING,
        "dhw": Activity.DHW,
        "defrost": Activity.DEFROST,
        "pool": Activity.OTHER,
        "pool_heat": Activity.OTHER,
        "alarm": Activity.OTHER,
    },
)
