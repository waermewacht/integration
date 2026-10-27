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
    label: str  # shown in the setup
    platform: str
    # Device part of "[<prefix>_]<device>_<key>" unique ids (EMS-ESP:
    # "boiler"); None for "<gateway>-<key>" (Bosch HomeCom).
    device: str | None
    # Candidate keys per signal, preferred first: (entity domain, key).
    signals: dict[Signal, tuple[tuple[str, str], ...]]
    # Keys that must be present to call a device a heat pump of this template.
    required: tuple[Signal, ...]
    activity_values: dict[str, Activity] = field(default_factory=dict)
    # Keys naming the same counter in another id format (both may exist; the
    # older one often has the longer statistics, used for the backfill).
    aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Energy entities hold today's sum of a cloud's hourly values, delivered
    # up to two hours late: they start anew at midnight, and standby is told
    # from the heat of the same fetch instead of the compressor state.
    day_values: bool = False

    def split(self, unique_id: str) -> tuple[str, str] | None:
        """(prefix, key) of a unique id, None if it is not of this format."""
        if self.device is None:
            # Split at the first "-": keys may contain one ("dhw1-delta_t").
            prefix, separator, key = unique_id.partition("-")
            return (prefix, key) if separator and prefix and key else None
        marker = f"{self.device}_"
        if unique_id.startswith(marker):
            return "", unique_id[len(marker) :]
        position = unique_id.find(f"_{marker}")
        if position <= 0:
            return None
        return unique_id[:position], unique_id[position + len(marker) + 1 :]

    def parse_activity(self, state: str | None) -> Activity | None:
        """Map an activity state; None while unknown, OTHER if not recognized."""
        if state is None or state in ("unknown", "unavailable", ""):
            return None
        return self.activity_values.get(state.strip().casefold(), Activity.OTHER)


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

# Bosch HomeCom (bosch_homecom, checked v1.5.2 and v1.6.0): unique ids
# "<gateway id>-<key>". The energy per mode is today's sum of the cloud's
# hourly values (disabled by default in bosch_homecom); there is no activity,
# so no defrosts and no mode of a run. The pump volume flow is left out: it
# reports "L/min" but delivers l/h. Sources: docs/ENTWICKLUNG.md, section 4.
BOSCH_HOMECOM = Template(
    key="bosch_homecom",
    label="Bosch HomeCom",
    platform="bosch_homecom",
    device=None,
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
        Signal.STARTS_TOTAL: ((_S, "compressor_starts"),),
        Signal.OUTDOOR_TEMP: ((_S, "outdoor_temp"),),
        Signal.FLOW_TEMP: ((_S, "supply_temperature"),),
        Signal.RETURN_TEMP: ((_S, "return_temperature"),),
        Signal.ELEC_POWER: ((_S, "local_compressor_power"),),
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING),
    day_values=True,
)

TEMPLATES: dict[str, Template] = {t.key: t for t in (EMS_ESP, BOSCH_HOMECOM)}


def find(template: Template, entries: Iterable[RegistryEntry]) -> list[Match]:
    """Heat pumps of `template` among the registry entries, one per prefix."""
    by_prefix: dict[str, dict[tuple[str, str], str]] = {}
    for entry in entries:
        if entry.platform != template.platform:
            continue
        parts = template.split(entry.unique_id)
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
