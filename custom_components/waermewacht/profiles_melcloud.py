"""Source template: Mitsubishi Ecodan (Air-to-Water) via MELCloud.

Home Assistant core integration `melcloud` (platform "melcloud"), read at
core dev 8f785c4 (2026-10-28) with python-melcloud 0.1.3 (module pymelcloud).
Derived from source code, not from a real installation: experimental.

Unique ids are "<serial>-<mac>-<key>" (entity.py, MelCloudDescriptionEntity);
zone 2 sensors end in "-zone-2", the water heater has the bare serial, the
zone climates "<serial>-<zone>". Split at a known key at the end.

Energy: the six "Daily ..." values of MELCloud's ListDevices (HA 2026.5+),
kWh, total_increasing in HA; heat (produced) and all cooling values are
disabled by default in melcloud. They are the previous day's totals
(0.01 kWh), constant all day and changing once just after midnight:
ListDevices dumps show DailyEnergyConsumedDate = yesterday next to them, a
5-minute log of an Ecodan shows the value unchanged while it heated, and
OpenEnergyMonitor users report the same (research 2026-10-28, see
docs/ENTWICKLUNG.md). Wärmewacht books them into the previous day
(previous_day); today's figures of this source stay empty.

Left out on purpose: the compressor frequency (key "fan_frequency") comes
from ListDevices, refreshed at most every 30 minutes: runs and starts from
it would be wrong. The status (defrost, hot water, heating) exists only as
the attribute "status" of the water heater, not as an entity state. No
starts, no backup heater energy.
"""

from __future__ import annotations

from .model import Signal
from .profiles import Template

_S = "sensor"
MELCLOUD = Template(
    experimental=True,
    key="melcloud",
    label="Mitsubishi Ecodan (MELCloud)",
    platform="melcloud",
    # "<serial>-<mac>-<key>": the prefix holds a "-" itself, which keeps
    # "<gateway>-<key>" ids of other integrations out.
    id_format=r"(?P<prefix>.*[^-]-+[^-].*)-(?P<key>{key})",
    signals={
        Signal.HEAT_HEATING: ((_S, "daily_heating_energy_produced"),),
        Signal.HEAT_DHW: ((_S, "daily_hot_water_energy_produced"),),
        Signal.HEAT_COOLING: ((_S, "daily_cooling_energy_produced"),),
        Signal.ELEC_HEATING: ((_S, "daily_heating_energy_consumed"),),
        Signal.ELEC_DHW: ((_S, "daily_hot_water_energy_consumed"),),
        Signal.ELEC_COOLING: ((_S, "daily_cooling_energy_consumed"),),
        # 1 °C, updated every 1-2 hours by the unit (melcloud docs).
        Signal.OUTDOOR_TEMP: ((_S, "outside_temperature"),),
        # System flow/return (ListDevices FlowTemperature/ReturnTemperature),
        # only created when reported; not the zone values.
        Signal.FLOW_TEMP: ((_S, "system_flow_temperature"),),
        Signal.RETURN_TEMP: ((_S, "system_return_temperature"),),
        Signal.DHW_TEMP: ((_S, "tank_temperature"),),
    },
    # No compressor signal (see above): heat and electricity of heating only.
    required=(Signal.HEAT_HEATING, Signal.ELEC_HEATING),
    day_values=True,
    previous_day=True,
)
