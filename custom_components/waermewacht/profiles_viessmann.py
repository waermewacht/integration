"""Source template: Viessmann heat pumps via the core integration vicare.

Read at Home Assistant core dev 8f785c4 (2026-10-28) with PyViCare 2.63.0,
the version its manifest pins. Derived from source code and the test data of
both projects, not from a real installation: experimental until a recorded
fixture exists.

Unique ids are "<gateway serial>_<device serial or id>-<key>[-<component>]"
(entity.py); "-" in the device serial is replaced by "_", so the first "-"
ends the prefix. Some keys contain spaces ("power consumption today").
Component entities end in "-<index>"; only compressor 0 is followed.

Two controller generations, see docs/ENTWICKLUNG.md:
- E3 (Vitocal 150-A ... 252-A): electricity per mode as today's sum of the
  cloud, compressor, starts. The compressor phase is off / preparing /
  not_ready / ready - no mode, no defrost; those values are foreign.
- Vitotronic (Vitocal 200-S, 222-S, 300-G, 333-G ...): compressor, phase
  with defrost, hot water charging, starts; no energy at all.
There is no heat counter in Home Assistant (PyViCare has no getter), so
there are no ratios: cycling and electricity only.

The cloud's day values are said to start anew at midnight UTC (forum
reports, unconfirmed). Counting days in UTC is the safe choice: if the cloud
uses local midnight after all, a day's first value is only booked an hour or
two late, nothing is lost; the other way round most of a day would land in
the wrong day.
"""

from __future__ import annotations

from .model import Activity, Signal
from .profiles import Template

# Compressor phase after vicare's normalize_state ("-" -> "_"), Vitotronic
# vocabulary (setPhase enum in PyViCare test data Vitocal 300-G, 333-G,
# 200-S AWB). A defrost run is announced by preparing_defrost; passive
# defrost (fan only, compressor off) counts as a defrost as well.
VICARE_ACTIVITY: dict[str, Activity | None] = {
    "heating": Activity.HEATING,
    "cooling": Activity.COOLING,
    "defrost": Activity.DEFROST,
    "preparing_defrost": Activity.DEFROST,
    "passive_defrost": Activity.DEFROST,
    "preparing": Activity.OFF,
    "pause": Activity.OFF,
    "off": Activity.OFF,
    "null": None,  # seen on a Vitocal 200-A outdoor unit: no information
}
# E3 vocabulary: "ready" is reported while the compressor runs as well.
VICARE_FOREIGN = frozenset({"ready", "not_ready"})

_S, _B = "sensor", "binary_sensor"
VICARE = Template(
    experimental=True,
    key="vicare",
    label="Viessmann ViCare",
    platform="vicare",
    device=None,
    signals={
        # E3 only; today's sum of the cloud (0.1 kWh), enabled by default.
        Signal.ELEC_HEATING: ((_S, "energy_summary_consumption_heating_currentday"),),
        Signal.ELEC_DHW: ((_S, "energy_dhw_summary_consumption_heating_currentday"),),
        # Only where heating.power.consumption.cooling is enabled (Vitocal 151-A).
        Signal.ELEC_COOLING: ((_S, "energy_consumption_cooling_today"),),
        Signal.COMPRESSOR: ((_B, "compressor_active-0"),),
        # Mode and defrost on Vitotronic only; foreign on E3 (see above).
        Signal.ACTIVITY: ((_S, "compressor_phase-0"),),
        # heating.dhw.charging, Vitotronic only.
        Signal.DHW_FLAG: ((_B, "charging_active"),),
        Signal.STARTS_TOTAL: ((_S, "compressor_starts-0"),),
        Signal.OUTDOOR_TEMP: ((_S, "outside_temperature"),),
        # Heat pump flow (secondary circuit), not a heating circuit after its
        # mixer (supply_temperature-N) nor the common supply.
        Signal.FLOW_TEMP: ((_S, "secondary_circuit_supply_temperature"),),
        Signal.RETURN_TEMP: (
            (_S, "return_temperature"),
            (_S, "secondary_circuit_return_temperature"),
        ),
        Signal.DHW_TEMP: ((_S, "dhw_storage_temperature"),),
        # Left out: volumetric_flow (no device class, feature deprecated in
        # PyViCare), heating rod (starts/hours only, no energy).
    },
    required=(Signal.COMPRESSOR,),
    activity_values=VICARE_ACTIVITY,
    activity_foreign=VICARE_FOREIGN,
    day_values=True,
    day_timezone="UTC",
)
