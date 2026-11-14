"""Source template: Bosch/Buderus Home Comfort (HACS `bosch_buderus_heating`).

Pure Python, no Home Assistant imports. Proposed by the integration's author
in waermewacht/integration#7 (2026-11-14) and checked against the source of
SoftwareSchmied/ha-bosch-buderus-heating v0.9.1 (2026-11-14): sensor.py
(energy keys), local_only.py and local_only_sensor.py (local unique ids and
signals) and its entity baseline tests/fixtures/w0-entity-baseline.json
(plant "k40": unique ids, units, device and state classes, enum options,
entities disabled by default). Not from a real installation of Wärmewacht:
experimental until a recorded fixture exists.

The integration reads the Bosch PointT cloud (K30/K40 gateways, MX300/MX400,
iCom gateways) and, from 0.9 on, optionally a K40/K40RF gateway locally
(firmware 15.00.01 or newer, reading only). Unique ids "<gateway>:<key>": the
key is the PointT resource path with ":" for "/", a few base values have
fixed names "gateway:<name>", values only the local access delivers are
"local_only:<path>" (local_only_sensor.py, UNIQUE_ID_PART). A local value
the cloud later serves moves to the cloud id; the entity id stays.

Energy: lifetime counters per mode from /heatSources/emon (not day values,
no `day_values`), about every 5 minutes. Electricity "<mode>Consumption:
compressor" and the backup heater ":eheater" are total_increasing; heat
("gateway:<mode>_heat_produced" = emon outputProduced) is total, because it
drops by 0.2-0.6 kWh during a defrost (the heat taken from the house, issue
#7). counter.py keeps the old maximum as the baseline for such dips, so
only the net heat is booked.

Compressor: the local heat pump signal SRC.CUHP.HP1.CompressorStatus
(on/off, disabled by default), then the local display signal
SRC.CUHP.HMI.CompressorActive (on/off, enabled), else the cloud modulation
above 0. Activity: /heatSources/compressor/status with the PointT values
(as bosch_homecom and buderus_ha). Flow: the local primary flow TC1 at the
heat pump (/heatSources/additionalHeater/flowTemp) first, else the system
supply (behind a buffer). System pressure "gateway:system_pressure" (bar).
"""

from __future__ import annotations

from .model import Signal
from .profiles import POINTT_ACTIVITY, Template

PLATFORM = "bosch_buderus_heating"
_S = "sensor"
_LOCAL = "local_only:"
BOSCH_BUDERUS = Template(
    experimental=True,
    key="bosch_buderus",
    label="Bosch/Buderus Home Comfort",
    platform=PLATFORM,
    # "<gateway>:<key>"; keys contain ":", the gateway id does not.
    id_format=r"(?P<prefix>[^:]+):(?P<key>.+)",
    signals={
        Signal.HEAT_HEATING: ((_S, "gateway:heating_heat_produced"),),
        Signal.HEAT_DHW: ((_S, "gateway:hot_water_heat_produced"),),
        Signal.HEAT_COOLING: (
            (_S, "heatSources:emon:coolingConsumption:outputProduced"),
        ),
        Signal.ELEC_HEATING: ((_S, "heatSources:emon:chConsumption:compressor"),),
        Signal.ELEC_DHW: ((_S, "heatSources:emon:dhwConsumption:compressor"),),
        Signal.ELEC_COOLING: ((_S, "heatSources:emon:coolingConsumption:compressor"),),
        Signal.AUX_HEATING: ((_S, "heatSources:emon:chConsumption:eheater"),),
        Signal.AUX_DHW: ((_S, "heatSources:emon:dhwConsumption:eheater"),),
        Signal.COMPRESSOR: (
            (_S, _LOCAL + "signals:SRC.CUHP.HP1.CompressorStatus"),
            (_S, _LOCAL + "signals:SRC.CUHP.HMI.CompressorActive"),
            (_S, "gateway:modulation"),
        ),
        Signal.ACTIVITY: ((_S, "heatSources:compressor:status"),),
        Signal.STARTS_TOTAL: ((_S, "heatSources:hs1:numberOfStarts:total"),),
        Signal.RUNTIME_HEATING: ((_S, "heatSources:hs1:workingTime:ch"),),
        Signal.STARTS_HEATING: ((_S, "heatSources:hs1:numberOfStarts:ch"),),
        Signal.OUTDOOR_TEMP: ((_S, "gateway:outdoor_temperature"),),
        Signal.FLOW_TEMP: (
            (_S, _LOCAL + "heatSources:additionalHeater:flowTemp"),
            (_S, "gateway:supply_temperature"),
        ),
        Signal.RETURN_TEMP: ((_S, "gateway:return_temperature"),),
        Signal.DHW_TEMP: ((_S, "gateway:hot_water_temperature"),),
        Signal.SYSTEM_PRESSURE: ((_S, "gateway:system_pressure"),),
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING),
    activity_values=POINTT_ACTIVITY,
)
