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

Split systems (Vitocal 200-A; PyViCare test data Vitocal200A_SystemController
= device 0, Vitocal200A_OutdoorUnit = device 1, same gateway): the outdoor
unit carries compressor, phase, starts and the heat pump flow, the system
controller the electricity, hot water and heating circuits. Home Assistant
makes two devices with two prefixes of the same gateway. Rule (group()):
- Devices are told apart by registry entries, disabled ones included.
- Per gateway (prefix up to the first "_"), only when exactly one device has
  the compressor: the donor is the one other device without a burner that
  has an energy signal the compressor device has no entity for at all.
- With exactly one donor, its entities fill every signal the compressor
  device has no entity for; the compressor device's own always win. The
  match keeps the compressor device's prefix; the donor is no group of its
  own any more.
- Two compressor devices (two heat pumps) or several donors merge nothing:
  the user picks by hand. A device with a burner (gas boiler of a hybrid)
  is never a donor.

The cloud's day values are said to start anew at midnight UTC (forum
reports, unconfirmed). Counting days in UTC is the safe choice: if the cloud
uses local midnight after all, a day's first value is only booked an hour or
two late, nothing is lost; the other way round most of a day would land in
the wrong day.
"""

from __future__ import annotations

from collections.abc import Iterable

from .model import ENERGY_SIGNALS, Activity, Signal
from .profiles import RegistryEntry, Template

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

# Keys of a gas or oil burner (binary_sensor burner_active-N, sensor
# burner_starts-N ...): such a device is a boiler, never a donor.
_BURNER = "burner_"


class ViCareTemplate(Template):
    """Groups by device; a split system's controller joins its outdoor unit
    (rule in the module docstring)."""

    def group(
        self, entries: Iterable[RegistryEntry]
    ) -> dict[str, dict[tuple[str, str], str]]:
        entries = list(entries)
        by_prefix = super().group(entries)
        # Every (domain, key) per device, disabled entries included.
        known: dict[str, set[tuple[str, str]]] = {}
        for entry in entries:
            if entry.platform != self.platform:
                continue
            if (parts := self.split(entry.unique_id)) is not None:
                domain = entry.entity_id.split(".", 1)[0]
                known.setdefault(parts[0], set()).add((domain, parts[1]))
        gateways: dict[str, list[str]] = {}
        for prefix in sorted(known):
            gateways.setdefault(prefix.partition("_")[0], []).append(prefix)
        for prefixes in gateways.values():
            self._merge(by_prefix, known, prefixes)
        return by_prefix

    def _merge(
        self,
        by_prefix: dict[str, dict[tuple[str, str], str]],
        known: dict[str, set[tuple[str, str]]],
        prefixes: list[str],
    ) -> None:
        """Fill the compressor device of one gateway from its single donor."""
        compressor = set(self.signals[Signal.COMPRESSOR])
        pumps = [p for p in prefixes if known[p] & compressor]
        if len(pumps) != 1 or pumps[0] not in by_prefix:
            return
        pump = pumps[0]
        lacking = [
            signal
            for signal, candidates in self.signals.items()
            if not known[pump].intersection(candidates)
        ]
        energy = {c for s in lacking if s in ENERGY_SIGNALS for c in self.signals[s]}
        donors = [
            p
            for p in prefixes
            if p != pump
            and not any(key.startswith(_BURNER) for _, key in known[p])
            and energy.intersection(by_prefix.get(p, ()))
        ]
        if len(donors) != 1:
            return
        donor = by_prefix.pop(donors[0])
        found = by_prefix[pump]
        for signal in lacking:
            for candidate in self.signals[signal]:
                if candidate in donor:
                    found[candidate] = donor[candidate]


_S, _B = "sensor", "binary_sensor"
VICARE = ViCareTemplate(
    experimental=True,
    key="vicare",
    label="Viessmann ViCare",
    platform="vicare",
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
