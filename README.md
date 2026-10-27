# Wärmewacht

**Gesundheits-Check für Wärmepumpen in Home Assistant** – Arbeitszahlen je Betriebsart und Zeitraum, Takte, Kurzläufe, Abtauungen und Diagnosewerte, berechnet aus den Entitäten, die deine Wärmepumpe schon liefert. Nur lesen, nie steuern; keine Cloud.

> **Im Aufbau.** Noch nicht für den Alltag gedacht. Erste Vorlage: Bosch/Buderus über [EMS-ESP](https://github.com/emsesp/EMS-ESP32); Bosch HomeCom folgt.

## Was Wärmewacht anders macht als Template-Sensoren

- **Arbeitszahl eines Zeitraums = Σ Wärme / Σ Strom**, nie der Mittelwert von Tageswerten.
- **Kein Verbrauch → unbekannt, nicht 0.** Nullen ziehen Mittelwerte und Statistiken nach unten.
- **Stillstand getrennt:** Strom bei stehendem Kompressor (Elektronik, bei Bosch im Heizen-Zähler) zählt nicht in die Arbeitszahl je Modus, wohl aber in die Arbeitszahl Heizen + Warmwasser – wie bei den Feldtests des Fraunhofer ISE.
- **Kühlen nie in der Jahresarbeitszahl;** es hat eine eigene Leistungszahl (EER).
- **Takte aus echten Läufen:** Starts, Laufzeit pro Start, Kurzläufe, kürzeste Pause, Abtauungen. Ein Neustart von Home Assistant mitten im Lauf ist kein neuer Start; ein Wechsel von Heizen auf Warmwasser ohne Stopp ist ein Lauf.
- **Zähler-Resets und kleine Rücksprünge** werden erkannt und nicht gebucht.
- **Rückblick:** Monat und Saison enthalten schon bei der Einrichtung die Werte aus der Langzeitstatistik.

## Bilanzgrenze

Die Arbeitszahlen gelten für die Zähler, die deine Wärmepumpe meldet. Bei Bosch über EMS-ESP sind das Kompressor-Stromzähler (etwa SEPEMO H1, mit Heizstab H3) – ohne Umwälzpumpen, Regelung und Speicherladepumpen. Eine System-Arbeitszahl mit externem Stromzähler liegt deshalb niedriger. Wärmewacht ist eine **Orientierung, keine Fachdiagnose**.

## Verwandte Projekte

- [home-assistant-heat-pump-performance](https://github.com/vandecook/home-assistant-heat-pump-performance) – Arbeitszahlen aus Wärme- und Stromzähler, herstellerneutral.
- [daikin_cycle_ml](https://github.com/elRadix/daikin_cycle_ml) – umfangreiche Auswertung für Daikin Altherma mit ESPAltherma.
- [heatpumpmonitor.org](https://heatpumpmonitor.org/) – öffentlicher Vergleich vieler Anlagen; Wärmewacht übernimmt dessen Definitionen, damit Werte vergleichbar sind.

## Lizenz

MIT
