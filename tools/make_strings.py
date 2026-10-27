"""Generate strings.json, translations/en.json, de.json and icons.json for Wärmewacht."""

import json
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) / "custom_components" / "waermewacht"

PERIODS = {
    "today": ("today", "heute"),
    "yesterday": ("yesterday", "gestern"),
    "month": ("month", "Monat"),
    "season": ("season", "Saison"),
    "total": ("total", "gesamt"),
}
SCOPES = {
    # Short names: lists cut longer ones before the period.
    "heating": ("COP heating", "AZ Heizen", "mdi:heat-pump-outline"),
    "dhw": ("COP hot water", "AZ Warmwasser", "mdi:water-boiler"),
    "combined": ("COP heating+DHW", "AZ Heizen+WW", "mdi:heat-pump"),
    "cooling": ("EER cooling", "EER Kühlen", "mdi:snowflake"),
}
SENSORS = {
    "heat_heating": ("Heat heating", "Wärme Heizen", "mdi:fire"),
    "heat_dhw": ("Heat hot water", "Wärme Warmwasser", "mdi:water-boiler"),
    "heat_cooling": (
        "Heat removed cooling",
        "Wärme Kühlen",
        "mdi:snowflake-thermometer",
    ),
    "electricity_heating": (
        "Electricity heating",
        "Strom Heizen",
        "mdi:lightning-bolt",
    ),
    "electricity_dhw": (
        "Electricity hot water",
        "Strom Warmwasser",
        "mdi:lightning-bolt",
    ),
    "electricity_cooling": (
        "Electricity cooling",
        "Strom Kühlen",
        "mdi:lightning-bolt",
    ),
    "standby": ("Standby electricity", "Strom Stillstand", "mdi:power-sleep"),
    "cost_month": ("Electricity cost month", "Stromkosten Monat", "mdi:currency-eur"),
    "cost_season": (
        "Electricity cost season",
        "Stromkosten Saison",
        "mdi:currency-eur",
    ),
    "heat_cost_season": (
        "Heat cost per kWh season",
        "Wärmekosten je kWh Saison",
        "mdi:cash",
    ),
    "gas_savings_season": (
        "Savings vs. gas boiler season",
        "Ersparnis ggü. Gaskessel Saison",
        "mdi:piggy-bank-outline",
    ),
    "co2_savings_season": (
        "CO₂ savings vs. gas boiler season",
        "CO₂-Ersparnis ggü. Gaskessel Saison",
        "mdi:molecule-co2",
    ),
    "starts_today": ("Starts today", "Starts heute", "mdi:counter"),
    "starts_yesterday": ("Starts yesterday", "Starts gestern", "mdi:counter"),
    "starts_total": ("Starts total", "Starts gesamt", "mdi:counter"),
    "runtime_today": ("Run time today", "Laufzeit heute", "mdi:timer-outline"),
    "run_minutes_today": (
        "Run time per start today",
        "Laufzeit pro Start heute",
        "mdi:timer-sand",
    ),
    "run_minutes_week": (
        "Run time per start 7 days",
        "Laufzeit pro Start 7 Tage",
        "mdi:timer-sand",
    ),
    "run_minutes_month": (
        "Run time per start month",
        "Laufzeit pro Start Monat",
        "mdi:timer-sand",
    ),
    "short_runs_today": (
        "Short runs today",
        "Kurzläufe heute",
        "mdi:timer-alert-outline",
    ),
    "shortest_pause_today": (
        "Shortest pause today",
        "Kürzeste Pause heute",
        "mdi:pause-circle-outline",
    ),
    "defrosts_today": ("Defrosts today", "Abtauungen heute", "mdi:snowflake-melt"),
    "aux_share_month": (
        "Backup heater share month",
        "Heizstab-Anteil Monat",
        "mdi:heating-coil",
    ),
    "aux_share_season": (
        "Backup heater share season",
        "Heizstab-Anteil Saison",
        "mdi:heating-coil",
    ),
    "spread_today": (
        "Flow-return spread today",
        "Spreizung heute",
        "mdi:thermometer-lines",
    ),
    "flow_temp_today": (
        "Flow temperature today",
        "Vorlauftemperatur heute",
        "mdi:thermometer-water",
    ),
}
BINARY = {
    "cycling_problem": ("Conspicuous cycling", "Auffälliges Takten", "mdi:sine-wave")
}

FIELDS = {
    "heat_heating": ("Heat heating (meter)", "Wärme Heizen (Zähler)"),
    "elec_heating": ("Compressor electricity heating", "Strom Kompressor Heizen"),
    "aux_heating": ("Backup heater heating", "Strom Heizstab Heizen"),
    "heat_dhw": ("Heat hot water (meter)", "Wärme Warmwasser (Zähler)"),
    "elec_dhw": ("Compressor electricity hot water", "Strom Kompressor Warmwasser"),
    "aux_dhw": ("Backup heater hot water", "Strom Heizstab Warmwasser"),
    "heat_cooling": ("Heat removed cooling (meter)", "Wärme Kühlen (entzogen, Zähler)"),
    "elec_cooling": ("Compressor electricity cooling", "Strom Kompressor Kühlen"),
    "compressor": (
        "Compressor running (on/off or speed)",
        "Kompressor läuft (an/aus oder Drehzahl)",
    ),
    "activity": ("Activity", "Betriebsart (Aktivität)"),
    "starts_total": ("Compressor starts total", "Kompressorstarts gesamt"),
    "aux_total": (
        "Backup heater total (only without per mode)",
        "Strom Heizstab gesamt (nur ohne Aufteilung je Modus)",
    ),
    "outdoor_temp": ("Outdoor temperature", "Außentemperatur"),
    "flow_temp": ("Flow temperature", "Vorlauftemperatur"),
    "return_temp": ("Return temperature", "Rücklauftemperatur"),
    "flow_rate": ("Flow rate", "Durchfluss"),
}
SECTIONS = {
    "heating": (
        ("Heating", "Heizen"),
        ("heat_heating", "elec_heating", "aux_heating"),
        ("Cumulative meters in Wh/kWh/MWh.", "Fortlaufende Zähler in Wh/kWh/MWh."),
    ),
    "dhw": (("Hot water", "Warmwasser"), ("heat_dhw", "elec_dhw", "aux_dhw"), None),
    "cooling": (("Cooling", "Kühlen"), ("heat_cooling", "elec_cooling"), None),
    "operation": (
        ("Operation", "Betrieb"),
        ("compressor", "activity", "starts_total", "aux_total"),
        (
            "For starts, short runs, defrosts and standby.",
            "Für Starts, Kurzläufe, Abtauungen und Stillstand.",
        ),
    ),
    "measurements": (
        ("Measurements", "Messwerte"),
        ("outdoor_temp", "flow_temp", "return_temp", "flow_rate"),
        None,
    ),
}
MONTHS_EN = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
MONTHS_DE = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]


def build(lang: int) -> dict:
    t = lambda pair: pair[lang]  # noqa: E731
    sections = {}
    for key, (names, fields, desc) in SECTIONS.items():
        section = {"name": t(names), "data": {f: t(FIELDS[f]) for f in fields}}
        if desc:
            section["description"] = t(desc)
        sections[key] = section
    sensors = {}
    for scope, (en, de, _) in SCOPES.items():
        for period, names in PERIODS.items():
            sensors[f"ratio_{scope}_{period}"] = {
                "name": f"{(en, de)[lang]} {t(names)}"
            }
    sensors.update({k: {"name": t(v[:2])} for k, v in SENSORS.items()})
    return {
        "config": {
            "step": {
                "user": {
                    "title": t(("Set up a heat pump", "Wärmepumpe einrichten")),
                    "description": t(
                        (
                            "Wärmewacht only reads existing entities and never controls the heat pump. Templates (EMS-ESP, Bosch HomeCom) found {found} heat pump(s); every entity can be changed in the next step.\n\nDisabled entities a template would use: {disabled}. Enable them in the entity settings, wait until they report a value, then start this setup again.",
                            "Wärmewacht liest nur vorhandene Entitäten und steuert die Wärmepumpe nie. Vorlagen (EMS-ESP, Bosch HomeCom) haben {found} Wärmepumpe(n) gefunden; im nächsten Schritt lässt sich jede Entität ändern.\n\nDeaktivierte Entitäten, die eine Vorlage nutzen würde: {disabled}. In den Entitäts-Einstellungen aktivieren, warten, bis sie einen Wert melden, dann diese Einrichtung neu starten.",
                        )
                    ),
                    "data": {
                        "name": t(("Name", "Name")),
                        "source": t(("Source", "Quelle")),
                    },
                    "data_description": {
                        "name": t(
                            ("Prefix of the entity ids.", "Präfix der Entity-IDs.")
                        ),
                        "source": t(
                            (
                                "A found heat pump fills in the entities; manual: pick them yourself.",
                                "Eine gefundene Wärmepumpe füllt die Entitäten aus; manuell: selbst auswählen.",
                            )
                        ),
                    },
                },
                "entities": {
                    "title": t(("Entities", "Entitäten")),
                    "description": t(
                        (
                            "At least one mode needs a heat and an electricity meter. Electricity meters of the compressor without backup heater; the backup heater separately.",
                            "Mindestens ein Modus braucht einen Wärme- und einen Stromzähler. Stromzähler des Kompressors ohne Heizstab; den Heizstab getrennt.",
                        )
                    ),
                    "sections": sections,
                },
            },
            "error": {
                "no_mode": t(
                    (
                        "Choose a heat and an electricity meter for at least one mode.",
                        "Für mindestens einen Modus einen Wärme- und einen Stromzähler wählen.",
                    )
                ),
                "energy_unit": t(
                    (
                        "An energy meter has no unit Wh, kWh or MWh.",
                        "Ein Energiezähler hat nicht die Einheit Wh, kWh oder MWh.",
                    )
                ),
                "aux_twice": t(
                    (
                        "Backup heater either per mode or as total, not both.",
                        "Heizstab entweder je Modus oder gesamt, nicht beides.",
                    )
                ),
            },
            "abort": {
                "already_configured": t(
                    (
                        "This heat pump is already set up.",
                        "Diese Wärmepumpe ist bereits eingerichtet.",
                    )
                ),
                "reconfigure_successful": t(
                    (
                        "Entities saved.",
                        "Entitäten gespeichert.",
                    )
                ),
            },
        },
        "options": {
            "step": {
                "init": {
                    "title": t(("Settings", "Einstellungen")),
                    "data": {
                        "min_electricity": t(
                            (
                                "Minimum electricity for a ratio",
                                "Mindeststrom für eine Arbeitszahl",
                            )
                        ),
                        "short_run_minutes": t(("Short run below", "Kurzlauf unter")),
                        "critical_run_minutes": t(
                            ("Critical run below", "Kritischer Lauf unter")
                        ),
                        "starts_per_hour": t(
                            (
                                "Conspicuous above starts per hour",
                                "Auffällig ab Starts pro Stunde über",
                            )
                        ),
                        "season_start_month": t(
                            ("Season starts in", "Saison beginnt im")
                        ),
                    },
                    "data_description": {
                        "min_electricity": t(
                            (
                                "Below it the ratio is unknown instead of a random value.",
                                "Darunter ist die Arbeitszahl unbekannt statt zufällig.",
                            )
                        ),
                        "season_start_month": t(
                            (
                                "The current season is recomputed from the statistics.",
                                "Die laufende Saison wird aus der Statistik neu berechnet.",
                            )
                        ),
                    },
                    "sections": {
                        "costs": {
                            "name": t(
                                (
                                    "Costs and gas comparison (optional)",
                                    "Kosten und Gasvergleich (optional)",
                                )
                            ),
                            "description": t(
                                (
                                    "Every field may stay empty. Without an electricity price there are no costs; without a gas price the comparison shows CO₂ only; without a base price only the working prices are compared.",
                                    "Jedes Feld darf leer bleiben. Ohne Strompreis gibt es keine Kosten, ohne Gaspreis vergleicht Wärmewacht nur das CO₂, ohne Grundpreis nur die Arbeitspreise.",
                                )
                            ),
                            "data": {
                                "electricity_price": t(
                                    ("Electricity price", "Strompreis")
                                ),
                                "gas_price": t(
                                    ("Gas working price", "Gas-Arbeitspreis")
                                ),
                                "gas_base_price": t(
                                    ("Gas base price", "Gas-Grundpreis")
                                ),
                            },
                            "data_description": {
                                "electricity_price": t(
                                    (
                                        "Gross price per kWh of the heat pump's electricity.",
                                        "Bruttopreis je kWh für den Strom der Wärmepumpe.",
                                    )
                                ),
                                "gas_price": t(
                                    (
                                        "Gross, per kWh on the gross calorific value (as on the gas bill). Boiler efficiency 0.87.",
                                        "Brutto je kWh Brennwert (wie auf der Gasrechnung). Kesselwirkungsgrad 0,87.",
                                    )
                                ),
                                "gas_base_price": t(
                                    (
                                        "Gross per year; spread over the days of a period.",
                                        "Brutto je Jahr; wird auf die Tage eines Zeitraums verteilt.",
                                    )
                                ),
                            },
                        },
                    },
                }
            }
        },
        "selector": {
            "source": {"options": {"manual": t(("Manual", "Manuell"))}},
            "month": {
                "options": {
                    str(i + 1): (MONTHS_EN, MONTHS_DE)[lang][i] for i in range(12)
                }
            },
        },
        "entity": {
            "binary_sensor": {k: {"name": t(v[:2])} for k, v in BINARY.items()},
            "sensor": sensors,
        },
        "exceptions": {
            "start_after_end": {
                "message": t(
                    (
                        "The start must be before the end.",
                        "Der Beginn muss vor dem Ende liegen.",
                    )
                )
            },
            "no_recorder": {
                "message": t(
                    (
                        "The report needs the recorder (long-term statistics).",
                        "Der Bericht braucht den Recorder (Langzeitstatistik).",
                    )
                )
            },
        },
        "issues": {
            "missing_entity": {
                "title": t(("Wärmewacht: entity missing", "Wärmewacht: Entität fehlt")),
                "description": t(
                    (
                        "The heat pump {name} uses entities that no longer exist: {entities}. Renamed or removed? Choose them again under Devices & services → Wärmewacht → Reconfigure.",
                        "Die Wärmepumpe {name} nutzt Entitäten, die es nicht mehr gibt: {entities}. Umbenannt oder entfernt? Unter Geräte & Dienste → Wärmewacht → Neu konfigurieren wieder auswählen.",
                    )
                ),
            },
            "energy_unit": {
                "title": t(
                    ("Wärmewacht: unusable unit", "Wärmewacht: unbrauchbare Einheit")
                ),
                "description": t(
                    (
                        "These energy meters of {name} report no unit Wh, kWh or MWh and are not counted: {entities}.",
                        "Diese Energiezähler von {name} melden nicht die Einheit Wh, kWh oder MWh und werden nicht gezählt: {entities}.",
                    )
                ),
            },
        },
        "services": {
            "report": {
                "name": t(("Report", "Bericht")),
                "description": t(
                    (
                        "Heat, electricity and ratios of a period, also before the setup (from the long-term statistics), with months.",
                        "Wärme, Strom und Arbeitszahlen eines Zeitraums, auch vor der Einrichtung (aus der Langzeitstatistik), mit Monaten.",
                    )
                ),
                "fields": {
                    "config_entry": {
                        "name": t(("Heat pump", "Wärmepumpe")),
                        "description": t(
                            ("The Wärmewacht entry.", "Der Wärmewacht-Eintrag.")
                        ),
                    },
                    "start": {
                        "name": t(("Start", "Beginn")),
                        "description": t(
                            (
                                "Without: start of the current season. Times without zone are local time.",
                                "Ohne: Beginn der laufenden Saison. Zeiten ohne Zone sind Ortszeit.",
                            )
                        ),
                    },
                    "end": {
                        "name": t(("End", "Ende")),
                        "description": t(("Without: now.", "Ohne: jetzt.")),
                    },
                },
            }
        },
    }


def icons() -> dict:
    sensor = {}
    for scope, (_, _, icon) in SCOPES.items():
        for period in PERIODS:
            sensor[f"ratio_{scope}_{period}"] = {"default": icon}
    sensor.update({k: {"default": v[2]} for k, v in SENSORS.items()})
    return {
        "entity": {
            "binary_sensor": {k: {"default": v[2]} for k, v in BINARY.items()},
            "sensor": sensor,
        },
        "services": {"report": {"service": "mdi:file-chart-outline"}},
    }


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


write(ROOT / "strings.json", build(0))
write(ROOT / "translations" / "en.json", build(0))
write(ROOT / "translations" / "de.json", build(1))
write(ROOT / "icons.json", icons())
print("ok")
