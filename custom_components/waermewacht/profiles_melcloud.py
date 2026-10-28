"""Source template: Mitsubishi Ecodan (Air-to-Water) via MELCloud.

Home Assistant core integration `melcloud` (platform "melcloud"), read at
core dev 8f785c4 (2026-10-28) with python-melcloud 0.1.3 (module pymelcloud).
Derived from source code, not from a real installation: experimental.

Unique ids are "<serial>-<mac>-<key>" (entity.py, MelCloudDescriptionEntity);
zone 2 sensors end in "-zone-2", the water heater has the bare serial, the
zone climates "<serial>-<zone>". Split at a known key at the end.

Energy: the six "Daily ..." values of MELCloud's ListDevices (HA 2026.5+),
kWh, total_increasing in HA; heat (produced) and all cooling values are
disabled by default in melcloud. Booked as day values like Bosch HomeCom.
Whether MELCloud reports today's running value (HA docs: "reset at
midnight") or the previous day's (CN105 frames carry a date; one community
report) is unconfirmed. If it is the previous day, each day is booked one
day late; heat and electricity move together, so the ratios hold.

Left out on purpose: the compressor frequency (key "fan_frequency") comes
from ListDevices, refreshed at most every 30 minutes: runs and starts from
it would be wrong. The status (defrost, hot water, heating) exists only as
the attribute "status" of the water heater, not as an entity state. No
starts, no backup heater energy.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Signal
from .profiles import Template


def split_dash_suffix(unique_id: str, keys: set[str]) -> tuple[str, str] | None:
    """(prefix, key) of "<serial>-<mac>-<key>", None if no key fits.

    The longest key first; the prefix must itself contain a "-" (serial and
    MAC), which keeps "<gateway>-<key>" ids of other integrations out.
    """
    for key in sorted(keys, key=len, reverse=True):
        marker = f"-{key}"
        if unique_id.endswith(marker):
            prefix = unique_id[: -len(marker)]
            if "-" in prefix.strip("-"):
                return prefix, key
    return None


@dataclass(frozen=True)
class DashSuffixTemplate(Template):
    """A template whose unique ids are "<serial>-<mac>-<key>"."""

    def split(self, unique_id: str) -> tuple[str, str] | None:
        return split_dash_suffix(
            unique_id, {k for keys in self.signals.values() for _, k in keys}
        )


_S = "sensor"
MELCLOUD = DashSuffixTemplate(
    experimental=True,
    key="melcloud",
    label="Mitsubishi Ecodan (MELCloud)",
    platform="melcloud",
    device=None,
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
)
