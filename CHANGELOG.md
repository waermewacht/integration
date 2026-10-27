# Changelog

## Unveröffentlicht

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
