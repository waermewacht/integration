"""Source template: Mitsubishi Ecodan via the F1p CN105-to-MQTT bridge.

Firmware F1p/Home-Assistant-Mitsubishi-CN105-to-MQTT ("Ecodan Bridge", ESP32
or ESP8266 on the CN105 port of the FTC), read at tag v7.1.1 (commit e2ab484,
2026-10-23): MQTTDiscovery.h, MQTTConfig.h (PublishDiscoveryTopics),
ECODAN_Bridge.ino (SystemReport, EnergyReport), EcodanDecoder.h/.cpp.
Home Assistant MQTT discovery, platform "mqtt" (shared with EMS-ESP).
Derived from source code, not from a real installation: experimental.

Unique ids are MQTT_SENSOR_UNIQUE_ID[i] + deviceId (MQTTConfig.h:728), e.g.
"ashp_consumed_heat_<id>". The deviceId is the chip id in lower-case hex by
default (ESP32: efuse MAC, ESP8266: chip id; user-changeable in the setup
portal). Some keys have no trailing "_" ("ashp_comp_op_times<id>"), and some
keys start with another key ("ashp_dhw_temp_" / "ashp_dhw_temp_thw5a_"), so
the split matches against the full list of the firmware's keys, longest
first. The keys do not depend on the firmware language; names and entity ids
do (English: "sensor.ecodan_ashp_<name>").

Discovery attributes (MQTTConfig.h:733-739): every entity with a unit gets a
device class for units below index 8 and state_class "measurement" except
for kWh. So the energy values are kWh, device class energy, *without* state
class: no long-term statistics (no backfill before the setup), but usable
for Wärmewacht's energy selector as they are.

Energy: "Consumed/Delivered Heating/Cooling/DHW Yesterday", 0.01 kWh, from
the FTC's packets 0xA1 (consumed) and 0xA2 (delivered), which carry a date
(EcodanDecoder.cpp Process0xA1/0xA2, polled in the same cycle). EnergyReport
publishes them only when that date is yesterday; otherwise it substitutes
the bridge's own integrated estimate of yesterday (cumulativeEnergyYesterday)
or 0, and nothing at all between 23:59 and 00:05. The values are the previous
day's totals: previous_day.

Activity: "System Operation Mode" (SystemOperationModeString, English in all
firmware languages), overridden with "Defrosting" while the defrost state is
2 (ECODAN_Bridge.ino SystemReport). The separate "Defrost" sensor has the
words Off / Standby / Defrosting / Waiting Restart, not on/off, so it is no
DEFROST_FLAG. Compressor: frequency in Hz. Starts: "Compressor Start
Quantity", the FTC's count in hundreds (value template "* 100"), state class
measurement. Immersion and booster heaters are on/off only: no aux energy.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Activity, Signal
from .profiles import Template

# MQTT_SENSOR_UNIQUE_ID of the air-to-water bridge, v7.1.1, in firmware order
# (0-104 sensor, 105-109 climate, 110-121 switch, 122-126 select, 127 update,
# 128 text). The air-to-air variant uses two-letter ids ("aa<id>").
F1P_KEYS: tuple[str, ...] = (
    "ashp_bridge_lwt_",
    "ashp_bridge_firmware_",
    "ashp_bridge_rssi_",
    "ashp_ftc_",
    "ashp_op_mode_",
    "ashp_heater_return_",
    "ashp_heater_flow_",
    "ashp_outside_air_temp_",
    "ashp_defrost_status_",
    "ashp_pump_power_",
    "ashp_compressor_freq_",
    "ashp_flow_rate_",
    "ashp_run_hours_",
    "ashp_max_flow_temp_",
    "ashp_min_flow_temp_",
    "ashp_boiler_flow_temp_",
    "ashp_boiler_return_temp_",
    "ashp_mixing_tank_temp_",
    "ashp_refrige_temp_",
    "ashp_immersion_active_",
    "ashp_booster_active_",
    "ashp_primary_water_pump_active_",
    "ashp_water_pump_2_active_",
    "ashp_3WayValve_1_active_",
    "ashp_3WayValve_2_active_",
    "ashp_dhw_temp_",
    "ashp_dhw_temp_thw5a_",
    "ashp_dhw_prohibit_",
    "ashp_dhw_active_",
    "ashp_dhw_mode_",
    "ashp_legionella_setpoint_",
    "ashp_dhw_max_tempdrop_",
    "ashp_dhw_phase_",
    "ashp_z1_flow_temp_",
    "ashp_z1_return_temp_",
    "ashp_z2_flow_temp_",
    "ashp_z2_return_temp_",
    "ashp_twozone_z1_working_",
    "ashp_twozone_z2_working_",
    "ashp_consumed_heat_",
    "ashp_delivered_heat_",
    "ashp_consumed_cool_",
    "ashp_delivered_cool_",
    "ashp_consumed_dhw_",
    "ashp_delivered_dhw_",
    "ashp_total_consumed_",
    "ashp_total_delivered_",
    "ashp_heat_cop_",
    "ashp_cool_cop_",
    "ashp_dhw_cop_",
    "ashp_total_cop_",
    "ashp_refrige_flt_code_",
    "ashp_err_code_",
    "ashp_flt_code_",
    "ashp_delta_t_",
    "ashp_est_heat_pwr_out_",
    "ashp_est_cool_pwr_out_",
    "ashp_heat_active_",
    "ashp_cool_active_",
    "ashp_z1h_prohibit_",
    "ashp_z1c_prohibit_",
    "ashp_z2h_prohibit_",
    "ashp_z2c_prohibit_",
    "ashp_z1_fsp",
    "ashp_z2_fsp",
    "ashp_z1_tstat_demand",
    "ashp_z2_tstat_demand",
    "ashp_ext_tstat_demand",
    "ashp_water_pump_4_active",
    "ashp_water_pump_3_active",
    "ashp_water_pump_13_active",
    "ashp_input_power_",
    "ashp_est_pwr_in_",
    "ashp_ftc_sw_v_",
    "ashp_dhw_eco_boost_",
    "ashp_mix_valve_pos_",
    "ashp_bridge_cpu_",
    "ashp_booster2_active_",
    "ashp_instant_cop_",
    "ashp_liquid_temp_",
    "ashp_comp_op_times",
    "ashp_th4_discharge_",
    "ashp_subcool_",
    "ashp_th8_",
    "ashp_th6_",
    "ashp_fan1_rpm_",
    "ashp_fan2_rpm_",
    "ashp_LEVA_",
    "ashp_LEVB_",
    "ashp_th32_",
    "ashp_est_dhw_pwr_out_",
    "ashp_est_dhw_pwr_in_",
    "ashp_est_heating_pwr_out_",
    "ashp_est_heating_pwr_in_",
    "ashp_est_cooling_pwr_in_",
    "ashp_superheat_",
    "ashp_actv_ctrl_cycl_prtc_",
    "ashp_outdoor_sw_v_",
    "ashp_mel_status_",
    "ashp_dip_sw_conf_",
    "ashp_pri_pump_pwm_",
    "gshp_brine_in_",
    "gshp_brine_out_",
    "ashp_est_cop_today",
    "ashp_booster2pl_active_",
    "ashp_dhw_climate_",
    "ashp_Zone1_climate_",
    "ashp_Zone2_climate_",
    "ashp_Zone1_flow_climate_",
    "ashp_Zone2_flow_climate_",
    "ashp_dhw_boost_",
    "ashp_systempower_",
    "ashp_holidaymode_",
    "ashp_svr_control_mode_",
    "ashp_svrctrol_dhw_",
    "ashp_svrctrol_z1h_",
    "ashp_svrctrol_z1c_",
    "ashp_svrctrol_z2h_",
    "ashp_svrctrol_z2c_",
    "ashp_svrctrol_norm_dhw_",
    "ashp_actv_ctrl_cycl_",
    "ashp_melcloud_readonly_",
    "ashp_dhw_mode",
    "ashp_heat_cool_mode",
    "ashp_heat_cool_mode_z2",
    "ashp_unit_size_",
    "ashp_glycol_",
    "ashp_bridge_fmwre_upd_",
    "ashp_web_password_",
)
_LONGEST_FIRST = sorted(F1P_KEYS, key=len, reverse=True)


def split_key_prefix(unique_id: str) -> tuple[str, str] | None:
    """(deviceId, key) of "<key><deviceId>", None if no F1p key fits.

    The longest key first ("ashp_dhw_temp_thw5a_" before "ashp_dhw_temp_");
    a deviceId starting with "_" would mean a shorter key ate part of a
    longer one ("ashp_dhw_mode" of "ashp_dhw_mode_<id>"), so it is refused.
    """
    for key in _LONGEST_FIRST:
        if unique_id.startswith(key):
            device_id = unique_id[len(key) :]
            if device_id and not device_id.startswith("_"):
                return device_id, key
            return None
    return None


@dataclass(frozen=True)
class KeyPrefixTemplate(Template):
    """A template whose unique ids are "<key><deviceId>"."""

    def split(self, unique_id: str) -> tuple[str, str] | None:
        return split_key_prefix(unique_id)


# SystemOperationModeString (EcodanDecoder.h) plus "Defrosting" (SystemReport).
# Legionella is a hot water charge to the disinfection temperature. Zero V
# and Frost Protect are no mode of their own (OTHER, as any unknown word).
F1P_ACTIVITY: dict[str, Activity | None] = {
    "off": Activity.OFF,
    "hot water": Activity.DHW,
    "legionella": Activity.DHW,
    "heating": Activity.HEATING,
    "heating eco": Activity.HEATING,
    "cooling": Activity.COOLING,
    "defrosting": Activity.DEFROST,
    "zero v": Activity.OTHER,
    "frost protect": Activity.OTHER,
}

_S = "sensor"
F1P = KeyPrefixTemplate(
    experimental=True,
    key="f1p",
    label="Mitsubishi Ecodan (F1p Ecodan Bridge)",
    platform="mqtt",
    device=None,
    signals={
        # Previous day's totals, kWh, device class energy, no state class.
        Signal.HEAT_HEATING: ((_S, "ashp_delivered_heat_"),),
        Signal.HEAT_DHW: ((_S, "ashp_delivered_dhw_"),),
        Signal.HEAT_COOLING: ((_S, "ashp_delivered_cool_"),),
        Signal.ELEC_HEATING: ((_S, "ashp_consumed_heat_"),),
        Signal.ELEC_DHW: ((_S, "ashp_consumed_dhw_"),),
        Signal.ELEC_COOLING: ((_S, "ashp_consumed_cool_"),),
        Signal.COMPRESSOR: ((_S, "ashp_compressor_freq_"),),  # Hz
        Signal.ACTIVITY: ((_S, "ashp_op_mode_"),),
        # No STARTS_TOTAL: "ashp_comp_op_times" counts in hundreds (FTC
        # service code 3) and only once the bridge has read it; Wärmewacht
        # counts the starts itself from the compressor.
        Signal.OUTDOOR_TEMP: ((_S, "ashp_outside_air_temp_"),),
        # Heat pump outlet/inlet (HeaterFlow/HeaterReturn), not the zones'
        # or the external boiler's.
        Signal.FLOW_TEMP: ((_S, "ashp_heater_flow_"),),
        Signal.RETURN_TEMP: ((_S, "ashp_heater_return_"),),
        Signal.FLOW_RATE: ((_S, "ashp_flow_rate_"),),  # whole L/min
        # Tank sensor (TH5), not the upper one (THW5A).
        Signal.DHW_TEMP: ((_S, "ashp_dhw_temp_"),),
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING),
    activity_values=F1P_ACTIVITY,
    day_values=True,
    previous_day=True,
)
