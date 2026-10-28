"""Source template: Vaillant (also Saunier Duval, Bulex) via the myVAILLANT
cloud, HACS integration mypyllant (signalkraft/mypyllant-component).

Read at tag v0.9.19 (commit c8cb4c4) with myPyllant 0.9.18 (a4b8773), the
version its manifest pins. Derived from source code only: experimental until
a fixture of a real registry exists.

Energy sensors ("DataSensor", sensor.py) have the unique id
"mypyllant_<system id>_<device uuid>_<da>_<de>": de is the position of the
device in the system, da the position of the series in the device's data
list. That list is in API order and differs between installations (myPyllant
test data: "heat generated" heating before or after hot water), so the
position tells nothing. What a series is, is only in the entity name, which
mypyllant builds in English from the API values (no translation key):
"<home> Device <de> <device name> <Energy Type> <Operation Mode>". The
registry keeps it as original_name; a user's rename does not touch it.

The state is today's sum of the completed hours in Wh, rounded to 100 Wh,
set to 0 at 00:00:01 and fetched only once at load unless the option
"Seconds between energy data updates" is set. Every fetch also writes the
hourly buckets of yesterday and today as external statistics
"mypyllant:<unique id lowercased, '-' -> '_'>" (sum in Wh, unrounded, only
completed hours). Wärmewacht books from those (hourly_statistics).

A heat pump is the device with "Earned Environment Energy" series; another
device of the system with electricity for hot water is its backup heater.
There is no compressor signal and no defrost.
"""

from __future__ import annotations

from collections.abc import Iterable

from .model import Activity, Signal
from .profiles import RegistryEntry, Template

PLATFORM = "mypyllant"
_PREFIX = f"{PLATFORM}_"

# English words mypyllant builds the names from (enum value, "_" -> " ",
# title case): myPyllant DeviceData.energy_type and operation_mode.
_ENERGY = {
    "Consumed Electrical Energy": "elec",
    "Heat Generated": "heat",
    "Earned Environment Energy": "env",
}
_MODES = {"Heating": "heating", "Domestic Hot Water": "dhw", "Cooling": "cooling"}
_SUFFIXES = {
    f" {energy} {mode}": f"{e}_{m}"
    for energy, e in _ENERGY.items()
    for mode, m in _MODES.items()
}


def split_data_sensor(unique_id: str) -> tuple[str, str] | None:
    """(system id, device uuid) of an energy sensor's unique id, else None."""
    if not unique_id.startswith(_PREFIX):
        return None
    parts = unique_id[len(_PREFIX) :].rsplit("_", 3)
    if len(parts) != 4:
        return None
    system, device, da, de = parts
    if not (system and device and da.isdigit() and de.isdigit()):
        return None
    return system, device


def data_key(original_name: str | None) -> str | None:
    """'<energy>_<mode>' ("heat_dhw") from the name mypyllant gave the sensor."""
    if not original_name:
        return None
    return next(
        (key for suffix, key in _SUFFIXES.items() if original_name.endswith(suffix)),
        None,
    )


def _domain(entry: RegistryEntry) -> str:
    return entry.entity_id.split(".", 1)[0]


class VaillantTemplate(Template):
    """Groups by heat pump; keys "hp:<key>", "aux:<key>" and, for the
    system's other entities, the unique id after "mypyllant_<system>_"
    (a device's own sensors as "device_<key>")."""

    def statistic_id(self, unique_id: str) -> str | None:
        if split_data_sensor(unique_id) is None:
            return None
        return f"{PLATFORM}:{unique_id}".lower().replace("-", "_")

    def group(
        self, entries: Iterable[RegistryEntry]
    ) -> dict[str, dict[tuple[str, str], str]]:
        own = [e for e in entries if e.platform == self.platform]
        # Energy series per device, disabled ones included (classification).
        devices: dict[tuple[str, str], dict[str, RegistryEntry]] = {}
        for entry in own:
            if (ids := split_data_sensor(entry.unique_id)) and (
                key := data_key(entry.original_name)
            ):
                devices.setdefault(ids, {})[key] = entry
        pumps = sorted(
            d for d, keys in devices.items() if any(k.startswith("env_") for k in keys)
        )
        by_prefix: dict[str, dict[tuple[str, str], str]] = {}
        for system in sorted({s for s, _ in pumps}):
            system_pumps = [d for d in pumps if d[0] == system]
            # Backup heater: another device with electricity for hot water
            # (a ventilation unit has heating only). Ambiguous: none.
            heaters = [
                d
                for d, keys in devices.items()
                if d[0] == system and d not in pumps and "elec_dhw" in keys
            ]
            marker = f"{_PREFIX}{system}_"
            shared = {
                (_domain(e), e.unique_id[len(marker) :]): e.entity_id
                for e in own
                if e.usable
                and e.unique_id.startswith(marker)
                and split_data_sensor(e.unique_id) is None
            }
            for pump in system_pumps:
                found = dict(shared)
                infix = f"device_{pump[1]}_"
                for (domain, key), entity_id in shared.items():
                    if key.startswith(infix):
                        found[(domain, f"device_{key[len(infix) :]}")] = entity_id
                for key, entry in devices[pump].items():
                    if entry.usable:
                        found[(_domain(entry), f"hp:{key}")] = entry.entity_id
                if len(system_pumps) == 1 and len(heaters) == 1:
                    for key, entry in devices[heaters[0]].items():
                        if entry.usable:
                            found[(_domain(entry), f"aux:{key}")] = entry.entity_id
                by_prefix[f"{system}_device_{pump[1]}"] = found
        return by_prefix


_S = "sensor"
VAILLANT = VaillantTemplate(
    experimental=True,
    key="mypyllant",
    label="Vaillant myVAILLANT",
    platform=PLATFORM,
    device=None,
    signals={
        Signal.HEAT_HEATING: ((_S, "hp:heat_heating"),),
        Signal.HEAT_DHW: ((_S, "hp:heat_dhw"),),
        Signal.HEAT_COOLING: ((_S, "hp:heat_cooling"),),
        Signal.ELEC_HEATING: ((_S, "hp:elec_heating"),),
        Signal.ELEC_DHW: ((_S, "hp:elec_dhw"),),
        Signal.ELEC_COOLING: ((_S, "hp:elec_cooling"),),
        # Electricity of the backup heater device per mode (a resistance
        # heater: its heat equals its electricity).
        Signal.AUX_HEATING: ((_S, "aux:elec_heating"),),
        Signal.AUX_DHW: ((_S, "aux:elec_dhw"),),
        # System state "energyManagerState" (STANDBY, HEATING, DHW, COOLING),
        # not on every system; polled every 30 min by default. No defrost.
        Signal.ACTIVITY: ((_S, "home_energy_manager_state"),),
        Signal.OUTDOOR_TEMP: ((_S, "home_outdoor_temperature"),),
        # System flow first (not on every system), else circuit 0's flow.
        Signal.FLOW_TEMP: (
            (_S, "home_system_flow_temperature"),
            (_S, "circuit_0_flow_temperature"),
        ),
        Signal.DHW_TEMP: (
            (_S, "domestic_hot_water_0_tank_temperature"),
            (_S, "home_top_dhw_temperature"),
        ),
    },
    required=(Signal.HEAT_HEATING, Signal.ELEC_HEATING),
    activity_values={
        "standby": Activity.OFF,
        "heating": Activity.HEATING,
        "dhw": Activity.DHW,
        "cooling": Activity.COOLING,
    },
    hourly_statistics=True,
    heat_includes_electricity=True,
)
