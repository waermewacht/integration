<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/waermewacht/integration/main/assets/github/readme-header-dark@2x.png">
  <img alt="Wärmewacht – Jede Kilowattstunde. Jeder Takt." src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/github/readme-header-light@2x.png" width="640">
</picture>

[![Release](https://img.shields.io/github/v/release/waermewacht/integration?color=DE5E32)](https://github.com/waermewacht/integration/releases)
[![CI](https://github.com/waermewacht/integration/actions/workflows/ci.yml/badge.svg)](https://github.com/waermewacht/integration/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-F5A623.svg)](LICENSE)

**Deutsch** · [English](https://github.com/waermewacht/integration/blob/main/README.en.md)

> **Neu.** Die Vorlagen für EMS-ESP und Bosch HomeCom laufen an einer echten Anlage, alle anderen sind Beta (siehe [Voraussetzungen](#voraussetzungen)). Rückmeldungen sind willkommen, siehe [Fehler melden](#fehler-melden).

**Wie effizient arbeitet deine Wärmepumpe wirklich?** Wärmewacht berechnet in Home Assistant Arbeitszahlen je Betriebsart und Zeitraum, zählt Starts, Kurzläufe und Abtauungen und zeigt einige Diagnosewerte. Grundlage sind die Entitäten, die deine Wärmepumpe schon liefert. Wärmewacht liest nur und steuert nie. Keine Cloud, keine Netzabfragen.

> **Orientierung, keine Fachdiagnose.** Die Werte hängen davon ab, was die Zähler deiner Wärmepumpe messen. Siehe [Bilanzgrenze und Grenzen der Aussage](#bilanzgrenze-und-grenzen-der-aussage).

Die Oberfläche gibt es auf Deutsch und Englisch; sie folgt der Sprache deines Home Assistant.

<img src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/screenshots/arbeitszahlen.png" alt="Dashboard mit Arbeitszahlen je Betriebsart für heute, Monat und Saison, Kosten und Takten" width="720">

<sub>Echte Werte einer Bosch Compress 5800i AW (EMS-ESP) im Oktober. „Heizen+WW“ ist die Arbeitszahl mit Stillstand-Strom und liegt deshalb unter beiden Einzelwerten.</sub>

## Was Wärmewacht kann

- **Arbeitszahlen** für Heizen, Warmwasser und Heizen + Warmwasser, dazu die **Leistungszahl Kühlen (EER)**, jeweils für heute, gestern, Monat, Saison und gesamt.
- **Wärme- und Strom-Sensoren je Betriebsart** und ein Sensor für den **Stillstand**, mit Langzeitstatistik für Statistik-Karten.
- **Takte:** Starts, Laufzeit, Laufzeit pro Start, Kurzläufe, kürzeste Pause, Abtauungen und ein Binärsensor **Auffälliges Takten**.
- **Diagnose:** Heizstab-Anteil, Spreizung und mittlere Vorlauftemperatur im Heizbetrieb (mit Betriebsart).
- **Warmwasser je Ladung:** Arbeitszahl der letzten Ladung und der Ladungen der letzten 30 Tage, letzte thermische Desinfektion.
- **Gesundheits-Check:** meldet gesunkene Effizienz bei gleichem Wetter, eine gesunkene Warmwasser-Effizienz gegenüber dem Vorjahr und den Heizstab bei milder Witterung oder bei Warmwasserladungen. Reparaturhinweise, wenn ein Zähler stillsteht, eine Quelle ausfällt, die Außentemperatur hängt oder Durchfluss, Vor- und Rücklauf nicht stimmen.
- **Kosten und Gasvergleich** (optional, mit festen Preisen): Stromkosten, Wärmekosten je kWh und die Ersparnis gegenüber einem Gaskessel.
- **AZ-Kennlinie und Heizlast:** Arbeitszahl Heizen über der Außentemperatur und Heizlast aus der Energiesignatur. Als Sensoren und per Aktion für beliebige Zeiträume. Dazu Kennwerte wie Gradtage, Vorlauf bei 0 °C (die Heizkurve), Spreizung an kalten Tagen und Leistung je Heizlast.
- **Gasheizung vor dem Umstieg:** Heizlast, Heizgrenze und Warmwasseranteil aus dem Gasverbrauch der letzten 365 Tage, als eigener Eintrag ([mehr](#gasheizung-vor-dem-umstieg)).
- **Bericht für einen beliebigen Zeitraum** per Aktion, je Monat aufgeschlüsselt. Auch **vor der Einrichtung**, so weit die Langzeitstatistik deiner Zähler zurückreicht.
- **Vorlagen für EMS-ESP und Bosch HomeCom:** finden Bosch/Buderus-Wärmepumpen selbst und füllen die Entitäten aus. Als Beta dazu Luxtronik (alpha innotec, Novelan), Stiebel Eltron/Tecalor (ISG), Panasonic Aquarea (HeishaMon), Lambda, iDM, Viessmann (ViCare), Mitsubishi Ecodan (MELCloud, F1p-Brücke oder ESPHome), Vaillant (myVAILLANT), Waterkotte, Buderus über das Gateway MX300/MX400 (Integration `buderus`) und Daikin Altherma (P1P2MQTT). Andere Wärmepumpen ordnest du von Hand zu.
- **Schont SD-Karten:** schreibt nur, wenn sich etwas geändert hat, und dann höchstens alle 10 Minuten. Dazu am Ende eines Laufs, um Mitternacht und beim Beenden. Die Sensoren aktualisieren sich einmal pro Minute und bei Ereignissen.

## Was Wärmewacht anders macht als Template-Sensoren

- **Arbeitszahl eines Zeitraums = Σ Wärme / Σ Strom**, nie der Mittelwert von Tageswerten.
- **Unbekannt statt 0:** Ohne Wärme oder unter dem Mindeststrom (Vorgabe 0,5 kWh) ist eine Arbeitszahl unbekannt. Nullen würden Mittelwerte und Statistiken nach unten ziehen.
- **Stillstand getrennt:** Strom bei stehendem Kompressor zählt nicht in die Arbeitszahl je Betriebsart, wohl aber in die Arbeitszahl Heizen + Warmwasser. So rechnet auch das Fraunhofer ISE in seinen Feldtests.
- **Kühlen nie in der Jahresarbeitszahl.** Es hat eine eigene Leistungszahl (EER).
- **Takte aus echten Läufen** des Kompressors: Ein Neustart von Home Assistant mitten im Lauf ist kein neuer Start. Wechselt die Wärmepumpe ohne Stopp von Heizen auf Warmwasser, bleibt es ein Lauf. Ein Lauf, der beim ersten Blick schon lief, zählt nicht als Start.
- **Zähler-Resets und Rücksprünge:** Rücksprünge halten den Höchststand, gebucht wird nur Wärme darüber (netto). Das betrifft Rauschen und das Abtauen, bei dem die Wärmepumpe die entzogene Wärme abzieht. Erst ein Rückgang um mehr als 10 % und mehr als 1 kWh gilt als Reset mit neuer Basis, unplausible Sprünge werden nicht gebucht. `unknown` und `unavailable` gelten nie als 0.
- **Rückblick aus der Langzeitstatistik:** Heute, gestern, Monat, Saison und gesamt enthalten schon bei der Einrichtung die Werte der Zeit davor.

## Voraussetzungen

Für eine Gasheizung vor dem Umstieg genügen Gaszähler und Außentemperatur, siehe [Gasheizung vor dem Umstieg](#gasheizung-vor-dem-umstieg). Für eine Wärmepumpe:

- Home Assistant 2026.4 oder neuer.
- Der Recorder (in Home Assistant standardmäßig an) für Rückblick, Bericht, AZ-Kennlinie und Heizlast. Welche Entitäten er aufzeichnen muss: [Recorder schlank halten](#recorder-schlank-halten).
- Mindestens eine Betriebsart mit einem **Wärmezähler** und einem **Stromzähler des Kompressors**: fortlaufende Energiesensoren in Wh, kWh oder MWh. Ohne Wärmezähler genügt der Kompressorstatus; dann gibt es Takte und Strom, aber keine Arbeitszahlen.

| Quelle | Status |
| --- | --- |
| [EMS-ESP](https://github.com/emsesp/EMS-ESP32) (MQTT) mit Bosch/Buderus-Wärmepumpen, z. B. CS5800i/CS6800i, WLW176i/WLW186i | Vorlage, erprobt an einer CS5800i/CS6800i |
| [Bosch HomeCom](https://github.com/serbanb11/bosch-homecom-hass) (`bosch_homecom`, lokal und Cloud) | Vorlage, neu, an derselben CS5800i/CS6800i mit EMS-ESP verglichen |
| [Luxtronik](https://github.com/BenPru/luxtronik) (`luxtronik2`; alpha innotec, Novelan) | Beta, aus dem Quellcode; Strom je Betriebsart erst mit neuerer Firmware |
| [Stiebel Eltron / Tecalor ISG](https://github.com/pail23/stiebel_eltron_isg_component) (`stiebel_eltron_isg`) | Beta, aus dem Quellcode; Zähler in ganzen kWh; kein Strom fürs Kühlen, also keine EER |
| [Panasonic Aquarea über HeishaMon](https://github.com/kamaradclimber/heishamon-homeassistant) (`aquarea`) | Beta, aus dem Quellcode; Energie aus den Leistungen aufsummiert, kein Heizstab |
| [Lambda](https://github.com/GuidoJeuken-6512/lambda_heat_pumps) (`lambda_heat_pumps`) | Beta, aus dem Quellcode; eigene Zähler für Abtauen und Stillstand |
| [iDM Navigator 2.0](https://github.com/Xerolux/idm-heatpump-hass) (`idm_heatpump`, mit Weboberfläche) | Beta, aus dem Quellcode |
| [Viessmann ViCare](https://www.home-assistant.io/integrations/vicare/) (Core `vicare`) | Beta, aus dem Quellcode; **nur Takte und Strom, keine Arbeitszahl** |
| [Mitsubishi Ecodan über MELCloud](https://www.home-assistant.io/integrations/melcloud/) (Core `melcloud`, ab HA 2026.5) | Beta, aus dem Quellcode; Arbeitszahlen ohne Takte |
| [Vaillant myVAILLANT](https://github.com/signalkraft/mypyllant-component) (`mypyllant`) | Beta, aus dem Quellcode; Arbeitszahlen ohne Takte |
| [Mitsubishi Ecodan über F1p-Brücke](https://github.com/F1p/Home-Assistant-Mitsubishi-CN105-to-MQTT) (MQTT, CN105) | Beta, aus dem Quellcode; Arbeitszahlen, Takte und Abtauen |
| [Mitsubishi Ecodan mit ESPHome](https://github.com/gekkekoe/esphome-ecodan-hp) (`esphome`, esphome-ecodan-hp) | Beta, aus dem Quellcode; Arbeitszahlen, Takte und Abtauen |
| [Waterkotte EcoTouch](https://github.com/marq24/ha-waterkotte) (`waterkotte_heatpump`) | Beta, aus dem Quellcode; Kompressorstrom nur gesamt |
| [Buderus/Bosch über MX300, MX400, K30](https://github.com/BassXT/buderus) (`buderus_ha`) | Beta, aus dem Quellcode; Arbeitszahlen, Takte und Abtauen |
| [Daikin Altherma über P1P2MQTT](https://github.com/Arnold-n/P1P2Serial) (MQTT) | Beta, aus dem Quellcode; Arbeitszahlen, Takte und Abtauen, Zähler in ganzen kWh |
| beliebige Wärme- und Stromzähler | manuelle Zuordnung |

Die EMS-ESP-Vorlage erkennt die Wärmepumpe am Gerät `boiler`. Sie braucht Kompressorstatus (`hpcompon`) und die Zähler für Heizen. Sie findet die Entitäten über die Entitäten-Registry, nicht über die Entity-ID. Umbenennen und alle Namensformate von EMS-ESP sind deshalb kein Problem. Die Betriebsart (`hpactivity`) versteht sie in allen Sprachen von EMS-ESP und im Index-Format.

Die HomeCom-Vorlage braucht die Energie je Betriebsart („Wärme erzeugt Heizung“, „Strom Kompressor Heizung“ usw.). `bosch_homecom` legt diese Entitäten deaktiviert an: Aktiviere sie zuerst. Die Einrichtung zeigt, welche noch deaktiviert sind. „Kompressor läuft“ ist die Kompressordrehzahl über 0. Gegenüber EMS-ESP hat HomeCom Grenzen:

- **Tageswerte aus der Cloud:** Die Energie kommt als Summe des Tages, bis zu zwei Stunden verspätet. Wärmewacht bucht sie, wenn sie eintrifft, „heute“ hinkt also nach. Die letzten ein bis zwei Stunden eines Tages liefert die Cloud nie (beobachtet bis 0,5 kWh am Tag).
- **Stillstand:** Strom eines Abrufs, mit dem keine Wärme derselben Betriebsart kam.
- **Betriebsart erst mit dem Kompressorstatus:** Bis `bosch_homecom` den Sensor „Kompressorstatus“ liefert ([PR #217](https://github.com/serbanb11/bosch-homecom-hass/pull/217)), gibt es keine Abtauungen, keine Spreizung und keinen mittleren Vorlauf. Sobald er da ist, übernimmt Wärmewacht ihn beim nächsten Start von selbst.
- **Kein Durchfluss:** `bosch_homecom` meldet „L/min“, liefert aber l/h.

Läuft bei dir EMS-ESP, nimm EMS-ESP: Zähler auf 0,01 kWh im Minutentakt und die Betriebsart.

**Beta-Vorlagen** sind aus dem Quellcode der jeweiligen Integration abgeleitet, nicht an einer echten Anlage bestätigt. Die Einrichtung zeigt sie mit „(beta)“. Hast du so eine Anlage, hilft eine Rückmeldung mit [Diagnose-Datei](#fehler-melden) sehr. Die wichtigsten Grenzen:

- **Viessmann ViCare:** Home Assistant liefert keine Wärme (die Bibliothek PyViCare liest sie noch nicht aus). Wärmewacht zeigt deshalb Takte, Laufzeiten, Strom je Betriebsart und Kosten, aber keine Arbeitszahl. E3-Regler (Vitocal 150-A bis 252-A) melden keine Betriebsart; ältere Vitotronic-Regler melden Abtauen, aber keine Energie. Die Tageswerte der Cloud zählt Wärmewacht in UTC-Tagen: Beginnt die Cloud doch um Mitternacht Ortszeit, kommt der erste Wert eines Tages nur ein bis zwei Stunden später an.
- **Mitsubishi Ecodan (MELCloud):** Die Wärme je Betriebsart legt `melcloud` deaktiviert an: Aktiviere sie zuerst. Ohne brauchbares Kompressorsignal (nur alle 30 Minuten) gibt es keine Takte und keine Abtauungen. MELCloud meldet die Summen des **Vortags**: Sie springen einmal kurz nach Mitternacht und bleiben dann den Tag über gleich. Wärmewacht bucht sie deshalb in den Vortag, und Monat und Saison stimmen auch am Monatswechsel. „Heute“ bleibt bei dieser Quelle leer, „gestern“ ist der früheste Wert. Bleibt die Aktualisierung der Cloud einmal aus, fehlt der Tag.
- **Mitsubishi Ecodan (F1p-Brücke):** Lokal über den CN105-Anschluss, mit Kompressor und Betriebsart, also mit Takten und Abtauungen. Die Energie kommt wie bei MELCloud als Summe des Vortags. Die Brücke sendet vor dem echten Wert manchmal eine eigene Schätzung; liegt sie höher, zählt Wärmewacht etwas zu viel. Ohne `state_class` der Brücke gibt es keinen Rückblick vor der Einrichtung.
- **Mitsubishi Ecodan (ESPHome):** Die Firmware esphome-ecodan-hp liefert wie die F1p-Brücke Kompressor, Betriebsart, Abtauen und die Energie als Summe des Vortags. Die Vorlage erkennt die Entitäten an den Namen der Firmware; hast du sie im YAML umbenannt, ordne von Hand zu. Die Uhr der FTC muss stimmen, auch nach der Zeitumstellung. Abtauen schließt Standby und Wiederanlauf mit ein und fällt deshalb eher zu lang aus.
- **Buderus/Bosch über MX300/MX400 (`buderus`):** Liest wie Bosch HomeCom die Bosch-Cloud, aber mit Lebenszeit-Zählern je Betriebsart (0,01 kWh, alle 10 Minuten abgerufen) und mit der Betriebsart samt Abtauen. „Kompressor läuft“ ist die Modulation über 0. Kein Durchfluss.
- **Daikin Altherma (P1P2MQTT):** Die Zähler der Wärmepumpe selbst (Wärme und Strom je Betriebsart, Heizstab) in ganzen kWh. Sie kommen nur, wenn in der Brücke die Zählerabfrage („Counter_Request_Function“) eingeschaltet ist. Betriebsart aus den Flags Abtauen, Warmwasser, Kühlen und Heizen. Die Warmwasser-Entitäten gibt es nur mit den passenden Feldeinstellungen am Regler.
- **Waterkotte:** Die Zähler sind Jahressummen, Wärme je Betriebsart, Kompressorstrom aber nur gesamt. Wärmewacht ordnet den Strom der laufenden Betriebsart zu, im Rückblick nach dem Anteil an der Wärme. Ein Lauf ohne Warmwasser- oder Kühl-Merker zählt als Heizen (die Heizfreigabe `status_heating` ist kein Heizzustand). Aktiviere „Kühlen“ (`state_cooling`), sonst zählt Kühlbetrieb als Heizen. Es gibt keinen Startzähler (Wärmewacht zählt selbst) und kein Abtausignal.
- **Vaillant (myVAILLANT):** Wärmewacht bucht Stunde für Stunde aus der Statistik, die mypyllant selbst schreibt. Stelle in mypyllant die Option „Seconds between energy data updates“ auf 3600 bis 7200 Sekunden, sonst ruft es die Energie nur beim Start ab. Die Zahlen hinken dadurch ein bis drei Stunden nach. Es gibt kein Kompressorsignal und kein Abtauen, also keine Takte. Stillstand ist eine Stunde ohne Umweltwärme.

### Recorder schlank halten

Wer in der `recorder`-Konfiguration Entitäten ausschließt (`exclude`) oder nur ausgewählte aufnimmt (`include`): Eine nicht aufgezeichnete Entität bekommt auch **keine Langzeitstatistik**. Wärmewacht liest fast nur diese Statistik, eine Zeile je Stunde.

- **Müssen aufgezeichnet werden:**
  - die Energie-Sensoren von Wärmewacht (Wärme und Strom je Betriebsart, Strom Stillstand) für Bericht, AZ-Kennlinie, Heizlast, Gradtage und Gesundheits-Check;
  - die Außentemperatur für dieselben Auswertungen und die Prüfung des Fühlers;
  - die Vorlauftemperatur für „Vorlauf bei 0 °C“.
- **Sollten aufgezeichnet werden:**
  - die Energiezähler der Wärmepumpe. Wärmewacht braucht sie für die Zeit vor der Einrichtung: Rückblick, „Rückblick neu berechnen“ und Bericht. Ohne sie fehlt bei einem neu angelegten Eintrag der Rückblick;
  - der Startzähler. Ohne Statistik zählt „Starts Saison“ erst ab dem ersten Wert, den Wärmewacht sieht.
- **Dürfen fehlen:**
  - alle übrigen Sensoren von Wärmewacht (Arbeitszahlen, Takte, Kosten, Gesundheit, Diagnose) sowie die Binärsensoren. Wärmewacht speichert seinen Stand selbst. Deren Verlauf in eigenen Diagrammen fehlt dann allerdings;
  - Kompressorstatus und Betriebsart. Ihren Verlauf liest Wärmewacht nur einmal bei der Einrichtung, um die Takte der letzten 10 Tage nachzutragen.

Beispiel für `include` (Entity-IDs auf der Geräteseite prüfen; das `*` am Ende erfasst auch Endungen wie `_2`):

```yaml
recorder:
  include:
    entity_globs:
      - sensor.*_warme_heizen*
      - sensor.*_warme_warmwasser*
      - sensor.*_strom_heizen*
      - sensor.*_strom_warmwasser*
      - sensor.*_strom_stillstand*
    entities:
      - sensor.aussentemperatur      # deine Außentemperatur
      - sensor.vorlauftemperatur     # deine Vorlauftemperatur
      - sensor.waermemenge_heizen    # deine Zähler, je Betriebsart
```

Geht es nur um die Größe der Datenbank, genügt oft eine kurze Aufbewahrung (`purge_keep_days`, Standard 10 Tage). Die Langzeitstatistik bleibt davon unberührt.

## Installation

Wärmewacht wird über HACS als benutzerdefiniertes Repository installiert. Jede Version ist ein reguläres GitHub-Release.

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/waermewacht/integration`, Typ *Integration*.
2. Wärmewacht suchen und herunterladen. Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Wärmewacht*.

## Einrichtung

1. **Name und Quelle:** Der Name (Vorgabe „Wärmepumpe“) wird Gerätename und Präfix der Entity-IDs. Als Quelle stehen die gefundenen Wärmepumpen zur Wahl (EMS-ESP, bei mehreren mit ihrem MQTT-Präfix; Bosch HomeCom mit der Gateway-Nummer) oder *Manuell*.
2. **Entitäten:** Mit einer Vorlage ist das Formular ausgefüllt; jedes Feld lässt sich ändern. Manuell wählst du selbst.

<table>
  <tr>
    <td valign="top"><img src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/screenshots/einrichtung_1.png" alt="Schritt 1: Name und Quelle, die Vorlagen haben zwei Wärmepumpen gefunden" width="360"></td>
    <td valign="top"><img src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/screenshots/einrichtung_2.png" alt="Schritt 2: von der EMS-ESP-Vorlage ausgefüllte Zähler für Heizen, Warmwasser und Kühlen" width="360"></td>
  </tr>
</table>

| Abschnitt | Feld | EMS-ESP (Standardformat) |
| --- | --- | --- |
| Heizen | Erzeugte Wärme Heizen (Zähler) | `sensor.boiler_nrgheat` |
| | Strom Kompressor Heizen | `sensor.boiler_meterheat` |
| | Strom Heizstab Heizen | `sensor.boiler_auxelecheatnrgconsheating` |
| Warmwasser | Erzeugte Wärme Warmwasser (Zähler) | `sensor.boiler_dhw_nrg` |
| | Strom Kompressor Warmwasser | `sensor.boiler_dhw_meter` |
| | Strom Heizstab Warmwasser | `sensor.boiler_dhw_auxelecheatnrgcons` |
| | Warmwasser-Temperatur (Ist, Speicher) | `sensor.boiler_dhw_curtemp` |
| Kühlen | Wärme Kühlen (entzogen, Zähler) | `sensor.boiler_nrgcool` |
| | Strom Kompressor Kühlen | `sensor.boiler_metercool` |
| Betrieb | Kompressor läuft (an/aus oder Drehzahl) | `binary_sensor.boiler_hpcompon` |
| | Betriebsart (Aktivität) | `sensor.boiler_hpactivity` |
| | Kompressorstarts gesamt | `sensor.boiler_totalcompstarts` |
| | Strom Kompressor gesamt (nur ohne Aufteilung je Modus) | – |
| | Strom Heizstab gesamt (nur ohne Aufteilung je Modus) | – |
| | Strom Abtauen | – |
| | Strom Stillstand | – |
| Betriebsart aus mehreren Entitäten | Abtauen läuft (an/aus) | – |
| | Warmwasser läuft (an/aus) | – |
| | Kühlen läuft (an/aus) | – |
| | Heizen läuft (an/aus) | – |
| | Eingestellte Betriebsart (Kühlen?) | – |
| Messwerte | Außentemperatur | `sensor.boiler_outdoortemp` |
| | Vorlauftemperatur | `sensor.boiler_hptc1` |
| | Rücklauftemperatur | `sensor.boiler_hptc0` |
| | Durchfluss | `sensor.boiler_pc0flow` |

- Die Stromzähler je Betriebsart sind die des **Kompressors ohne Heizstab**. Den Heizstab trägst du getrennt ein: entweder je Betriebsart oder als „Strom Heizstab gesamt“, nicht beides. Der Gesamtzähler wird der Betriebsart zugerechnet, die gerade läuft oder zuletzt lief. Ohne Betriebsart zählt er zum Heizen.
- Gibt es den Kompressorstrom nur als einen Zähler für alle Betriebsarten (Waterkotte), trag ihn als „Strom Kompressor gesamt“ ein statt je Betriebsart. Wärmewacht rechnet ihn wie den Heizstab der laufenden Betriebsart zu; Strom ohne Kompressorlauf ist Stillstand.
- **Strom Abtauen** und **Strom Stillstand** sind für Quellen, die diesen Strom in eigenen Zählern führen (Vorlagen Lambda und iDM). Strom Abtauen zählt zur Betriebsart, die gerade läuft oder zuletzt lief (ohne Betriebsart zum Heizen), Strom Stillstand zum Stillstand. EMS-ESP hat solche Zähler nicht.
- Die Vorlage nimmt Zähler mit 0,01 kWh, wenn es sie gibt, sonst die ganzzahligen (z. B. `sensor.boiler_nrgsuppheating`). Den Heizstab je Betriebsart liefert EMS-ESP nur in ganzen kWh.
- Ohne „Kompressor läuft“ gibt es keine Takte. Ohne „Betriebsart“ keine Abtauungen, keine Spreizung und kein mittlerer Vorlauf. „Kompressor läuft“ darf ein Binärsensor oder eine Drehzahl bzw. Modulation sein (läuft bei über 0). Bei manueller Zuordnung versteht Wärmewacht die Werte von EMS-ESP: `0`–`7` oder Texte wie „Heizen“, „Warmwasser“, „Abtauen“ bzw. `heating`, `hot water`, `defrost`.
- Die Außentemperatur nutzen [AZ-Kennlinie und Heizlast](#kennlinie-und-heizlast). Wärmewacht liest ihre Stundenmittel aus der Langzeitstatistik; der Sensor braucht also eine Statistik (`state_class: measurement`). Den Durchfluss prüft Wärmewacht nur auf Plausibilität (siehe [Fehlerbehebung](#fehlerbehebung)). Dafür braucht es die Betriebsart, für den Vergleich mit Wärme und Spreizung auch Vor- und Rücklauf.

- **Betriebsart aus mehreren Entitäten** (Abschnitt eingeklappt): Hat die Wärmepumpe keine einzelne Betriebsart-Entität, sondern Merker (an/aus) für Abtauen, Warmwasser, Kühlen und Heizen, trägst du diese ein. Ein Merker „an“ gewinnt in dieser Reihenfolge: Abtauen, Warmwasser, Kühlen, Heizen. Läuft der Kompressor und kein Merker ist an, zählt der Lauf als Heizen. Die *eingestellte Betriebsart* (z. B. „Cool“) macht aus Heizen Kühlen, wenn die Betriebsart-Entität nur zwischen Heizen und Warmwasser unterscheidet (Umschaltventil). Die Vorlagen für Stiebel und HeishaMon füllen das aus, die für ViCare den Merker Warmwasser.

Mehrere Wärmepumpen: je einen Eintrag anlegen.

### Einstellungen

*Wärmewacht → Eintrag → Zahnrad (Konfigurieren)*. Jede Änderung lädt den Eintrag neu. Die Felder in der Reihenfolge des Formulars:

| Einstellung | Vorgabe | Bedeutung |
| --- | --- | --- |
| Mindeststrom für eine Arbeitszahl | 0,5 kWh | Darunter ist die Arbeitszahl unbekannt statt zufällig. |
| Kurzlauf unter | 10 min | Fraunhofer ISE weist Zyklen unter etwa 10 Minuten gesondert aus. |
| Kritischer Lauf unter | 6 min | Mindestlaufzeit laut Dimplex-Projektierungshandbuch etwa 6 Minuten. |
| Auffällig ab Starts pro Stunde über | 3 | Mehr Starts innerhalb einer Stunde gelten als auffällig. Verdichterhersteller nennen 6 bis 12 Starts pro Stunde als Obergrenze. |
| Heizstab: milde Witterung ab | 5 °C | Gesundheits-Check: Tagesmittel der Außentemperatur, ab dem die Wärmepumpe allein heizen sollte (eigene Annahme). |
| Effizienz gesunken ab | 15 % | Gesundheits-Check: Rückgang der AZ Heizen gegenüber der Vorsaison bei gleicher Außentemperatur; aus erst 5 Punkte darunter (eigene Annahme). |
| Thermische Desinfektion ab | 60 °C | Warmwasser-Temperatur, ab der eine Ladung als thermische Desinfektion zählt. DVGW W 551 verlangt 60 °C am Austritt; der Speicherfühler zeigt oft etwas weniger. |
| Saison beginnt im | Juli | Beginn der Saison (Heizperiode Juli bis Juni). |
| ***Kosten und Gasvergleich (optional)*** | | |
| Strompreis | – | ct/kWh brutto. Ohne ihn gibt es keine Kosten-Sensoren. |
| Strom-Grundpreis | – | €/Jahr brutto, nur bei eigenem Wärmepumpenzähler (Wärmepumpentarif). Am Haushaltszähler leer lassen: Dessen Grundpreis fällt ohnehin an. |
| Gas-Arbeitspreis | – | ct/kWh brutto auf den Brennwert (wie auf der Gasrechnung). Für die Ersparnis gegenüber einem Gaskessel. |
| Gas-Grundpreis | – | €/Jahr brutto, anteilig je Tag. Ohne ihn vergleicht Wärmewacht nur die Arbeitspreise. |
| ***Heizlast (optional)*** | | |
| Normaußentemperatur | – | °C nach DIN/TS 12831-1 für deine Postleitzahl (z. B. BWP-Klimakarte). Für die Heizlast bei Normaußentemperatur. |
| Heizleistung bei A−7/W35 | – | kW laut Datenblatt. Ergibt den Sensor „Leistung je Heizlast“. |
| Kleinste Heizleistung | – | kW laut Datenblatt. Zeigt, ob in der Übergangszeit Takten zu erwarten ist. |

Jedes optionale Feld darf leer bleiben. Quellen der Vorgaben in [docs/ENTWICKLUNG.md](docs/ENTWICKLUNG.md). Wird der Saisonbeginn geändert, berechnet Wärmewacht die laufende Saison aus der Langzeitstatistik neu (Stillstand vor der Einrichtung stundenweise geschätzt).

### Neu konfigurieren

*Wärmewacht → ⋮ → Neu konfigurieren* zeigt das Entitäten-Formular erneut, mit der bisherigen Zuordnung. Die bisher gebuchten Werte bleiben. Ein neu hinzugefügter Zähler zählt ab diesem Zeitpunkt; die Zeit vor der Einrichtung holt die Schaltfläche **Rückblick neu berechnen** nach.

**Rückblick neu berechnen** (Schaltfläche, Konfiguration) rechnet die Energie vor der Einrichtung neu aus der Langzeitstatistik, mit den heutigen Entitäten und Regeln: nach einem neu eingetragenen Zähler oder wenn ein Update die Regeln des Rückblicks verbessert hat. Was Wärmewacht seit der Einrichtung gebucht hat, bleibt. Die Zeit zwischen Einrichtung und Nachtragen eines Zählers fehlt weiterhin, und die nachgetragene Statistik der eigenen Energie-Sensoren vor der Einrichtung bleibt, wie sie war. Nicht bei Quellen mit Vortageswerten (MELCloud, F1p-Brücke): Deren Statistik taugt nicht für den Rückblick.

Kennt eine Vorlage nach einem Update ein neues Signal (etwa die Warmwasser-Temperatur), trägt Wärmewacht es beim Start selbst ein, wenn es dieselbe Wärmepumpe betrifft und der Eintrag noch keins hat. Was du unter *Neu konfigurieren* bewusst entfernst, bleibt entfernt.

## Gasheizung vor dem Umstieg

Wer noch mit Gas heizt und über eine Wärmepumpe nachdenkt, braucht vor allem die **Heizlast**: Wie viel Leistung braucht das Haus am kältesten Tag? Wärmewacht rechnet sie aus dem Gasverbrauch, mit derselben [Energiesignatur](#kennlinie-und-heizlast) wie bei einer Wärmepumpe. Dazu kommen Heizgrenze, Wärme je Gradtag und der Warmwasseranteil.

**Einrichtung:** *Integration hinzufügen → Wärmewacht*, als Quelle **Gasheizung (vor dem Umstieg)**. Dann:

| Feld | Bedeutung |
| --- | --- |
| Gas gesamt | Ein Zähler für Heizen und Warmwasser: Gaszähler (Impuls, AI-on-the-edge) oder der Zähler der Therme, in kWh oder m³ |
| Gas nur Heizen | statt „Gas gesamt“, wenn die Therme Heizen und Warmwasser getrennt zählt (z. B. Viessmann ViCare) |
| Gas Warmwasser | optional, wenn Warmwasser getrennt gezählt wird |
| Außentemperatur | Pflicht, mit Langzeitstatistik; eine nahe Wetterstation genügt |
| Brennwert, Zustandszahl | nur für Zähler in m³, aus der Gasrechnung (kWh = m³ × Brennwert × Zustandszahl) |

Die Zähler brauchen eine Langzeitstatistik (Zustandsklasse `total` oder `total_increasing`). Wärmewacht liest nur sie, und zwar die **letzten 365 Tage**: Reicht die Statistik deines Gaszählers schon so weit zurück (etwa aus dem Energie-Dashboard), gibt es die Ergebnisse 2 Minuten nach der Einrichtung. Danach rechnet Wärmewacht täglich um 3 Uhr neu. Es hört keine Zustände ab und speichert nichts.

**Wärme aus Gas:** Gas in kWh auf den Brennwert (wie auf der Rechnung) mal **Nutzungsgrad 0,87**, dem Feldwert von Brennwertkesseln (Jagnow/Wolff, DBU 2004). Ältere Kessel liegen darunter; stell den Wert in den Einstellungen um. Die Heizlast ändert sich im selben Verhältnis.

**Warmwasser** zählt nicht zur Heizlast. Wärmewacht trennt es so:

- mit einem eigenen Warmwasser-Zähler: aus diesem (von „Gas gesamt“ abgezogen);
- mit „Gas gesamt“ ohne Warmwasser-Zähler aus dem **Sommersockel**: Der Median des Tagesverbrauchs an Tagen mit mindestens 15 °C Tagesmittel (Heizgrenze nach VDI 3807) gilt als Warmwasser und geht von jedem Tag ab. Dafür braucht es mindestens 14 solche Tage in den 365 Tagen. Fehlen sie (Zähler erst seit dem Herbst), zieht Wärmewacht nichts ab, und der Warmwasseranteil bleibt unbekannt (`no_summer_days`). Die normgerechte Heizlast stimmt trotzdem, weil sie nur aus der Steigung kommt; die Heizgrenze liegt dann zu hoch.

| Entität | Einheit | Bedeutung |
| --- | --- | --- |
| Heizlast je Kelvin | W/K | Steigung der Energiesignatur. Attribute wie bei der Wärmepumpe, dazu `boiler_efficiency` und `dhw_method` |
| Heizlast bei Normaußentemperatur | kW | normgerecht, nur mit der Einstellung Normaußentemperatur |
| Heizgrenze | °C | wo die Gerade 0 erreicht |
| Wärme je Gradtag | kWh/K·d | Wärme fürs Heizen je Gradtag G20/15, über die Heiztage |
| Warmwasseranteil | % | Anteil des Gases für Warmwasser. Attribute `method` (`counter`, `summer_base`, `no_summer_days`, `heating_only`), `summer_days`, `summer_base_kwh_per_day` |
| Gas 365 Tage | kWh | Gas der letzten 365 Tage. Attribute `days` (Tage mit Daten), `complete`, `heat_kwh` (Wärme nach Nutzungsgrad) |
| Gaskosten 365 Tage | € | nur mit Gaspreis in den Einstellungen; mit Grundpreis |

Ist ein Wert unbekannt, nennt das Attribut `reason` den Grund (`not_analysed_yet`, `no_recorder`, `gas_unit`, `no_calorific_value` oder die Gründe der Energiesignatur). Die Aktion [Heizlast](#heizlast) geht auch für eine Gasheizung, vorgegeben sind dann die letzten 365 Tage.

**Grenzen:**

- Thermen schätzen ihren Gasverbrauch meist aus Brennerlaufzeit und Leistung, statt ihn zu messen. Ein echter Gaszähler ist genauer.
- Ein Gasherd am selben Zähler zählt als Warmwasser (Sommersockel) oder als Heizen; trennen lässt er sich nicht.
- Kamin, Kachelofen oder Solarthermie senken den Gasverbrauch an kalten oder sonnigen Tagen. Die Heizlast fällt dann zu niedrig aus.

## Entitäten

Alle Entitäten hängen an einem eigenen Gerät je Wärmepumpe. Welche entstehen, hängt von den zugeordneten Signalen und Einstellungen ab.

### Arbeitszahlen

| Entität | Braucht |
| --- | --- |
| AZ Heizen *Zeitraum* | Wärme und Strom Heizen |
| AZ Warmwasser *Zeitraum* | Wärme und Strom Warmwasser |
| AZ Heizen+WW *Zeitraum* | Heizen oder Warmwasser vollständig |
| EER Kühlen *Zeitraum* (Leistungszahl) | Wärme und Strom Kühlen |

*Zeitraum* ist **heute**, **gestern**, **Monat**, **Saison** oder **gesamt**. Das sind zusammen bis zu 20 Sensoren ohne Einheit („AZ“ = Arbeitszahl). Heute und gestern schwanken stark und sind deshalb standardmäßig deaktiviert. Die Saison des Kühlens ist das Kalenderjahr: Gekühlt wird von Frühjahr bis Herbst, eine Heizsaison ab Juli würde das teilen. „Gesamt“ reicht so weit zurück wie die Langzeitstatistik deiner Zähler bei der Einrichtung.

- Arbeitszahl je Betriebsart = Wärme / Strom (Kompressor plus Heizstab), **ohne** Stillstand.
- Heizen + Warmwasser = Wärme beider / (Strom beider + Stillstand). Das entspricht einer Jahresarbeitszahl.

Die Sensoren haben eine Langzeitstatistik (`state_class: measurement`). Sie ist ein Zeitmittel des Quotienten, keine Bilanz. Für Monats- oder Jahreswerte nimm die [Energie-Sensoren](#energie) oder den [Bericht](#bericht).

Attribute:

| Attribut | Bedeutung |
| --- | --- |
| `heat_kwh` | Wärme im Zeitraum |
| `electricity_kwh` | Strom im Zeitraum (Kompressor plus Heizstab, ohne Stillstand) |
| `standby_kwh` | Stillstand im Zeitraum (nur Heizen + Warmwasser) |
| `period_start` | Beginn des Zeitraums (bei „gesamt“ leer) |
| `counter_step_kwh` | Auflösung des gröbsten beteiligten Zählers: 0,01 oder 1 kWh |
| `reliable` | `true`, wenn die Rundung der Zähler höchstens 5 % des Stroms ausmacht |

### Energie

| Entität | Einheit | Bedeutung |
| --- | --- | --- |
| Wärme Heizen / Warmwasser / Kühlen | kWh | Wärme seit der Einrichtung (beim Kühlen: entzogene Wärme) |
| Strom Heizen / Warmwasser / Kühlen | kWh | Strom bei laufendem Kompressor, mit Heizstab und „Strom Abtauen“, ohne Stillstand |
| Strom Stillstand | kWh | Strom bei stehendem Kompressor, alle Betriebsarten, dazu „Strom Stillstand“ der Quelle. Attribute aus dem Tagebuch (mit der täglichen Analyse, also nur mit Außentemperatur): mittlere Leistung der letzten 7 Tage (`mean_power_w_7d`) gegen den Median der 30 Tage davor (`reference_w`), kleinster und größter Tag (`min_day_w`, `max_day_w`); `rising` ist an ab +50 % **und** +10 W (eigene Annahme) |

Alle mit Langzeitstatistik (`total_increasing`). Jeder Sensor entsteht nur, wenn der passende Zähler zugeordnet ist. „Strom Stillstand“ entsteht, wenn sich der Stillstand abtrennen lässt: mit Wärme- und Stromzähler derselben Betriebsart oder mit Stromzähler und „Kompressor läuft“ (nicht bei Tageswerten aus der Cloud). Bitte nicht deaktivieren und nicht aus dem [Recorder](#recorder-schlank-halten) ausschließen: Bericht, AZ-Kennlinie und Heizlast lesen ihre Statistik für die Zeit nach der Einrichtung.

**Statistik vor der Einrichtung:** Einmal nach der Einrichtung (bei älteren Einträgen beim Update) schreibt Wärmewacht die Stunden davor in die Statistik dieser Sensoren. Sie sind aus der Statistik deiner Zähler berechnet, mit stundenweise geschätztem Stillstand. Statistik-Karten zeigen damit auch die Monate vor der Einrichtung. Wärmewacht schreibt nur Stunden vor der ersten Zeile, die Home Assistant selbst aufgezeichnet hat. Etwa 15 Minuten nach dem Start hebt Wärmewacht die Summen ab der ersten importierten Stunde einmalig an. So beginnen sie bei 0, und der erste Balken einer Statistik-Karte ist nicht negativ. Die Änderung je Stunde bleibt dabei gleich. Die Stunde der Einrichtung fehlt bis zum Einrichtungszeitpunkt.

**Stillstand:** Strom einer Betriebsart gilt als Stillstand, wenn seit dem letzten Zählerwert weder Wärme dieser Betriebsart kam noch der Kompressor in ihr lief. Ohne Kompressorstatus entscheidet nur die Wärme. Gibt es weder Kompressorstatus noch Wärmezähler dieser Betriebsart, zählt ihr Strom als Lauf.

### Takte

Die meisten Takt-Sensoren brauchen „Kompressor läuft“. Abtauungen brauchen nur die Betriebsart. „Starts gesamt“ gibt es auch, wenn nur der Startzähler der Wärmepumpe zugeordnet ist.

| Entität | Einheit | Bedeutung |
| --- | --- | --- |
| Starts heute, Starts gestern | – | beobachtete Kompressorstarts |
| Starts Saison | – | Starts seit Saisonbeginn aus dem Zähler der Wärmepumpe und seiner Langzeitstatistik. Reicht die Statistik nicht so weit zurück, zählt er ab ihrem ersten Wert. Attribute `since` und `per_day`. Zur Einordnung: 90 % der Luft/Wasser-Anlagen im Fraunhofer-Feldtest liegen unter 5.500 Starts im Jahr, etwa 15 am Tag. Braucht den Startzähler und die Außentemperatur (wird mit der täglichen Analyse bestimmt). |
| Starts gesamt | – | Zähler der Wärmepumpe, wenn zugeordnet (Attribut `source: heat_pump`), sonst beobachtete Starts seit der Einrichtung (`since_setup`) |
| Laufzeit heute | min | Kompressor-Laufzeit, in Schritten von 5 Minuten |
| Laufzeit pro Start heute, 7 Tage, Monat | min | mittlere Dauer der Läufe, die im Zeitraum endeten |
| Kurzläufe heute | – | Läufe unter der Kurzlauf-Grenze; Attribute `threshold_minutes`, `critical_runs`, `critical_threshold_minutes` |
| Kürzeste Pause heute | min | kürzeste Zeit zwischen Ende und nächstem Start |
| Abtauungen heute | – | Anzahl; Attribute `minutes` (Dauer heute), `yesterday` (Anzahl gestern). Mit der täglichen Analyse (nur mit Außentemperatur) für die letzten 7 Tage Anzahl (`defrosts_7d`), warme Abtauungen (`warm_defrosts_7d`, Stundenmittel ab 10 °C), mittlere und längste Dauer (`mean_minutes_7d`, `longest_minutes_7d`), dazu `classes`: Abtauungen je Laufstunde je 2-K-Klasse gegen die Vorsaison (`factor` = laufende ÷ vorige) |

Fehlte der Kompressorstatus länger als 5 Minuten (Home Assistant oder Quelle aus), gilt der betroffene Lauf als unsicher. Er zählt dann nicht für Laufzeit pro Start, Kurzläufe und Pausen.

### Auffälliges Takten

Binärsensor (Problem), nur mit „Kompressor läuft“. Er ist an, wenn in den letzten 24 Stunden

- innerhalb einer Stunde mehr Starts lagen als eingestellt (Vorgabe: mehr als 3) **oder**
- mindestens 3 Läufe kürzer waren als der kritische Lauf (Vorgabe: 6 Minuten).

Attribute: `max_starts_per_hour`, `critical_runs_24h`, `short_runs_24h`, `starts_per_hour_limit`.

### Warmwasser-Ladungen

Eine Ladung ist ein zusammenhängender Zeitraum mit der Betriebsart Warmwasser. Eine Abtauung dazwischen beendet sie nicht. Wärme und Strom der Ladung kommen aus den Warmwasser-Zählern, ohne Stillstand. Was die Zähler bis 5 Minuten nach dem Ende melden, zählt noch dazu; bei Zählern in ganzen kWh (Daikin) bis 2 Stunden, längstens bis zur nächsten Ladung. Der Wert der letzten Ladung erscheint dann entsprechend später. Wärmewacht hält die Ladungen 40 Tage.

| Entität | Bedeutung | Braucht |
| --- | --- | --- |
| AZ Warmwasser letzte Ladung | Wärme durch Strom (Kompressor und Heizstab) der zuletzt beendeten Ladung. Attribute: `start`, `minutes`, `heat_kwh`, `electricity_kwh`, `aux_kwh`, `start_temp`, `max_temp`, `disinfection`, `uncertain` | Warmwasser vollständig und Betriebsart, Zähler laufend (nicht bei Tages- oder Stundenwerten aus der Cloud, also nicht bei Bosch HomeCom, ViCare, MELCloud, F1p-Brücke und myVAILLANT: Die Werte kommen zu spät) |
| AZ Warmwasser-Ladungen 30 Tage | dasselbe über die normalen Ladungen der letzten 30 Tage, ohne thermische Desinfektion. Attribute: `charges`, `uncertain`, `mean_minutes`, `mean_heat_kwh`, `mean_lift` (Temperaturhub in K), `aux_share`, `disinfections` | ebenso |
| Letzte thermische Desinfektion | Zeitpunkt, an dem der Speicher zuletzt die eingestellte Temperatur erreicht hat (Vorgabe 60 °C nach DVGW W 551). Eine neue zählt erst, wenn er dazwischen 5 K darunter war. | Warmwasser-Temperatur |

`uncertain`: Die Betriebsart war während der Ladung unbekannt, oder Home Assistant lief nicht. Solche Ladungen zählen in der AZ mit, aber nicht in Dauer, Wärme und Hub je Ladung.

### Gesundheits-Check

Wärmewacht prüft einmal täglich (gegen 3 Uhr) Auffälligkeiten, die Geld kosten oder auf einen Defekt hindeuten. Er sagt, **was** auffällt und **woran** das zu sehen ist, nicht **warum**. Reichen die Daten nicht, ist ein Sensor *unbekannt* und nennt im Attribut `reason` den Grund, nie „aus“ mangels Daten. Hergeleitet und belegt in [docs/GESUNDHEITSCHECK.md](docs/GESUNDHEITSCHECK.md).

<img src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/screenshots/gesundheit.png" alt="Problem-Sensoren des Gesundheits-Checks: Effizienz gesunken, Heizstab bei milder Witterung, Heizstab bei Warmwasserladungen, Auffälliges Takten" width="400">

| Binärsensor (Problem) | An, wenn | Braucht |
| --- | --- | --- |
| Effizienz gesunken | Die Arbeitszahl Heizen der laufenden Saison liegt bei gleicher Außentemperatur mindestens 15 % unter der Vorsaison (einstellbar). Aus erst wieder 5 Punkte darunter. | Heizen vollständig und Außentemperatur |
| Heizstab bei Warmwasserladungen | Der Heizstab hat in den letzten 30 Tagen mehr als 10 % des Stroms normaler [Warmwasser-Ladungen](#warmwasser-ladungen) gebraucht (ohne thermische Desinfektion, mindestens 10 Ladungen). Neu bewertet nach jeder Ladung und um Mitternacht. | Ladungen, Warmwasser-Temperatur und ein Heizstab-Zähler |
| Warmwasser-Effizienz unter Vorjahr | Die AZ normaler [Warmwasser-Ladungen](#warmwasser-ladungen) der letzten 30 Tage liegt mindestens 15 % unter denselben 30 Tagen des Vorjahres (ohne thermische Desinfektion, je mindestens 10 Ladungen). Gleiche Jahreszeit, weil das Kaltwasser im Winter kälter ist. Ursachen: höhere Speichertemperatur, verkalkter Wärmetauscher. Frühestens ein Jahr nach der Einrichtung, neu bewertet einmal am Tag. | Ladungen und Warmwasser-Temperatur |
| Heizstab bei milder Witterung | Der Heizstab hat in den letzten 7 Tagen an Tagen ab 5 °C Tagesmittel (einstellbar) zusammen mindestens 2 kWh fürs Heizen gebraucht. Unbekannt mit weniger als 3 milden Tagen mit Heizwärme im Fenster. | dazu ein Heizstab-Zähler |

- **Gleiches Wetter:** Verglichen wird je 2-K-Klasse der [AZ-Kennlinie](#kennlinie-und-heizlast), gewichtet mit der Wärme der laufenden Saison. Hat eine Saison Klassen zusammengefasst (am Saisonanfang mit wenigen Tagen üblich), zählt Wärmewacht die Klassen der anderen über denselben Bereich zusammen. Nötig sind mindestens 4 K gemeinsamer Bereich mit zusammen 14 Tagen und 10 kWh Strom.
- **Attribute:** Effizienz: `ratio_current`, `ratio_previous_same_weather`, `drop_percent`, `threshold_percent` und `classes` (je Klasse Tage und AZ beider Saisons). Heizstab: `aux_kwh_7d`, `mild_days_7d`, `min_outdoor_temp`, `threshold_kwh` und `days` (je milder Tag). Warmwasser-Vorjahr: `ratio`, `charges`, `from`, `to`, dieselben mit `previous_` für das Vorjahr, `change_percent`, `threshold_percent`. Die Listen werden nicht aufgezeichnet.
- **Gründe für *unbekannt*:** `not_analysed_yet` (nach dem Start), `no_previous_season`, `too_few_classes`, `too_few_days`, `too_little_electricity`, `comparison_restarted`, `too_few_charges`, `no_previous_year` (im Vorjahr weniger als 10 Ladungen, etwa im ersten Jahr).
- **Effizienzvergleich neu starten** (Schaltfläche, Konfiguration): nach einer gewollten Änderung, etwa einer neuen Heizkurve. Die nächsten 28 Tage werden die neue Vergleichsbasis, bis dahin ist „Effizienz gesunken“ unbekannt.
- **Datenfehler** (Zähler steht still, Quelle nicht erreichbar, Außentemperatur unbrauchbar, Durchfluss unplausibel oder 0, Vor- und Rücklauf vertauscht) meldet Wärmewacht als [Reparaturhinweis](#fehlerbehebung), nicht als Sensor.
- **Tagebuch:** Wärmewacht legt um Mitternacht einen Eintrag für den Vortag an (Außentemperatur, Starts, Laufzeit je Betriebsart, Kurzläufe, Abtauungen, Spreizung, Vorlauf, Durchfluss, Energie, Warmwasser-Ladungen), bis zu 3 Jahre. Es steht in der Verlaufsdatei und wird nur einmal am Tag geschrieben. Daraus kommen „Spreizung 7 Tage“, der Anstieg des Stillstands und die Abtauungen je Klasse.

### Diagnose

| Entität | Einheit | Bedeutung | Braucht |
| --- | --- | --- | --- |
| Heizstab-Anteil Monat, Saison | % | Anteil des Heizstabs am Strom für Heizen und Warmwasser (mit Stillstand) | Heizstab-Zähler |
| Spreizung heute | K | Vorlauf minus Rücklauf, zeitgewichtet über die Zeit mit Kompressor im Heizbetrieb | Vorlauf, Rücklauf und Betriebsart |
| Vorlauftemperatur heute | °C | mittlere Vorlauftemperatur, ebenso gewichtet | Vorlauf und Betriebsart |

### Kosten und Gasvergleich

Mit einem Strompreis in den [Einstellungen](#einstellungen).

| Entität | Einheit | Bedeutung | Braucht |
| --- | --- | --- | --- |
| Stromkosten Monat, Saison | € | aller Strom der Wärmepumpe (alle Betriebsarten, Stillstand, Heizstab) × Strompreis, plus anteiliger Strom-Grundpreis; in Schritten von 10 Cent | Strompreis und ein Stromzähler |
| Wärmekosten je kWh Saison | €/kWh | Kosten für Heizen und Warmwasser (Strom mit Stillstand, anteiliger Strom-Grundpreis) je kWh Wärme; unter 0,5 kWh Wärme unbekannt | Strompreis, Heizen oder Warmwasser vollständig |
| Ersparnis ggü. Gaskessel Saison | € | Gaskosten (Arbeitspreis plus anteiliger Gas-Grundpreis) für dieselbe Wärme minus die Kosten der Wärmepumpe für Heizen und Warmwasser (Strom mit Stillstand, anteiliger Strom-Grundpreis); in ganzen Euro | Strompreis, Gas-Arbeitspreis, Heizen oder Warmwasser vollständig |

- **Saison** heißt Heizperiode ab dem eingestellten Monat (Vorgabe: 1. Juli bis 30. Juni). Den Beginn nennt das Attribut `period_start`.
- **Preise** gelten fest, so wie sie in den Einstellungen stehen. Dynamische Tarife berücksichtigt Wärmewacht nicht.
- **Grundpreise** werden je Tag verteilt (Jahrespreis ÷ 365 bzw. 366). Der Strom-Grundpreis zählt nur bei eigenem Wärmepumpenzähler und gehört zu Heizen und Warmwasser.
- **Gaskessel:** Er bräuchte für dieselbe Wärme (Heizen und Warmwasser, ohne Kühlen) Wärme ÷ 0,87 an Gas, bezogen auf den Brennwert. 0,87 ist der Nutzungsgrad, den Feldmessungen an Brennwertkesseln ergeben haben (Jagnow/Wolff, DBU 2004). Gas wird nach Brennwert abgerechnet, deshalb gilt der Wert auf den Brennwert.
- **Kein CO₂-Vergleich:** Er hinge zu stark an Annahmen (Durchschnitts- oder Stundenmix, Vorketten, PV-Eigenverbrauch, Batterie, Ökostrom).

Attribute von „Ersparnis ggü. Gaskessel Saison“:

| Attribut | Bedeutung |
| --- | --- |
| `period_start` | Beginn der Saison |
| `heat_kwh` | Wärme Heizen und Warmwasser in der Saison |
| `heat_pump_cost_eur` | Kosten der Wärmepumpe für diese Wärme (Strom mit Stillstand, anteiliger Strom-Grundpreis) |
| `electricity_base_cost_eur` | darin enthaltener anteiliger Strom-Grundpreis (0 ohne Einstellung) |
| `gas_kwh` | Gas für dieselbe Wärme, auf den Brennwert |
| `gas_cost_eur` | Gaskosten mit anteiligem Grundpreis |
| `gas_base_cost_eur` | darin enthaltener anteiliger Gas-Grundpreis (0 ohne Einstellung) |
| `boiler_efficiency` | Kesselnutzungsgrad auf den Brennwert (0,87) |

### Kennlinie und Heizlast

Alle Sensoren dieses Abschnitts brauchen die Außentemperatur sowie Wärme und Strom Heizen, dazu den Recorder. Wärmewacht rechnet 2 Minuten nach dem Start und dann täglich ab 3 Uhr, aus der Langzeitstatistik (vor der Einrichtung aus der Statistik deiner Zähler, wie der [Bericht](#bericht)). Die Ergebnisse liegen nur im Speicher. Nach einem Neustart sind die Sensoren deshalb etwa 2 Minuten leer.

| Entität | Einheit | Bedeutung |
| --- | --- | --- |
| AZ-Kennlinie Heizen | Zeitpunkt | Wann zuletzt gerechnet wurde. Die Kennlinie steht in den Attributen. |
| Heizlast je Kelvin | W/K | Steigung der Energiesignatur der letzten vollständigen Saison. |
| Heizlast bei Normaußentemperatur | kW | Heizlast „normgerecht“ (Gerade durch 0 bei 20 °C). Nur mit der Einstellung Normaußentemperatur. |
| Spreizung 7 Tage | K | Spreizung im Heizbetrieb an kalten Tagen (unter 5 °C) der letzten 7 Tage, ab 10 Stunden Heizbetrieb. Braucht dazu Vorlauf, Rücklauf und Betriebsart. Attribute `all_days` (alle Tage), `field_reference` und `field_range` (Feldtest WPsmart: 6,8 K, 3,2–9,8 K). Kein Alarm: Hydraulik und Fühlerort prägen den Wert. |
| Leistung je Heizlast | – | Heizleistung laut Datenblatt geteilt durch die normgerechte Heizlast. Nur mit der Einstellung Heizleistung. Attribute `measured_factor` (gegen die gemessene Heizlast), `load_at_7c_kw` und mit kleinster Heizleistung `cycling_expected`. Feldmittel 1,5 (Fraunhofer WP-QS). |
| Vorlauf bei 0 °C | °C | Die Heizkurve als Kennwert: Ausgleichsgerade des Vorlaufs über der Außentemperatur, abgelesen bei 0 °C. Braucht dazu die Vorlauftemperatur. Je Tag zählen nur Stunden mit Heizwärme (ab 0,3 kWh) und ohne Warmwasser, mindestens 2 je Tag; nötig sind 14 Tage über 6 K Spanne. Attribute `slope` (K Vorlauf je K Außentemperatur), `r_squared`, `days`, `spread`, `reasons`, `previous_season` und `previous_slope` (dasselbe für die Vorsaison). Zeigt, ob eine geänderte Heizkurve wirkt. Etwas unter dem eingestellten Wert, weil Pausen in der Stunde mitzählen. |
| Gradtage Saison | K·d | Gradtagzahl G20/15 nach VDI 3807 seit Saisonbeginn bis gestern: je Tag 20 °C minus Tagesmittel, nur an Tagen unter 15 °C. Als Zähler: Eine Statistik-Karte zeigt damit die Gradtage je Monat. Attribute `base` (`G20/15`), `days_counted`, `days_missing` (unter 20 Stundenwerten), `days_without_heating`. |
| Wärme je Gradtag Saison | kWh/K·d | Wärme fürs Heizen geteilt durch die Gradtage, nur über Heiztage (ab 1 kWh Heizwärme am Tag), erst ab 10 K·d. Kühle Tage ohne Heizbetrieb im Sommer und Herbst würden den Wert sonst stark drücken. Ohne Heizwärme ist er unbekannt. Attribut `degree_days_heating` am Gradtage-Sensor: die Gradtage dieser Heiztage. Attribut `previous_season`: derselbe Wert der ganzen Vorsaison. Ein Maß für den Wärmebedarf des Hauses, bereinigt ums Wetter. Er schwankt von Monat zu Monat um etwa 18 %, deshalb nur als Saisonwert. |

**AZ-Kennlinie:** Arbeitszahl Heizen je 2-K-Klasse der Tagesmitteltemperatur, ohne Stillstand. Laufende und vorige Saison bleiben getrennt: Eine geänderte Heizkurve würde sonst beide verwischen.

- Ein Tag zählt mit mindestens 20 Stundenwerten der Außentemperatur und nur, wenn er Wärme fürs Heizen brachte. Stunden ohne Außentemperatur fallen mit ihrer Energie weg. Werte außerhalb von −35 bis 45 °C werden verworfen.
- Eine Klasse braucht mindestens 7 Tage. Dünne Randklassen werden zur Nachbarklasse gezogen. Dünne Klassen dazwischen bleiben stehen, haben aber `sparse: true` und `ratio: null`.

Attribute von „AZ-Kennlinie Heizen“:

| Attribut | Bedeutung |
| --- | --- |
| `current_start`, `previous_start` | Beginn der laufenden und der vorigen Saison |
| `current`, `previous` | Klassen der laufenden und der vorigen Saison, kälteste zuerst |

Jede Klasse hat `lower` und `upper` (°C, untere Grenze eingeschlossen), `days`, `mean_outdoor` (Mittel der Tagesmittel), `heat_kwh`, `electricity_kwh`, `ratio` (`null` unter dem Mindeststrom oder bei dünner Klasse) und `sparse`.

**Heizlast (Energiesignatur):** Wochenmittel der Heizleistung über dem Wochenmittel der Außentemperatur. Nur die Wärme fürs Heizen zählt, Warmwasser nicht. Durch die Wochen legt Wärmewacht eine Ausgleichsgerade.

- Eine Woche beginnt Montag 0 Uhr. Sie zählt mit mindestens 6 vollen Tagen und einem Mittel unter 12 °C.
- Ein voller Tag hat mindestens 20 Stundenwerte der Außentemperatur und keine Kühlung. Werte außerhalb von −35 bis 45 °C werden verworfen. Ein Frosttag hat ein Tagesmittel unter 0 °C.
- Ein Ergebnis gibt es erst mit mindestens 8 Wochen, 10 K Spanne zwischen kältester und wärmster Woche, 5 Frosttagen und einer fallenden Geraden. Sonst bleibt der Wert leer, und `reasons` nennt den Grund.
- „Gemessen“ (`measured_kw`) ist die Gerade bei Normaußentemperatur, mit inneren und solaren Gewinnen. „Normgerecht“ (`standard_kw`) ist die parallel verschobene Gerade durch 0 bei 20 °C, ohne diese Gewinne. Der Sensor „Heizlast bei Normaußentemperatur“ zeigt den normgerechten Wert.

Attribute von „Heizlast je Kelvin“:

| Attribut | Bedeutung |
| --- | --- |
| `start`, `end` | ausgewerteter Zeitraum (die letzte vollständige Saison) |
| `sufficient` | `true`, wenn die Daten für ein Ergebnis reichen |
| `reasons` | Gründe, wenn nicht: `too_few_weeks`, `spread_too_small`, `too_few_frost_days`, `slope_not_negative` |
| `week_count` | gültige Wochen |
| `spread` | Spanne der Wochenmittel in K |
| `frost_days` | Frosttage in den gültigen Wochen |
| `intercept_kw`, `slope_kw_per_k` | Gerade P = a + b · T (a in kW, b in kW/K, negativ) |
| `r_squared` | Bestimmtheitsmaß der Geraden |
| `heating_limit` | Heizgrenze in °C: Dort erreicht die Gerade 0 |
| `design_temp` | Normaußentemperatur aus den Einstellungen |
| `measured_kw`, `standard_kw` | Heizlast bei Normaußentemperatur, gemessen und normgerecht |
| `weeks` | gültige Wochen mit `start`, `days`, `hours`, `mean_outdoor`, `power_kw` |

Ohne ausreichende Daten sind die Werte der Geraden `null`. Für andere Zeiträume und Heizen mit Warmwasser gibt es die [Aktionen](#aktionen). Diagramme zeigen die [Dashboard-Beispiele](#dashboard-beispiele).

## Aktionen

*Einstellungen → Werkzeuge → Aktionen* (früher *Entwicklerwerkzeuge → Aktionen*) → Aktion wählen, Wärmepumpe und Zeitraum wählen, „Antwort anzeigen“. Die Antwort lässt sich auch in Skripten und Automationen verwenden (`response_variable`). Zeiten ohne Zeitzone gelten als Ortszeit deines Home Assistant. Alle Aktionen brauchen den Recorder.

### Bericht

**Wärmewacht: Bericht** liefert Wärme, Strom und Arbeitszahlen eines Zeitraums, je Monat aufgeschlüsselt.

```yaml
action: waermewacht.report
data:
  config_entry: <Eintrag auswählen>
  start: "2026-09-01 00:00:00"
```

Ohne Beginn: Beginn der laufenden Saison. Ohne Ende: jetzt. Beispiel-Antwort (erfundene Werte):

```yaml
start: "2026-09-01T00:00:00+02:00"
end: "2026-10-27T10:15:00+01:00"
data_until: "2026-10-27T10:00:00+01:00"
estimated_until: "2026-10-20T15:00:00+02:00"
heating:
  heat_kwh: 440.7
  electricity_kwh: 110.8
  ratio: 3.98
dhw:
  heat_kwh: 240.6
  electricity_kwh: 87.6
  ratio: 2.75
heating_dhw:
  heat_kwh: 681.3
  electricity_kwh: 198.4
  standby_kwh: 32
  ratio: 2.96
cooling:
  heat_kwh: 21.5
  electricity_kwh: 6.2
  ratio: 3.47
months:
  - month: 2026-09
    heating:
      heat_kwh: 38.4
      electricity_kwh: 9.6
      ratio: 4
    dhw:
      heat_kwh: 121.7
      electricity_kwh: 44.1
      ratio: 2.76
    heating_dhw:
      heat_kwh: 160.1
      electricity_kwh: 53.7
      standby_kwh: 17.9
      ratio: 2.24
    cooling:
      heat_kwh: 21.5
      electricity_kwh: 6.2
      ratio: 3.47
  - month: 2026-10
    heating:
      heat_kwh: 402.3
      electricity_kwh: 101.2
      ratio: 3.98
    dhw:
      heat_kwh: 118.9
      electricity_kwh: 43.5
      ratio: 2.73
    heating_dhw:
      heat_kwh: 521.2
      electricity_kwh: 144.7
      standby_kwh: 14.1
      ratio: 3.28
    cooling:
      heat_kwh: 0
      electricity_kwh: 0
      ratio: null
```

- `heating`, `dhw`, `heating_dhw` und `cooling` erscheinen nur für eingerichtete Betriebsarten. `ratio` ist bei `cooling` die Leistungszahl (EER); `null` heißt unbekannt (keine Wärme oder unter dem Mindeststrom).
- `electricity_kwh` ist ohne Stillstand; bei `heating_dhw` geht `standby_kwh` in die Arbeitszahl ein.
- `degree_days` (gesamt und je Monat, nur mit Außentemperatur): Gradtage G20/15, Wärme fürs Heizen je Gradtag (`kwh_per_degree_day`, nur Heiztage ab 1 kWh, ab 10 K·d) und die gezählten Tage. Nur ganze Tage mit mindestens 20 Stundenwerten zählen.
- `data_until`: bis wann Stundenwerte vorlagen. `estimated_until`: bis wann aus den Zählern der Wärmepumpe gerechnet wurde (siehe unten); `null`, wenn der Zeitraum erst nach der Einrichtung beginnt.
- **Vor der Einrichtung** rechnet Wärmewacht aus der Langzeitstatistik deiner Zähler. Dort gibt es keinen Kompressorstatus. Deshalb gilt der Strom einer Betriebsart in einer Stunde ohne Wärme dieser Betriebsart als Stillstand. Stunden mit Lauf behalten ihre Minuten Stillstand als Lauf; die Arbeitszahl je Betriebsart fällt dort etwas niedriger aus.
- **Ab der ersten vollen Stunde nach der Einrichtung** nutzt der Bericht die Statistik der eigenen [Energie-Sensoren](#energie).

### AZ-Kennlinie

**Wärmewacht: AZ-Kennlinie** (`waermewacht.performance_curve`) rechnet die [Kennlinie](#kennlinie-und-heizlast) für einen beliebigen Zeitraum.

```yaml
action: waermewacht.performance_curve
data:
  config_entry: <Eintrag auswählen>
  start: "2025-07-01 00:00:00"
  end: "2026-07-01 00:00:00"
  scope: heating_dhw
```

| Feld | Vorgabe | Bedeutung |
| --- | --- | --- |
| `start` | Beginn der laufenden Saison | Saisons mit verschiedener Heizkurve nicht mischen. |
| `end` | jetzt | |
| `scope` | `heating` | `heating` (Heizen) oder `heating_dhw` (Heizen und Warmwasser, beides ohne Stillstand) |

Die Antwort enthält `start`, `end`, `scope` und `classes`: die Klassen wie im Attribut `current` des Sensors.

### Heizlast

**Wärmewacht: Heizlast** (`waermewacht.heat_load`) rechnet die [Energiesignatur](#kennlinie-und-heizlast) für einen beliebigen Zeitraum.

```yaml
action: waermewacht.heat_load
data:
  config_entry: <Eintrag auswählen>
  design_outdoor_temp: -12
```

| Feld | Vorgabe | Bedeutung |
| --- | --- | --- |
| `start` | Beginn der letzten vollständigen Saison (Gasheizung: vor 365 Tagen) | |
| `end` | Ende der letzten vollständigen Saison; mit `start`: jetzt | |
| `design_outdoor_temp` | Normaußentemperatur aus den Einstellungen | °C, für `measured_kw` und `standard_kw` |

Die Antwort enthält dieselben Werte wie die Attribute von „Heizlast je Kelvin“.

AZ-Kennlinie und Heizlast melden einen Fehler, wenn keine Außentemperatur zugeordnet ist oder der Recorder fehlt.

## Dashboard-Beispiele

Die Entity-IDs hängen vom Namen des Eintrags ab (hier die Vorgabe „Wärmepumpe“). Eine Karte fügst du so hinzu: *Dashboard bearbeiten → Karte hinzufügen → Manuell*.

### Statistik-Karte: Wärme und Strom je Monat

Eine Arbeitszahl je Monat liefert der [Bericht](#bericht). Wärme und Strom je Monat zeigt eine Statistik-Karte, der Stillstand als eigener Balken. Die Monate vor der Einrichtung stammen aus der Langzeitstatistik der Zähler:

<img src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/screenshots/monatsdiagramm.png" alt="Balkendiagramm Wärme und Strom je Monat für Heizen und Warmwasser, dazu der Stillstand" width="480">

```yaml
type: statistics-graph
title: Wärme und Strom je Monat
chart_type: bar
period: month
stat_types:
  - change
days_to_show: 365
entities:
  - entity: sensor.warmepumpe_warme_heizen
    name: Wärme Heizen
  - entity: sensor.warmepumpe_warme_warmwasser
    name: Wärme Warmwasser
  - entity: sensor.warmepumpe_strom_heizen
    name: Strom Heizen
  - entity: sensor.warmepumpe_strom_warmwasser
    name: Strom Warmwasser
  - entity: sensor.warmepumpe_strom_stillstand
    name: Stillstand
```

### AZ-Kennlinie und Energiesignatur

<img src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/screenshots/analyse.png" alt="AZ-Kennlinie Heizen über der Außentemperatur, Energiesignatur mit Heizlast-Gerade und Kennwerte wie Heizlast, Heizgrenze und Gradtage" width="720">

Beide Diagramme brauchen die HACS-Karte [apexcharts-card](https://github.com/RomRider/apexcharts-card). Sie kennt nur eine Zeitachse. Die Beispiele bilden deshalb die Außentemperatur von −15 bis 25 °C auf die 40 Stunden ab, die am Ende des heutigen Tages enden (1 K = 1 Stunde). Die Beschriftung der Achse rechnet die Zeit zurück in °C. Die Grenzen der y-Achse (`min`, `max`) passt du an deine Anlage an.

AZ-Kennlinie Heizen, vorige und laufende Saison:

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: "AZ-Kennlinie Heizen (x: Außentemperatur Tagesmittel)"
graph_span: 40h
span:
  end: day
now:
  show: false
apex_config:
  chart:
    height: 260
  xaxis:
    tickAmount: 8
    labels:
      formatter: "EVAL:(v, ts) => { const t = typeof ts === 'number' ? ts : Number(v); const e = new Date(); e.setHours(24, 0, 0, 0); return Math.round((t - e.getTime()) / 3600000 + 25) + ' °C'; }"
    tooltip:
      enabled: false
  yaxis:
    - min: 2
      max: 6
      tickAmount: 4
      decimalsInFloat: 1
      title:
        text: Arbeitszahl
  tooltip:
    x:
      formatter: "EVAL:(v) => { const e = new Date(); e.setHours(24, 0, 0, 0); return (Math.round(((v - e.getTime()) / 3600000 + 25) * 10) / 10) + ' °C'; }"
  markers:
    size: 5
  legend:
    show: true
grid_options:
  columns: full
  rows: 6
series:
  - entity: sensor.warmepumpe_az_kennlinie_heizen
    name: Vorige Saison
    color: "#2F6FB0"
    extend_to: false
    curve: straight
    show:
      legend_value: false
      in_header: false
    data_generator: |
      const e0 = new Date(); e0.setHours(24, 0, 0, 0);
      const x = (t) => e0.getTime() + (t - 25) * 3600000;
      return (entity.attributes.previous || []).filter(c => c.ratio !== null).map(c => [x((c.lower + c.upper) / 2), c.ratio]);
  - entity: sensor.warmepumpe_az_kennlinie_heizen
    name: Laufende Saison
    color: "#DE5E32"
    extend_to: false
    curve: straight
    show:
      legend_value: false
      in_header: false
    data_generator: |
      const e0 = new Date(); e0.setHours(24, 0, 0, 0);
      const x = (t) => e0.getTime() + (t - 25) * 3600000;
      return (entity.attributes.current || []).filter(c => c.ratio !== null).map(c => [x((c.lower + c.upper) / 2), c.ratio]);
```

Energiesignatur: die Wochen als Punkte und die Gerade von der Normaußentemperatur (ohne Einstellung −12 °C) bis zur Heizgrenze (sonst 15 °C):

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: "Energiesignatur (x: Außentemperatur Wochenmittel)"
graph_span: 40h
span:
  end: day
now:
  show: false
apex_config:
  chart:
    height: 260
  xaxis:
    tickAmount: 8
    labels:
      formatter: "EVAL:(v, ts) => { const t = typeof ts === 'number' ? ts : Number(v); const e = new Date(); e.setHours(24, 0, 0, 0); return Math.round((t - e.getTime()) / 3600000 + 25) + ' °C'; }"
    tooltip:
      enabled: false
  yaxis:
    - min: 0
      max: 4
      tickAmount: 4
      decimalsInFloat: 1
      title:
        text: Heizleistung kW
  tooltip:
    x:
      formatter: "EVAL:(v) => { const e = new Date(); e.setHours(24, 0, 0, 0); return (Math.round(((v - e.getTime()) / 3600000 + 25) * 10) / 10) + ' °C'; }"
  markers:
    size: [5, 0]
  legend:
    show: true
grid_options:
  columns: full
  rows: 6
series:
  - entity: sensor.warmepumpe_heizlast_je_kelvin
    name: Wochen
    color: "#2F6FB0"
    stroke_width: 0
    extend_to: false
    curve: straight
    show:
      legend_value: false
      in_header: false
    data_generator: |
      const e0 = new Date(); e0.setHours(24, 0, 0, 0);
      const x = (t) => e0.getTime() + (t - 25) * 3600000;
      return (entity.attributes.weeks || []).map(w => [x(w.mean_outdoor), w.power_kw]).sort((a, b) => a[0] - b[0]);
  - entity: sensor.warmepumpe_heizlast_je_kelvin
    name: Gerade
    color: "#DE5E32"
    stroke_width: 2
    extend_to: false
    curve: straight
    show:
      legend_value: false
      in_header: false
    data_generator: |
      const e0 = new Date(); e0.setHours(24, 0, 0, 0);
      const x = (t) => e0.getTime() + (t - 25) * 3600000;
      const a = entity.attributes;
      if (a.intercept_kw == null) return [];
      const lo = a.design_temp ?? -12, hi = a.heating_limit ?? 15;
      return [[x(lo), a.intercept_kw + a.slope_kw_per_k * lo], [x(hi), Math.max(0, a.intercept_kw + a.slope_kw_per_k * hi)]];
```

Im `data_generator` sind `start` und `end` schon vorbelegt. Das Tagesende heißt deshalb `e0` (im Formatter `e`).

## Bilanzgrenze und Grenzen der Aussage

- **Bilanzgrenze:** Eine Arbeitszahl gilt immer für die Zähler, aus denen sie stammt. Üblich sind die Grenzen nach SEPEMO: H1 Wärmepumpe bzw. Verdichter, H2 plus Ventilator bzw. Solepumpe, H3 plus Heizstab, H4 plus Umwälz- und Ladepumpen. Mit den Kompressor-Stromzählern von EMS-ESP entspricht Wärmewacht **etwa H1**, mit Heizstab **H3**. Umwälzpumpen, Regelung und Speicherladepumpen fehlen. Eine System-Arbeitszahl mit externem Stromzähler (wie bei [heatpumpmonitor.org](https://heatpumpmonitor.org/), H4) liegt deshalb niedriger.
- **Stillstand laut Wärmepumpe:** Bosch-Wärmepumpen buchen bei stehendem Kompressor gleichmäßig Strom in den Heizen-Zähler, beobachtet etwa 25 W, auch im Sommer. Der konstante Wert deutet auf einen Modellwert der Firmware, nicht auf eine Messung. Ob er stimmt, zeigt nur ein externer Zähler. Die Arbeitszahlen je Betriebsart hängen davon nicht ab; die Arbeitszahl Heizen + Warmwasser schon.
- **Ganzzahlige Zähler:** Nicht jedes Modell liefert Zähler mit 0,01 kWh. Bei ganzen kWh ist eine kurze Zeitspanne ungenau (1 kWh von 5 kWh sind 20 %). Das Attribut `reliable` ist erst `true`, wenn der Strom mindestens das 20-Fache der Zählerauflösung erreicht.
- **Abtauen:** Die Wärmezähler von Bosch ziehen die beim Abtauen entzogene Wärme ab (beobachtet an einer CS5800i/CS6800i); Wärmewacht bucht deshalb netto. Wie es die Zähler anderer Hersteller halten, ist nicht geklärt.
- **Rückblick:** Den Stillstand vor der Einrichtung schätzt Wärmewacht stundenweise (siehe [Bericht](#bericht)). In den Sensoren fehlt die angebrochene Stunde der Einrichtung: Die Langzeitstatistik hat für sie noch keinen Wert.
- **Lücken:** Lief Home Assistant nicht, bucht der erste Zählerwert danach den ganzen Zuwachs. Ob das Lauf oder Stillstand war, entscheidet die Wärme im selben Zeitraum.

## Fehlerbehebung

Wärmewacht meldet Probleme unter *Einstellungen → Reparaturen*. Das geschieht frühestens 10 Minuten nach dem Start, damit Entitäten nach einem Neustart Zeit haben.

- **Entität fehlt:** Eine zugeordnete Entität gibt es nicht mehr, z. B. nach Umbenennen. Unter *Wärmewacht → ⋮ → Neu konfigurieren* wieder auswählen.
- **Unbrauchbare Einheit:** Ein Energiezähler meldet nicht Wh, kWh oder MWh. Seine Werte werden nicht gezählt, bis die Einheit passt. Einheit in der Quelle prüfen oder unter *Neu konfigurieren* einen anderen Zähler wählen.
- **Zähler steht still:** Der Kompressor lief, aber ein Zähler der laufenden Betriebsart stieg nicht: 1 Stunde bei Zählern mit Nachkommastellen, 6 Stunden bei ganzen kWh oder Tageswerten. Meist liefert die Quelle keine Werte mehr, die Entität ist deaktiviert oder der falsche Zähler zugeordnet. Quelle prüfen, Entität aktivieren oder unter *Neu konfigurieren* den richtigen Zähler wählen.
- **Quelle nicht erreichbar:** Eine zugeordnete Entität ist seit mehr als 60 Minuten `unavailable`. Quelle prüfen (EMS-ESP, MQTT, Cloud).
- **Außentemperatur unbrauchbar:** Sie hat sich 48 Stunden nicht verändert oder lag gestern mehr als 3 Stunden außerhalb von −35 bis +45 °C. Davon hängen Kennlinie, Heizlast und der Gesundheits-Check ab. Fühler prüfen oder unter *Neu konfigurieren* eine andere Entität wählen.
- **Durchfluss unplausibel:** Gestern lag der gemessene Durchfluss beim Heizen um mehr als das Zehnfache über oder unter dem Wert, den Wärme und Spreizung ergeben (nach mindestens 1 Stunde Heizbetrieb, 1 kWh Wärme und 2 K Spreizung). Meist stimmt die Einheit nicht (etwa l/h als L/min gemeldet) oder es ist der falsche Sensor. Entität prüfen oder unter *Neu konfigurieren* eine andere wählen. Der Hinweis verschwindet nach einem Tag mit passendem Durchfluss.
- **Durchfluss 0 beim Heizen:** 15 Minuten Heizbetrieb mit Durchfluss 0. Meist liefert der Sensor keinen echten Wert. Entität prüfen oder unter *Neu konfigurieren* entfernen.
- **Vor- und Rücklauf vertauscht?** Gestern war der Vorlauf beim Heizen im Mittel mehr als 1 K kälter als der Rücklauf, nach mindestens einer Stunde Heizbetrieb. Meist sind die Entitäten oder die Fühler vertauscht; ein Vorlauffühler hinter einem Mischer kann es auch sein. Entitäten unter *Neu konfigurieren* tauschen oder die Fühler prüfen. Der Hinweis verschwindet nach einem Tag mit normaler Spreizung.
- **Betriebsart-Entität ohne Betriebsart:** Die zugeordnete Betriebsart meldet Werte, die bei diesem Gerät keine Betriebsart tragen (bei ViCare-E3-Reglern „ready“ / „not_ready“). Abtauungen und die Betriebsart der Läufe bleiben leer. Die Entität unter *Neu konfigurieren* entfernen.
- **Keine neuen Energiewerte:** Bei einer Quelle mit Stundenwerten (myVAILLANT) kamen seit mehr als 30 Stunden keine neuen Stundenwerte der Energie. In mypyllant die Option „Seconds between energy data updates“ auf 3600 bis 7200 Sekunden stellen oder einen ihrer Energie-Sensoren per Automation aktualisieren. Wärmewacht holt die fehlenden Stunden nach, sobald sie da sind.
- **Energie-Entitäten haben ihre Bedeutung geändert:** Eine Energie-Entität misst nicht mehr, wofür sie gewählt wurde. Bei myVAILLANT geschieht das, wenn die Cloud ihre Energiereihen neu ordnet, etwa nach dem Freischalten von Kühlen. Wärmewacht bucht nichts, bis die Entitäten unter *Neu konfigurieren* erneut gewählt sind.

Die Meldungen verschwinden von selbst, wenn das Problem behoben ist.

Weiteres:

- **Arbeitszahl bleibt unbekannt:** Im Zeitraum gab es keine Wärme oder weniger Strom als den Mindeststrom. Das ist im Sommer beim Heizen normal.
- **Keine Takte:** „Kompressor läuft“ ist nicht zugeordnet.
- **Kennlinie oder Heizlast leer:** Nach einem Neustart etwa 2 Minuten warten. Haben die Außentemperatur oder die Energie-Sensoren keine Langzeitstatistik (aus dem [Recorder](#recorder-schlank-halten) ausgeschlossen?), bleiben beide leer. Bei der Heizlast nennt das Attribut `reasons`, was fehlt.
- **Diagnose:** *Wärmewacht → Eintrag → ⋮ → Diagnosedaten herunterladen*. **Debug-Protokoll:** *Wärmewacht → ⋮ → Debug-Protokoll aktivieren*.

## Datenschutz

Wärmewacht rechnet lokal, liest nur die Entitäten, die du zuordnest, und fragt nichts im Netz ab. Gespeichert werden je Eintrag die gebuchte Energie, die Läufe und Warmwasser-Ladungen der letzten 40 Tage und das Tagebuch (bis zu 3 Jahre). Die Diagnose-Datei enthält Zuordnung, Einstellungen, die aktuellen Zustände der Quell-Entitäten (also Zählerstände) und Energiesummen, aber nicht den Namen des Eintrags. Unter `source` listet sie alle Entitäten der Quellgeräte mit Hersteller, Modell und Firmware; Seriennummern und Eintrags-IDs darin sind durch erfundene Werte gleicher Länge ersetzt, Gerätenamen und Bereiche fehlen. Prüfe sie, bevor du sie öffentlich teilst.

## Entfernen

1. *Einstellungen → Geräte & Dienste → Wärmewacht* → beim Eintrag ⋮ → *Löschen*. Die gespeicherten Werte und Reparaturmeldungen dieses Eintrags werden mit gelöscht.
2. Optional: HACS → Wärmewacht → ⋮ → *Entfernen*, dann Home Assistant neu starten.

Die Langzeitstatistik der gelöschten Sensoren bleibt in Home Assistant erhalten, bis du sie unter *Einstellungen → Werkzeuge → Statistik* (früher *Entwicklerwerkzeuge*) entfernst.

## Fehler melden

Bitte als [Issue](https://github.com/waermewacht/integration/issues), am besten mit Diagnose-Datei, dem Modell der Wärmepumpe und den Versionen von Home Assistant, Wärmewacht und gegebenenfalls EMS-ESP. Sicherheitslücken bitte vertraulich melden, siehe [SECURITY.md](SECURITY.md).

**Besitzt du eine Wärmepumpe mit Beta-Vorlage?** Besonders bei Viessmann (ViCare), Mitsubishi Ecodan (MELCloud) und Vaillant (myVAILLANT) beruhen einzelne Annahmen nur auf dem Quellcode der Integrationen. Eine Rückmeldung mit Diagnose-Datei nach ein paar Tagen Betrieb hilft, sie zu bestätigen: ob die Zahlen plausibel sind und wann die Tageswerte springen.

**Wärmepumpe ohne Vorlage?** Richte Wärmewacht manuell ein (mindestens Wärme und Strom Heizen und „Kompressor läuft“) und hänge die Diagnose-Datei an ein Issue. Unter `source` stehen dann alle Entitäten der Geräte dahinter, mit Plattform, unique_id, Einheit und Zustand. Daraus lässt sich eine Vorlage bauen.

## Verwandte Projekte

- [home-assistant-heat-pump-performance](https://github.com/vandecook/home-assistant-heat-pump-performance): Arbeitszahlen aus Wärme- und Stromzähler, herstellerneutral.
- [daikin_cycle_ml](https://github.com/elRadix/daikin_cycle_ml): umfangreiche Auswertung für Daikin Altherma mit ESPAltherma. Für Daikin die passende Wahl.
- [eedc – Energie Effizienz Data Center](https://github.com/supernova1963/eedc-homeassistant): Add-on für die Auswertung des ganzen Haushalts (PV, Speicher, E-Auto, Wärmepumpe) mit Wirtschaftlichkeit. Ergänzt sich mit Wärmewacht, das bei der Wärmepumpe tiefer geht.
- [heatpumpmonitor.org](https://heatpumpmonitor.org/): öffentlicher Vergleich vieler Anlagen. Wärmewacht nutzt dieselben Begriffe (SEPEMO-Bilanzgrenzen, Starts), damit sich Werte einordnen lassen.

## Lizenz

MIT
