"""Summary at the top of the settings form: what the entry reads and what is
missing with its consequence."""

from __future__ import annotations

from custom_components.waermewacht.summary import boiler_summary, heat_pump_summary

EMS_ESP = {
    "heat_heating": "sensor.boiler_nrgheat",
    "elec_heating": "sensor.boiler_meterheat",
    "heat_dhw": "sensor.boiler_dhw_nrg",
    "elec_dhw": "sensor.boiler_dhw_meter",
    "heat_cooling": "sensor.boiler_nrgcool",
    "elec_cooling": "sensor.boiler_metercool",
    "aux_heating": "sensor.boiler_metereheatheat",
    "compressor": "binary_sensor.boiler_hpcompon",
    "activity": "sensor.boiler_hpactivity",
    "starts_total": "sensor.boiler_totalcompstarts",
    "outdoor_temp": "sensor.boiler_outdoortemp",
    "flow_temp": "sensor.boiler_hptc1",
    "return_temp": "sensor.boiler_hptc0",
}


def test_template_entry_with_everything() -> None:
    text = heat_pump_summary(
        EMS_ESP,
        {
            "electricity_price": 27.75,
            "design_outdoor_temp": -12.0,
            "starts_per_hour": 4,
            "short_run_minutes": 12,
        },
        "EMS-ESP",
        "de",
    )
    assert text == (
        "**Eingerichtet**\n"
        "- **Quelle:** Vorlage EMS-ESP\n"
        "- **Zähler:** Heizen: Wärme, Strom · Warmwasser: Wärme, Strom"
        " · Kühlen: Wärme, Strom · Heizstab je Betriebsart\n"
        "- **Betrieb:** Kompressor ✓, Betriebsart ✓, Startzähler ✓\n"
        "- **Messwerte:** außen ✓, Vorlauf ✓, Rücklauf ✓\n"
        "- **Strompreis:** fest 27,75 ct/kWh\n"
        "- **PV-Aufteilung:** aus\n"
        "- **Grenzen:** 4 Starts/h, Kurzlauf 12 min, kritisch 6 min"
    )


def test_own_mapping_without_feed_in_meter() -> None:
    """Own mapping, one meter for all, grid import without feed-in and PV:
    the hints say what that costs."""
    text = heat_pump_summary(
        {
            "heat_total": "sensor.wmz",
            "elec_heating": "sensor.elec_heating",
            "elec_dhw": "sensor.elec_dhw",
            "compressor": "binary_sensor.compressor",
            "activity": "sensor.status",
            "outdoor_temp": "sensor.outdoor",
        },
        {
            "electricity_price_entity": "sensor.tibber",
            "electricity_price": 30,
            "grid_import_entity": "sensor.grid",
            "battery_charged_entity": "sensor.charged",
            "starts_per_day": 30,
        },
        None,
        "de",
    )
    lines = text.split("\n")[1:]
    assert lines[0] == "- **Quelle:** eigene Zuordnung"
    assert lines[1] == (
        "- **Zähler:** Heizen: Wärme gesamt, Strom · Warmwasser: Wärme gesamt, Strom"
    )
    assert "- **Strompreis:** Sensor (sonst 30 ct/kWh)" in lines
    assert "- **PV-Aufteilung:** Wärmepumpe zuerst, mit Batterie" in lines
    assert "30 Starts/Tag" in text
    assert text.endswith(
        "**Was fehlt**\n"
        "- Keine Normaußentemperatur: Heizlast nur je Kelvin.\n"
        "- Kein Einspeise- und PV-Zähler: die PV-Aufteilung rechnet nur"
        " „Wärmepumpe zuerst aus dem Netz“."
    )


def test_missing_meters_and_activity_in_english() -> None:
    text = heat_pump_summary(
        {"heat_heating": "sensor.heat", "elec_heating": "sensor.e", "elec_dhw": "x"},
        {},
        None,
        "en-GB",
    )
    assert (
        "- **Meters:** Heating: heat, electricity · Hot water: no heat, electricity"
        in text
    )
    hints = text.split("**Missing**\n")[1].split("\n")
    assert hints == [
        "- No hot water heat meter: no hot water performance factor.",
        "- No compressor state: no runs and starts, standby only from the heat.",
        "- No activity: no defrosts, no spread, no mean flow temperature.",
        "- No outdoor temperature: no performance curve, heat load or degree days.",
        "- No electricity price: no costs and no gas comparison.",
    ]


def test_heat_total_without_activity() -> None:
    text = heat_pump_summary(
        {"heat_total": "a", "elec_total": "b", "compressor": "c"}, {}, None, "de"
    )
    assert "- **Zähler:** Heizen: Wärme gesamt, Strom gesamt" in text
    assert (
        "- Erzeugte Wärme gesamt ohne Betriebsart: alle Wärme zählt zum Heizen." in text
    )


def test_gas_entry() -> None:
    text = boiler_summary(
        {},
        {"gas_total": "sensor.gas", "outdoor_temp": "sensor.out", "flow_temp": "f"},
        {"gas_price": 11.5},
        oil=False,
        language="de",
    )
    assert text == (
        "**Eingerichtet**\n"
        "- **Art:** Gasheizung\n"
        "- **Zähler:** gesamt (Heizen und Warmwasser)\n"
        "- **Messwerte:** außen ✓, Vorlauf ✓\n"
        "- **Gaspreis:** 11,5 ct/kWh · Nutzungsgrad 0,87 · Normaußentemperatur –\n"
        "\n"
        "**Was fehlt**\n"
        "- Gesamtzähler ohne Warmwasserzähler und ohne Haken"
        " „Vorlauffühler sitzt im Heizkreis“: kein Vorlauf bei 0 °C.\n"
        "- Keine Normaußentemperatur: Heizlast nur je Kelvin."
    )
    # With the flow sensor in the heating circuit nothing is missing there.
    circuit = boiler_summary(
        {"flow_in_circuit": True},
        {"gas_total": "sensor.gas", "outdoor_temp": "sensor.out", "flow_temp": "f"},
        {"gas_price": 11.5, "design_outdoor_temp": -12.0},
        oil=False,
        language="de",
    )
    assert "Vorlauf ✓ (im Heizkreis)" in circuit
    assert "Was fehlt" not in circuit


def test_oil_tank_by_hand() -> None:
    text = boiler_summary(
        {"fuel": "oil", "manual_unit": "tank"},
        {"outdoor_temp": "sensor.out"},
        {"boiler_type": "condensing", "oil_price": 98.5, "design_outdoor_temp": -10},
        oil=True,
        language="en",
    )
    assert "- **Kind:** Oil boiler" in text
    assert "- **Meters:** tank level" in text
    assert "- **Oil price:** 98.5 €/100 l" in text
    assert "design temperature -10 °C" in text
    assert "Missing" not in text


def test_whole_kwh_heat_meter_without_compressor() -> None:
    """Without a compressor a heat meter in whole kWh costs running
    electricity (standby until its first step); with one nothing is said."""
    meters = {"heat_total": "sensor.wmz", "elec_total": "sensor.elec"}
    hint = (
        "- Ohne Kompressor zählt bei einem Wärmezähler in ganzen kWh ein Teil des"
        " Laufstroms als Stillstand – Kompressor eintragen, wenn vorhanden."
    )
    text = heat_pump_summary(meters, {}, None, "de", coarse_heat=True)
    hints = text.split("**Was fehlt**\n")[1].split("\n")
    assert (
        hints[
            hints.index(
                "- Kein Kompressor-Zustand: keine Läufe und Starts, Stillstand nur über die Wärme."
            )
            + 1
        ]
        == hint
    )
    assert hint not in heat_pump_summary(meters, {}, None, "de")
    with_compressor = {**meters, "compressor": "binary_sensor.c"}
    assert "ganzen kWh" not in heat_pump_summary(
        with_compressor, {}, None, "de", coarse_heat=True
    )
    english = heat_pump_summary(meters, {}, None, "en", coarse_heat=True)
    assert (
        "- Without a compressor, part of the running electricity counts as standby"
        " with a heat meter in whole kWh – map the compressor if there is one."
        in english
    )


def test_temperatures_without_statistics() -> None:
    """Modbus sensors without a state class (forum, PN 09.11.): no
    performance curve and heat load, no flow temperature at 0 °C."""
    from custom_components.waermewacht.model import Signal

    text = heat_pump_summary(
        EMS_ESP,
        {"electricity_price": 30.0, "design_outdoor_temp": -12.0},
        None,
        "de",
        no_statistics={Signal.OUTDOOR_TEMP, Signal.FLOW_TEMP},
    )
    assert "- Außentemperatur ohne Langzeitstatistik (keine state_class)" in text
    assert "- Vor- oder Rücklauf ohne Langzeitstatistik (keine state_class)" in text
    complete = heat_pump_summary(
        EMS_ESP, {"electricity_price": 30.0, "design_outdoor_temp": -12.0}, None, "de"
    )
    assert "Langzeitstatistik" not in complete
