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
    "performance_curve_heating": (
        "Performance curve heating",
        "AZ-Kennlinie Heizen",
        "mdi:chart-bell-curve-cumulative",
    ),
    "heat_load_per_kelvin": (
        "Heat load per kelvin",
        "Heizlast je Kelvin",
        "mdi:home-thermometer-outline",
    ),
    "heat_load_design": (
        "Heat load at design temperature",
        "Heizlast bei Normaußentemperatur",
        "mdi:home-thermometer",
    ),
    "starts_today": ("Starts today", "Starts heute", "mdi:counter"),
    "starts_yesterday": ("Starts yesterday", "Starts gestern", "mdi:counter"),
    "starts_total": ("Starts total", "Starts gesamt", "mdi:counter"),
    "starts_season": ("Starts season", "Starts Saison", "mdi:counter"),
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
    "spread_7d": (
        "Flow-return spread 7 days",
        "Spreizung 7 Tage",
        "mdi:arrow-expand-vertical",
    ),
    "oversize_factor": (
        "Power per heat load",
        "Leistung je Heizlast",
        "mdi:resize",
    ),
    "flow_at_zero": (
        "Flow temperature at 0 °C",
        "Vorlauf bei 0 °C",
        "mdi:chart-line-variant",
    ),
    "degree_days_season": (
        "Degree days season",
        "Gradtage Saison",
        "mdi:thermometer-minus",
    ),
    "heat_per_degree_day_season": (
        "Heat per degree day season",
        "Wärme je Gradtag Saison",
        "mdi:home-thermometer-outline",
    ),
    "ratio_dhw_last_charge": (
        "COP hot water last charge",
        "AZ Warmwasser letzte Ladung",
        "mdi:water-boiler",
    ),
    "ratio_dhw_charges_30d": (
        "COP hot water charges 30 days",
        "AZ Warmwasser-Ladungen 30 Tage",
        "mdi:water-boiler",
    ),
    "last_disinfection": (
        "Last thermal disinfection",
        "Letzte thermische Desinfektion",
        "mdi:bacteria-outline",
    ),
    # Gas boiler entry (gas_sensor.py).
    "gas_heat_load_per_kelvin": (
        "Heat load per kelvin",
        "Heizlast je Kelvin",
        "mdi:home-thermometer-outline",
    ),
    "gas_heat_load_design": (
        "Heat load at design temperature",
        "Heizlast bei Normaußentemperatur",
        "mdi:home-thermometer",
    ),
    "gas_heating_limit": (
        "Heating limit",
        "Heizgrenze",
        "mdi:thermometer-chevron-up",
    ),
    "gas_heat_per_degree_day": (
        "Heat per degree day",
        "Wärme je Gradtag",
        "mdi:chart-bell-curve-cumulative",
    ),
    "gas_dhw_share": ("Hot water share", "Warmwasseranteil", "mdi:water-boiler"),
    "gas_consumption_year": ("Gas 365 days", "Gas 365 Tage", "mdi:fire"),
    "gas_cost_year": ("Gas cost 365 days", "Gaskosten 365 Tage", "mdi:cash"),
}
BINARY = {
    "cycling_problem": ("Conspicuous cycling", "Auffälliges Takten", "mdi:sine-wave"),
    "efficiency_drop": (
        "Efficiency dropped",
        "Effizienz gesunken",
        "mdi:trending-down",
    ),
    "aux_mild_weather": (
        "Backup heater on mild days",
        "Heizstab bei milder Witterung",
        "mdi:heating-coil",
    ),
    "aux_dhw_charges": (
        "Backup heater in hot water charges",
        "Heizstab bei Warmwasserladungen",
        "mdi:water-boiler-alert",
    ),
    "dhw_efficiency_drop": (
        "Hot water efficiency below last year",
        "Warmwasser-Effizienz unter Vorjahr",
        "mdi:water-thermometer-outline",
    ),
}
BUTTONS = {
    "restart_comparison": (
        "Restart efficiency comparison",
        "Effizienzvergleich neu starten",
        "mdi:restart",
    ),
    "rebuild_history": (
        "Recalculate look-back",
        "Rückblick neu berechnen",
        "mdi:history",
    ),
}

FIELDS = {
    "heat_heating": ("Heat produced heating (meter)", "Erzeugte Wärme Heizen (Zähler)"),
    "elec_heating": ("Compressor electricity heating", "Strom Kompressor Heizen"),
    "aux_heating": ("Backup heater heating", "Strom Heizstab Heizen"),
    "heat_dhw": (
        "Heat produced hot water (meter)",
        "Erzeugte Wärme Warmwasser (Zähler)",
    ),
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
    "elec_total": (
        "Compressor electricity total (only without per mode)",
        "Strom Kompressor gesamt (nur ohne Aufteilung je Modus)",
    ),
    "aux_total": (
        "Backup heater total (only without per mode)",
        "Strom Heizstab gesamt (nur ohne Aufteilung je Modus)",
    ),
    "outdoor_temp": ("Outdoor temperature", "Außentemperatur"),
    "flow_temp": ("Flow temperature", "Vorlauftemperatur"),
    "return_temp": ("Return temperature", "Rücklauftemperatur"),
    "flow_rate": ("Flow rate", "Durchfluss"),
    "dhw_temp": (
        "Hot water temperature (actual, tank)",
        "Warmwasser-Temperatur (Ist, Speicher)",
    ),
    "elec_defrost": ("Electricity defrost", "Strom Abtauen"),
    "elec_standby": ("Electricity standby", "Strom Stillstand"),
    "defrost_flag": ("Defrost running (on/off)", "Abtauen läuft (an/aus)"),
    "dhw_flag": ("Hot water running (on/off)", "Warmwasser läuft (an/aus)"),
    "cooling_flag": ("Cooling running (on/off)", "Kühlen läuft (an/aus)"),
    "heating_flag": ("Heating running (on/off)", "Heizen läuft (an/aus)"),
    "cooling_mode": (
        "Set operating mode (cooling?)",
        "Eingestellte Betriebsart (Kühlen?)",
    ),
}
# Help below a field of the setup form (data_description).
FIELD_HELP = {
    "elec_heating": (
        "Electricity of the compressor for heating, without the backup heater.",
        "Strom des Kompressors fürs Heizen, ohne Heizstab.",
    ),
    "aux_heating": (
        "Electricity of the backup heater for heating, if it is metered apart.",
        "Strom des Heizstabs fürs Heizen, falls er getrennt gezählt wird.",
    ),
    "dhw_temp": (
        "Actual temperature in the hot water tank, not the setpoint. Gives charges and disinfections.",
        "Ist-Temperatur im Warmwasserspeicher, nicht der Sollwert. Ergibt Ladungen und Desinfektionen.",
    ),
    "compressor": (
        'An on/off entity, or a number above 0 while the compressor runs (speed, frequency, modulation in %). Not a status text such as "heating": that belongs under Activity.',
        "Eine An/aus-Entität oder eine Zahl, die beim Lauf über 0 liegt (Drehzahl, Frequenz, Modulation in %). Kein Status-Text wie „heating“ – der gehört unter „Betriebsart“.",
    ),
    "activity": (
        'What the heat pump is doing (heating, hot water, defrost, ...), e.g. EMS-ESP "hpactivity". Gives defrosts and the mode of each run; without it runs are counted without a mode.',
        "Was die Wärmepumpe gerade tut (Heizen, Warmwasser, Abtauen …), z. B. EMS-ESP „hpactivity“. Ergibt Abtauungen und die Betriebsart jedes Laufs; ohne sie werden Läufe ohne Betriebsart gezählt.",
    ),
    "starts_total": (
        "The heat pump's own counter of compressor starts. Without it Wärmewacht counts starts from the setup on.",
        "Zähler der Kompressorstarts der Wärmepumpe selbst. Ohne ihn zählt Wärmewacht die Starts ab der Einrichtung.",
    ),
    "elec_total": (
        "Only if the compressor electricity exists as one meter for all modes; then leave the fields per mode empty.",
        "Nur, wenn es den Kompressorstrom nur als einen Zähler für alle Betriebsarten gibt; dann die Felder je Betriebsart leer lassen.",
    ),
    "aux_total": (
        "Only if the backup heater exists as one meter for all modes; then leave the fields per mode empty.",
        "Nur, wenn es den Heizstab nur als einen Zähler für alle Betriebsarten gibt; dann die Felder je Betriebsart leer lassen.",
    ),
    "elec_defrost": (
        "Only if the heat pump meters this electricity apart (Lambda, iDM).",
        "Nur, wenn die Wärmepumpe diesen Strom getrennt zählt (Lambda, iDM).",
    ),
    "elec_standby": (
        "Only if the heat pump meters this electricity apart (Lambda). Otherwise Wärmewacht separates standby itself.",
        "Nur, wenn die Wärmepumpe diesen Strom getrennt zählt (Lambda). Sonst trennt Wärmewacht den Stillstand selbst ab.",
    ),
    "outdoor_temp": (
        "Preferably the heat pump's own outdoor sensor; if it is in the sun, a nearby weather station.",
        "Am besten der Außenfühler der Wärmepumpe; liegt er in der Sonne, eine nahe Wetterstation.",
    ),
    "flow_rate": (
        "Flow in the heating circuit (l/h, L/min, m³/h, ...).",
        "Durchfluss im Heizkreis (l/h, L/min, m³/h …).",
    ),
}
SECTIONS = {
    "heating": (
        ("Heating", "Heizen"),
        ("heat_heating", "elec_heating", "aux_heating"),
        (
            "The heat the heat pump produced and the electricity its compressor needed for it: cumulative meters in Wh/kWh/MWh, not power.",
            "Die Wärme, die die Wärmepumpe erzeugt hat, und der Strom, den ihr Kompressor dafür gebraucht hat: fortlaufende Zähler in Wh/kWh/MWh, keine Leistung.",
        ),
    ),
    "dhw": (
        ("Hot water", "Warmwasser"),
        ("heat_dhw", "elec_dhw", "aux_dhw", "dhw_temp"),
        None,
    ),
    "cooling": (("Cooling", "Kühlen"), ("heat_cooling", "elec_cooling"), None),
    "operation": (
        ("Operation", "Betrieb"),
        (
            "compressor",
            "activity",
            "starts_total",
            "elec_total",
            "aux_total",
            "elec_defrost",
            "elec_standby",
        ),
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
    "activity_parts": (
        ("Activity from several entities", "Betriebsart aus mehreren Entitäten"),
        ("defrost_flag", "dhw_flag", "cooling_flag", "heating_flag", "cooling_mode"),
        (
            "Only if the heat pump has no single activity entity. An 'on' flag wins in this order: defrost, hot water, cooling, heating. The set mode turns heating into cooling while it cools.",
            "Nur, wenn die Wärmepumpe keine einzelne Betriebsart-Entität hat. Ein Merker „an“ gewinnt in dieser Reihenfolge: Abtauen, Warmwasser, Kühlen, Heizen. Die eingestellte Betriebsart macht aus Heizen Kühlen, solange sie kühlt.",
        ),
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


def _build(lang: int) -> dict:
    t = lambda pair: pair[lang]  # noqa: E731
    sections = {}
    for key, (names, fields, desc) in SECTIONS.items():
        section = {"name": t(names), "data": {f: t(FIELDS[f]) for f in fields}}
        if desc:
            section["description"] = t(desc)
        if help_texts := {f: t(FIELD_HELP[f]) for f in fields if f in FIELD_HELP}:
            section["data_description"] = help_texts
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
                            "Wärmewacht only reads existing entities and never controls the heat pump. Templates found {found} heat pump(s); every entity can be changed in the next step.",
                            "Wärmewacht liest nur vorhandene Entitäten und steuert die Wärmepumpe nie. Vorlagen haben {found} Wärmepumpe(n) gefunden; im nächsten Schritt lässt sich jede Entität ändern.",
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
                        "Choose a heat and an electricity meter for at least one mode, or at least the compressor (then cycling and electricity only, no ratios).",
                        "Für mindestens einen Modus einen Wärme- und einen Stromzähler wählen oder wenigstens den Kompressor (dann nur Takte und Strom, keine Arbeitszahlen).",
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
                "elec_twice": t(
                    (
                        "Compressor electricity either per mode or as total, not both.",
                        "Strom Kompressor entweder je Modus oder gesamt, nicht beides.",
                    )
                ),
                "day_counter": t(
                    (
                        "An energy meter fell back at the same time of day on several days: it looks like a day counter (energy today). Choose lifetime counters (total energy) here. If it is a total counter after all, submit again unchanged.",
                        "Ein Energiezähler ist an mehreren Tagen zur selben Uhrzeit zurückgefallen: Er sieht nach einem Tageszähler aus (Energie heute). Hier Lebenszeit-Zähler (Gesamtenergie) wählen. Ist es doch ein Gesamtzähler, unverändert noch einmal absenden.",
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
                        "aux_mild_from": t(
                            (
                                "Backup heater: mild weather from",
                                "Heizstab: milde Witterung ab",
                            )
                        ),
                        "efficiency_drop_percent": t(
                            ("Efficiency dropped from", "Effizienz gesunken ab")
                        ),
                        "disinfection_temp": t(
                            ("Thermal disinfection from", "Thermische Desinfektion ab")
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
                        "aux_mild_from": t(
                            (
                                "Daily mean outdoor temperature from which the heat pump should heat alone.",
                                "Tagesmittel der Außentemperatur, ab dem die Wärmepumpe allein heizen sollte.",
                            )
                        ),
                        "efficiency_drop_percent": t(
                            (
                                "Drop of the heating ratio against the previous season at the same outdoor temperature; off again 5 points lower.",
                                "Rückgang der AZ Heizen gegenüber der Vorsaison bei gleicher Außentemperatur; aus erst 5 Punkte darunter.",
                            )
                        ),
                        "disinfection_temp": t(
                            (
                                "Hot water temperature from which a charge counts as thermal disinfection (DVGW W 551: 60 °C at the outlet; the storage sensor may read lower).",
                                "Warmwasser-Temperatur, ab der eine Ladung als thermische Desinfektion zählt (DVGW W 551: 60 °C am Austritt; der Speicherfühler zeigt oft weniger).",
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
                                    "Every field may stay empty. Without an electricity price there are no costs; without a gas price no gas comparison; without a base price only the working prices are compared.",
                                    "Jedes Feld darf leer bleiben. Ohne Strompreis gibt es keine Kosten, ohne Gaspreis kein Gasvergleich, ohne Grundpreis nur die Arbeitspreise.",
                                )
                            ),
                            "data": {
                                "electricity_price": t(
                                    ("Electricity price", "Strompreis")
                                ),
                                "electricity_base_price": t(
                                    ("Electricity base price", "Strom-Grundpreis")
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
                                "electricity_base_price": t(
                                    (
                                        "Only for a separate heat pump meter (heat pump tariff), gross per year. On the household meter leave it empty: that base price is paid anyway.",
                                        "Nur bei eigenem Wärmepumpenzähler (Wärmepumpentarif), brutto je Jahr. Am Haushaltszähler leer lassen: Dessen Grundpreis fällt ohnehin an.",
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
                        "heat_load": {
                            "name": t(("Heat load (optional)", "Heizlast (optional)")),
                            "data": {
                                "design_outdoor_temp": t(
                                    (
                                        "Design outdoor temperature",
                                        "Normaußentemperatur",
                                    )
                                ),
                                "rated_power_kw": t(
                                    (
                                        "Rated heating power at A-7/W35",
                                        "Heizleistung bei A−7/W35",
                                    )
                                ),
                                "min_power_kw": t(
                                    ("Smallest heating power", "Kleinste Heizleistung")
                                ),
                            },
                            "data_description": {
                                "design_outdoor_temp": t(
                                    (
                                        "From DIN/TS 12831-1 for your postcode (e.g. the BWP climate map). Without it the heat load is given per kelvin only.",
                                        "Aus DIN/TS 12831-1 für deine Postleitzahl (z. B. BWP-Klimakarte). Ohne sie nur die Heizlast je Kelvin.",
                                    )
                                ),
                                "rated_power_kw": t(
                                    (
                                        "From the data sheet; gives the power per heat load.",
                                        "Aus dem Datenblatt; ergibt die Leistung je Heizlast.",
                                    )
                                ),
                                "min_power_kw": t(
                                    (
                                        "From the data sheet; shows whether cycling in mild weather is to be expected.",
                                        "Aus dem Datenblatt; zeigt, ob Takten in der Übergangszeit zu erwarten ist.",
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
            "curve_scope": {
                "options": {
                    "heating": t(("Heating", "Heizen")),
                    "heating_dhw": t(
                        ("Heating and hot water", "Heizen und Warmwasser")
                    ),
                }
            },
            "month": {
                "options": {
                    str(i + 1): (MONTHS_EN, MONTHS_DE)[lang][i] for i in range(12)
                }
            },
        },
        "entity": {
            "binary_sensor": {k: {"name": t(v[:2])} for k, v in BINARY.items()},
            "button": {k: {"name": t(v[:2])} for k, v in BUTTONS.items()},
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
            "no_outdoor": {
                "message": t(
                    (
                        "This needs an outdoor temperature in the entities.",
                        "Dafür braucht es eine Außentemperatur bei den Entitäten.",
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
            "no_look_back": {
                "message": t(
                    (
                        "This source has no usable statistics for a look-back.",
                        "Diese Quelle hat keine brauchbare Statistik für einen Rückblick.",
                    )
                )
            },
            "look_back_failed": {
                "message": t(
                    (
                        "Reading the statistics failed; see the log.",
                        "Die Statistik ließ sich nicht lesen; Details im Protokoll.",
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
            "flow_implausible": {
                "title": t(
                    (
                        "Wärmewacht: flow rate implausible",
                        "Wärmewacht: Durchfluss unplausibel",
                    )
                ),
                "description": t(
                    (
                        "While heating yesterday, {entities} of {name} showed {measured} l/h on average; heat and spread give about {expected} l/h. Usually the unit is wrong (e.g. l/h reported as L/min) or it is the wrong sensor. Check the entity or choose another one under Devices & services → Wärmewacht → Reconfigure. The notice disappears after a day with a fitting flow rate.",
                        "Beim Heizen zeigte {entities} von {name} gestern im Mittel {measured} l/h; Wärme und Spreizung ergeben etwa {expected} l/h. Meist stimmt die Einheit nicht (etwa l/h als L/min gemeldet) oder es ist der falsche Sensor. Prüfe die Entität oder wähle unter Geräte & Dienste → Wärmewacht → Neu konfigurieren eine andere. Der Hinweis verschwindet nach einem Tag mit passendem Durchfluss.",
                    )
                ),
            },
            "flow_zero": {
                "title": t(
                    (
                        "Wärmewacht: flow rate 0 while heating",
                        "Wärmewacht: Durchfluss 0 beim Heizen",
                    )
                ),
                "description": t(
                    (
                        "The flow rate of {name} ({entities}) stood at 0 for {minutes} minutes while the compressor was heating. A heat pump cannot heat without flow; usually the sensor delivers no real value. Check the entity or remove it under Reconfigure. The notice disappears as soon as flow returns.",
                        "Der Durchfluss von {name} ({entities}) stand {minutes} Minuten auf 0, während der Kompressor heizte. Ohne Durchfluss kann eine Wärmepumpe nicht heizen; meist liefert der Sensor keinen echten Wert. Prüfe die Entität oder entferne sie unter Neu konfigurieren. Der Hinweis verschwindet, sobald wieder Durchfluss kommt.",
                    )
                ),
            },
            "day_counter": {
                "title": t(
                    (
                        "Wärmewacht: day counter instead of total",
                        "Wärmewacht: Tageszähler statt Gesamtzähler",
                    )
                ),
                "description": t(
                    (
                        "These energy meters of {name} fell back at the same time of day on several days, like a day counter (energy today): {entities}. Wärmewacht counts them as lifetime counters and misses energy, on days below 1 kWh all of it. Choose the matching total counter under Reconfigure. If it is a total counter after all, ignore this notice.",
                        "Diese Energiezähler von {name} sind an mehreren Tagen zur selben Uhrzeit zurückgefallen, wie ein Tageszähler (Energie heute): {entities}. Wärmewacht zählt sie als Lebenszeit-Zähler und verpasst Energie, an Tagen unter 1 kWh die ganze. Unter Neu konfigurieren den passenden Gesamtzähler wählen. Ist es doch ein Gesamtzähler, den Hinweis ignorieren.",
                    )
                ),
            },
            "energy_stale": {
                "title": t(
                    (
                        "Wärmewacht: no new energy values",
                        "Wärmewacht: keine neuen Energiewerte",
                    )
                ),
                "description": t(
                    (
                        "For more than 30 hours the source of {name} has written no new hourly energy values ({entities}). With myVAILLANT (mypyllant) the energy is fetched only once at load unless the option 'Seconds between energy data updates' is set: set it to 3600 to 7200 seconds, or update one of its energy sensors with an automation. Wärmewacht catches up on the missing hours as soon as they arrive.",
                        "Seit mehr als 30 Stunden hat die Quelle von {name} keine neuen Stundenwerte der Energie geschrieben ({entities}). Bei myVAILLANT (mypyllant) wird die Energie nur einmal beim Laden abgerufen, wenn die Option „Seconds between energy data updates“ nicht gesetzt ist: Stelle sie auf 3600 bis 7200 Sekunden oder aktualisiere einen ihrer Energie-Sensoren per Automation. Wärmewacht holt die fehlenden Stunden nach, sobald sie da sind.",
                    )
                ),
            },
            "source_changed": {
                "title": t(
                    (
                        "Wärmewacht: energy entities changed meaning",
                        "Wärmewacht: Energie-Entitäten haben ihre Bedeutung geändert",
                    )
                ),
                "description": t(
                    (
                        "At least one energy entity of {name} no longer measures what it was chosen for ({entities}); with myVAILLANT this happens when the cloud reorders its energy series, for example after cooling was enabled. Wärmewacht books nothing until the entities are chosen again under Devices & services → Wärmewacht → Reconfigure.",
                        "Mindestens eine Energie-Entität von {name} misst nicht mehr, wofür sie gewählt wurde ({entities}). Bei myVAILLANT geschieht das, wenn die Cloud ihre Energiereihen neu ordnet, etwa nach dem Freischalten von Kühlen. Wärmewacht bucht nichts, bis die Entitäten unter Geräte & Dienste → Wärmewacht → Neu konfigurieren erneut gewählt sind.",
                    )
                ),
            },
            "activity_foreign": {
                "title": t(
                    (
                        "Wärmewacht: activity entity without an activity",
                        "Wärmewacht: Betriebsart-Entität ohne Betriebsart",
                    )
                ),
                "description": t(
                    (
                        "{entities} of {name} reports values that carry no activity on this device (for ViCare E3 controllers 'ready' / 'not_ready'). Defrosts and the mode of runs stay empty. Remove the entity under Devices & services → Wärmewacht → Reconfigure.",
                        "{entities} von {name} meldet Werte, die bei diesem Gerät keine Betriebsart tragen (bei ViCare-E3-Reglern „ready“ / „not_ready“). Abtauungen und die Betriebsart der Läufe bleiben leer. Entferne die Entität unter Geräte & Dienste → Wärmewacht → Neu konfigurieren.",
                    )
                ),
            },
            "flow_return_swapped": {
                "title": t(
                    (
                        "Wärmewacht: flow and return swapped?",
                        "Wärmewacht: Vor- und Rücklauf vertauscht?",
                    )
                ),
                "description": t(
                    (
                        "While heating yesterday, the flow of {name} was {spread} K colder than the return on average: {entities}. A heat pump warms the water, so the flow must be warmer. Usually the two entities are swapped in Wärmewacht (Devices & services → Wärmewacht → Reconfigure) or the sensors at the heat pump. A flow sensor behind a mixing valve can also cause this. Spread and flow temperature are wrong until then. The notice disappears after a day with a normal spread.",
                        "Beim Heizen war gestern der Vorlauf von {name} im Mittel {spread} K kälter als der Rücklauf: {entities}. Eine Wärmepumpe erwärmt das Wasser, der Vorlauf muss also wärmer sein. Meist sind die beiden Entitäten in Wärmewacht vertauscht (Geräte & Dienste → Wärmewacht → Neu konfigurieren) oder die Fühler an der Wärmepumpe. Auch ein Vorlauffühler hinter einem Mischer kann das bewirken. Spreizung und Vorlauftemperatur stimmen bis dahin nicht. Der Hinweis verschwindet nach einem Tag mit normaler Spreizung.",
                    )
                ),
            },
            "counter_stuck": {
                "title": t(
                    ("Wärmewacht: meter stands still", "Wärmewacht: Zähler steht still")
                ),
                "description": t(
                    (
                        "At {name} the compressor ran for {hours} hours, but these meters did not rise: {entities}. Wärmewacht books nothing meanwhile. Check whether the source (e.g. EMS-ESP) still sends values and whether the entity is enabled. If it is the wrong meter, choose another under Devices & services → Wärmewacht → Reconfigure. The notice disappears as soon as the meter rises again.",
                        "Bei {name} lief der Kompressor {hours} Stunden, aber diese Zähler sind nicht gestiegen: {entities}. Wärmewacht kann in dieser Zeit nichts buchen. Prüfe, ob die Quelle (etwa EMS-ESP) noch Werte schickt und ob die Entität aktiviert ist. Ist es der falsche Zähler, wähle unter Geräte & Dienste → Wärmewacht → Neu konfigurieren einen anderen. Der Hinweis verschwindet, sobald der Zähler wieder steigt.",
                    )
                ),
            },
            "source_unavailable": {
                "title": t(
                    (
                        "Wärmewacht: source unreachable",
                        "Wärmewacht: Quelle nicht erreichbar",
                    )
                ),
                "description": t(
                    (
                        "These entities of {name} have been unavailable for more than {minutes} minutes: {entities}. Meanwhile Wärmewacht lacks values. Check the source (e.g. EMS-ESP, MQTT or Bosch HomeCom). The notice disappears as soon as values arrive again.",
                        "Diese Entitäten von {name} sind seit mehr als {minutes} Minuten nicht verfügbar: {entities}. Solange fehlen Wärmewacht Werte. Prüfe die Quelle (etwa EMS-ESP, MQTT oder Bosch HomeCom). Der Hinweis verschwindet, sobald wieder Werte kommen.",
                    )
                ),
            },
            "outdoor_temp_stuck": {
                "title": t(
                    (
                        "Wärmewacht: outdoor temperature unusable",
                        "Wärmewacht: Außentemperatur unbrauchbar",
                    )
                ),
                "description": t(
                    (
                        "The outdoor temperature of {name} ({entities}) has not changed for {hours} hours. Performance curve, heat load and the checks 'Efficiency dropped' and 'Backup heater on mild days' depend on it. Check the sensor or choose another entity under Reconfigure.",
                        "Die Außentemperatur von {name} ({entities}) hat sich seit {hours} Stunden nicht verändert. Kennlinie, Heizlast und die Prüfungen „Effizienz gesunken“ und „Heizstab bei milder Witterung“ hängen an ihr. Prüfe den Fühler oder wähle unter Neu konfigurieren eine andere Entität.",
                    )
                ),
            },
            "outdoor_temp_implausible": {
                "title": t(
                    (
                        "Wärmewacht: outdoor temperature unusable",
                        "Wärmewacht: Außentemperatur unbrauchbar",
                    )
                ),
                "description": t(
                    (
                        "The outdoor temperature of {name} ({entities}) was outside -35 to +45 °C for {hours} hours yesterday. Performance curve, heat load and the checks 'Efficiency dropped' and 'Backup heater on mild days' depend on it. Check the sensor or choose another entity under Reconfigure.",
                        "Die Außentemperatur von {name} ({entities}) lag gestern {hours} Stunden außerhalb von −35 bis +45 °C. Kennlinie, Heizlast und die Prüfungen „Effizienz gesunken“ und „Heizstab bei milder Witterung“ hängen an ihr. Prüfe den Fühler oder wähle unter Neu konfigurieren eine andere Entität.",
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
            },
            "performance_curve": {
                "name": t(("Performance curve", "AZ-Kennlinie")),
                "description": t(
                    (
                        "Ratio per 2-K class of the daily mean outdoor temperature, without standby (at least 7 days per class).",
                        "Arbeitszahl je 2-K-Klasse der Tagesmitteltemperatur, ohne Stillstand (mindestens 7 Tage je Klasse).",
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
                                "Without: start of the current season. Do not mix seasons with different heating curves.",
                                "Ohne: Beginn der laufenden Saison. Saisons mit verschiedener Heizkurve nicht mischen.",
                            )
                        ),
                    },
                    "end": {
                        "name": t(("End", "Ende")),
                        "description": t(("Without: now.", "Ohne: jetzt.")),
                    },
                    "scope": {
                        "name": t(("Scope", "Umfang")),
                        "description": t(
                            (
                                "Heating, or heating and hot water.",
                                "Heizen oder Heizen und Warmwasser.",
                            )
                        ),
                    },
                },
            },
            "heat_load": {
                "name": t(("Heat load", "Heizlast")),
                "description": t(
                    (
                        "Energy signature: weekly heating power over the weekly mean outdoor temperature (weeks below 12 °C).",
                        "Energiesignatur: Wochenmittel der Heizleistung über dem Wochenmittel der Außentemperatur (Wochen unter 12 °C).",
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
                                "Without: the last complete season.",
                                "Ohne: die letzte vollständige Saison.",
                            )
                        ),
                    },
                    "end": {
                        "name": t(("End", "Ende")),
                        "description": t(
                            (
                                "Without: end of the last complete season, or now with a start.",
                                "Ohne: Ende der letzten vollständigen Saison, mit Beginn: jetzt.",
                            )
                        ),
                    },
                    "design_outdoor_temp": {
                        "name": t(
                            ("Design outdoor temperature", "Normaußentemperatur")
                        ),
                        "description": t(
                            (
                                "Without: the one from the settings.",
                                "Ohne: die aus den Einstellungen.",
                            )
                        ),
                    },
                },
            },
        },
    }


DISABLED_HINT = (
    "Disabled entities a template would use: {disabled}. Enable them in the entity settings, wait until they report a value, then start this setup again.",
    "Deaktivierte Entitäten, die eine Vorlage nutzen würde: {disabled}. In den Entitäts-Einstellungen aktivieren, warten, bis sie einen Wert melden, dann diese Einrichtung neu starten.",
)


# Gas boiler entry (config_flow.async_step_gas, options, actions).
GAS_STEP = {
    "title": ("Set up a gas boiler", "Gasheizung einrichten"),
    "description": (
        "Before switching to a heat pump: heat load, heating limit and hot water share from the gas consumption of the last 365 days. Wärmewacht reads the long-term statistics of the counters, so a counter with a long history gives results at once. Choose either a total counter (heating and hot water) or a heating counter.",
        "Vor dem Umstieg auf eine Wärmepumpe: Heizlast, Heizgrenze und Warmwasseranteil aus dem Gasverbrauch der letzten 365 Tage. Wärmewacht liest die Langzeitstatistik der Zähler; ein Zähler mit langer Statistik liefert sofort Ergebnisse. Wähle entweder einen Gesamtzähler (Heizen und Warmwasser) oder einen Zähler nur fürs Heizen.",
    ),
}
GAS_FIELDS = {
    "gas_total": (
        "Gas total (heating and hot water)",
        "Gas gesamt (Heizen und Warmwasser)",
    ),
    "gas_heating": ("Gas heating only", "Gas nur Heizen"),
    "gas_dhw": ("Gas hot water", "Gas Warmwasser"),
    "outdoor_temp": ("Outdoor temperature", "Außentemperatur"),
    "calorific_value": ("Calorific value", "Brennwert"),
    "z_number": ("Z-number", "Zustandszahl"),
}
GAS_FIELD_HELP = {
    "gas_total": (
        "A gas meter (pulse, AI-on-the-edge) or the boiler's counter, in kWh or m³, with statistics. Hot water is estimated from summer days unless you choose a hot water counter.",
        "Ein Gaszähler (Impuls, AI-on-the-edge) oder der Zähler der Therme, in kWh oder m³, mit Langzeitstatistik. Warmwasser schätzt Wärmewacht aus Sommertagen, wenn du keinen Warmwasser-Zähler wählst.",
    ),
    "gas_heating": (
        'Only if the boiler counts heating and hot water apart (e.g. Viessmann ViCare); then add the hot water counter as well. Leave "Gas total" empty.',
        "Nur wenn die Therme Heizen und Warmwasser getrennt zählt (z. B. Viessmann ViCare); dann auch den Warmwasser-Zähler eintragen. „Gas gesamt“ bleibt leer.",
    ),
    "gas_dhw": (
        "Optional: gas for hot water, if counted apart.",
        "Optional: Gas für Warmwasser, wenn getrennt gezählt.",
    ),
    "outdoor_temp": (
        "With long-term statistics (state class measurement). A nearby weather station is fine.",
        "Mit Langzeitstatistik (Zustandsklasse measurement). Eine nahe Wetterstation ist in Ordnung.",
    ),
    "calorific_value": (
        "Only for counters in m³: from the gas bill (kWh per m³, gross calorific value Hs).",
        "Nur für Zähler in m³: aus der Gasrechnung (kWh je m³, Brennwert Hs).",
    ),
    "z_number": (
        "Only for counters in m³: from the gas bill (Zustandszahl).",
        "Nur für Zähler in m³: aus der Gasrechnung.",
    ),
}
GAS_ERRORS = {
    "gas_none": (
        "Choose a gas counter: total, or heating.",
        "Wähle einen Gaszähler: gesamt oder nur Heizen.",
    ),
    "gas_twice": (
        'Either "Gas total" or "Gas heating only", not both.',
        "Entweder „Gas gesamt“ oder „Gas nur Heizen“, nicht beides.",
    ),
    "gas_unit": (
        "A gas counter has no unit Wh, kWh, MWh or m³.",
        "Ein Gaszähler hat keine Einheit Wh, kWh, MWh oder m³.",
    ),
    "gas_no_statistics": (
        "A gas counter has no long-term statistics (state class total or total_increasing).",
        "Ein Gaszähler hat keine Langzeitstatistik (Zustandsklasse total oder total_increasing).",
    ),
    "gas_calorific_value": (
        "Counters in m³ need the calorific value and the Z-number from the gas bill.",
        "Zähler in m³ brauchen Brennwert und Zustandszahl aus der Gasrechnung.",
    ),
}
GAS_OPTIONS = {
    "boiler_efficiency": (
        ("Boiler efficiency (Hs)", "Nutzungsgrad des Kessels (Hs)"),
        (
            "Share of the gas that becomes heat, on the gross calorific value. 0.87 is the field value of condensing boilers (Jagnow/Wolff); older boilers are lower. The heat load changes in proportion.",
            "Anteil des Gases, der zu Wärme wird, bezogen auf den Brennwert. 0,87 ist der Feldwert von Brennwertkesseln (Jagnow/Wolff); ältere Kessel liegen darunter. Die Heizlast ändert sich im selben Verhältnis.",
        ),
    ),
    "design_outdoor_temp": (
        ("Design outdoor temperature", "Normaußentemperatur"),
        (
            "From DIN/TS 12831-1 for your postcode (e.g. the BWP climate map). Without it the heat load is given per kelvin only.",
            "Aus DIN/TS 12831-1 für deine Postleitzahl (z. B. BWP-Klimakarte). Ohne sie nur die Heizlast je Kelvin.",
        ),
    ),
    "gas_price": (
        ("Gas working price", "Gas-Arbeitspreis"),
        (
            "Gross, per kWh on the gross calorific value (as on the gas bill).",
            "Brutto, je kWh auf den Brennwert (wie auf der Gasrechnung).",
        ),
    ),
    "gas_base_price": (
        ("Gas base price", "Gas-Grundpreis"),
        ("Gross per year.", "Brutto je Jahr."),
    ),
    "calorific_value": (
        ("Calorific value", "Brennwert"),
        (
            "Only for counters in m³: from the gas bill.",
            "Nur für Zähler in m³: aus der Gasrechnung.",
        ),
    ),
    "z_number": (
        ("Z-number", "Zustandszahl"),
        (
            "Only for counters in m³: from the gas bill.",
            "Nur für Zähler in m³: aus der Gasrechnung.",
        ),
    ),
}
GAS_SOURCE = ("Gas boiler (before switching)", "Gasheizung (vor dem Umstieg)")
NOT_FOR_GAS = (
    "This action is for heat pumps; a gas boiler has the heat load only.",
    "Diese Aktion gilt für Wärmepumpen; eine Gasheizung hat nur die Heizlast.",
)
HEAT_LOAD_START = (
    "Without: the last complete season (gas boiler: the last 365 days).",
    "Ohne: die letzte vollständige Saison (Gasheizung: die letzten 365 Tage).",
)


def _add_gas(data: dict, lang: int) -> None:
    """The gas boiler entry's texts (added after the heat pump's)."""
    data["config"]["step"]["gas"] = {
        "title": GAS_STEP["title"][lang],
        "description": GAS_STEP["description"][lang],
        "data": {k: v[lang] for k, v in GAS_FIELDS.items()},
        "data_description": {k: v[lang] for k, v in GAS_FIELD_HELP.items()},
    }
    data["config"]["error"].update({k: v[lang] for k, v in GAS_ERRORS.items()})
    data["options"]["step"]["gas"] = {
        "title": ("Settings", "Einstellungen")[lang],
        "data": {k: v[0][lang] for k, v in GAS_OPTIONS.items()},
        "data_description": {k: v[1][lang] for k, v in GAS_OPTIONS.items()},
    }
    data["selector"]["source"]["options"]["gas"] = GAS_SOURCE[lang]
    data["exceptions"]["not_for_gas"] = {"message": NOT_FOR_GAS[lang]}
    fields = data["services"]["heat_load"]["fields"]
    fields["start"]["description"] = HEAT_LOAD_START[lang]


def build(lang: int) -> dict:
    data = _build(lang)
    steps = data["config"]["step"]
    # The first step again, with the hint on disabled entities (config_flow).
    user = steps["user"]
    steps["user_disabled"] = {
        **user,
        "description": user["description"] + "\n\n" + DISABLED_HINT[lang],
    }
    _add_gas(data, lang)
    return data


def icons() -> dict:
    sensor = {}
    for scope, (_, _, icon) in SCOPES.items():
        for period in PERIODS:
            sensor[f"ratio_{scope}_{period}"] = {"default": icon}
    sensor.update({k: {"default": v[2]} for k, v in SENSORS.items()})
    return {
        "entity": {
            "binary_sensor": {k: {"default": v[2]} for k, v in BINARY.items()},
            "button": {k: {"default": v[2]} for k, v in BUTTONS.items()},
            "sensor": sensor,
        },
        "services": {
            "report": {"service": "mdi:file-chart-outline"},
            "performance_curve": {"service": "mdi:chart-bell-curve-cumulative"},
            "heat_load": {"service": "mdi:home-thermometer"},
        },
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
