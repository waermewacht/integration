"""Source template: Mitsubishi Ecodan via the ESPHome firmware esphome-ecodan-hp.

Firmware gekkekoe/esphome-ecodan-hp (ESP32 on the CN105 port of the FTC),
read at main 30eb1b4 (2026-10-28): confs/base.yaml, confs/energy.yaml,
confs/request-codes.yaml, confs/ecodan-labels-*.yaml, components/ecodan
(sensor.py, binary_sensor.py, response.cpp, status.h). Home Assistant core
integration esphome (platform "esphome"), dev 33ee669 (2026-10-28) with
aioesphomeapi 46.21.0. Derived from source code, not from a real
installation: experimental.

Unique ids are built from the entity's name (aioesphomeapi
build_unique_id): "<MAC>/<sub-device id>/<entity type>/<name>" (version 3,
current HA; the main device is 0), before that "<MAC>-<entity type>-
<object_id>" (version 1, object_id = name in snake case with every other
character replaced by "_"; "@<sub-device id>" appended for sub-devices),
which HA migrates to version 3. The names are the firmware's labels
(substitutions of confs/ecodan-labels-<language>.yaml, 14 languages; the
user picks one file and may edit any label). So the key of an entity is
found by its name: the registry's original_name (what the firmware calls
it; a rename in Home Assistant does not touch it), else the name in the
unique id. Every label of the signals below is unique across all languages
except the German and Italian "status_operation", which equals the select
"heatpump_select_operating_mode" of the same language; the entity domain
(sensor vs. select) keeps them apart. Labels a user changed are not found:
such installations choose their entities by hand.

Energy: "Heating/DHW/Cool Consumed/Delivered" (kWh, 0.01 kWh, state class
total) from the FTC's packets 0xA1/0xA2, published on every poll. They are
the previous day's totals: the packets carry a date (protocol.md), the
Italian labels say "Ieri", and energy.yaml adds each value once, at the
first value after the FTC's day change, to lifetime counters ("Total
Heating Consumed" ..., total_increasing). Wärmewacht reads the day values,
not those lifetime counters: a lifetime counter rises just after midnight
by the previous day's total as well (still previous_day), the core treats
previous-day energy only as day values (electricity told from standby by
the heat of the same day, no hot water charges), and energy.yaml takes
the first value after the FTC's midnight without checking the packet's
date: should the FTC answer with the old day for a moment (the F1p bridge
publishes these only when the date is yesterday, and nothing from 23:59 to
00:05), that day is counted twice and the next one lost. A day value that
changes late is booked correctly. The FTC's clock must be right: a value
that changes before local midnight is taken as a rise within the day.

Activity: "Operation Mode" (text sensor status_operation, its words are
labels too: operation_off, hotwater, heating, cooling, frost_protection,
legionella_prevention; "Unknown" while unavailable) plus the defrost flag
"Defrost" (binary sensor status_defrost, packet 0x02 byte 3 != 0; that
byte is 1 standby, 2 defrosting, 3 waiting restart in the F1p decoder, so
the flag also covers the defrost's standby and restart wait). Compressor:
frequency in Hz (packet 0x04). No starts: "Accumulated Compressor Starts"
is the FTC's count in hundreds (response.cpp: "* 100"); Wärmewacht counts
the starts itself. Immersion and booster heaters are on/off only: no aux
energy.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .model import Activity, Signal
from .profiles import RegistryEntry, Template

PLATFORM = "esphome"

# Labels of the entities Wärmewacht reads (confs/ecodan-labels-<lang>.yaml
# at 30eb1b4), by firmware key, in the order of LANGUAGES.
LANGUAGES = (
    "ca",
    "da",
    "de",
    "en",
    "es",
    "fi",
    "fr",
    "it",
    "nl",
    "no",
    "pl",
    "sk",
    "sl",
    "sv",
)

LABELS: dict[str, tuple[str, ...]] = {
    "heating_consumed": (
        "Consum de calefacció",  # ca
        "Opvarmning brugt",  # da
        "Heizung Verbraucht",  # de
        "Heating Consumed",  # en
        "Calefacción Consumida",  # es
        "Lämmityksen kulutus",  # fi
        "Conso chauffage",  # fr
        "En. Risc. Utilizzata",  # it
        "Verwarmen verbruikt",  # nl
        "Oppvarming brukt",  # no
        "Ogrzewanie zużyte",  # pl
        "Spotreba kúrenia",  # sk
        "Ogrevanje porabljeno",  # sl
        "Uppvärmning förbrukad",  # sv
    ),
    "heating_delivered": (
        "Producció de calefacció",  # ca
        "Opvarmning leveret",  # da
        "Heizung Geliefert",  # de
        "Heating Delivered",  # en
        "Calefacción Entregada",  # es
        "Lämmityksen tuotanto",  # fi
        "Energ Délivrée Chauffage",  # fr
        "En. Risc. Prod. Ieri",  # it
        "Verwarmen geleverd",  # nl
        "Oppvarming levert",  # no
        "Ogrzewanie dostarczone",  # pl
        "Dodaná energia kúrenia",  # sk
        "Ogrevanje oddano",  # sl
        "Uppvärmning levererad",  # sv
    ),
    "dhw_consumed": (
        "Consum d'ACS",  # ca
        "Brugsvand brugt",  # da
        "TWW Verbraucht",  # de
        "DHW Consumed",  # en
        "ACS Consumida",  # es
        "LKV kulutettu",  # fi
        "Conso ECS",  # fr
        "En. ACS Utilizzata",  # it
        "SWW verbruikt",  # nl
        "DHW brukt",  # no
        "CWU zużyte",  # pl
        "Spotreba TÚV",  # sk
        "TSV porabljeno",  # sl
        "Varmvatten förbrukad",  # sv
    ),
    "dhw_delivered": (
        "Producció d'ACS",  # ca
        "Brugsvand leveret",  # da
        "TWW Geliefert",  # de
        "DHW Delivered",  # en
        "ACS Entregada",  # es
        "LKV tuotettu",  # fi
        "Energ Délivrée ECS",  # fr
        "En. ACS Prod. Ieri",  # it
        "SWW geleverd",  # nl
        "DHW levert",  # no
        "CWU dostarczone",  # pl
        "Dodaná energia TÚV",  # sk
        "TSV oddano",  # sl
        "Varmvatten levererad",  # sv
    ),
    "cool_consumed": (
        "Consum de refrigeració",  # ca
        "Køling brugt",  # da
        "Kühlung Verbraucht",  # de
        "Cool Consumed",  # en
        "Refrigeración Consumida",  # es
        "Jäähdytys kulutettu",  # fi
        "Conso Clim",  # fr
        "En. Raff. Utilizzata",  # it
        "Koelen verbruikt",  # nl
        "Kjøling brukt",  # no
        "Chłodzenie zużyte",  # pl
        "Spotreba chladenia",  # sk
        "Hlajenje porabljeno",  # sl
        "Kylning förbrukad",  # sv
    ),
    "cool_delivered": (
        "Producció de refrigeració",  # ca
        "Køling leveret",  # da
        "Kühlung Geliefert",  # de
        "Cool Delivered",  # en
        "Refrigeración Entregada",  # es
        "Jäähdytys tuotettu",  # fi
        "Energ Délivrée Clim",  # fr
        "En. Raff. Prod. Ieri",  # it
        "Koelen geleverd",  # nl
        "Kjøling levert",  # no
        "Chłodzenie dostarczone",  # pl
        "Dodané chladenie",  # sk
        "Hlajenje oddano",  # sl
        "Kylning levererad",  # sv
    ),
    "compressor_frequency": (
        "Freqüència del compressor",  # ca
        "Kompressor frekvens",  # da
        "Kompressor-Frequenz",  # de
        "Compressor Frequency",  # en
        "Frecuencia del Compresor",  # es
        "Kompressorin taajuus",  # fi
        "Freq Compresseur",  # fr
        "Freq. Compressore",  # it
        "Compressor frequentie",  # nl
        "Kompressorfrekvens",  # no
        "Częstotliwość sprężarki",  # pl
        "Frekvencia kompresora",  # sk
        "Frekvenca kompresorja",  # sl
        "Kompressor frekvens",  # sv
    ),
    "status_operation": (
        "Mode de funcionament",  # ca
        "Driftsmodus",  # da
        "Betriebsmodus",  # de
        "Operation Mode",  # en
        "Modo de Operación",  # es
        "Toimintatila",  # fi
        "Mode de fonctionnement",  # fr
        "Modalità Funzionamento",  # it
        "Status Bedrijf",  # nl
        "Driftsmodus",  # no
        "Tryb pracy",  # pl
        "Prevádzkový režim",  # sk
        "Način delovanja",  # sl
        "Driftläge",  # sv
    ),
    "status_defrost": (
        "Desglaç",  # ca
        "Afrimning",  # da
        "Abtauen",  # de
        "Defrost",  # en
        "Descongelar",  # es
        "Sulatus",  # fi
        "Dégivrage",  # fr
        "Sbrinamento",  # it
        "Status defrost",  # nl
        "Avrim",  # no
        "Odmrażanie",  # pl
        "Odmrazovanie",  # sk
        "Odtajevanje",  # sl
        "Avfrostning",  # sv
    ),
    "outside_temp": (
        "Temp. exterior",  # ca
        "Udetemperatur",  # da
        "Außentemperatur",  # de
        "Outside Temp",  # en
        "Temp. Exterior",  # es
        "Ulkolämpötila",  # fi
        "Temp Ext",  # fr
        "T. Esterna",  # it
        "Buiten temp",  # nl
        "Utetemperatur",  # no
        "Temperatura zewnętrzna",  # pl
        "Vonkajšia teplota",  # sk
        "Zunanja temperatura",  # sl
        "Utetemperatur",  # sv
    ),
    "hp_feed_temp": (
        "Temp. impulsió",  # ca
        "Fremledning temperatur",  # da
        "Vorlauftemperatur",  # de
        "Feed Temp",  # en
        "Temp. Alimentación",  # es
        "Menolämpötila",  # fi
        "Temp départ",  # fr
        "T. Mandata PDC",  # it
        "Aanvoer temp",  # nl
        "Fremløp temperatur",  # no
        "Temperatura zasilania",  # pl
        "Výstupná teplota",  # sk
        "Temperatura dovoda",  # sl
        "Framledning temperatur",  # sv
    ),
    "hp_return_temp": (
        "Temp. retorn",  # ca
        "Retur temperatur",  # da
        "Rücklauftemperatur",  # de
        "Return Temp",  # en
        "Temp. Retorno",  # es
        "Paluulämpötila",  # fi
        "Temp retour",  # fr
        "T. Ritorno Liq. Refr.",  # it
        "Retour temp",  # nl
        "Retur temperatur",  # no
        "Temperatura powrotu",  # pl
        "Vratná teplota",  # sk
        "Temperatura povratka",  # sl
        "Retur temperatur",  # sv
    ),
    "flow_rate": (
        "Cabal",  # ca
        "Flow",  # da
        "Durchflussrate",  # de
        "Flow Rate",  # en
        "Caudal",  # es
        "Virtausnopeus",  # fi
        "Débit",  # fr
        "Portata",  # it
        "Flow waarde",  # nl
        "Flytrate",  # no
        "Przepływ",  # pl
        "Prietok vody",  # sk
        "Pretok",  # sl
        "Flöde",  # sv
    ),
    "dhw_temp": (
        "Temp. actual ACS",  # ca
        "Brugsvand nuværende temp",  # da
        "TWW Aktuelle Temperatur",  # de
        "DHW Current Temp",  # en
        "Temperatura Actual ACS",  # es
        "LKV lämpötila",  # fi
        "Temp actuelle ECS",  # fr
        "T. Serbatoio Inf.",  # it
        "SWW huidige temp",  # nl
        "DHW nåværende temperatur",  # no
        "Aktualna temperatura CWU",  # pl
        "Teplota TÚV",  # sk
        "TSV trenutna temperatura",  # sl
        "Varmvatten nuvarande temp",  # sv
    ),
}

OPERATION_LABELS: dict[str, tuple[str, ...]] = {
    "operation_off": (
        "Aturada",  # ca
        "Fra",  # da
        "Aus",  # de
        "Off",  # en
        "Apagado",  # es
        "Pois päältä",  # fi
        "Off",  # fr
        "Spento",  # it
        "Uit",  # nl
        "Av",  # no
        "Wyłączony",  # pl
        "Vypnuté",  # sk
        "Izklopljeno",  # sl
        "Av",  # sv
    ),
    "hotwater": (
        "Escalfant ACS",  # ca
        "Brugsvand",  # da
        "Warmwasser",  # de
        "Heating Water",  # en
        "Agua Caliente",  # es
        "Käyttöveden lämmitys",  # fi
        "Eau chaude",  # fr
        "Acqua Calda",  # it
        "SWW",  # nl
        "Varmtvann",  # no
        "Woda grzewcza",  # pl
        "Ohrev vody",  # sk
        "Ogrevanje TSV",  # sl
        "Varmvatten",  # sv
    ),
    "heating": (
        "Calefacció",  # ca
        "Opvarmning",  # da
        "Raumheizung",  # de
        "Space Heating",  # en
        "Calefacción",  # es
        "Tilojen lämmitys",  # fi
        "Chauffage",  # fr
        "Riscaldamento",  # it
        "Verwarmen",  # nl
        "Oppvarming",  # no
        "Ogrzewanie pomieszczeń",  # pl
        "Kúrenie",  # sk
        "Ogrevanje prostorov",  # sl
        "Uppvärmning",  # sv
    ),
    "cooling": (
        "Refrigeració",  # ca
        "Køling",  # da
        "Raumkühlung",  # de
        "Space Cooling",  # en
        "Refrigeración",  # es
        "Tilojen jäähdytys",  # fi
        "Climatisation",  # fr
        "Raffreddamento",  # it
        "Koelen",  # nl
        "Kjøling",  # no
        "Chłodzenie pomieszczeń",  # pl
        "Chladenie",  # sk
        "Hlajenje prostorov",  # sl
        "Kylning",  # sv
    ),
    "frost_protection": (
        "Protecció antigel",  # ca
        "Frostbeskyttelse",  # da
        "Frostschutz",  # de
        "Frost Protection",  # en
        "Protección contra heladas",  # es
        "Jäätymissuojaus",  # fi
        "Protection contre le givre",  # fr
        "protezione dal gelo",  # it
        "Vorstbescherming",  # nl
        "Frostbeskyttelse",  # no
        "Ochrona przed mrozem",  # pl
        "Ochrana pred mrazom",  # sk
        "Zaščita pred zmrzaljo",  # sl
        "Frostskydd",  # sv
    ),
    "legionella_prevention": (
        "Prevenció de legionel·la",  # ca
        "Legionella forebyggelse",  # da
        "Legionellen-Schutz",  # de
        "Legionella Prevention",  # en
        "Prevención de Legionela",  # es
        "Legionellasuojaus",  # fi
        "Prévention Légionelle",  # fr
        "Prevenzione della Legionella",  # it
        "Legionellapreventie",  # nl
        "Legionella forebygging",  # no
        "Zapobieganie legionelli",  # pl
        "Prevencia legionely",  # sk
        "Zaščita pred legionelo",  # sl
        "Legionellaskydd",  # sv
    ),
}


def _loose(text: str) -> str:
    """A name the way a version 1 object_id keeps it: lower case, every
    other character "_" (one per byte or per character, depending on the
    ESPHome version), runs of "_" collapsed. lower(), not casefold(): "ß"
    stays one character."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", text.lower()))


_BY_NAME: dict[str, str] = {
    label.casefold(): key for key, labels in LABELS.items() for label in labels
}
_BY_LOOSE: dict[str, str] = {
    _loose(label): key for key, labels in LABELS.items() for label in labels
}
_MAC = re.compile(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}")
_TYPES = frozenset({"sensor", "binary_sensor", "text_sensor"})


def parse_unique_id(unique_id: str) -> tuple[str, str] | None:
    """(device, name or object_id) of an ESPHome sensor's unique id.

    The device is the MAC, with "/<sub-device id>" for a sub-device; None
    for other formats and other entity types.
    """
    if "/" in unique_id:  # version 3
        parts = unique_id.split("/", 3)
        if len(parts) != 4:
            return None
        mac, device_id, kind, name = parts
        sub = "" if device_id == "0" else device_id
    else:  # versions 1 and 2
        mac, _, rest = unique_id.partition("-")
        kind, _, name = rest.partition("-")
        name, _, sub = name.partition("@")
    if not (_MAC.fullmatch(mac) and kind in _TYPES and name):
        return None
    if sub and not sub.isdigit():
        return None
    device = mac.upper()
    return (f"{device}/{sub}" if sub else device), name


def label_key(name: str | None) -> str | None:
    """Firmware key of an entity name in any language, None if unknown."""
    if not name:
        return None
    return _BY_NAME.get(name.strip().casefold()) or _BY_LOOSE.get(_loose(name))


class EsphomeEcodanTemplate(Template):
    """Groups by ESP (MAC); the key is the firmware key of the entity's name."""

    def split(self, unique_id: str) -> tuple[str, str] | None:
        if (parts := parse_unique_id(unique_id)) is None:
            return None
        device, name = parts
        key = label_key(name)
        return (device, key) if key else None

    def group(
        self, entries: Iterable[RegistryEntry]
    ) -> dict[str, dict[tuple[str, str], str]]:
        by_prefix: dict[str, dict[tuple[str, str], str]] = {}
        for entry in entries:
            if entry.platform != self.platform or not entry.usable:
                continue
            if (parts := parse_unique_id(entry.unique_id)) is None:
                continue
            device, name = parts
            # The firmware's name; the unique id's only if the registry has none.
            key = label_key(entry.original_name) or label_key(name)
            if key is None:
                continue
            domain = entry.entity_id.split(".", 1)[0]
            by_prefix.setdefault(device, {})[(domain, key)] = entry.entity_id
        return by_prefix


# status_operation (confs/base.yaml): legionella prevention is a hot water
# charge to the disinfection temperature, frost protection no mode of its
# own; "Unknown" (English in every language) while the FTC has not told.
_OPERATION = {
    "operation_off": Activity.OFF,
    "hotwater": Activity.DHW,
    "heating": Activity.HEATING,
    "cooling": Activity.COOLING,
    "frost_protection": Activity.OTHER,
    "legionella_prevention": Activity.DHW,
}
ESPHOME_ECODAN_ACTIVITY: dict[str, Activity | None] = {
    word.casefold(): _OPERATION[key]
    for key, words in OPERATION_LABELS.items()
    for word in words
} | {"unknown": None}

_S, _B = "sensor", "binary_sensor"
ESPHOME_ECODAN = EsphomeEcodanTemplate(
    experimental=True,
    key="esphome_ecodan",
    label="Mitsubishi Ecodan (ESPHome esphome-ecodan-hp)",
    platform=PLATFORM,
    signals={
        # Previous day's totals, kWh, state class total.
        Signal.HEAT_HEATING: ((_S, "heating_delivered"),),
        Signal.HEAT_DHW: ((_S, "dhw_delivered"),),
        Signal.HEAT_COOLING: ((_S, "cool_delivered"),),
        Signal.ELEC_HEATING: ((_S, "heating_consumed"),),
        Signal.ELEC_DHW: ((_S, "dhw_consumed"),),
        Signal.ELEC_COOLING: ((_S, "cool_consumed"),),
        Signal.COMPRESSOR: ((_S, "compressor_frequency"),),  # Hz
        Signal.ACTIVITY: ((_S, "status_operation"),),  # a text sensor
        Signal.DEFROST_FLAG: ((_B, "status_defrost"),),
        Signal.OUTDOOR_TEMP: ((_S, "outside_temp"),),
        # Heat pump outlet/inlet, not the zones' or the boiler's.
        Signal.FLOW_TEMP: ((_S, "hp_feed_temp"),),
        Signal.RETURN_TEMP: ((_S, "hp_return_temp"),),
        Signal.FLOW_RATE: ((_S, "flow_rate"),),  # whole L/min
        # Packet 0x0C byte 7, the tank sensor (THW5 in the F1p decoder), not
        # the secondary one (byte 10, THW5A).
        Signal.DHW_TEMP: ((_S, "dhw_temp"),),
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING),
    activity_values=ESPHOME_ECODAN_ACTIVITY,
    day_values=True,
    previous_day=True,
)
