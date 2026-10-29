# Changelog

## Unveröffentlicht

- **Starts Saison bei Startzählern ohne Statistik:** Hat der Startzähler der Wärmepumpe keine Langzeitstatistik (P1P2MQTT: keine Zustandsklasse), blieb „Starts Saison“ dauerhaft unbekannt. Jetzt zählt der Sensor ab dem ersten gesehenen Stand der Saison (Attribut `since`), auch über Neustarts (Rückmeldung im simon42-Forum).
- **Einrichtung verständlicher:** Felder heißen klarer („Erzeugte Wärme Heizen“, „Warmwasser-Temperatur (Ist, Speicher)“), und unter den schwierigen Feldern steht eine Erläuterung – vor allem bei „Kompressor läuft“: eine An/aus-Entität oder eine Zahl über 0, kein Status-Text. Bei der Außentemperatur ist eine nahe Wetterstation ausdrücklich in Ordnung, wenn der Fühler der Wärmepumpe in der Sonne liegt (Rückmeldungen im simon42-Forum).
- **Bosch HomeCom mit Betriebsart:** Die Vorlage nimmt den neuen Sensor „Kompressorstatus“ von `bosch_homecom` (ab [PR #217](https://github.com/serbanb11/bosch-homecom-hass/pull/217)) als Betriebsart. Damit gibt es auch mit HomeCom Abtauungen, die Zuordnung der Läufe zu Heizen und Warmwasser, Spreizung und mittleren Vorlauf. Bestehende Einträge übernehmen den Sensor beim nächsten Start von selbst, sobald er da ist.

## 0.1.4 – 2026-10-29

- **Neue Vorlage (beta): Daikin Altherma über P1P2MQTT** ([P1P2Serial](https://github.com/Arnold-n/P1P2Serial)): die Zähler der Wärmepumpe je Betriebsart (ganze kWh), Takte und Abtauungen (Rückmeldung im simon42-Forum).
- **Neue Vorlage (beta): Buderus/Bosch über MX300, MX400, K30** ([BassXT/buderus](https://github.com/BassXT/buderus), Bosch-Cloud): Arbeitszahlen je Betriebsart aus Lebenszeit-Zählern, Takte und Abtauungen (Rückmeldung im simon42-Forum).
- **EMS-ESP mit langen Namen:** Die Vorlage erkennt jetzt auch das EMS-ESP-Format „Single instance, long names (v3.4)“, bei dem die Entitäten englische Langnamen tragen (`sensor.boiler_energy_heating` statt `sensor.boiler_nrgheat`). Bisher wurde die Wärmepumpe dann nicht gefunden (Rückmeldung im simon42-Forum).

## 0.1.3 – 2026-10-29

- **Durchfluss** lässt sich jetzt auch wählen, wenn die Entität keine Geräteklasse „Volumenstrom“ hat, aber eine bekannte Einheit (z. B. `L/min` bei P1P2MQTT). Bisher blieb die Auswahl leer (Rückmeldung im simon42-Forum).
- **Heizlast (Energiesignatur):** Tage ohne Energiedaten zählen nicht mehr. Lagen Außentemperaturen weiter zurück als die Statistik der Zähler (z. B. ein später angelegter Zähler), gingen diese Wochen mit 0 kW ein und verdarben die Gerade.
- **Intern:** Vorlagen beschreiben das Format ihrer unique_ids als Muster (`id_format`) statt mit eigenem Code; fünf Sonderklassen entfallen. Am Verhalten ändert sich nichts.

## 0.1.2 – 2026-10-28

- **Leistung je Heizlast** wird wie die Arbeitszahlen als Zahl angezeigt (Dezimalkomma statt „1.56“) und bekommt Langzeitstatistik.
- **Einrichtung:** Der Hinweis auf deaktivierte Entitäten erscheint nur noch, wenn eine Vorlage welche nutzen würde (bisher stand dort „…: –.“).

## 0.1.1 – 2026-10-28

Erste Version ohne Beta-Kennzeichen. Die Vorlagen für EMS-ESP und Bosch HomeCom laufen an einer echten Anlage; alle anderen Vorlagen bleiben beta, bis Rückmeldungen mit Diagnose-Datei sie bestätigen. Änderungen seit 0.1.0b8:

**Neue Hersteller (beta, aus dem Quellcode der Integrationen, noch ohne echte Anlage bestätigt):**

- **Viessmann ViCare** (Core `vicare`): Takte, Laufzeiten, Strom je Betriebsart und Kosten. Keine Arbeitszahl, weil Home Assistant keine Wärme liefert. Abtauen bei Vitotronic-Reglern. Tageswerte in UTC-Tagen. Neuer Reparaturhinweis „Betriebsart-Entität ohne Betriebsart“ (E3-Regler melden nur „ready“ / „not_ready“).
- **Mitsubishi Ecodan über MELCloud** (Core `melcloud`): Arbeitszahlen aus den Tageswerten, ohne Takte. MELCloud meldet die Summen des Vortags; Wärmewacht bucht sie in den Vortag.
- **Vaillant myVAILLANT** (`mypyllant`): Arbeitszahlen Stunde für Stunde aus der Statistik von mypyllant, ohne Takte. Neue Reparaturhinweise „keine neuen Energiewerte“ und „Energie-Entitäten haben ihre Bedeutung geändert“.
- **Mitsubishi Ecodan über die F1p-Brücke** (MQTT, CN105): Arbeitszahlen, Takte und Abtauungen; Energie als Vortageswert.
- **Mitsubishi Ecodan mit ESPHome-Firmware** ([esphome-ecodan-hp](https://github.com/gekkekoe/esphome-ecodan-hp)): wie die F1p-Brücke, ohne Startzähler. Erkannt an den Firmware-Namen der Entitäten in allen 14 Sprachen.
- **Waterkotte** (`waterkotte_heatpump`, EcoTouch): Arbeitszahlen, Takte. Der Kompressorstrom kommt nur als Jahressumme für alle Betriebsarten; Wärmewacht ordnet ihn der laufenden Betriebsart zu (neues Feld „Strom Kompressor gesamt“ im Abschnitt Betrieb).
- **Viessmann Vitocal 200-A** (geteilt in Außengerät und Systemsteuerung): Die ViCare-Vorlage führt beide Geräte zu einer Wärmepumpe zusammen.
- **Lambda und iDM:** Der Strom beim Abtauen zählt jetzt zur laufenden Betriebsart (meist Heizen), bei Lambda auch der eigene Stillstand-Zähler. Bisher fehlte der Abtau-Strom, die AZ Heizen fiel zu gut aus. Dafür gibt es im Abschnitt Betrieb die neuen Felder „Strom Abtauen“ und „Strom Stillstand“.
- Einrichtung auch nur mit Kompressor: dann Takte und Strom ohne Arbeitszahl. Strom ohne Wärmezähler zählt als Laufstrom.

**Gesundheits-Check:**

- **Neue Reparaturhinweise:** „Vor- und Rücklauf vertauscht?“ (Spreizung beim Heizen einen Tag lang unter −1 K), „Durchfluss unplausibel“ (Faktor 10 gegen Wärme und Spreizung), „Durchfluss 0 beim Heizen“ (15 Minuten).
- **Neue Kennwerte:** „Spreizung 7 Tage“ (kalte Tage), „Leistung je Heizlast“ (mit den neuen Einstellungen Heizleistung bei A−7/W35 und kleinste Heizleistung), „Vorlauf bei 0 °C“ (die Heizkurve, mit dem Wert der Vorsaison), „Starts Saison“ mit Starts je Tag.
- **Neue Attribute:** Anstieg des Stillstands (`rising`), Abtauungen der letzten 7 Tage und je Außentemperatur-Klasse gegen die Vorsaison.

**Gradtage, Kosten:**

- **Wärme je Gradtag** zählt nur Heiztage (ab 1 kWh Heizwärme am Tag). Kühle Tage ohne Heizbetrieb drückten den Wert bisher auf ein Drittel, wenn die Heizung erst im Oktober anlief. Ohne Heizwärme ist er unbekannt statt 0.
- **Kosten-Sensoren** nennen im Attribut `period_start`, ab wann Monat bzw. Saison zählen.

**Kleineres:**

- **Laufzeit heute** in Minuten statt Stunden, wie alle anderen Dauern.
- **Weniger Schreibvorgänge:** Stromkosten in 10-Cent-Schritten, Ersparnis ggü. Gaskessel in ganzen Euro (wie angezeigt), Laufzeit heute in 5-Minuten-Schritten. Gemessen vorher: 78 Zustände pro Stunde für 98 Entitäten, ein Viertel aus Kosten und Ersparnis.
- **Diagnose-Datei:** Buchungsart der Vorlage, Zeitpunkt der letzten Zählerwerte, Stand der Stundenbuchung, letzte Tagebuch-Einträge. Die Entity-IDs der Zuordnung sind jetzt ebenfalls maskiert.
- **„Zähler hängt“ bei Vortageswerten** (F1p, ESPHome) erst nach 30 Stunden Laufzeit ohne neuen Wert statt nach 6: Diese Zähler steigen nur einmal am Tag.
- **Vorlagen ohne Wärme- und Stromleistung:** Wärmewacht hat sie nie ausgewertet, und beim Neu-Konfigurieren gingen sie verloren.

**Beim Update beachten:**

- **Neue Felder der Vorlagen** übernimmt Wärmewacht jetzt selbst: Findet die Vorlage für dieselbe Wärmepumpe ein Signal, das es beim Einrichten noch nicht gab (etwa die Warmwasser-Temperatur oder „Strom Abtauen“ bei Lambda und iDM), wird es beim Start eingetragen. Ein Feld, das du später unter *Neu konfigurieren* entfernst, bleibt entfernt.
- „Laufzeit heute“ wechselt von Stunden auf Minuten; der bisherige Verlauf zeigt bis zum Update Stunden.

## 0.1.0b8 – 2026-10-27

- **Diagnose-Datei für neue Hersteller:** listet unter `source` alle Entitäten der Quellgeräte (Plattform, unique_id, Einheit, Zustand) sowie Hersteller, Modell und Firmware. Seriennummern und Eintrags-IDs sind maskiert. Damit lässt sich aus einer manuellen Einrichtung eine Vorlage bauen.
- **Gradtage:** Sensoren „Gradtage Saison“ (G20/15 nach VDI 3807, als Zähler für Statistik-Karten) und „Wärme je Gradtag Saison“ mit dem Wert der Vorsaison. Der Bericht nennt Gradtage und Wärme je Gradtag gesamt und je Monat.
- **Warmwasser je Ladung:** Sensoren „AZ Warmwasser letzte Ladung“ und „AZ Warmwasser-Ladungen 30 Tage“ (normale Ladungen ohne Desinfektion), mit Dauer, Wärme, Temperaturhub und Heizstab-Anteil als Attribute. Nicht für Bosch HomeCom (Tageswerte).
- **Neues Feld Warmwasser-Temperatur** (Vorlagen EMS-ESP, Bosch HomeCom, Stiebel, Luxtronik) und Sensor „Letzte thermische Desinfektion“. Die Schwelle (Vorgabe 60 °C) steht in den Einstellungen. Bestehende Einträge: die Warmwasser-Temperatur einmal unter *Neu konfigurieren* auswählen.
- **Gesundheits-Check:** Problem-Sensor „Heizstab bei Warmwasserladungen“: mehr als 10 % Heizstab-Strom in normalen Ladungen der letzten 30 Tage.
- **Tagebuch:** enthält jetzt die normalen Warmwasser-Ladungen je Tag, als Grundlage für einen späteren Vergleich mit dem Vorjahr.
- **Effizienz gesunken:** Hat eine Saison Außentemperatur-Klassen zusammengefasst (am Saisonanfang üblich), vergleicht Wärmewacht jetzt mit der Summe der Klassen der anderen Saison über denselben Bereich. Statt „mindestens 2 gemeinsame Klassen“ gilt „mindestens 4 K gemeinsamer Bereich“. Der Vergleich ist damit nicht mehr wochenlang unbekannt.

## 0.1.0b7 – 2026-10-27

- **Weitere Hersteller (beta):**
  - Vorlagen für Luxtronik (alpha innotec, Novelan; Strom je Betriebsart erst ab neuerer Firmware), Stiebel Eltron/Tecalor über die ISG, Panasonic Aquarea über HeishaMon (Integration `aquarea`), Lambda und iDM (Navigator 2.0 mit Weboberfläche).
  - Abgeleitet aus dem Quellcode der jeweiligen Integration, noch nicht an einer echten Anlage bestätigt. Die Einrichtung zeigt sie deshalb mit „(beta)“.
  - Rückmeldungen mit Diagnose-Datei sind willkommen.
- **Gesundheits-Check:**
  - Binärsensoren „Effizienz gesunken“ (AZ Heizen bei gleicher Außentemperatur gegenüber der Vorsaison) und „Heizstab bei milder Witterung“. Reichen die Daten nicht, sind sie unbekannt und nennen den Grund. Schwellen in den Einstellungen.
  - Schaltfläche „Effizienzvergleich neu starten“ nach einer gewollten Änderung, etwa einer neuen Heizkurve.
  - Neue Reparaturhinweise: Zähler steht still, Quelle nicht erreichbar, Außentemperatur unbrauchbar.
  - Tagebuch: ein Eintrag je Tag in der Verlaufsdatei, Grundlage für spätere Prüfungen.
- **Betriebsart aus mehreren Entitäten:** Merker für Abtauen, Warmwasser, Kühlen und Heizen sowie die eingestellte Betriebsart, für Wärmepumpen ohne einzelne Betriebsart-Entität. Die Vorlagen Stiebel und HeishaMon nutzen das; damit gibt es dort Abtauungen, Spreizung und Vorlauf.

## 0.1.0b6 – 2026-10-27

- **AZ-Kennlinie Heizen:** Arbeitszahl je 2-K-Klasse der Tagesmitteltemperatur, laufende und vorige Saison getrennt, als Attribute für ein Diagramm (Beispiel mit apexcharts-card im README). Aktion `performance_curve` für beliebige Zeiträume.
- **Heizlast aus der Energiesignatur:** Heizlast je Kelvin und, mit der neuen Einstellung Normaußentemperatur, die Heizlast bei Normaußentemperatur. Aktion `heat_load`.

- **Strom-Grundpreis** als optionale Einstellung für einen eigenen Wärmepumpenzähler: anteilig in Stromkosten, Wärmekosten und Gasvergleich.

## 0.1.0b5 – 2026-10-27

- **Kosten und Gasvergleich:**
  - Neue Einstellungen Strompreis, Gas-Arbeitspreis und Gas-Grundpreis, alle optional.
  - Damit gibt es die Sensoren Stromkosten Monat und Saison, Wärmekosten je kWh Saison und Ersparnis gegenüber einem Gaskessel (Wirkungsgrad 0,87 auf den Brennwert).
- **Statistik vor der Einrichtung:** Der erste importierte Monat zeigte die ganze Vergangenheit als einen negativen Balken, weil Home Assistant die erste Zeile gegen 0 rechnet. Die Summen werden jetzt einmal angehoben und beginnen bei 0. Ein Import aus 0.1.0b4 wird beim Update repariert.

## 0.1.0b4 – 2026-10-27

- **Statistik vor der Einrichtung:** Die Energie-Sensoren bekommen einmalig die Stunden vor der Einrichtung in ihre Statistik (aus der Statistik der Zähler, Stillstand stundenweise geschätzt). Statistik-Karten zeigen damit auch die Monate davor. Bestehende Einträge holen das beim Update einmal nach. Aufgezeichnete Zeilen bleiben unverändert.
- **Kühlsaison = Kalenderjahr:** „EER Kühlen Saison“ zählt jetzt von Januar bis Dezember, nicht mehr ab Juli. Damit bleibt die Kühlperiode von Frühjahr bis Herbst in einer Saison. Beim Update rechnet Wärmewacht das laufende Jahr aus der Statistik nach.
- **HomeCom-Tageswerte robuster:**
  - Ein Wert wird nach einem Neustart mit seinem eigenen Zeitstempel gebucht. Ein Abruf von gestern zählt nicht mehr als heutiger.
  - Die Plausibilitätsprüfung misst einen Tageswert an der Zeit seit Mitternacht. Ein Abruf, der nach einem Neustart zwei Stunden auf einmal bringt, wird nicht mehr verworfen.
  - Ein verworfener Wert verschiebt die Basis nicht.
- **Periodenwechsel:** Strom eines Abrufs kurz vor Mitternacht landet im selben Tag oder Monat wie seine Wärme. Wartender Strom übersteht einen Stromausfall.

## 0.1.0b3 – 2026-10-27

- **Vorlage Bosch HomeCom** (`bosch_homecom`): findet die Wärmepumpe am Gateway und füllt die Entitäten aus. Die Einrichtung nennt Entitäten, die eine Vorlage bräuchte, die aber deaktiviert sind (bei `bosch_homecom` die Energie je Betriebsart). Tageswerte der Cloud beginnen um Mitternacht neu; ein Rücksprung am selben Tag (Zeitumstellung) wird nicht doppelt gebucht. Stillstand ist hier Strom eines Abrufs ohne Wärme.
- **„Kompressor läuft“** darf auch eine Drehzahl oder Modulation sein (läuft bei über 0).
- **Spreizung und Vorlauftemperatur heute** gibt es nur noch mit Betriebsart. Ohne sie mischten sich Warmwasserläufe in den Heizbetrieb.

## 0.1.0b2 – 2026-10-27

- **Anzeige:** Arbeitszahlen erscheinen jetzt als Zahl mit 2 Nachkommastellen (bisher Rohwert mit vielen Stellen) und mit kurzen Namen, die in Listen nicht mehr abgeschnitten werden: „AZ Heizen Monat“, „AZ Warmwasser Saison“, „AZ Heizen+WW gesamt“, „EER Kühlen …“. Bestehende Entity-IDs bleiben. Ihr Verlauf erscheint jetzt auch in der Statistik (als Zeitmittel; die Bilanz liefern die Energie-Sensoren und der Bericht).
- **Takte ab dem ersten Tag:** Bei der Einrichtung – und beim Update von 0.1.0b1 – holt Wärmewacht Läufe und Abtauungen der letzten Tage aus dem Verlauf von Home Assistant nach (so weit der Recorder sie hält, meist 10 Tage). „Starts heute“, „Laufzeit pro Start 7 Tage“ usw. sind damit sofort gefüllt.
- **Weniger Schreiblast (SD-Karten):** Werte werden auf die angezeigte Genauigkeit gerundet (Energie 0,1 kWh, Laufzeit 0,1 h, Temperaturen 0,1 °C), minütlich wandernde Attribute nicht mehr aufgezeichnet, und die Lauf-Historie liegt in einer eigenen Datei, die nur am Ende eines Laufs und um Mitternacht geschrieben wird.

## 0.1.0b1 – 2026-10-27

Erste Beta.

- **Einrichtung mit Vorlage EMS-ESP** (Bosch/Buderus-Wärmepumpen): findet die Wärmepumpe über die Entitäten-Registry, versteht alle ID-Formate von EMS-ESP und die Betriebsart in allen EMS-ESP-Sprachen; jede Entität lässt sich ändern. Andere Wärmepumpen: eigene Zuordnung.
- **Arbeitszahlen** Heizen, Warmwasser, Heizen + Warmwasser und **Leistungszahl Kühlen** für heute, gestern, Monat, Saison und gesamt (heute/gestern standardmäßig aus). Σ Wärme / Σ Strom; unbekannt statt 0 ohne Wärme oder unter dem Mindeststrom; Attribute zu Zählerschritt und Verlässlichkeit.
- **Stillstand getrennt:** Strom bei stehendem Kompressor zählt nicht in die Arbeitszahl je Betriebsart, wohl aber in Heizen + Warmwasser. Wärme- und Strom-Sensoren je Betriebsart und ein Stillstand-Sensor für die Langzeitstatistik.
- **Abtauen netto:** Beim Abtauen ziehen die Wärmezähler die entzogene Wärme ab; Wärmewacht bucht nur die Netto-Wärme.
- **Takte:** Starts heute/gestern/gesamt, Laufzeit heute, Laufzeit pro Start (heute, 7 Tage, Monat), Kurzläufe, kürzeste Pause, Abtauungen und Binärsensor „Auffälliges Takten“. Neustart mitten im Lauf und Wechsel Heizen → Warmwasser ohne Stopp zählen nicht als neuer Start.
- **Diagnose:** Heizstab-Anteil (Monat, Saison), Spreizung und Vorlauftemperatur im Heizbetrieb.
- **Rückblick:** Bei der Einrichtung füllen die Stundenwerte der Langzeitstatistik heute, gestern, Monat, Saison und gesamt; Stillstand stundenweise geschätzt. Ältere EMS-ESP-Namen desselben Zählers werden mitgelesen. Ein geänderter Saisonbeginn rechnet die Saison neu.
- **Aktion „Bericht“** (`waermewacht.report`): Wärme, Strom und Arbeitszahlen eines beliebigen Zeitraums, mit Monaten – auch vor der Einrichtung.
- **Reparaturhinweise** bei fehlender Entität oder unbrauchbarer Einheit; Diagnose-Download.
- Schont SD-Karten: speichert höchstens alle 10 Minuten, am Ende eines Laufs, um Mitternacht und beim Beenden.
- Icon und Logo (Außengerät mit Lüfter in Verkehrsorange); Home Assistant zeigt sie ab 2026.3.
