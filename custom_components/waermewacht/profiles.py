"""Source templates: which entity of an integration is which signal.

Pure Python, no Home Assistant imports: the caller passes registry entries as
`RegistryEntry` tuples. Templates are data; the core knows no vendor.
Sources of every name and value: docs/ENTWICKLUNG.md, section 4.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import NamedTuple

from .model import ACTIVITY_PARTS, Activity, Signal

# "<gateway>-<key>" (Bosch HomeCom, HeishaMon "<entry id>-<TOPxx>"): split
# at the first "-", keys may contain one ("dhw1-delta_t").
DASH_ID = r"(?P<prefix>[^-]+)-(?P<key>.+)"


class RegistryEntry(NamedTuple):
    """The parts of an entity registry entry a template matches on."""

    entity_id: str
    platform: str
    unique_id: str
    # Name the integration gave the entity (registry original_name; not the
    # user's name). Only templates whose unique ids carry no meaning use it.
    original_name: str | None = None
    # Enabled and reporting a state. Unusable entries only help to classify
    # devices (a disabled sensor still tells what its device is).
    usable: bool = True


@dataclass(frozen=True)
class Template:
    """How to find the signals of one heat pump in one integration."""

    key: str
    label: str  # shown in the setup
    platform: str
    # Candidate keys per signal, preferred first: (entity domain, key).
    signals: dict[Signal, tuple[tuple[str, str], ...]]
    # Keys that must be present to call a device a heat pump of this template.
    required: tuple[Signal, ...]
    # Format of the unique ids: a regular expression for the whole id with
    # the groups "key" and, optionally, "prefix" (one heat pump each; missing
    # means ""). "{key}" stands for the template's own keys, tried longest
    # first, where the key cannot be told apart otherwise. With a group
    # "domain", only keys of that entity domain count.
    id_format: str = DASH_ID
    # None: the source itself does not know (ViCare "null").
    activity_values: dict[str, Activity | None] = field(default_factory=dict)
    # Values showing that the activity entity carries no activity on this
    # device (ViCare E3 compressor phase: ready / not_ready).
    activity_foreign: frozenset[str] = frozenset()
    # Keys naming the same counter in another id format (both may exist; the
    # older one often has the longer statistics, used for the backfill).
    aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Energy entities hold today's sum of a cloud's hourly values, delivered
    # up to two hours late: they start anew at midnight, and standby is told
    # from the heat of the same fetch instead of the compressor state.
    day_values: bool = False
    # Time zone in which the day values start anew; None: local time.
    day_timezone: str | None = None
    # The day values are the previous day's total (MELCloud): booked into
    # the previous day.
    previous_day: bool = False
    # Built from the integration's source code, not yet confirmed on a real
    # installation: shown as "(beta)" in the setup.
    experimental: bool = False
    # Energy is booked hour by hour from the long-term statistics the source
    # writes itself (statistic_id), not from state changes.
    hourly_statistics: bool = False
    # Heat of a mode is electricity plus environmental yield (a calculated
    # value): an hour is standby when heat does not exceed electricity.
    heat_includes_electricity: bool = False

    def statistic_id(self, unique_id: str) -> str | None:
        """Statistic id of the hourly energy of an entity, None if it has none."""
        return None

    def group(
        self, entries: Iterable[RegistryEntry]
    ) -> dict[str, dict[tuple[str, str], str]]:
        """{prefix: {(entity domain, key): entity_id}} of the usable entries."""
        by_prefix: dict[str, dict[tuple[str, str], str]] = {}
        for entry in entries:
            if entry.platform != self.platform or not entry.usable:
                continue
            parts = self.split(entry.unique_id)
            if parts is None:
                continue
            prefix, key = parts
            domain = entry.entity_id.split(".", 1)[0]
            by_prefix.setdefault(prefix, {})[(domain, key)] = entry.entity_id
        return by_prefix

    def split(self, unique_id: str) -> tuple[str, str] | None:
        """(prefix, key) of a unique id, None if it is not of this format."""
        for pattern, domain in self._id_patterns:
            match = pattern.fullmatch(unique_id)
            if match is None or (domain is not None and match["domain"] != domain):
                continue
            return match.groupdict().get("prefix") or "", match["key"]
        return None

    @cached_property
    def _id_patterns(self) -> tuple[tuple[re.Pattern[str], str | None], ...]:
        """`id_format` compiled, once per key where it names them."""
        if "{key}" not in self.id_format:
            return ((re.compile(self.id_format), None),)
        by_domain = "(?P<domain>" in self.id_format
        candidates = {
            (domain if by_domain else None, key)
            for keys in self.signals.values()
            for domain, key in keys
        }
        return tuple(
            (re.compile(self.id_format.replace("{key}", re.escape(key))), domain)
            for domain, key in sorted(candidates, key=lambda c: -len(c[1]))
        )

    def parse_activity(self, state: str | None) -> Activity | None:
        """Map an activity state; None while unknown, OTHER if not recognized."""
        if state is None or state in ("unknown", "unavailable", ""):
            return None
        key = state.strip().casefold()
        if key in self.activity_foreign:
            return None
        return self.activity_values.get(key, Activity.OTHER)

    def is_foreign_activity(self, state: str | None) -> bool:
        return (state or "").strip().casefold() in self.activity_foreign


def parse_compressor(state: str | None) -> bool | None:
    """Compressor running: on/off, or a speed or modulation above 0."""
    match state:
        case "on":
            return True
        case "off":
            return False
    try:
        return float(state or "") > 0
    except ValueError:
        return None  # unknown, unavailable


@dataclass(frozen=True)
class Match:
    """A heat pump found by a template."""

    template: Template
    prefix: str  # MQTT base of the "multiple instances" format, else ""
    entities: dict[Signal, str]
    # Other entities of the same counter (other id format), for the backfill.
    history: dict[Signal, list[str]] = field(default_factory=dict)

    @property
    def missing(self) -> list[Signal]:
        return [s for s in self.template.signals if s not in self.entities]


def drop_foreign_activity(match: Match, state_of: Callable[[str], str | None]) -> Match:
    """Without the activity (and its parts) when its entity shows a value
    that carries no activity on this device."""
    entity_id = match.entities.get(Signal.ACTIVITY)
    if entity_id is None or not match.template.is_foreign_activity(state_of(entity_id)):
        return match
    keep = {
        s: e
        for s, e in match.entities.items()
        if s is not Signal.ACTIVITY and s not in ACTIVITY_PARTS
    }
    return replace(match, entities=keep)


def _words(values: dict[Activity, tuple[str, ...]]) -> dict[str, Activity]:
    return {
        word.casefold(): activity
        for activity, words in values.items()
        for word in words
    }


# EMS-ESP: enum_hpactivity (src/core/locale_common.h) with the words of
# src/core/locale_translations.h, in the order en, de, nl, sv, pl, no, fr, tr,
# it, sk, cs; plus the index format ("Enum format = index"). Pool and alarm
# are OTHER. Checked against EMS-ESP dev 3.9.0-dev.20 on 2026-10-27.
EMS_ESP_ACTIVITY = _words(
    {
        Activity.OFF: ("0", "off", "aus", "uit", "av", "wyłączono", "kapalı", "vyp"),
        Activity.HEATING: (
            "1",
            "heating",
            "Heizen",
            "verwarmen",
            "Uppvärmning",
            "ogrzewanie",
            "oppvarming",
            "chauffage",
            "ısıtma",
            "riscaldamento",
            "kúrenie",
            "topení",
        ),
        Activity.COOLING: (
            "2",
            "cooling",
            "Kühlen",
            "koelen",
            "Kyler",
            "chłodzenie",
            "kjøling",
            "refroidissement",
            "soğuma",
            "raffreddamento",
            "chladenie",
            "chlazení",
        ),
        Activity.DHW: (
            "3",
            "hot water",
            "Warmwasser",
            "warm water",
            "varmvatten",
            "c.w.u.",
            "varmtvann",
            "eau chaude",
            "sıcak su",
            "acqua calda",
            "horúca voda",
            "horká voda",
        ),
        Activity.DEFROST: (
            "6",
            "defrost",
            "Abtauen",
            "ontdooien",
            "avfrostning",
            "odladzanie",
            "tine",
            "dégivrage",
            "buz çözücü",
            "scongelamento",
            "odmrazenie",
            "odmrazování",
        ),
    }
)

# Keys after "<device>_": current names (EMS-ESP >= 3.7, "dhw_…") first, then
# the 3.6-compatible formats ("…ww", "ww…"); within each, the counters in
# 0.01 kWh (telegrams 0x4AE/0x4AF) before the whole-kWh ones (0x494/0x495).
_S, _B = "sensor", "binary_sensor"
EMS_ESP = Template(
    key="ems_esp",
    label="EMS-ESP",
    platform="mqtt",
    # "[<prefix>_]boiler_<key>"; the prefix is the MQTT base of the
    # "multiple instances" format. Keys are short names ("nrgheat"); the
    # format "single instance, long names (v3.4)" uses the English full name
    # instead (mqtt.cpp, entity_format 0: spaces to "_", lower case, DHW
    # values "dhw_<name>"), listed after each short name ("energy_heating").
    id_format=r"(?:(?P<prefix>(?!boiler_).+?)_)?boiler_(?P<key>.+)",
    signals={
        Signal.HEAT_HEATING: (
            (_S, "nrgheat"),
            (_S, "energy_heating"),
            (_S, "nrgsuppheating"),
            (_S, "total_energy_supplied_heating"),
        ),
        Signal.HEAT_DHW: (
            (_S, "dhw_nrg"),
            (_S, "dhw_energy"),
            (_S, "nrgww"),
            (_S, "dhw_nrgsupp"),
            (_S, "dhw_total_energy_warm_supplied"),
            (_S, "nrgsuppww"),
        ),
        Signal.HEAT_COOLING: (
            (_S, "nrgcool"),
            (_S, "energy_cooling"),
            (_S, "nrgsuppcooling"),
            (_S, "total_energy_supplied_cooling"),
        ),
        Signal.ELEC_HEATING: (
            (_S, "meterheat"),
            (_S, "meter_heating"),
            (_S, "nrgconscompheating"),
            (_S, "energy_consumption_compressor_heating"),
        ),
        Signal.ELEC_DHW: (
            (_S, "dhw_meter"),
            (_S, "wwmeter"),
            (_S, "dhw_nrgconscomp"),
            (_S, "dhw_energy_consumption_compressor"),
            (_S, "nrgconscompww"),
        ),
        Signal.ELEC_COOLING: (
            (_S, "metercool"),
            (_S, "meter_cooling"),
            (_S, "nrgconscompcooling"),
            (_S, "energy_consumption_compressor_cooling"),
        ),
        # The backup heater per mode exists in whole kWh only; the 0.01 kWh
        # total (metereheat) would need an attribution to modes.
        Signal.AUX_HEATING: (
            (_S, "auxelecheatnrgconsheating"),
            (_S, "aux_elec._heater_energy_consumption_heating"),
        ),
        Signal.AUX_DHW: (
            (_S, "dhw_auxelecheatnrgcons"),
            (_S, "dhw_aux_elec._heater_energy_consumption"),
            (_S, "auxelecheatnrgconsww"),
        ),
        Signal.COMPRESSOR: (
            (_B, "hpcompon"),
            (_B, "hp_compressor"),
        ),
        Signal.ACTIVITY: (
            (_S, "hpactivity"),
            (_S, "compressor_activity"),
        ),
        Signal.STARTS_TOTAL: (
            (_S, "totalcompstarts"),
            (_S, "total_compressor_control_starts"),
        ),
        Signal.OUTDOOR_TEMP: (
            (_S, "outdoortemp"),
            (_S, "outside_temperature"),
        ),
        Signal.FLOW_TEMP: (
            (_S, "hptc1"),
            (_S, "heat_carrier_forward_(tc1)"),
        ),
        Signal.RETURN_TEMP: (
            (_S, "hptc0"),
            (_S, "heat_carrier_return_(tc0)"),
        ),
        Signal.FLOW_RATE: (
            (_S, "pc0flow"),
            (_S, "flow_pc0"),
        ),
        # Storage temperature, 3.7+ name first.
        Signal.DHW_TEMP: (
            (_S, "dhw_curtemp"),
            (_S, "dhw_current_intern_temperature"),
            (_S, "wwcurtemp"),
        ),
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING),
    activity_values=EMS_ESP_ACTIVITY,
    # Same telegram field, 3.7+ name vs. 3.6-compatible name (mqtt.cpp,
    # dhw_old). Observed: after a change of the format setting both exist
    # with equal values, the old one with statistics reaching further back.
    aliases={
        "dhw_nrg": ("nrgww",),
        "dhw_meter": ("wwmeter",),
        "dhw_nrgsupp": ("nrgsuppww",),
        "dhw_nrgconscomp": ("nrgconscompww",),
        "dhw_auxelecheatnrgcons": ("auxelecheatnrgconsww",),
        "nrgww": ("dhw_nrg",),
        "wwmeter": ("dhw_meter",),
        "nrgsuppww": ("dhw_nrgsupp",),
        "nrgconscompww": ("dhw_nrgconscomp",),
        "auxelecheatnrgconsww": ("dhw_auxelecheatnrgcons",),
    },
)

# Compressor status of the Bosch PointT cloud (/heatSources/compressor/status,
# K40 gateways), the same words as EMS-ESP's hpactivity. Read by BassXT/buderus
# and, from bosch_homecom PR #217 (homecom_alt PR #151) on, by bosch_homecom.
POINTT_ACTIVITY: dict[str, Activity | None] = {
    "off": Activity.OFF,
    "heating": Activity.HEATING,
    "cooling": Activity.COOLING,
    "dhw": Activity.DHW,
    "defrost": Activity.DEFROST,
    "pool": Activity.OTHER,
    "pool_heat": Activity.OTHER,
    "alarm": Activity.OTHER,
}

# Bosch HomeCom (bosch_homecom, checked v1.5.2 and v1.6.0): unique ids
# "<gateway id>-<key>". The energy per mode is today's sum of the cloud's
# hourly values (disabled by default in bosch_homecom). The activity
# ("compressor_status") exists only from bosch_homecom PR #217 on; without
# it there are no defrosts and no mode of a run, and an existing entry takes
# it over once it appears (adopt.py). The pump volume flow is left out: it
# reports "L/min" but delivers l/h. Sources: docs/ENTWICKLUNG.md, section 4.
BOSCH_HOMECOM = Template(
    key="bosch_homecom",
    label="Bosch HomeCom",
    platform="bosch_homecom",
    signals={
        Signal.HEAT_HEATING: ((_S, "heat_produced_ch"),),
        Signal.HEAT_DHW: ((_S, "heat_produced_dhw"),),
        Signal.HEAT_COOLING: ((_S, "heat_produced_cooling"),),
        Signal.ELEC_HEATING: ((_S, "energy_compressor_ch"),),
        Signal.ELEC_DHW: ((_S, "energy_compressor_dhw"),),
        Signal.ELEC_COOLING: ((_S, "energy_compressor_cooling"),),
        Signal.AUX_HEATING: ((_S, "energy_eheater_ch"),),
        Signal.AUX_DHW: ((_S, "energy_eheater_dhw"),),
        # Local speed first (about a minute late), the cloud modulation else.
        Signal.COMPRESSOR: (
            (_S, "local_compressor_speed"),
            (_S, "compressor_modulation"),
        ),
        Signal.ACTIVITY: ((_S, "compressor_status"),),
        Signal.STARTS_TOTAL: ((_S, "compressor_starts"),),
        Signal.OUTDOOR_TEMP: ((_S, "outdoor_temp"),),
        Signal.FLOW_TEMP: ((_S, "supply_temperature"),),
        Signal.RETURN_TEMP: ((_S, "return_temperature"),),
        Signal.DHW_TEMP: ((_S, "dhw1"),),
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING),
    activity_values=POINTT_ACTIVITY,
    day_values=True,
)


def find(template: Template, entries: Iterable[RegistryEntry]) -> list[Match]:
    """Heat pumps of `template` among the registry entries, one per prefix."""
    by_prefix = template.group(entries)

    matches = []
    for prefix, found in sorted(by_prefix.items()):
        entities: dict[Signal, str] = {}
        history: dict[Signal, list[str]] = {}
        for signal, candidates in template.signals.items():
            chosen = next((c for c in candidates if c in found), None)
            if chosen is None:
                continue
            entities[signal] = found[chosen]
            domain, key = chosen
            if others := [
                found[(domain, alias)]
                for alias in template.aliases.get(key, ())
                if (domain, alias) in found
            ]:
                history[signal] = others
        if all(s in entities for s in template.required):
            matches.append(Match(template, prefix, entities, history))
    return matches
