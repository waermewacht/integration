"""Source template for Waterkotte heat pumps (HACS integration waterkotte_heatpump).

Pure Python, no Home Assistant imports. Derived from the source code of
marq24/ha-waterkotte 2026.10.7 (commit 311382f, 2026-10-24) on 2026-10-28
(__init__.py, const.py, binary_sensor.py, sensor.py, config_flow.py,
pywaterkotte_ha/tags.py), not from a real installation: experimental until a
recorded fixture exists. EcoTouch and EasyCon controllers share the keys.

Unique ids (__init__.py, `WKHPBaseEntity.unique_id`): "waterkotte_heatpump.<key>"
in lower case; with the setup option "add_serial_as_id" (several heat pumps,
off by default) "waterkotte_heatpump.<key>_<serial>". The serial is
"WE"/"00" plus digits (`_decode_ro_sn`), or a random uuid in hex when the
controller reports none; neither contains "_". Entity ids are
"<domain>.wkh_[<serial>_]<key>". `id_format` tells key and serial apart by
the known keys.

Energy: every counter is the controller's sum of the current year (tags
A444..A463, float word pairs, kWh with decimals, state class
total_increasing). It starts anew on 1 January (Wärmewacht's Counter takes
the big drop as a reset). If "Gesamt" (all years, D428) is selected in the
web interface instead of a year (I1261), the same tags carry lifetime sums;
switching the view in the middle of a year makes the values jump.
Heat exists per mode (heating, hot water, cooling, pool), electricity only
for the compressor as a whole (A444), the backup heater (A448) and the source
pump (A446, disabled by default). The compressor electricity is booked to
the mode running (ELEC_TOTAL), the backup heater likewise (AUX_TOTAL). The
source pump is left out (outside the boundary of the other templates), as is
"energy_consumption_total_year" (compressor + source pump + heater, would
book the heater twice).

Activity: no activity entity and no defrost signal (most Waterkotte units
are brine or water source). Bits of the operating state I51 as binary
sensors: "state_water" (bit 8, hot water) and "state_cooling" (bit 7,
disabled by default). Heating has no state of its own: "status_heating"
(I137) is the release, on while the compressor stands as well, so it is not
used. A run that is neither hot water nor cooling is heating (core rule in
activity.combine). Pool heating has no signal of its own and counts as
heating; its heat counter is left out.
No compressor start counter and no flow rate entity exist.
"""

from __future__ import annotations

from .model import Signal
from .profiles import Template

PLATFORM = "waterkotte_heatpump"
_S, _B = "sensor", "binary_sensor"
WATERKOTTE = Template(
    experimental=True,
    key="waterkotte",
    label="Waterkotte",
    platform=PLATFORM,
    # "waterkotte_heatpump.<key>[_<serial>]": the serial is alphanumeric
    # with digits ("we0612345" or a uuid in hex); key endings such as
    # "_1h" or "_setpoint" are none.
    id_format=r"waterkotte_heatpump\.(?P<key>{key})"
    r"(?:_(?P<prefix>(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{5,}))?",
    signals={
        # Yearly sums in kWh (see above).
        Signal.HEAT_HEATING: ((_S, "heating_energy_production_year"),),
        Signal.HEAT_DHW: ((_S, "hot_water_energy_production_year"),),
        # Whether passive cooling (source pump only) counts here is not
        # documented; with it the EER has heat without compressor electricity.
        Signal.HEAT_COOLING: ((_S, "cooling_energy_year"),),
        Signal.ELEC_TOTAL: ((_S, "compressor_electric_consumption_year"),),
        Signal.AUX_TOTAL: ((_S, "electrical_heater_electric_consumption_year"),),
        # Compressor 1 (I51 bit 3); a second compressor ("state_compressor2",
        # bit 4) is not followed.
        Signal.COMPRESSOR: ((_B, "state_compressor"),),
        Signal.DHW_FLAG: ((_B, "state_water"),),
        Signal.COOLING_FLAG: ((_B, "state_cooling"),),
        Signal.OUTDOOR_TEMP: ((_S, "temperature_outside"),),
        Signal.FLOW_TEMP: ((_S, "temperature_flow"),),
        Signal.RETURN_TEMP: ((_S, "temperature_return"),),
        Signal.DHW_TEMP: ((_S, "temperature_water"),),
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_TOTAL),
)
