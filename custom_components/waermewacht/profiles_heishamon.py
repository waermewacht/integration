"""Source template for Panasonic Aquarea heat pumps via HeishaMon.

Pure Python, no Home Assistant imports. Derived from the source code of the
HACS integration kamaradclimber/heishamon-homeassistant (domain `aquarea`,
2.12.1, commit 086c1a9, 2026-10-26) and the MQTT topic list of the HeishaMon
firmware (heishamon/HeishaMon); not yet checked against a real installation,
so experimental.

Why this integration: the HeishaMon firmware publishes plain MQTT topics but
no Home Assistant MQTT discovery. HeishaMon's own Home Assistant guide
points to this integration first; its alternative, the YAML package
`heishamon.yaml`, declares its sensors without `unique_id`, so they never
reach the entity registry and cannot be found by a template (users of it
pick the entities by hand).

Unique ids are "<config entry id>-<topic id>" (`TOPxx`, `SETxx` for switches
and selects, which also carry the TOP value). The entry id (UUID hex or ULID)
has no "-", so `Template.split` with `device=None` fits as it is.

Energy: HeishaMon delivers power per mode only (W, TOP15/16 heating, TOP38/39
cooling, TOP40/41 DHW; on K/L series the extra block XTOP0-5, merged into the
same entities). The integration adds a left Riemann sum in kWh for each of
them ("<entry>-TOPxx_integration", state class total, entity category
diagnostic). Those are the counters used here.
"""

from __future__ import annotations

from .model import Activity, Signal
from .profiles import Template

_S = "sensor"

HEISHAMON = Template(
    experimental=True,
    key="heishamon",
    label="HeishaMon (Panasonic Aquarea)",
    platform="aquarea",
    device=None,
    signals={
        Signal.HEAT_HEATING: ((_S, "TOP15_integration"),),
        Signal.HEAT_DHW: ((_S, "TOP40_integration"),),
        # The cooling power sensors are disabled by default in `aquarea`;
        # their sums exist but stay unknown until the user enables them.
        Signal.HEAT_COOLING: ((_S, "TOP38_integration"),),
        Signal.ELEC_HEATING: ((_S, "TOP16_integration"),),
        Signal.ELEC_DHW: ((_S, "TOP41_integration"),),
        Signal.ELEC_COOLING: ((_S, "TOP39_integration"),),
        # No energy of the backup heater: only on/off (TOP60/61) and hours.
        Signal.COMPRESSOR: ((_S, "TOP8"),),  # Compressor_Freq in Hz
        # Three-way valve "Room"/"Tank": the mode, but no defrost and no
        # cooling (see `heishamon_activity` for the full rule).
        Signal.ACTIVITY: ((_S, "TOP20"),),
        Signal.STARTS_TOTAL: ((_S, "TOP12"),),  # Operations_Counter
        Signal.OUTDOOR_TEMP: ((_S, "TOP14"),),
        Signal.FLOW_TEMP: ((_S, "TOP6"),),  # Main_Outlet_Temp
        Signal.RETURN_TEMP: ((_S, "TOP5"),),  # Main_Inlet_Temp
        Signal.FLOW_RATE: ((_S, "TOP1"),),  # Pump_Flow in L/min
        # Sums over the modes, made by the integration.
        Signal.HEAT_POWER: ((_S, "heishamon_w_production"),),
        Signal.ELEC_POWER: ((_S, "heishamon_w_consumption"),),
        # See ACTIVITY_PARTS below: the defrost switch and the set mode.
        Signal.DEFROST_FLAG: (("switch", "SET12"), ("binary_sensor", "SET12")),
        Signal.COOLING_MODE: (("select", "SET9"),),
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING),
    activity_values={"room": Activity.HEATING, "tank": Activity.DHW},
)

# Entities the full activity needs besides the valve, (domain, key) as in
# `Template.signals`. Not signals yet: the core takes one activity entity.
# Defrosting_State (TOP26) is the switch SET12 ("Aquarea Defrost routine",
# writing it forces a defrost; Wärmewacht only reads it) and a read-only
# binary sensor with the same unique id, disabled by default.
# Operating_Mode_State (TOP4) is the select SET9: the set mode, reported as
# "Auto(Cool)…" while auto mode cools.
ACTIVITY_PARTS: dict[str, tuple[tuple[str, str], ...]] = {
    "valve": ((_S, "TOP20"),),
    "defrost": (("switch", "SET12"), ("binary_sensor", "SET12")),
    "operating_mode": (("select", "SET9"),),
}

_UNKNOWN = (None, "", "unknown", "unavailable")


def heishamon_activity(
    valve: str | None, defrost: str | None, operating_mode: str | None
) -> Activity | None:
    """Activity from the states of the three entities of `ACTIVITY_PARTS`.

    Defrost wins; the valve on "Tank" is hot water; on "Room" it is cooling
    when the set mode cools ("Cool only", "Cool+DHW", "Auto(Cool)…"), else
    heating. None while the valve is unknown.
    """
    if defrost == "on":
        return Activity.DEFROST
    if valve in _UNKNOWN:
        return None
    match valve.strip().casefold():
        case "tank":
            return Activity.DHW
        case "room":
            mode = (operating_mode or "").casefold()
            return Activity.COOLING if "cool" in mode else Activity.HEATING
    return Activity.OTHER
