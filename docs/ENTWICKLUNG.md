# Wärmewacht – Entwicklerdokumentation

Stand: 2026-10-27 (Projektstart). Vor größeren Arbeiten lesen. Maßgeblich ist der Code; dieses Dokument erklärt, was dort nicht steht.

## 1. Ziel und Umfang

Wärmewacht wertet aus vorhandenen Home-Assistant-Entitäten aus, wie effizient eine Wärmepumpe arbeitet und wie sie sich verhält. Sie ersetzt Eigenbau-Lösungen aus Utility Metern und Template-Sensoren. Nur lesen, nie steuern; keine Cloud, keine Abhängigkeiten.

**Stufe 1 (MVP)**

- Arbeitszahlen je Modus (Heizen, Warmwasser, Heizen + Warmwasser) und Leistungszahl Kühlen, je Zeitraum (heute, gestern, Monat, Saison, gesamt). Saisonbeginn beim Einrichten aus der Langzeitstatistik.
- Bereinigte Wärme- und Strom-Sensoren je Modus (Langzeitstatistik), Stillstand als eigener Sensor, Aktion „Bericht“ für beliebige Zeiträume.
- Takte: Starts (heute, gestern, gesamt), Laufzeit pro Start (heute, 7 Tage, Monat), Kurzläufe, kürzeste Pause, Kompressor-Laufzeit, Binärsensor „auffällig taktend“.
- Diagnose: Heizstab-Anteil, Abtauungen (Anzahl, Dauer), Spreizung und mittlere Vorlauftemperatur bei laufendem Kompressor im Heizbetrieb (zeitgewichtet; Warmwasser später).

**Stufe 2:** Arbeitszahl über Außentemperatur (Klassen, Aktion mit Antwortdaten für Diagramme), Gradtage und witterungsbereinigte Wärme, Wärmekosten (fester Preis oder Preissensor), Vergleich mit Gaskessel (Kosten, CO₂), PV-Anteil als Näherung.

**Stufe 3:** Heizlast-Schätzung (Energiesignatur), Einordnung gegen Feldtests, Warmwasser je Ladung und Legionellenschaltungen.

**Fahrplan:** Vorlage EMS-ESP komplett → Parallelbetrieb mit dem Eigenbau des Inhabers → Vorlage Bosch HomeCom (Gegenprobe an derselben Anlage) → erste öffentliche Version → Stufe 2, Stufe 3. Vorstellung im EMS-ESP-Forum/Discord, simon42 und HA Community (postet der Inhaber).

## 2. Abgrenzung (geprüft 2026-10-27)

| Projekt | Stand | Warum keine Lösung |
|---|---|---|
| [vandecook/home-assistant-heat-pump-performance](https://github.com/vandecook/home-assistant-heat-pump-performance) | angelegt 2026-10-15, alle Commits an einem Tag, keine Releases, keine Tests, 1 Stern | Nur Gesamt-AZ aus Zählerdeltas; Modus-Flags gespeichert, aber ungenutzt; kein Kühlen, keine Takte, keine Diagnose; Periodenwechsel nur bei Zustandsänderung; `async_save()` bei jeder Änderung. Entscheidung: nicht anfragen, im README nennen. |
| [elRadix/daikin_cycle_ml](https://github.com/elRadix/daikin_cycle_ml) | HACS-Standardliste, sehr aktiv | Fast voller Funktionsumfang, aber **nur Daikin Altherma mit ESPAltherma**. Im README als Daikin-Alternative nennen. |
| [st03psn/heat-pump-hero](https://github.com/st03psn/heat-pump-hero) | v0.9.0-rc6, keine Releases | Auf Panasonic/HeishaMon ausgelegt, Utility Meter und 23 Automationen |
| [VitisEK/cop-scop-card](https://github.com/VitisEK/cop-scop-card) | HACS-Standardliste (Karte) | Nur Anzeige aus Langzeitstatistik, keine Sensoren, keine Takte |
| [VitisEK/nibe_energy_conversion](https://github.com/VitisEK/nibe_energy_conversion) | – | Nur NIBE, nur letzte Stunde |
| [pegaverzum/hvac_cop_advisor](https://github.com/pegaverzum/hvac_cop_advisor) | – | COP modelliert aus Nennwerten, nicht gemessen |
| HA Core | bis 2026.10 | Keine Arbeitszahl. [Architektur #1522](https://github.com/home-assistant/architecture/discussions/1522) („heat“ als Energiequelle, 2026-10-16) klammert COP ausdrücklich aus; [Feature Request #2917](https://github.com/orgs/home-assistant/discussions/2917) unbeantwortet. |
| [heatpumpmonitor.org](https://heatpumpmonitor.org/about) | extern | Datenupload nötig. Definitionen (SEPEMO H1–H4, Starts, „running COP“) übernehmen, damit Werte vergleichbar sind. Export dorthin ist ein späterer Ausbau. |

Name: keine Treffer für „Wärmewacht“/`waermewacht` auf GitHub, PyPI, HACS, im Web; Domains laut Index frei. **DPMAregister von Hand prüfen** (nicht automatisierbar).

## 3. Fachregeln (keine Fachdiagnose)

### Begriffe und Bilanzgrenzen

- **SEPEMO-Grenzen** (Zottl/Nordman/Miara 2011, [System Boundaries for SPF-Calculation](https://etkhpcorderapi.extweb.sp.se/api/file/709)), Wärme jeweils Heizen + Warmwasser: **H1** Wärmepumpe/Verdichter; **H2** + Ventilator bzw. Solepumpe; **H3** + Heizstab (Grenze für den Vergleich mit Öl/Gas); **H4** + Umwälz-/Ladepumpen auf der Gebäudeseite. heatpumpmonitor.org weist SEPEMO H4 aus.
- **Fraunhofer ISE** ([WP-QS-Schlussbericht, 25.11.2025](https://www.ise.fraunhofer.de/content/dam/ise/de/documents/projekte/WP-QS_Schlussbericht.pdf), Tab. 5, S. 67): JAZ 3 (Erzeugerarbeitszahl, ≈ H3, Hauptkennzahl, Abtauwärme abgezogen), JAZ 5 (Systemarbeitszahl nach Speicher, im Mittel ~15 % unter JAZ 3). **Teil-JAZ Heizung/Warmwasser ohne Stillstandsverbrauch** (Regelung, Kurbelwannenheizung) – der geht nur in die Gesamt-JAZ ein (Kap. 5.2, S. 66–69). Wärmewacht übernimmt das.
- „JAZ“ darf Heizen + Warmwasser kombinieren (SEPEMO, Fraunhofer, [VDI 4650 Blatt 1](https://vdi.de/en/home/vdi-standards/details/vdi-4650-blatt-1-calculation-of-the-seasonal-coefficient-of-performance-of-heat-pumps-electric-heat-pumps-for-space-heating-and-domestic-hot-water)). Getrennt: „Arbeitszahl Heizen“, „Arbeitszahl Warmwasser“.
- **Kühlen** wird mit EER bewertet und nie in eine JAZ eingerechnet (Fraunhofer rechnet es heraus, WP-QS S. 69).

### Regeln der Berechnung

1. Arbeitszahl eines Zeitraums = Σ Wärme / Σ Strom, nie Mittel von Tageswerten.
2. Keine Wärme oder Strom unter Mindestmenge (Vorgabe 0,5 kWh) → `unknown`, nie 0.
3. Heizstab gehört zum Strom des jeweiligen Modus (H3); optional zusätzlich ohne Heizstab.
4. Stillstand (Strom bei stehendem Kompressor) getrennt buchen: nicht in Arbeitszahlen je Modus, wohl in der Gesamt-JAZ.
5. Abtauung: dem Heizsystem entzogene Wärme abziehen, nicht abschneiden (Fraunhofer S. 68; OEM: ~0,1 SPF/Jahr, [EoH-Analyse](https://docs.openenergymonitor.org/heatpumpmonitor/eoh.html)). Ob die Bosch-Zähler das schon tun, ist offen (Abschnitt 8).
6. Zähler: echte Resets erkennen (neue Basis, nichts buchen); kleine Rücksprünge (an einer Anlage beobachtet: −0,02 kWh) glätten, nicht als Reset werten – sonst wird doppelt gebucht.
7. `unknown`/`unavailable` nie als 0 lesen.

### Vergleichswerte Fraunhofer ISE (WP-QS, Auswertejahr 2024)

- Luft/Wasser JAZ 3: Mittel 3,4 (2,6–4,9, Median 3,3, n = 49); Heizen 3,9 (n = 25), Warmwasser 2,8 (n = 18); Wärmeanteil Warmwasser 19 %. Erdreich: 4,3 (3,6–5,4).
- Heizstab-Anteil im Mittel ~1,3 %; Ausreißer 17 %/21 % waren Defekte.
- Verdichterstarts (51 Luft/Wasser): 540–15.820 pro Jahr; 90 % unter 5.500 (~15/Tag), ein Drittel ≤ 2.000. Stopps unter 30 s nicht sicher erkennbar. Leistung bei A-7/W35 im Mittel ~50 % über der Heizlast.

### Weitere Feldwerte (Recherche 2026-10-27)

- **Fraunhofer ISE, „WPsmart im Bestand“, Abschlussbericht 2020** (primär gelesen): 29 Luft/Wasser für Heizen und Warmwasser, Juli 2018 bis Juni 2019, JAZ im Mittel 3,1 (2,5–3,8 ohne zwei Ausreißer); mittlere Heizkreistemperatur 36,9 °C, mittlere Spreizung 6,8 K (3,2–9,8 K, Gruppe nur Heizen); Wärme zu 85 % Heizen, 15 % Warmwasser. Bilanzgrenze 2/3 (ohne Umwälzpumpen, Abtauwärme als Aufwand). [Bericht](https://wp-monitoring.ise.fraunhofer.de/wpqs-im-bestand/download/Berichte/BMWi-03ET1272A-WPsmart_im_Bestand-Schlussbericht.pdf)
- **Fraunhofer ISE, Pressemitteilung 2025** zu WP-QS (primär gelesen): 77 Anlagen, Messjahr 2024, Luft/Wasser 3,4 (2,6–4,9), Heizstab 1,3 % (milder Zeitraum), keine Abhängigkeit vom Baujahr, viele Anlagen überdimensioniert, teils sehr häufiges Takten. [PDF](https://www.ise.fraunhofer.de/content/dam/ise/de/documents/presseinformationen/2025/3025_ISE_PI_Waermepumpen-heizen-auch-im-Altbau-klimafreundlich.pdf)
- **heatpumpmonitor.org:** 3,86 für 170 Luft-Anlagen, Bilanzgrenze H4 (mit Umwälzpumpen), MID-Zähler, 1.11.2024–1.11.2025; ob Mittel oder Median, sagt die Seite nicht. Wegen H4 nicht direkt vergleichbar. [Doku](https://docs.openenergymonitor.org/heatpumpmonitor/introduction.html)
- **UK Electrification of Heat:** Luft-WP H4 Mittel 2,81 (n = 428), Median 2,80 (n = 291, Zwischenbericht) – nur sekundär gelesen.
- **Bosch-Datenblatt:** SCOP AW 5 OR-S laut Sekundärquelle 4,57 (35 °C) bzw. 3,50 (55 °C), mittleres Klima – an EPREL prüfen, bevor es irgendwo steht.
- **Takt-Grenzwerte** aus Blogs und Foren (3–8 Starts/h, Mindestlaufzeit 5–20 min) sind nicht primär belegt; es gelten die Herstellerwerte im Abschnitt „Takten“.

### Warmwasser und Legionellen

- DVGW W 551 (2004): mindestens 60 °C am Austritt des Trinkwassererwärmers, Pflicht bei Großanlagen, empfohlen bei Kleinanlagen. `charges.py` erkennt eine thermische Desinfektion an ≥ 60 °C (einstellbar, weil der Speicherfühler nicht der Austritt ist). Dass Desinfektionen oft mit Heizstab laufen, ist eine Beobachtung ohne Quelle.

### Takten

- Verdichterhersteller: höchstens 6 Starts/h (RIES), 6–12 (BITZER), 10 (Copeland) – zitiert WP-QS S. 98. VDI 4645 ohne Vorgaben. Fraunhofer: Zyklen von 2–3 min vermeiden, unter ~10 min gesondert ausweisen (S. 204–205). Dimplex: Mindestlaufzeit ~6 min ([Projektierungshandbuch 03/2023](https://www.dimplex.co.uk/sites/g/files/emiian551/files/2024-01/20230313_Projektierungshandbuch_de.pdf), S. 317). Werte von Bosch/Buderus nicht gefunden.
- **Vorgaben** (einstellbar): Lauf < 10 min = kurz, < 6 min = kritisch, > 3 Starts/h = auffällig. Fest: auffällig auch ab 3 kritischen Läufen in 24 h (`CRITICAL_RUNS_PER_DAY`). Hochrechnung > 5.500 Starts/Jahr = obere 10 % des Fraunhofer-Felds – Orientierung, noch nicht umgesetzt.
- Ein Start = Kompressor aus → an (heatpumpmonitor: Leistung über Startschwelle). Laufzeit pro Start zählt Läufe des Kompressors, nicht Modus-Abschnitte.

### Emissionsfaktoren (Stufe 2)

| Faktor | Wert | Quelle |
|---|---|---|
| Strommix direkt 2025 (geschätzt) | 344 g CO₂/kWh | [UBA Climate Change 16/2026](https://www.umweltbundesamt.de/system/files/medien/11850/publikationen/2026-03/16_2026_CC.pdf), Tab. 1/2 |
| Strommix THG mit Vorketten 2025 | 406 g CO₂-Äq/kWh | ebenda |
| Erdgas GEG Anlage 9 | 240 g CO₂-Äq/kWh | [GEG Anlage 9](https://www.gesetze-im-internet.de/geg/anlage_9.html) (Bezug Heizwert und Vorketten nur geschlossen, nicht belegt) |
| Erdgas direkt | 201 g CO₂/kWh (Hi) | [BAFA Infoblatt CO₂-Faktoren 3.4](https://www.bafa.de/SharedDocs/Downloads/DE/Energie/eew_infoblatt_co2_faktoren_2025.pdf?__blob=publicationFile&v=4), UBA CC 28/2022 |

- Paarweise nach gleicher Methodik: **Vorgabe mit Vorketten 406 / 240**, umschaltbar auf direkt 344 / 201. Nie mischen.
- Gas wird in kWh nach **Brennwert (Hs)** abgerechnet (DVGW G 685). Umrechnung Hs → Hi 0,906 (BAFA). CO₂ = kWh_Hs × 0,906 × Faktor_Hi.
- Kessel: Jahresnutzungsgrad Brennwertkessel im Feld 86,6 % (Hs) = 96,4 % (Hi) (Jagnow/Wolff, DBU 2004, 60 Kessel; auch bei Fraunhofer). **Vorgabe η_Hs = 0,87.** Gaskosten = Wärme / η_Hs × Preis (€/kWh_Hs).

### Normaußentemperatur, Gradtage, Heizlast (Stufe 2/3)

- Normaußentemperatur nach DIN/TS 12831-1:2020-04 je **Postleitzahl**, Nachschlagen über die [BWP-Klimakarte](https://www.waermepumpe.de/werkzeuge/klimakarte/). Stuttgart schwankt um ~2 K (70173: −9,3 °C; 70565: −11,3 °C; 70499: −11,2 °C) → Eingabe mit Verweis, kein fester Wert.
- Gradtagzahl **G20/15 nach VDI 3807 Blatt 1**: je Tag 20 °C − Tagesmittel, nur an Tagen mit Tagesmittel < 15 °C ([DWD-Beschreibung](https://opendata.dwd.de/climate_environment/CDC/derived_germany/techn/daily/heating_degreedays/hdd_3807/recent/BESCHREIBUNG_derivgermany_techn_daily_heating_degreedays_hdd_3807_recent_de.pdf)). Basiswerte einstellbar. Witterungsbereinigung nur auf den Heizanteil.
- Heizlast über Energiesignatur (EAV-Verfahren, wie Fraunhofer S. 93–94): Wärmeleistung (Wochen- statt Tagesmittel) über Außentemperatur, lineare Regression, Steigung = Wärmeverlust in W/K. Warmwasser abtrennen, nur kalte Tage (< ~10–12 °C), Tage mit Lücken/Kühlen/Störung ausschließen; normgerecht ohne Gewinne (Gerade auf Heizgrenze 20 °C verschieben, [EAV-Mustergutachten](https://www.energiesparkonto.de/gfx/esk/dokumente/Mustergutachten_EAV_de.pdf)). Erst ab ausreichend Daten (mindestens eine Heizperiode mit Frosttagen) anzeigen.

## 4. Datenquellen – verifizierte Eigenheiten

### EMS-ESP (Bosch/Buderus, MQTT, lokal)

Quellcode gelesen (EMS-ESP32 `dev` 3.9.0-dev.20 und `main` 3.8.6, [boiler.cpp](https://github.com/emsesp/EMS-ESP32/blob/dev/src/devices/boiler.cpp)) und an einer CS5800i/CS6800i mit K40RF beobachtet (2026-10-27).

**Energiezähler** (Gerät `boiler`, nur wenn EMS-ESP eine Wärmepumpe erkennt; alle `energy`, kWh, `total_increasing`):

| Größe | 0,01 kWh (Telegramm 0x4AE/0x4AF, Abruf jede Minute) | ganze kWh (0x494/0x495, Broadcast) |
|---|---|---|
| Wärme gesamt / Heizen / Warmwasser / Kühlen | `nrgtotal`, `nrgheat`, `dhw.nrg`, `nrgcool` | `nrgsupptotal`, `nrgsuppheating`, `dhw.nrgsupp`, `nrgsuppcooling` |
| Strom gesamt / Kompressor / Heizstab | `metertotal`, `metercomp`, `metereheat` | `nrgconstotal`, `nrgconscomptotal`, `auxelecheatnrgconstotal` |
| Strom Kompressor Heizen / Warmwasser / Kühlen | `meterheat`, `dhw.meter`, `metercool` | `nrgconscompheating`, `dhw.nrgconscomp`, `nrgconscompcooling` |
| Strom Heizstab Heizen / Warmwasser | – (Offsets 28/36 in 0x4AF nicht ausgewertet) | `auxelecheatnrgconsheating`, `dhw.auxelecheatnrgcons` |

- **`meter*` ist Strom, `nrg*` ist Wärme** (`meterheat` = Kompressorstrom im Heizbetrieb). Belege: [#1349](https://github.com/emsesp/EMS-ESP32/issues/1349), [#1350](https://github.com/emsesp/EMS-ESP32/issues/1350). Die Modus-Stromzähler sind **ohne Heizstab**: `metertotal` = `metercomp` + `metereheat`, `metercomp` = Summe der Modus-Zähler.
- Heizstab je Modus nur ganzzahlig; für kleine Mengen (Legionellenschaltung) ungenau.
- 0,01 kWh für Kühlen seit 3.7.0-dev.30 ([#1940](https://github.com/emsesp/EMS-ESP32/issues/1940)). Nicht jedes Modell liefert 0x4AE/0x4AF (CS7800iLW-Dump nur ganzzahlige Zähler, [#3286](https://github.com/emsesp/EMS-ESP32/issues/3286)) → Vorlage muss auf die ganzzahligen zurückfallen und dann die Rundungsunsicherheit kurzer Zeiträume ausweisen.
- **Stillstand im Heizen-Zähler:** Bei stehendem Kompressor steigt `meterheat` gleichmäßig (0,01 kWh etwa alle 24 min ≈ 25 W), auch im Sommer zwischen Kühl- und Warmwasserläufen; die Wärme bleibt bei 0. `hpcurrpower` zeigt im Stillstand konstant 25 W, unabhängig von der Außentemperatur. Die HomeCom-Tageswerte steigen im Stillstand genauso. Auch [#1348](https://github.com/emsesp/EMS-ESP32/issues/1348#issuecomment-1783767582) beschreibt Anstieg im Stillstand („Elektronik“). Folge ohne Abtrennung: Heiz-Arbeitszahl im Sommer 0, über das Jahr grob 10 % mehr Heizstrom.
- **`hppower` und `hpcurrpower`:** `hppower` (0x48D, 0,1 kW) ist an CS5800i/6800i im Heizen die **Wärmeleistung** (passt zum Anstieg von `nrgheat`; laut [#2957](https://github.com/emsesp/EMS-ESP32/issues/2957)/[#3140](https://github.com/emsesp/EMS-ESP32/issues/3140) modellabhängig, beim Kühlen 0). `hpcurrpower` (0x4AA, W) ist die **geschätzte elektrische** Aufnahme ([#1717](https://github.com/emsesp/EMS-ESP32/issues/1717): ein Nutzer 300–400 W über seinem Netzzähler).
- **`hpactivity`** (0x48D Byte 7): 0 aus, 1 Heizen, 2 Kühlen, 3 Warmwasser, 4 Pool, 5 Pool heizen, **6 Abtauen**, 7 Kompressoralarm ([locale_common.h](https://github.com/emsesp/EMS-ESP32/blob/dev/src/core/locale_common.h)). **Texte in der EMS-ESP-Sprache** (z. B. „Heizen“, „aus“, „Abtauen“); nur mit „Enum format = index“ Zahlen.
- **Abtauen:** Kompressor bleibt an, kein neuer Start, `hppower` geht auf 0; beobachtet 3–4 min. `hp4way` (VR4) ist an bei Kühlen **und** Abtauen und wird nur gesetzt, wenn die Kühlart „4-Wege-Ventil“ konfiguriert ist ([#2844](https://github.com/emsesp/EMS-ESP32/issues/2844)); in 3.8.0/3.8.1 fehlte es. → Abtauen über `hpactivity`, nicht über das Ventil. Es gibt `binary_sensor.boiler_hp4way` und zusätzlich `sensor.boiler_hp4way` (Text).
- **Ein Lauf kann den Modus wechseln:** Heizen → Warmwasser ohne Kompressorstopp beobachtet. Die Startzähler je Modus zählen nur den Modus beim Start (`dhw.startshp` bleibt dann stehen). Laufzeit pro Start je Modus aus Zählern ist deshalb verzerrt; robust sind Gesamtlaufzeit/Gesamtstarts und Läufe aus `hpcompon`.
- Starts und Laufzeiten aus 0x495: `totalcompstarts`, `heatingstarts` („Heizungsregelungstarts“ – ob Kompressor- oder Reglerstarts, ist nicht belegt), `dhw.startshp`, `coolingstarts`; Laufzeiten in **min** (`uptimecompheating`, `dhw.uptimecomp`, `uptimecompcooling`, `uptimecontrol` = Summe). `dhw.starts`, `burnstarts`, `ubauptime` sind andere Zähler.
- Startzähler steigen etwa 50 s nach `hpcompon` → an. Telegramme mit Abruf kommen jede Minute (`EMS_FETCH_FREQUENCY = 60000`), MQTT-Senden standardmäßig alle 10 s.
- Temperaturen (0x48F): `hptc0` Rücklauf, `hptc1` Vorlauf, `hptc3` Kondensator; `pc0flow` in l/h; `curflowtemp` aus 0xE4.
- **Neustart von HA oder EMS-ESP:** `unavailable` → `unknown` → Wert, auch mitten in einem Lauf oder einer Abtauung. Nach einem EMS-ESP-Neustart dauert es Minuten, bis alle Telegramme da sind.
- **Namen:** seit 3.7.0 `dhw.*` statt `ww*`. Fünf Formate für Entity-IDs (`mqtt.cpp` `entityFormat`): Standard „single instance, short name“ → `sensor.boiler_nrgheat`, `sensor.boiler_dhw_nrg`; „multiple instances“ → Präfix der MQTT-Basis (`sensor.ems_esp_boiler_…`); „long name (v3.4)“ → `sensor.boiler_energy_heating`; Kompatibilitätsformate 3/4 → `boiler_nrgww`, `boiler_wwmeter`. Beim Inhaber existieren alte und neue Namen nebeneinander (`boiler_nrgww` und `boiler_dhw_nrg`). **Erkennung über Plattform `mqtt` + `unique_id`** (= z. B. `boiler_nrgheat`), Gerät mit Kennung `("mqtt", "ems-esp-boiler")`.
- **Fallen:** Gasthermen haben dieselben Kurznamen (`nrgheat`, `meterheat`), dort berechnet bzw. andere Bedeutung → nur bei Wärmepumpen-Gerät anbieten. Gerät `heatpump` (HM200, HP Module) hat dieselben Kurznamen, `hppower` dort in W. K40RF erscheint zusätzlich als `gateway`/`connect` mit eigener `outdoortemp`.
- Modelle: Produkt 8 „CS5800i, CS6800i, WLW176i, WLW186i“, Produkt 172 „Enviline, Compress 6000AW, Hybrid 3000-7000iAW, SupraEco/Geo 5xx, WLW196i/WSW196i“ ([device_library.h](https://github.com/emsesp/EMS-ESP32/blob/dev/src/core/device_library.h)).

### Bosch HomeCom (`bosch_homecom`, HACS, Cloud und lokal)

Repo [serbanb11/bosch-homecom-hass](https://github.com/serbanb11/bosch-homecom-hass) (geprüft v1.5.2, Commit `50d4ac8`; v1.6.0 ohne Änderung an Energie-/Lokal-Code), Bibliothek `homecom_alt` 1.9, lokale API laut [api-docs `k-40-rf.yaml`](https://github.com/bosch-home-comfort/api-docs). Beobachtet an derselben Anlage (2026-10-27), Option „Datenquelle“ (lokal und Cloud), Takt 60 s.

- Gerät `("bosch_homecom", "<Gateway-ID>")`, `unique_id` `<Gateway-ID>-<schlüssel>` – am **ersten** „-“ trennen (Schlüssel wie `dhw1-delta_t` enthalten selbst „-“).
- **Energie = Summe der heutigen Stunden-Buckets der Cloud** (`/recordings/heatSources/emon/{total|ch|dhw|cooling}/{compressor|eheater|outputProduced}?interval=<Datum in HA-Zeitzone>`), obwohl „gesamt“ im Namen; `energy`, kWh, `total_increasing`. Abruf höchstens stündlich, die Phase wandert und springt bei jedem Neustart; Verzug 0–2 h, angefangene Stunden teils enthalten. Rücksprung auf 0 beim ersten Abruf nach Mitternacht. **Die letzten 1–2 Stunden eines Tages gehen verloren** (beobachtet −0,04 … −0,52 kWh je Tag). Zeitumstellung 25.10.: Rücksprung mitten am Tag (doppelte Stunde überschrieben). Modus-Entitäten (Strom Kompressor/Heizstab, Wärme erzeugt je Heizung/Warmwasser/Kühlung) standardmäßig deaktiviert (Designentscheidung, Kommentar `sensor.py`); sie stimmen bis auf den Verzug genau mit EMS-ESP überein.
- **Lebenszeit-Summen** gibt es nur als Attribute am Sensor „Wärmequelle“ (`totalConsumptionCompressor`, `…OutputProduced`, `…Eheater`, 0,01 kWh, minütlich) – gleich EMS-ESP-Summe aller Modi, nicht je Modus.
- „Kompressorleistung“ (`local_compressor_power`, lokal) = EMS-ESP `hpcurrpower` (Stillstand 25 W). Kompressor an: `local_compressor_speed` oder `compressor_modulation` (Cloud) > 0, ~1 min Verzug. Starts gesamt mit Attributen `ch`/`dhw`/`cooling` (Summe = gesamt → `heatingstarts` zählt Kompressorstarts). Laufzeit je Modus lokal (s), steigt im aktiven Modus. Vorlauf = EMS-ESP `curflowtemp` (Systemvorlauf, nicht `hptc1`), Rücklauf = `hptc0`.
- **Keine Betriebsart:** „Wärmebedarf“ zeigt `frost` während Heiz- und Warmwasserläufen und `ch` bei stehendem Kompressor. Abtauen nur heuristisch: „Wärmebedarf = idle bei laufendem Kompressor“ (4 von 4 in 10 Tagen, kleine Stichprobe). `homecom_alt` fragt lokal `refrigerant/status` (laut Spezifikation u. a. `defrost`) und lokale emon-Zähler ab, legt dafür aber keine Entitäten an.
- **Fehler upstream:** `local_pump_volume_flow` meldet „L/min“, liefert l/h (= `pc0flow`; Spezifikation l/h).
- **Vorlage gebaut (2026-10-27, `profiles.BOSCH_HOMECOM`):**
  - Erkennung über `<id>-<schlüssel>`. Die Einrichtung nennt deaktivierte Entitäten, die eine Vorlage bräuchte.
  - Tageszähler (`Counter.day_tz`): Ein neuer Tag beginnt nur beim Datumswechsel in der HA-Zeitzone. Dann zählt der erste Wert des Tages ganz, auch wenn er über dem letzten des Vortags liegt. Ein Rücksprung am selben Tag ist ein Dip. Ein unveränderter Wert, etwa bei einem Attribut-Update nach Mitternacht, lässt den Tag stehen.
  - Kompressor aus Drehzahl > 0 (`parse_compressor`), Verzug gegenüber EMS-ESP 20–60 s.
  - Stillstand je Abruf (`Template.day_values`): Strom wartet bis zum nächsten Minutentakt, mindestens 10 s, auf die Wärme desselben Abrufs (bis 30 s davor). Am 27.10. kamen Strom und Wärme in derselben Sekunde.
  - Spreizung und Vorlauf brauchen die Betriebsart.
  - Noch nicht: den Tagesrest aus den Lebenszeit-Summen am Sensor „Wärmequelle“ nachholen und die Abtau-Heuristik.
  - **Korrekturen nach unabhängiger Durchsicht (0.1.0b4):**
    - Beim Start werden Zählerwerte mit `state.last_updated` datiert statt mit „jetzt“. Ein Abruf von gestern zählt nach einem Neustart über Mitternacht nicht als heutiger Wert.
    - Die Plausibilitätsprüfung für Tageswerte misst gegen die Zeit seit Mitternacht statt gegen den Abstand zweier Abrufe, denn ein Abruf kann nach einem Neustart mehrere Stunden auf einmal bringen.
    - Ein verworfener Wert lässt die Basis stehen.
    - Wartender Strom wird vor einem Periodenwechsel gebucht (`PeriodMarks.due`) und mit `_heat_at` gespeichert.
- **Kein CO₂-Vergleich in der Oberfläche** (Wunsch des Inhabers 2026-10-27). Er hinge zu stark an Annahmen: Durchschnitts- oder Stundenmix, Vorketten, PV-Eigenverbrauch, Batterie, Ökostrom. `costs.py` rechnet CO₂ weiter mit (Faktoren mit Quellen), es wird aber nicht angezeigt.
- **Kühlsaison = Kalenderjahr** (`Period.YEAR`, Wunsch des Inhabers 2026-10-27). Bei einer Heizsaison ab Juli fiele das Kühlen von März bis Juni in die Vorsaison. Beim Update aus dem Bestand: `_async_rebase(Period.YEAR)`.
- **Statistik vor der Einrichtung** (`async_import_history`, einmal je Eintrag):
  - Schreibt Stunden vor der ersten eigenen Statistikzeile mit `async_import_statistics` (Quelle `recorder`).
  - Die Summen enden bei 0, wo HA die Summe eines neuen Sensors beginnt. Keine aufgezeichnete Zeile ändert sich, und es braucht keine Summenkorrektur.
  - Ein Sensor mit Zeilen vor der Einrichtung bleibt unberührt.
- Daneben gibt es die Community-Integration „Bosch/Buderus Heating (PointT)“ ([Forum](https://community.home-assistant.io/t/custom-integration-bosch-buderus-heating-pointt-cloud-integration-for-mybuderus-and-homecom-easy-systems/1022332)) – noch nicht betrachtet.

### Andere Hersteller (Quellcode-Recherche 2026-10-27 an festen Commits, nicht an echten Anlagen – erst mit Fixture)

| Integration | Daten für Wärmewacht | Erkennung (`unique_id`) |
|---|---|---|
| **Luxtronik** (HACS `luxtronik2`, lokal, 60 s) | Wärme und Strom je Modus fortlaufend (0,01–0,1 kWh), Heizstab nur gesamt, Kompressor binär, `status` mit `defrost`, Starts (standardmäßig aus), Vor-/Rücklauf, Durchfluss | ursprüngliche Entity-ID `sensor.<prefix>_<key>`, Präfix je Eintrag verschieden → Endung `_<key>` |
| **Panasonic HeishaMon** (`aquarea`, MQTT) | legt selbst kWh-Zähler aus den Leistungen an (`TOPxx_integration`, Riemann) für Wärme/Strom je Modus; Kompressor nur über Frequenz, Abtauen nur als Switch, Heizstab ohne Energie | `<entry_id>-<TOPxx>` |
| **Vaillant myVAILLANT** (HACS `mypyllant`, Cloud) | Wärme/Strom je Modus als Tageswert aus abgeschlossenen Stunden (0,1 kWh); Energie standardmäßig **nur einmal beim Laden** abgerufen; Stunde 23–24 Uhr nur in eigenen externen Statistiken; Energiemanager-Status ohne Abtauen; kein Kompressorsignal | Positionen in API-Listen; Wärme/Strom nur am englischen Namen erkennbar |
| **Nibe** (Core `nibe_heatpump`, lokal) | gut, aber Register je Modell verschieden, alle Entitäten standardmäßig deaktiviert | `<entry_id>-<Register>` |
| **Viessmann ViCare** (Core) | **keine Wärme** in HA (API hätte sie, PyViCare-PR #836 offen). Zwei Generationen, keine hat beides: E3 (Vitocal 150-A bis 252-A) Strom je Modus als Tageswert, Kompressor, Starts, Phase ohne Modus (`ready`/`not_ready`); Vitotronic Phase mit `defrost`, WW-Ladung, Starts, keine Energie | `<gateway>_<gerät>-<key>[-<komponente>]` |
| **Daikin Onecta** (HACS, Cloud) | Altherma: nur Strom-Tageswerte in ganzen kWh, Wärme nur Monat/Jahr und nur bei SkyAir belegt; kein Kompressor/Abtauen | `<uuid>_<embedded>_…` |

Rangfolge nach Bosch: **Luxtronik** (passt fast 1:1, nur Erkennung über Endung), dann HeishaMon, dann Vaillant (braucht Buchen aus Statistiken – hilft auch HomeCom). ViCare später als „Takte ohne Energie“, Daikin Onecta nicht (README: auf ESPAltherma/daikin_cycle_ml verweisen).

**Nachtrag 2026-10-27 (Subagenten, Quellcode an festen Commits):**

- **Vorlagen gebaut** (noch nicht eingebunden, „experimentell“): Luxtronik (`profiles_luxtronik.py`; Strom je Modus erst ab neuerer Firmware), Stiebel Eltron ISG (`profiles_stiebel.py`; `compressor_on`, `evaporator_defrost`, Energie als `day_and_total` in ganzen kWh, kein Kühlstrom), HeishaMon/`aquarea` (`profiles_heishamon.py`; Aktivität aus Ventil, Abtau-Schalter und Modus), Lambda (`profiles_lambda.py`; eigene Lebenszeit-Zähler je Modus inkl. Abtauen und Standby), iDM Navigator 2.0 mit Weboberfläche (`profiles_idm.py`; Strom je Modus nur aus der Web-Statistik).
- **Nicht ohne Kernarbeit:** Ecodan (`ecodan-ha-local`; Energie sind Vortageswerte), Waterkotte (nur Jahressumme Kompressorstrom), Vaillant und ViCare (siehe Tabelle).
- **Nicht sinnvoll:** Remeha (keine Energie), Wolf (`wolflink` ohne nutzbare Daten), Kermi, Dimplex, Ochsner (nur Bastelprojekte), LG Therma V (Strom nur bei neueren Geräten), Samsung EHS, NIBE über myUplink, Daikin über ESPAltherma (ohne externen Zähler).
- Entwürfe: `raw/vorlagen/lambda-ecodan-2026-10-27.md`, `raw/entwurf-idm-waterkotte.md`.

**Nachtrag 2026-10-28 (Subagenten-Entwürfe, umgesetzt in 0.1.0b9, alle beta):**

- **Viessmann ViCare** (`profiles_viessmann.py`): Takte und Strom ohne Wärme. Kern: Einrichtung nur mit Kompressor, Strom ohne Wärmezähler ist Laufstrom (`heat_modes`), Vorlagenfelder `activity_foreign` (E3-Phase, Reparaturhinweis `activity_foreign`) und `day_timezone` (ViCare-Tageswerte laut Forum ab Mitternacht UTC, unbelegt; UTC ist die sichere Wahl, weil ein Tageswechsel um lokale Mitternacht dann nur eine Verspätung von 1–2 h bedeutet). Abtauen aus der Aktivität geht der WW-Flagge vor.
- **Mitsubishi Ecodan über MELCloud** (`profiles_melcloud.py`, Core `melcloud` ab 2026.5): sechs Tageswerte je Modus, ohne Kompressor (nur 30-min-Momentwert). **Vortageswerte** (Recherche 28.10., ~85 % sicher): ListDevices-Dump mit `DailyEnergyConsumedDate` = gestern neben den Werten ([melcloud2mqtt](https://github.com/trx-base/melcloud2mqtt/blob/main/src/test/resources/mock-responses/ListDevices.json)), 5-Minuten-Log einer Ecodan mit konstantem Wert trotz Heizbetrieb ([Melcloudsimple](https://github.com/ferndalehall/Melcloudsimple/tree/master/src/Melcloudsimple/scripts)), [OpenEnergyMonitor](https://community.openenergymonitor.org/t/ecodan-energy-monitor/24646) („the daily energy numbers are for yesterday“). Sprung kurz nach Mitternacht, 0,01 kWh, gelegentlich ausbleibend. Umsetzung: `previous_day` (Zähler prüft gegen 24 h + Zeit seit Mitternacht, Buchung über `PeriodMarks.book_late` auf den Vortag 12 Uhr). Die HA-Doku („reset at midnight“) gilt für ATA. Folge für Core `melcloud`: `total_increasing` bucht den Vortag in die Stunde nach Mitternacht und bei höherem Folgewert nur die Differenz (Upstream-Kandidat, nur nach Rückfrage).
- **Vaillant myVAILLANT** (`profiles_vaillant.py`, `mypyllant` v0.9.19): Erkennung über `original_name` der Energiereihen (die Position in der Cloud-Liste trägt keine Bedeutung), Buchung Stunde für Stunde aus der externen Statistik `mypyllant:<unique_id>` (`hourly_statistics`, `backfill.bookable_hours`, `PeriodMarks.book_late`), Stillstand = Stunde ohne Umweltwärme (`heat_includes_electricity`). Reparaturhinweise `energy_stale` (30 h ohne neue Stunde) und `source_changed` (Zuordnung passt nicht mehr, dann keine Buchung). HA-Test belegt die Umrechnung Wh → kWh externer Statistiken.
- Entwürfe mit allen Quellen: `raw/vorlagen/ecodan-2026-10-28.md`, `raw/vorlagen/vaillant-2026-10-28.md`, `raw/vorlagen/viessmann-2026-10-28.md` (lokal); die Belege stehen auch in den Docstrings der Vorlagen.

Folge für den Kern: Erkennung als Daten verallgemeinern (Muster mit `prefix`/`key`, ggf. `original_name`); Zählerart je Signal (fortlaufend, täglich, monatlich, „aus Statistik buchen“); Kompressor aus Zahlwert > Schwelle; Aktivität aus mehreren Entitäten; Modus „Takte ohne Energie“; Heizstab gesamt → Modus.

### Stufe 2/3 – Machbarkeit mit echten Daten (Auswertung 2026-10-27, eine Saison)

- **Kennlinie** (Σ Wärme / Σ Strom je Außentemperatur-Klasse): 2-K-Klassen, mindestens 7 Tage je Klasse (Streuung der Klassen-AZ 0,14 bei n = 7), Randklassen zusammenfassen; **ohne Stillstand** rechnen, sonst knickt sie an milden Tagen künstlich ab. Der Zeitraum wirkt so stark wie die Temperatur (geänderte Heizkurve) → Saisons nie stillschweigend mischen, Vergleichszeitraum anbieten, Hinweis bei Bruch.
- **Gradtage:** G20/15 schwankt je Monat um ~18 % (kWh/Kd), passt zu einer Anlage mit Heizgrenze ~15 °C schlecht; Basis einstellbar, „Wärme je Gradtag“ nur als Saisonwert; Gradtage ohne Heizbetrieb ausweisen.
- **Heizlast (Energiesignatur):** Wochenmittel der Heizleistung (nur Heizen) über Wochenmittel der Außentemperatur, nur Wochen < 12 °C, R² ≈ 0,86; Ergebnis innerhalb ±5 % stabil gegen Grenze (10/12/15 °C) und Tag/Woche, aber abhängig vom Zeitraum (Herbst/Frühjahr). Mindestdaten: 8 gültige Wochen, Spanne ≥ 10 K, ≥ 5 Tage < 0 °C. Immer „gemessen (mit Gewinnen)“ und „normgerecht“ (auf 20 °C verschoben) ausweisen; Normaußentemperatur als Option ohne Vorgabe.
- **Bausteine:** Eingabe sind die Stunden-`Totals` aus `runtime._async_hours` (Stillstand je Stunde getrennt) plus Stundenmittel der Außentemperatur; Tage/Wochen lokal mit echten Stunden (23/25 h). Aktionen `performance_curve` und `heat_load` mit Antwortdaten; wenige Sensoren (Gradtage, Heizlast bei Normaußentemperatur), keine Sensoren je Temperaturklasse.
- **Daten:** `thermostat_dampedoutdoortemp` ist derselbe Fühler gefiltert – keine unabhängige zweite Quelle für die Plausibilitätsprüfung. Außentemperatur-Maxima im Sommer bis 44 °C (Sonne/Abwärme am Fühler) → Werte außerhalb −35 … +45 °C verwerfen.

## 5. Home Assistant – technischer Stand (Oktober 2026)

- Entwicklerdoku ist nach **contributors.home-assistant.io** umgezogen.
- **Helfer verworfen:** Seit 2026.8 darf ein Helfer seinen Eintrag nicht an das Gerät einer fremden Integration hängen ([Blog 2026-07-21](https://contributors.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/), [Folge 2026-08-24](https://contributors.home-assistant.io/blog/2026/08/24/device-registry-follow-up-changes/)). Wärmewacht ist `service` mit eigenem Gerät.
- **Subentries verworfen:** bei höchstens drei festen Modi zu viel Listener-/Reload-Logik. Ab 2026.11 bedingte Formularfelder (`visible=…`, [Blog](https://contributors.home-assistant.io/blog/2026/10/21/form-fields-visible/)) – erst nutzen, wenn die Mindestversion es erlaubt.
- Entity-Selector filtert seit **2026.4** nach `unit_of_measurement` (im Code geprüft) → Mindestversion 2026.4. Kein Filter nach `state_class`: in der Einrichtung selbst prüfen.
- **Sensoren:** Arbeitszahl ohne `device_class` und Einheit, mit `state_class: measurement` (sonst formatiert die Oberfläche den Wert nicht als Zahl – Rohwert mit 14 Nachkommastellen), `suggested_display_precision=2`. Energie `energy`/kWh mit `total_increasing`. Zähler „Starts heute“ `total_increasing` (Rücksprung auf 0 gilt als Reset) – sauberer ist ein nie zurückgesetzter Lebenszeit-Zähler. Laufzeit `duration`/h. `state_class` von Anfang an richtig setzen (spätere Änderung erzeugt Reparaturmeldungen).
- **Recorder-Statistik:** `statistics_during_period(..., types={"change"} | {"sum"})`; `state` ist der rohe Zählerstand, nicht reset-korrigiert. Für reines Lesen keine Änderung durch `mean_type`/`unit_class` (2026.11).
- **Aktion mit Antwort:** `SupportsResponse.ONLY`, Registrierung in `async_setup`.
- Flow-Methoden `async_show_form/menu/progress` und `async_external_step` mit `step_id` aufrufen (Pflicht ab 2027.5, [Blog](https://contributors.home-assistant.io/blog/2026/10/23/flow-results-require-step-id/)).
- **Manifest `categories`:** für Custom-Integrationen optional; hassfest warnt nur bei unbekannter Kategorie, die HACS-Action warnt ohne Schlüssel und scheitert bei unbekannter ([Blog 2026-10-20](https://contributors.home-assistant.io/blog/2026/10/20/integration-categories/), Liste unter [Integration categories](https://contributors.home-assistant.io/core/integrations/categories/)). Einspeisewacht sah am 2026-10-26 noch eine Ablehnung – beim ersten CI-Lauf prüfen.
- Brand-Bilder in `custom_components/waermewacht/brand/` (ab HA 2026.3).
- `pytest-homeassistant-custom-component` 0.13.375 = HA 2026.10.4, **Python ≥ 3.14**.
- Quality Scale: Ziel Bronze (Selbstprüfung; hassfest prüft `quality_scale.yaml` bei Custom-Integrationen nicht). Bronze hat 2026 20 Regeln (neu: `docs-conditions`, `docs-triggers`).

## 6. Entscheidungen

Siehe `CLAUDE.md`, Abschnitt „Verbindliche Entscheidungen“ (alle vom 2026-10-27). Begründungen:

- **Eine Quelle je Wärmepumpe:** hält Kern und Einrichtung einfach; Kombinationen später über den generischen Weg.
- **EMS-ESP vor HomeCom:** EMS-ESP liefert fortlaufende Zähler auf 0,01 kWh, Kompressorstatus und Abtauen im Minutentakt; HomeCom nur Tageswerte mit Verzug und kein Abtauen. HomeCom ist für Bosch-Besitzer ohne Bastelaufwand trotzdem wichtig.
- **Stillstand abtrennen:** Ob die ~25 W physikalisch stimmen, kann nur ein externer Zähler zeigen (konstanter Wert deutet auf einen Modellwert der Firmware). Die Abtrennung macht die Arbeitszahlen je Modus davon unabhängig; der Stillstand bleibt als eigener Wert sichtbar („laut Wärmepumpe“).
- **Perioden-Sensoren trotz Langzeitstatistik** (Abweichung von den Schwestern): Eine Arbeitszahl ist ein Quotient, die Statistik kann sie nicht aus Zählern bilden. Deshalb Perioden-Sensoren (mit `state_class: measurement` nur für die Anzeige; ihre Statistik ist ein Zeitmittel, keine Bilanz) plus Energie-Sensoren für die Statistik plus Aktion „Bericht“.

- **Kühlsaison = Kalenderjahr** (2026-10-27): Gekühlt wird von Frühjahr bis Herbst; eine Heizsaison ab Juli würde das teilen.
- **Kein CO₂-Vergleich in der Oberfläche** (Wunsch des Inhabers 2026-10-27): hinge zu stark an Annahmen (Durchschnitts- oder Stundenmix, Vorketten, PV-Eigenverbrauch, Batterie, Ökostrom). `costs.py` rechnet CO₂ mit belegten Faktoren mit, angezeigt wird es nicht.
- **Kein PV-Anteil** (Wunsch des Inhabers 2026-10-27): dieselbe Unschärfe (Batterie, Gleichzeitigkeit).
- **Preise nur als Einstellung**, nie als Vorgabe im Code; der Strom-Grundpreis nur für einen eigenen Wärmepumpenzähler.
- **Kennlinie und Heizlast:** laufende und vorige Saison nie gemischt (geänderte Heizkurve); täglich gegen 3 Uhr berechnet, nur im Speicher, große Attribute nicht aufgezeichnet.
- **Gesundheits-Check:** Entwurf in `docs/GESUNDHEITSCHECK.md`. Entscheidungen des Inhabers 2026-10-27: Problem-Sensoren ohne Diagnose-Kategorie, „Effizienz gesunken“ nur Heizen, Knopf „Vergleich neu starten“, Tagesbuch erlaubt.

## 7. Architektur

| Datei | Inhalt (ohne HA-Importe, lokal getestet) |
|---|---|
| `model.py` | `Signal`, `Mode`, `Activity` |
| `profiles.py` | Vorlagen als Daten (EMS-ESP), Erkennung über Registry-Einträge, Aktivitätswerte aller EMS-ESP-Sprachen |
| `counter.py` | Zählerstände → Zuwächse: erster Wert, Rücksprung (Rauschen, Abtauen: Höchststand halten = netto), Reset (> 10 % und > 1 kWh), Sprung, Tageszähler |
| `runs.py` | Läufe (Start beobachtet? Lücke?) und Abtauungen; unbekannte Zustände ändern nichts |
| `cycling.py` | Starts, Laufzeit, Kurzläufe, Pausen, Abtauungen je Zeitfenster; Starts je Stunde |
| `energy.py` | Energie je Art (Wärme, Strom Lauf, Stillstand, Heizstab) und Modus; Arbeitszahl-Regeln |
| `periods.py` | Stände zu Periodenbeginn (Grenzen lokal, gespeichert in UTC), Rückblick als negativer Stand |
| `backfill.py` | Stunden der Langzeitstatistik → Energie, Stillstand = Strom ohne Wärme in derselben Stunde |
| `averages.py` | zeitgewichtete Mittel (Spreizung, Vorlauf) |
| `report.py` | Kennzahlen der Aktion „Bericht“ je Bereich und Monat |

HA-Schicht: `runtime.py` (Zustandsänderungen, Minuten-Takt, Statistik, Speichern, Reparaturhinweise), `config_flow.py`, `sensor.py`, `binary_sensor.py`, `services.py` (Aktion `report`), `diagnostics.py`. Texte und Icons erzeugt `tools/make_strings.py` (DE/EN aus einer Tabelle; danach `ruff format`).

- **Aktion „Bericht“** (`waermewacht.report`): beliebiger Zeitraum (Vorgabe: laufende Saison bis jetzt), Antwort mit Bereichen `heating`, `dhw`, `heating_dhw` (mit Stillstand), `cooling` und `months`. Stunden vor der ersten vollen Stunde nach der Einrichtung aus den Quell-Zählern (Stillstand stundenweise geschätzt, `estimated_until`), danach aus den eigenen Energie-Sensoren. Nur volle Stunden der Statistik (`data_until`). Ohne Recorder: Fehlermeldung statt 0.
- **Reparaturhinweise** nach 10 Minuten Laufzeit: `missing_entity` (Quell-Entität fehlt), `energy_unit` (keine Wh/kWh/MWh). Verschwinden, sobald behoben; beim Löschen des Eintrags entfernt.
- **Zählerschritt:** Ein Zähler, der nie Nachkommastellen zeigte, gilt als ganzzahlig. Arbeitszahlen tragen `counter_step_kwh` und `reliable` (Strom ≥ 20 Schritte, also Rundung ≤ 5 %).

- **Stillstand live:** Strom eines Modus ist Stillstand, wenn seit dem letzten Zählerwert weder Wärme dieses Modus kam noch der Kompressor in diesem Modus lief (`runtime._running`). Ohne Kompressorsignal entscheidet nur die Wärme. Stillstand aller Zähler (auch eines Kühlen-Zählers) geht in die Arbeitszahl Heizen + Warmwasser ein – er gehört zum Gerät, nicht zu einem Modus.
- **Betriebsart bei eigener Zuordnung:** ohne Vorlage werden die Zustände mit den EMS-ESP-Wörtern gelesen; andere Werte gelten als „sonstiger Betrieb“ (keine Abtauungen). Eine eigene Werte-Zuordnung im Formular kommt mit weiteren Herstellern.
- **Saisonbeginn geändert:** Beim nächsten Start (Neuladen) wird die Saison aus der Statistik neu berechnet (`runtime._async_rebase_season`), statt ab der Änderung neu zu zählen.
- **Diagnose-Datei** enthält Zustände der Quell-Entitäten und Energiesummen (anders als bei Tarifwacht) – README rät, sie vor dem Teilen zu prüfen.
- **Schreiblast (SD-Karten, Raspberry Pi):**
  - Zwei `Store`-Dateien: `waermewacht.<entry>` (Zähler, Summen, Marken, laufender Lauf, wenige KB) alle 10 Minuten, wenn sich etwas geändert hat, sowie um Mitternacht und beim Beenden; `waermewacht.<entry>.history` (Läufe und Abtauungen der letzten 40 Tage, einige 10 KB) nur am Ende eines Laufs, nach einer Abtauung (mit dem nächsten Speichern) und um Mitternacht. Nie `async_delay_save` je Zählerwert.
  - Sensoren rechnen einmal pro Minute und bei Ereignissen; der Recorder schreibt aber nur bei geändertem Zustand oder Attribut. Deshalb werden die Werte auf die angezeigte Genauigkeit gerundet (Arbeitszahl 0,01; Energie 0,1 kWh; Laufzeit 0,1 h; Temperaturen 0,1) und die minütlich wandernden Attribute `heat_kwh`, `electricity_kwh`, `standby_kwh` nicht aufgezeichnet (`_unrecorded_attributes`).
  - Abschätzung bei 8 Laufstunden am Tag: einige hundert Zustandszeilen am Tag für alle Wärmewacht-Sensoren zusammen (Energie ~0,1 kWh-Schritte, Arbeitszahlen nur bei Änderung in der 2. Nachkommastelle) – weniger als die Quell-Entitäten von EMS-ESP selbst. Dazu die üblichen Statistikzeilen der `measurement`-Sensoren (Kurzzeit alle 5 min, 10 Tage gehalten; Langzeit stündlich). Vor dem ersten stabilen Release an der Anlage des Inhabers messen (Zeilen je Entität im Recorder), nicht nur schätzen.
- **Rückblick:** nur bei der ersten Einrichtung, aus den Stundenwerten (`change`) der Energie-Entitäten. Die angebrochene Stunde vor der Einrichtung fehlt (bekannte kleine Lücke).
- **Lücken (HA aus):** Der erste Zählerwert danach bucht den ganzen Zuwachs; ob er Lauf oder Stillstand war, entscheidet die Wärme im selben Zeitraum.

## 8. Integration Quality Scale (Selbstprüfung, Stand 2026-10-27)

Ziel Bronze. Für Custom-Integrationen vergibt Home Assistant keine Stufe.

| Bronze-Regel | Stand |
|---|---|
| action-setup | ✅ Aktion `report` in `async_setup` (`services.py`) |
| appropriate-polling | ➖ kein Polling – Zustandsänderungen und Minuten-Takt |
| brands | ⏳ Branding folgt (`brand/`) |
| common-modules | ✅ `entity.py`, `runtime.py` |
| config-flow-test-coverage | 🟡 Erkennung, manuell, Fehler, Optionen; Neu konfigurieren fehlt |
| config-flow | ✅ Abschnitte, `data_description` |
| dependency-transparency | ✅ keine `requirements` |
| docs-actions | ✅ README |
| docs-conditions / docs-triggers | ➖ keine eigenen |
| docs-high-level-description, -installation-instructions, -removal-instructions | ✅ README |
| entity-event-setup | ✅ Abo in `async_added_to_hass`, Abmeldung über `async_on_remove` |
| entity-unique-id | ✅ `<entry_id>_<key>` |
| has-entity-name | ✅ |
| runtime-data | ✅ `entry.runtime_data` |
| test-before-configure | ✅ Einrichtung prüft Modi und Einheiten |
| test-before-setup | ➖ bewusst nicht: Quell-Entitäten sind beim Start oft noch nicht da; Wärmewacht wartet, Reparaturhinweis nach 10 min |
| unique-config-entry | ✅ `<vorlage>:<präfix>` bzw. Wärmezähler |

Darüber hinaus: `config-entry-unloading`, `diagnostics`, `entity-translations`, `exception-translations`, `icon-translations`, `reconfiguration-flow`, `repair-issues`, `entity-device-class`.

## 9. Offene Fragen

- **Stillstand:** physikalisch korrekt oder Modellwert? Nur mit externem Zähler am WP-Anschluss klärbar (beim Inhaber keiner vorhanden). Für die Berechnung durch die Abtrennung unkritisch.
- **HomeCom-Tageswechsel:** Geht die letzte Stunde des Tages verloren, und wann genau springt der Wert? Nach einigen Tagen Verlauf der Modus-Entitäten prüfen (beim Inhaber seit 2026-10-27 aktiviert), dann Fixture.
- **HomeCom lokal/Cloud:** Welche Werte kommen lokal, welche aus der Cloud? Vorlage muss beide Fälle verkraften.
- ~~Abtauwärme~~ **geklärt 2026-10-27:** Die Bosch-Wärmezähler ziehen sie ab – `nrgheat` sank bei einer Abtauung um 0,31 kWh in Schritten von 0,04–0,06 kWh (ebenso `nrgtotal` und die HomeCom-Lebenszeit-Summe). `counter.py` hält deshalb den Höchststand (netto).
- ~~`heatingstarts`~~ **geklärt:** Kompressorstarts – HomeCom-Starts `ch` + `dhw` + `cooling` = `total` = `totalcompstarts`.
- Heizstab je Modus mit 0,01 kWh (0x4AF Offsets 28/36) – nicht in EMS-ESP ausgewertet.
- Passende `categories` für das Manifest.
- DPMAregister für den Namen prüfen (Inhaber).
