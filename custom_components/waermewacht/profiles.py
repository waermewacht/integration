"""Source templates: which entity of an integration is which signal.

Pure Python, no Home Assistant imports: the caller passes registry entries as
`RegistryEntry` tuples. Templates are data; the core knows no vendor.
Sources of every name and value: docs/ENTWICKLUNG.md, section 4.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import NamedTuple

from .model import Activity, Signal


class RegistryEntry(NamedTuple):
    """The parts of an entity registry entry a template matches on."""

    entity_id: str
    platform: str
    unique_id: str


@dataclass(frozen=True)
class Template:
    """How to find the signals of one heat pump in one integration."""

    key: str
    platform: str
    device: str  # device part of the unique id, e.g. "boiler"
    # Candidate keys per signal, preferred first: (entity domain, key).
    signals: dict[Signal, tuple[tuple[str, str], ...]]
    # Keys that must be present to call a device a heat pump of this template.
    required: tuple[Signal, ...]
    activity_values: dict[str, Activity] = field(default_factory=dict)
    # Keys naming the same counter in another id format (both may exist; the
    # older one often has the longer statistics, used for the backfill).
    aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def parse_activity(self, state: str | None) -> Activity | None:
        """Map an activity state; None while unknown, OTHER if not recognized."""
        if state is None or state in ("unknown", "unavailable", ""):
            return None
        return self.activity_values.get(state.strip().casefold(), Activity.OTHER)


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
    platform="mqtt",
    device="boiler",
    signals={
        Signal.HEAT_HEATING: ((_S, "nrgheat"), (_S, "nrgsuppheating")),
        Signal.HEAT_DHW: (
            (_S, "dhw_nrg"),
            (_S, "nrgww"),
            (_S, "dhw_nrgsupp"),
            (_S, "nrgsuppww"),
        ),
        Signal.HEAT_COOLING: ((_S, "nrgcool"), (_S, "nrgsuppcooling")),
        Signal.ELEC_HEATING: ((_S, "meterheat"), (_S, "nrgconscompheating")),
        Signal.ELEC_DHW: (
            (_S, "dhw_meter"),
            (_S, "wwmeter"),
            (_S, "dhw_nrgconscomp"),
            (_S, "nrgconscompww"),
        ),
        Signal.ELEC_COOLING: ((_S, "metercool"), (_S, "nrgconscompcooling")),
        # The backup heater per mode exists in whole kWh only; the 0.01 kWh
        # total (metereheat) would need an attribution to modes.
        Signal.AUX_HEATING: ((_S, "auxelecheatnrgconsheating"),),
        Signal.AUX_DHW: ((_S, "dhw_auxelecheatnrgcons"), (_S, "auxelecheatnrgconsww")),
        Signal.COMPRESSOR: ((_B, "hpcompon"),),
        Signal.ACTIVITY: ((_S, "hpactivity"),),
        Signal.STARTS_TOTAL: ((_S, "totalcompstarts"),),
        Signal.OUTDOOR_TEMP: ((_S, "outdoortemp"),),
        Signal.FLOW_TEMP: ((_S, "hptc1"),),
        Signal.RETURN_TEMP: ((_S, "hptc0"),),
        Signal.FLOW_RATE: ((_S, "pc0flow"),),
        Signal.HEAT_POWER: ((_S, "hppower"),),
        Signal.ELEC_POWER: ((_S, "hpcurrpower"),),
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

TEMPLATES: dict[str, Template] = {EMS_ESP.key: EMS_ESP}


def _split(unique_id: str, device: str) -> tuple[str, str] | None:
    """Split "<prefix>_<device>_<key>" or "<device>_<key>" into (prefix, key)."""
    marker = f"{device}_"
    if unique_id.startswith(marker):
        return "", unique_id[len(marker) :]
    position = unique_id.find(f"_{marker}")
    if position <= 0:
        return None
    return unique_id[:position], unique_id[position + len(marker) + 1 :]


def find(template: Template, entries: Iterable[RegistryEntry]) -> list[Match]:
    """Heat pumps of `template` among the registry entries, one per prefix."""
    by_prefix: dict[str, dict[tuple[str, str], str]] = {}
    for entry in entries:
        if entry.platform != template.platform:
            continue
        parts = _split(entry.unique_id, template.device)
        if parts is None:
            continue
        prefix, key = parts
        domain = entry.entity_id.split(".", 1)[0]
        by_prefix.setdefault(prefix, {})[(domain, key)] = entry.entity_id

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
