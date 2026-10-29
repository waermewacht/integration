"""Source template: Daikin Altherma (E-series) via the P1P2MQTT bridge.

Firmware Arnold-n/P1P2Serial, P1P2MQTT-bridge v0.9.58rc34 (HA_SW in
P1P2_Config.h), read at main c355262 (2026-09-13) on 2026-10-29:
examples/P1P2MQTT-bridge/P1P2MQTT-bridge.ino (publishHomeAssistantConfig,
buildMqttTopic), P1P2_HomeAssistant.h (units, device and state classes),
P1P2_NetworkParams.h (default names), P1P2_ParameterConversion.h (E_SERIES
decoding), doc/HomeAssistant.md and doc/LogicalFormat/Daikin-protocol-
EHYHBX08AAV3.md. Home Assistant MQTT discovery, platform "mqtt" (shared with
EMS-ESP and the F1p bridge). Derived from source code, not from a real
installation: experimental.

Unique ids (publishHomeAssistantConfig): "<deviceName>_<bridgeName>_<cat>
<src>_<name>_<src>", e.g. "P1P2MQTT_bridge0_T1_Temperature_R4T_Return_Water_1".
deviceName ("P1P2MQTT") and bridgeName ("bridge0") are the defaults, both
user-changeable (8 characters each); they are the prefix (one bridge, one heat
pump). <cat> is the firmware's category (T temperature, M measurement, S
setting/status, C counter), <src> the packet source (1: reply of the heat
pump, packet source 0x40). The key of a signal is the whole tail
"<cat><src>_<name>_<src>": the same name exists with another category or
source in raw parameter reports. Names are English and fixed; entity ids
follow the device ("<bridgeName>_Sensors", "_Mode", "_DHW", "_Meters"; older
EEPROM settings give "HC_Sensors" ...) and the name.

Energy: "Electricity_Consumed_Compressor_<mode>", "Energy_Produced_
Compressor_<mode>" and "Electricity_Consumed_Backup_<mode>" are the heat
pump's own lifetime counters (packet 0xB8, subtypes 00 and 01, u24) in whole
kWh, device class energy, state class total_increasing (long-term statistics,
so a backfill works). The bridge does not integrate anything into kWh; its
"Production_Heatpump" (flow x delta T) and "Consumption_Heatpump" (external
meter via MQTT) are W only. The heat pump sends 0xB8 only when asked: the
main controller's counter menu, or the bridge's "Counter_Request_Function"
(once a minute, outside the P1/P2 timing rules). Without it the entities
appear late or never and stay unchanged: Wärmewacht then books nothing.
Whether "Produced" includes the backup heater is open in the source
("compressor or heatpump including BUH?"); on EJHA* all produced counters are
0. "Electricity_Consumed_Total" (ELEC_TOTAL) is left out: per-mode meters
exist, and whether the total includes the backup heater is unknown. DHW
entities exist only while the field settings say DHW operation (E-05) or a
tank (E-06) is installed (M.R.useDHW).

Compressor: binary sensor "Compressor" (packet 0x10 byte 18 bit 0), else the
frequency "Compressor_RPM" (Hz despite the name; packet 0x15 parameter 2,
only on models that send these parameters). Activity from flags: "Defrost_
Active" (0x10 byte 17 bit 1), "DHW_Demand" (0x12 byte 12 bit 7), "Climate_
Cooling" / "Climate_Heating" (0x10 byte 2 bits 1/0, the active space mode).
"Valve_DHW_Tank" and "DHW" are no DHW activity: on one real Altherma (third-
party notes, github.com/OneTwo3D/PredAHSPControl docs/entity_mapping.md,
2026-10-07) the valve stays on at rest and "DHW" is the DHW function's
on/off, while "DHW_Demand" was on exactly during DHW runs. The bridge's doc
calls DHW_Demand the DHW flow switch of hybrids: with a gas boiler for hot
water a tap may show as DHW.

Starts: "Starts_Compressor" (0xB8 subtype 04) without unit and state class.
Flow: "Flow" in L/min, state class measurement, no device class (0x13 byte
9; some systems report 0.0). Flow temperature: R1T (after the heat pump's
heat exchanger, before the backup heater or gas boiler) first, named
"Temperature_R1T_Leaving_Water" when the bridge is set to use R1T as LWT,
else "Temperature_R1T_HP2Gas_Water"; R2T (after the backup heater) last, it
reads -128 on some units.
"""

from __future__ import annotations

from .model import Signal
from .profiles import Template

# Heat pump reply (packet source 0x40) in the categories the firmware sets.
_T, _M, _S1, _C = "T1_", "M1_", "S1_", "C1_"


def _key(cat: str, name: str) -> str:
    """Tail of a unique id: "<cat><src>_<name>_<src>" (source 1)."""
    return f"{cat}{name}_1"


_S, _B = "sensor", "binary_sensor"
P1P2MQTT = Template(
    experimental=True,
    key="p1p2mqtt",
    label="Daikin Altherma (P1P2MQTT)",
    platform="mqtt",
    # "<deviceName>_<bridgeName>_<tail>"; the names may contain "_" too, so
    # the tail is found by the template's own keys, longest first.
    id_format=r"(?P<prefix>.+)_(?P<key>{key})",
    signals={
        # Lifetime counters of the heat pump, whole kWh, total_increasing.
        Signal.HEAT_HEATING: ((_S, _key(_C, "Energy_Produced_Compressor_Heating")),),
        Signal.HEAT_DHW: ((_S, _key(_C, "Energy_Produced_Compressor_DHW")),),
        Signal.HEAT_COOLING: ((_S, _key(_C, "Energy_Produced_Compressor_Cooling")),),
        Signal.ELEC_HEATING: (
            (_S, _key(_C, "Electricity_Consumed_Compressor_Heating")),
        ),
        Signal.ELEC_DHW: ((_S, _key(_C, "Electricity_Consumed_Compressor_DHW")),),
        Signal.ELEC_COOLING: (
            (_S, _key(_C, "Electricity_Consumed_Compressor_Cooling")),
        ),
        Signal.AUX_HEATING: ((_S, _key(_C, "Electricity_Consumed_Backup_Heating")),),
        Signal.AUX_DHW: ((_S, _key(_C, "Electricity_Consumed_Backup_DHW")),),
        Signal.COMPRESSOR: (
            (_B, _key(_S1, "Compressor")),
            (_S, _key(_M, "Compressor_RPM")),  # Hz
        ),
        Signal.DEFROST_FLAG: ((_B, _key(_S1, "Defrost_Active")),),
        Signal.DHW_FLAG: ((_B, _key(_S1, "DHW_Demand")),),
        Signal.COOLING_FLAG: ((_B, _key(_S1, "Climate_Cooling")),),
        Signal.HEATING_FLAG: ((_B, _key(_S1, "Climate_Heating")),),
        Signal.STARTS_TOTAL: ((_S, _key(_C, "Starts_Compressor")),),
        # Outside sensor (or external R6T), else the outdoor unit's own.
        Signal.OUTDOOR_TEMP: (
            (_S, _key(_T, "Temperature_Outside")),
            (_S, _key(_T, "Temperature_Outside_Unit")),
        ),
        Signal.FLOW_TEMP: (
            (_S, _key(_T, "Temperature_R1T_Leaving_Water")),
            (_S, _key(_T, "Temperature_R1T_HP2Gas_Water")),
            (_S, _key(_T, "Temperature_R2T_Leaving_Water")),
        ),
        Signal.RETURN_TEMP: ((_S, _key(_T, "Temperature_R4T_Return_Water")),),
        Signal.FLOW_RATE: ((_S, _key(_M, "Flow")),),  # L/min
        Signal.DHW_TEMP: ((_S, _key(_T, "Temperature_R5T_DHW_Tank")),),
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING),
)
