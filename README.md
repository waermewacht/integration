<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/waermewacht/integration/main/assets/github/readme-header-dark@2x.png">
  <img alt="Wärmewacht – Jede Kilowattstunde. Jeder Takt." src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/github/readme-header-light@2x.png" width="640">
</picture>

[![Release](https://img.shields.io/github/v/release/waermewacht/integration?color=DE5E32)](https://github.com/waermewacht/integration/releases)
[![CI](https://github.com/waermewacht/integration/actions/workflows/ci.yml/badge.svg)](https://github.com/waermewacht/integration/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-F5A623.svg)](LICENSE)

**Deutsch** · [English](https://github.com/waermewacht/integration/blob/main/README.en.md)

> **Beta.** Wärmewacht ist neu, die aktuellen Versionen sind Betas. Rückmeldungen sind willkommen, siehe [Fehler melden](#fehler-melden).

**Wie effizient arbeitet deine Wärmepumpe wirklich?** Wärmewacht berechnet in Home Assistant Arbeitszahlen je Betriebsart und Zeitraum, zählt Starts, Kurzläufe und Abtauungen und zeigt einige Diagnosewerte. Grundlage sind die Entitäten, die deine Wärmepumpe schon liefert. Wärmewacht liest nur und steuert nie. Keine Cloud, keine Netzabfragen.

> **Orientierung, keine Fachdiagnose.** Die Werte hängen davon ab, was die Zähler deiner Wärmepumpe messen. Siehe [Bilanzgrenze und Grenzen der Aussage](#bilanzgrenze-und-grenzen-der-aussage).

Die Oberfläche gibt es auf Deutsch und Englisch; sie folgt der Sprache deines Home Assistant.

## Was Wärmewacht kann

- **Arbeitszahlen** für Heizen, Warmwasser und Heizen + Warmwasser, dazu die **Leistungszahl Kühlen (EER)**, jeweils für heute, gestern, Monat, Saison und gesamt.
- **Wärme- und Strom-Sensoren je Betriebsart** und ein Sensor für den **Stillstand**, mit Langzeitstatistik für Statistik-Karten.
- **Takte:** Starts, Laufzeit, Laufzeit pro Start, Kurzläufe, kürzeste Pause, Abtauungen und ein Binärsensor **Auffälliges Takten**.
- **Diagnose:** Heizstab-Anteil, Spreizung und mittlere Vorlauftemperatur im Heizbetrieb (mit Betriebsart).
- **Warmwasser je Ladung:** Arbeitszahl der letzten Ladung und der Ladungen der letzten 30 Tage, letzte thermische Desinfektion.
- **Gesundheits-Check:** meldet gesunkene Effizienz bei gleichem Wetter und den Heizstab bei milder Witterung. Reparaturhinweise, wenn ein Zähler stillsteht, eine Quelle ausfällt oder die Außentemperatur hängt.
- **Kosten und Gasvergleich** (optional, mit festen Preisen): Stromkosten, Wärmekosten je kWh und die Ersparnis gegenüber einem Gaskessel.
- **AZ-Kennlinie und Heizlast:** Arbeitszahl Heizen über der Außentemperatur und Heizlast aus der Energiesignatur. Als Sensoren und per Aktion für beliebige Zeiträume.
- **Bericht für einen beliebigen Zeitraum** per Aktion, je Monat aufgeschlüsselt. Auch **vor der Einrichtung**, so weit die Langzeitstatistik deiner Zähler zurückreicht.
- **Vorlagen für EMS-ESP und Bosch HomeCom:** finden Bosch/Buderus-Wärmepumpen selbst und füllen die Entitäten aus. Als Beta dazu Luxtronik (alpha innotec, Novelan), Stiebel Eltron/Tecalor (ISG), Panasonic Aquarea (HeishaMon), Lambda und iDM. Andere Wärmepumpen ordnest du von Hand zu.
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

- Home Assistant 2026.4 oder neuer.
- Der Recorder (in Home Assistant standardmäßig an) für Rückblick, Bericht, AZ-Kennlinie und Heizlast.
- Mindestens eine Betriebsart mit einem **Wärmezähler** und einem **Stromzähler des Kompressors**: fortlaufende Energiesensoren in Wh, kWh oder MWh.

| Quelle | Status |
| --- | --- |
| [EMS-ESP](https://github.com/emsesp/EMS-ESP32) (MQTT) mit Bosch/Buderus-Wärmepumpen, z. B. CS5800i/CS6800i, WLW176i/WLW186i | Vorlage, erprobt an einer CS5800i/CS6800i |
| [Bosch HomeCom](https://github.com/serbanb11/bosch-homecom-hass) (`bosch_homecom`, lokal und Cloud) | Vorlage, neu, an derselben CS5800i/CS6800i mit EMS-ESP verglichen |
| beliebige Wärme- und Stromzähler | manuelle Zuordnung |

Die EMS-ESP-Vorlage erkennt die Wärmepumpe am Gerät `boiler`. Sie braucht Kompressorstatus (`hpcompon`) und die Zähler für Heizen. Sie findet die Entitäten über die Entitäten-Registry, nicht über die Entity-ID. Umbenennen und alle Namensformate von EMS-ESP sind deshalb kein Problem. Die Betriebsart (`hpactivity`) versteht sie in allen Sprachen von EMS-ESP und im Index-Format.

Die HomeCom-Vorlage braucht die Energie je Betriebsart („Wärme erzeugt Heizung“, „Strom Kompressor Heizung“ usw.). `bosch_homecom` legt diese Entitäten deaktiviert an: Aktiviere sie zuerst. Die Einrichtung zeigt, welche noch deaktiviert sind. „Kompressor läuft“ ist die Kompressordrehzahl über 0. Gegenüber EMS-ESP hat HomeCom Grenzen:

- **Tageswerte aus der Cloud:** Die Energie kommt als Summe des Tages, bis zu zwei Stunden verspätet. Wärmewacht bucht sie, wenn sie eintrifft, „heute“ hinkt also nach. Die letzten ein bis zwei Stunden eines Tages liefert die Cloud nie (beobachtet bis 0,5 kWh am Tag).
- **Stillstand:** Strom eines Abrufs, mit dem keine Wärme derselben Betriebsart kam.
- **Keine Betriebsart:** keine Abtauungen, keine Spreizung und kein mittlerer Vorlauf.
- **Kein Durchfluss:** `bosch_homecom` meldet „L/min“, liefert aber l/h.

Läuft bei dir EMS-ESP, nimm EMS-ESP: Zähler auf 0,01 kWh im Minutentakt und die Betriebsart.

## Installation

Wärmewacht wird über HACS als benutzerdefiniertes Repository installiert. Jede Version ist ein reguläres GitHub-Release, auch die Betas.

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/waermewacht/integration`, Typ *Integration*.
2. Wärmewacht suchen und herunterladen. Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Wärmewacht*.

## Einrichtung

1. **Name und Quelle:** Der Name (Vorgabe „Wärmepumpe“) wird Gerätename und Präfix der Entity-IDs. Als Quelle stehen die gefundenen Wärmepumpen zur Wahl (EMS-ESP, bei mehreren mit ihrem MQTT-Präfix; Bosch HomeCom mit der Gateway-Nummer) oder *Manuell*.
2. **Entitäten:** Mit einer Vorlage ist das Formular ausgefüllt; jedes Feld lässt sich ändern. Manuell wählst du selbst.

| Abschnitt | Feld | EMS-ESP (Standardformat) |
| --- | --- | --- |
| Heizen | Wärme Heizen (Zähler) | `sensor.boiler_nrgheat` |
| | Strom Kompressor Heizen | `sensor.boiler_meterheat` |
| | Strom Heizstab Heizen | `sensor.boiler_auxelecheatnrgconsheating` |
| Warmwasser | Wärme Warmwasser (Zähler) | `sensor.boiler_dhw_nrg` |
| | Strom Kompressor Warmwasser | `sensor.boiler_dhw_meter` |
| | Strom Heizstab Warmwasser | `sensor.boiler_dhw_auxelecheatnrgcons` |
| | Warmwasser-Temperatur | `sensor.boiler_dhw_curtemp` |
| Kühlen | Wärme Kühlen (entzogen, Zähler) | `sensor.boiler_nrgcool` |
| | Strom Kompressor Kühlen | `sensor.boiler_metercool` |
| Betrieb | Kompressor läuft | `binary_sensor.boiler_hpcompon` |
| | Betriebsart (Aktivität) | `sensor.boiler_hpactivity` |
| | Kompressorstarts gesamt | `sensor.boiler_totalcompstarts` |
| | Strom Heizstab gesamt | – |
| Messwerte | Außentemperatur | `sensor.boiler_outdoortemp` |
| | Vorlauftemperatur | `sensor.boiler_hptc1` |
| | Rücklauftemperatur | `sensor.boiler_hptc0` |
| | Durchfluss | `sensor.boiler_pc0flow` |

- Die Stromzähler je Betriebsart sind die des **Kompressors ohne Heizstab**. Den Heizstab trägst du getrennt ein: entweder je Betriebsart oder als „Strom Heizstab gesamt“, nicht beides. Der Gesamtzähler wird der Betriebsart zugerechnet, die gerade läuft oder zuletzt lief. Ohne Betriebsart zählt er zum Heizen.
- Die Vorlage nimmt Zähler mit 0,01 kWh, wenn es sie gibt, sonst die ganzzahligen (z. B. `sensor.boiler_nrgsuppheating`). Den Heizstab je Betriebsart liefert EMS-ESP nur in ganzen kWh.
- Ohne „Kompressor läuft“ gibt es keine Takte. Ohne „Betriebsart“ keine Abtauungen, keine Spreizung und kein mittlerer Vorlauf. „Kompressor läuft“ darf ein Binärsensor oder eine Drehzahl bzw. Modulation sein (läuft bei über 0). Bei manueller Zuordnung versteht Wärmewacht die Werte von EMS-ESP: `0`–`7` oder Texte wie „Heizen“, „Warmwasser“, „Abtauen“ bzw. `heating`, `hot water`, `defrost`.
- Die Außentemperatur nutzen [AZ-Kennlinie und Heizlast](#kennlinie-und-heizlast). Wärmewacht liest ihre Stundenmittel aus der Langzeitstatistik; der Sensor braucht also eine Statistik (`state_class: measurement`). Den Durchfluss kannst du schon zuordnen, er wird aber noch nicht ausgewertet.

- **Betriebsart aus mehreren Entitäten** (Abschnitt eingeklappt): Hat die Wärmepumpe keine einzelne Betriebsart-Entität, sondern Merker (an/aus) für Abtauen, Warmwasser, Kühlen und Heizen, trägst du diese ein. Ein Merker „an“ gewinnt in dieser Reihenfolge: Abtauen, Warmwasser, Kühlen, Heizen. Die *eingestellte Betriebsart* (z. B. „Cool“) macht aus Heizen Kühlen, wenn die Betriebsart-Entität nur zwischen Heizen und Warmwasser unterscheidet (Umschaltventil). Die Vorlagen für Stiebel und HeishaMon füllen das aus.

Mehrere Wärmepumpen: je einen Eintrag anlegen.

### Einstellungen

*Wärmewacht → Eintrag → Zahnrad (Konfigurieren)*. Jede Änderung lädt den Eintrag neu. Die Felder in der Reihenfolge des Formulars:

| Einstellung | Vorgabe | Bedeutung |
| --- | --- | --- |
| Mindeststrom für eine Arbeitszahl | 0,5 kWh | Darunter ist die Arbeitszahl unbekannt statt zufällig. |
| Kurzlauf unter | 10 min | Fraunhofer ISE weist Zyklen unter etwa 10 Minuten gesondert aus. |
| Kritischer Lauf unter | 6 min | Mindestlaufzeit laut Dimplex-Projektierungshandbuch etwa 6 Minuten. |
| Auffällig ab Starts pro Stunde über | 3 | Mehr Starts innerhalb einer Stunde gelten als auffällig. Verdichterhersteller nennen 6 bis 12 Starts pro Stunde als Obergrenze. |
| Saison beginnt im | Juli | Beginn der Saison (Heizperiode Juli bis Juni). |
| ***Gesundheits-Check*** | | |
| Heizstab: milde Witterung ab | 5 °C | Tagesmittel der Außentemperatur, ab dem die Wärmepumpe allein heizen sollte (eigene Annahme). |
| Thermische Desinfektion ab | 60 °C | Warmwasser-Temperatur, ab der eine Ladung als thermische Desinfektion zählt. DVGW W 551 verlangt 60 °C am Austritt; der Speicherfühler zeigt oft etwas weniger. |
| Effizienz gesunken ab | 15 % | Rückgang der AZ Heizen gegenüber der Vorsaison bei gleicher Außentemperatur; aus erst 5 Punkte darunter (eigene Annahme). |
| ***Kosten und Gasvergleich (optional)*** | | |
| Strompreis | – | ct/kWh brutto. Ohne ihn gibt es keine Kosten-Sensoren. |
| Strom-Grundpreis | – | €/Jahr brutto, nur bei eigenem Wärmepumpenzähler (Wärmepumpentarif). Am Haushaltszähler leer lassen: Dessen Grundpreis fällt ohnehin an. |
| Gas-Arbeitspreis | – | ct/kWh brutto auf den Brennwert (wie auf der Gasrechnung). Für die Ersparnis gegenüber einem Gaskessel. |
| Gas-Grundpreis | – | €/Jahr brutto, anteilig je Tag. Ohne ihn vergleicht Wärmewacht nur die Arbeitspreise. |
| ***Heizlast (optional)*** | | |
| Normaußentemperatur | – | °C nach DIN/TS 12831-1 für deine Postleitzahl (z. B. BWP-Klimakarte). Für die Heizlast bei Normaußentemperatur. |

Jedes optionale Feld darf leer bleiben. Quellen der Vorgaben in [docs/ENTWICKLUNG.md](docs/ENTWICKLUNG.md). Wird der Saisonbeginn geändert, berechnet Wärmewacht die laufende Saison aus der Langzeitstatistik neu (Stillstand vor der Einrichtung stundenweise geschätzt).

### Neu konfigurieren

*Wärmewacht → ⋮ → Neu konfigurieren* zeigt das Entitäten-Formular erneut, mit der bisherigen Zuordnung. Die bisher gebuchten Werte bleiben. Ein neu hinzugefügter Zähler zählt ab diesem Zeitpunkt.

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
| Strom Heizen / Warmwasser / Kühlen | kWh | Strom bei laufendem Kompressor, mit Heizstab, ohne Stillstand |
| Strom Stillstand | kWh | Strom bei stehendem Kompressor, alle Betriebsarten |

Alle mit Langzeitstatistik (`total_increasing`). Jeder Sensor entsteht nur, wenn der passende Zähler zugeordnet ist. Bitte nicht deaktivieren: Bericht, AZ-Kennlinie und Heizlast lesen ihre Statistik für die Zeit nach der Einrichtung.

**Statistik vor der Einrichtung:** Einmal nach der Einrichtung (bei älteren Einträgen beim Update) schreibt Wärmewacht die Stunden davor in die Statistik dieser Sensoren. Sie sind aus der Statistik deiner Zähler berechnet, mit stundenweise geschätztem Stillstand. Statistik-Karten zeigen damit auch die Monate vor der Einrichtung. Wärmewacht schreibt nur Stunden vor der ersten Zeile, die Home Assistant selbst aufgezeichnet hat. Etwa 15 Minuten nach dem Start hebt Wärmewacht die Summen ab der ersten importierten Stunde einmalig an. So beginnen sie bei 0, und der erste Balken einer Statistik-Karte ist nicht negativ. Die Änderung je Stunde bleibt dabei gleich. Die Stunde der Einrichtung fehlt bis zum Einrichtungszeitpunkt.

**Stillstand:** Strom einer Betriebsart gilt als Stillstand, wenn seit dem letzten Zählerwert weder Wärme dieser Betriebsart kam noch der Kompressor in ihr lief. Ohne Kompressorstatus entscheidet nur die Wärme.

### Takte

Die meisten Takt-Sensoren brauchen „Kompressor läuft“. Abtauungen brauchen nur die Betriebsart. „Starts gesamt“ gibt es auch, wenn nur der Startzähler der Wärmepumpe zugeordnet ist.

| Entität | Einheit | Bedeutung |
| --- | --- | --- |
| Starts heute, Starts gestern | – | beobachtete Kompressorstarts |
| Starts gesamt | – | Zähler der Wärmepumpe, wenn zugeordnet (Attribut `source: heat_pump`), sonst beobachtete Starts seit der Einrichtung (`since_setup`) |
| Laufzeit heute | h | Kompressor-Laufzeit |
| Laufzeit pro Start heute, 7 Tage, Monat | min | mittlere Dauer der Läufe, die im Zeitraum endeten |
| Kurzläufe heute | – | Läufe unter der Kurzlauf-Grenze; Attribute `threshold_minutes`, `critical_runs`, `critical_threshold_minutes` |
| Kürzeste Pause heute | min | kürzeste Zeit zwischen Ende und nächstem Start |
| Abtauungen heute | – | Anzahl; Attribute `minutes` (Dauer heute) und `yesterday` (Anzahl gestern) |

Fehlte der Kompressorstatus länger als 5 Minuten (Home Assistant oder Quelle aus), gilt der betroffene Lauf als unsicher. Er zählt dann nicht für Laufzeit pro Start, Kurzläufe und Pausen.

### Auffälliges Takten

Binärsensor (Problem), nur mit „Kompressor läuft“. Er ist an, wenn in den letzten 24 Stunden

- innerhalb einer Stunde mehr Starts lagen als eingestellt (Vorgabe: mehr als 3) **oder**
- mindestens 3 Läufe kürzer waren als der kritische Lauf (Vorgabe: 6 Minuten).

Attribute: `max_starts_per_hour`, `critical_runs_24h`, `short_runs_24h`, `starts_per_hour_limit`.

### Warmwasser-Ladungen

Eine Ladung ist ein zusammenhängender Zeitraum mit der Betriebsart Warmwasser. Eine Abtauung dazwischen beendet sie nicht. Wärme und Strom der Ladung kommen aus den Warmwasser-Zählern, ohne Stillstand. Was die Zähler bis 5 Minuten nach dem Ende melden, zählt noch dazu. Wärmewacht hält die Ladungen 40 Tage.

| Entität | Bedeutung | Braucht |
| --- | --- | --- |
| AZ Warmwasser letzte Ladung | Wärme durch Strom (Kompressor und Heizstab) der zuletzt beendeten Ladung. Attribute: `start`, `minutes`, `heat_kwh`, `electricity_kwh`, `aux_kwh`, `start_temp`, `max_temp`, `disinfection`, `uncertain` | Warmwasser vollständig und Betriebsart, Zähler laufend (nicht Bosch HomeCom: Tageswerte kommen zu spät) |
| AZ Warmwasser-Ladungen 30 Tage | dasselbe über die normalen Ladungen der letzten 30 Tage, ohne thermische Desinfektion. Attribute: `charges`, `uncertain`, `mean_minutes`, `mean_heat_kwh`, `mean_lift` (Temperaturhub in K), `aux_share`, `disinfections` | ebenso |
| Letzte thermische Desinfektion | Zeitpunkt, an dem der Speicher zuletzt die eingestellte Temperatur erreicht hat (Vorgabe 60 °C nach DVGW W 551). Eine neue zählt erst, wenn er dazwischen 5 K darunter war. | Warmwasser-Temperatur |

`uncertain`: Die Betriebsart war während der Ladung unbekannt, oder Home Assistant lief nicht. Solche Ladungen zählen in der AZ mit, aber nicht in Dauer, Wärme und Hub je Ladung.

### Gesundheits-Check

Wärmewacht prüft einmal täglich (gegen 3 Uhr) Auffälligkeiten, die Geld kosten oder auf einen Defekt hindeuten. Er sagt, **was** auffällt und **woran** das zu sehen ist, nicht **warum**. Reichen die Daten nicht, ist ein Sensor *unbekannt* und nennt im Attribut `reason` den Grund, nie „aus“ mangels Daten. Hergeleitet und belegt in [docs/GESUNDHEITSCHECK.md](docs/GESUNDHEITSCHECK.md).

| Binärsensor (Problem) | An, wenn | Braucht |
| --- | --- | --- |
| Effizienz gesunken | Die Arbeitszahl Heizen der laufenden Saison liegt bei gleicher Außentemperatur mindestens 15 % unter der Vorsaison (einstellbar). Aus erst wieder 5 Punkte darunter. | Heizen vollständig und Außentemperatur |
| Heizstab bei Warmwasserladungen | Der Heizstab hat in den letzten 30 Tagen mehr als 10 % des Stroms normaler [Warmwasser-Ladungen](#warmwasser-ladungen) gebraucht (ohne thermische Desinfektion, mindestens 10 Ladungen). | Ladungen, Warmwasser-Temperatur und ein Heizstab-Zähler |
| Heizstab bei milder Witterung | Der Heizstab hat in den letzten 7 Tagen an Tagen ab 5 °C Tagesmittel (einstellbar) zusammen mindestens 2 kWh fürs Heizen gebraucht. | dazu ein Heizstab-Zähler |

- **Gleiches Wetter:** Verglichen wird je 2-K-Klasse der [AZ-Kennlinie](#kennlinie-und-heizlast), gewichtet mit der Wärme der laufenden Saison. Hat eine Saison Klassen zusammengefasst (am Saisonanfang mit wenigen Tagen üblich), zählt Wärmewacht die Klassen der anderen über denselben Bereich zusammen. Nötig sind mindestens 4 K gemeinsamer Bereich mit zusammen 14 Tagen und 10 kWh Strom.
- **Attribute:** Effizienz: `ratio_current`, `ratio_previous_same_weather`, `drop_percent`, `threshold_percent` und `classes` (je Klasse Tage und AZ beider Saisons). Heizstab: `aux_kwh_7d`, `mild_days_7d`, `min_outdoor_temp`, `threshold_kwh` und `days` (je milder Tag). Die Listen werden nicht aufgezeichnet.
- **Gründe für *unbekannt*:** `not_analysed_yet` (nach dem Start), `no_previous_season`, `too_few_classes`, `too_few_days`, `too_little_electricity`, `comparison_restarted`, `too_few_charges`.
- **Effizienzvergleich neu starten** (Schaltfläche, Konfiguration): nach einer gewollten Änderung, etwa einer neuen Heizkurve. Die nächsten 28 Tage werden die neue Vergleichsbasis, bis dahin ist „Effizienz gesunken“ unbekannt.
- **Datenfehler** (Zähler steht still, Quelle nicht erreichbar, Außentemperatur unbrauchbar) meldet Wärmewacht als [Reparaturhinweis](#fehlerbehebung), nicht als Sensor.
- **Tagebuch:** Wärmewacht legt um Mitternacht einen Eintrag für den Vortag an (Außentemperatur, Starts, Laufzeit je Betriebsart, Kurzläufe, Abtauungen, Spreizung, Vorlauf, Energie), bis zu 3 Jahre. Es steht in der Verlaufsdatei und wird nur einmal am Tag geschrieben. Spätere Prüfungen werten es aus.

### Diagnose

| Entität | Einheit | Bedeutung | Braucht |
| --- | --- | --- | --- |
| Heizstab-Anteil Monat, Saison | % | Anteil des Heizstabs am Strom für Heizen und Warmwasser (mit Stillstand) | Heizstab-Zähler |
| Spreizung heute | K | Vorlauf minus Rücklauf, zeitgewichtet über die Zeit mit Kompressor im Heizbetrieb | Vorlauf, Rücklauf und Betriebsart |
| Vorlauftemperatur heute | °C | mittlere Vorlauftemperatur, ebenso gewichtet | Vorlauf und Betriebsart |

### Kosten und Gasvergleich

Mit einem Strompreis in den [Einstellungen](#einstellungen) und Heizen oder Warmwasser vollständig zugeordnet.

| Entität | Einheit | Bedeutung | Braucht |
| --- | --- | --- | --- |
| Stromkosten Monat, Saison | € | aller Strom der Wärmepumpe (alle Betriebsarten, Stillstand, Heizstab) × Strompreis, plus anteiliger Strom-Grundpreis | Strompreis |
| Wärmekosten je kWh Saison | €/kWh | Kosten für Heizen und Warmwasser (Strom mit Stillstand, anteiliger Strom-Grundpreis) je kWh Wärme; unter 0,5 kWh Wärme unbekannt | Strompreis |
| Ersparnis ggü. Gaskessel Saison | € | Gaskosten (Arbeitspreis plus anteiliger Gas-Grundpreis) für dieselbe Wärme minus die Kosten der Wärmepumpe für Heizen und Warmwasser (Strom mit Stillstand, anteiliger Strom-Grundpreis) | Strompreis und Gas-Arbeitspreis |

- **Preise** gelten fest, so wie sie in den Einstellungen stehen. Dynamische Tarife berücksichtigt Wärmewacht nicht.
- **Grundpreise** werden je Tag verteilt (Jahrespreis ÷ 365 bzw. 366). Der Strom-Grundpreis zählt nur bei eigenem Wärmepumpenzähler und gehört zu Heizen und Warmwasser.
- **Gaskessel:** Er bräuchte für dieselbe Wärme (Heizen und Warmwasser, ohne Kühlen) Wärme ÷ 0,87 an Gas, bezogen auf den Brennwert. 0,87 ist der Nutzungsgrad, den Feldmessungen an Brennwertkesseln ergeben haben (Jagnow/Wolff, DBU 2004). Gas wird nach Brennwert abgerechnet, deshalb gilt der Wert auf den Brennwert.
- **Kein CO₂-Vergleich:** Er hinge zu stark an Annahmen (Durchschnitts- oder Stundenmix, Vorketten, PV-Eigenverbrauch, Batterie, Ökostrom).

Attribute von „Ersparnis ggü. Gaskessel Saison“:

| Attribut | Bedeutung |
| --- | --- |
| `heat_kwh` | Wärme Heizen und Warmwasser in der Saison |
| `heat_pump_cost_eur` | Kosten der Wärmepumpe für diese Wärme (Strom mit Stillstand, anteiliger Strom-Grundpreis) |
| `electricity_base_cost_eur` | darin enthaltener anteiliger Strom-Grundpreis (0 ohne Einstellung) |
| `gas_kwh` | Gas für dieselbe Wärme, auf den Brennwert |
| `gas_cost_eur` | Gaskosten mit anteiligem Grundpreis |
| `gas_base_cost_eur` | darin enthaltener anteiliger Gas-Grundpreis (0 ohne Einstellung) |
| `boiler_efficiency` | Kesselnutzungsgrad auf den Brennwert (0,87) |

### Kennlinie und Heizlast

Beide brauchen die Außentemperatur sowie Wärme und Strom Heizen, dazu den Recorder. Wärmewacht rechnet 2 Minuten nach dem Start und dann täglich ab 3 Uhr, aus der Langzeitstatistik (vor der Einrichtung aus der Statistik deiner Zähler, wie der [Bericht](#bericht)). Die Ergebnisse liegen nur im Speicher. Nach einem Neustart sind die Sensoren deshalb etwa 2 Minuten leer.

| Entität | Einheit | Bedeutung |
| --- | --- | --- |
| AZ-Kennlinie Heizen | Zeitpunkt | Wann zuletzt gerechnet wurde. Die Kennlinie steht in den Attributen. |
| Heizlast je Kelvin | W/K | Steigung der Energiesignatur der letzten vollständigen Saison. |
| Heizlast bei Normaußentemperatur | kW | Heizlast „normgerecht“ (Gerade durch 0 bei 20 °C). Nur mit der Einstellung Normaußentemperatur. |
| Gradtage Saison | K·d | Gradtagzahl G20/15 nach VDI 3807 seit Saisonbeginn bis gestern: je Tag 20 °C minus Tagesmittel, nur an Tagen unter 15 °C. Als Zähler: Eine Statistik-Karte zeigt damit die Gradtage je Monat. Attribute `days_counted`, `days_missing` (unter 20 Stundenwerten), `days_without_heating`. |
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
| `start` | Beginn der letzten vollständigen Saison | |
| `end` | Ende der letzten vollständigen Saison; mit `start`: jetzt | |
| `design_outdoor_temp` | Normaußentemperatur aus den Einstellungen | °C, für `measured_kw` und `standard_kw` |

Die Antwort enthält dieselben Werte wie die Attribute von „Heizlast je Kelvin“.

AZ-Kennlinie und Heizlast melden einen Fehler, wenn keine Außentemperatur zugeordnet ist oder der Recorder fehlt.

## Dashboard-Beispiele

Die Entity-IDs hängen vom Namen des Eintrags ab (hier die Vorgabe „Wärmepumpe“). Eine Karte fügst du so hinzu: *Dashboard bearbeiten → Karte hinzufügen → Manuell*.

### Statistik-Karte: Wärme und Strom je Monat

Eine Arbeitszahl je Monat liefert der [Bericht](#bericht). Wärme und Strom je Monat zeigt eine Statistik-Karte:

```yaml
type: statistics-graph
title: Heizen je Monat
chart_type: bar
period: month
stat_types:
  - change
days_to_show: 365
entities:
  - entity: sensor.warmepumpe_warme_heizen
    name: Wärme
  - entity: sensor.warmepumpe_strom_heizen
    name: Strom
```

### AZ-Kennlinie und Energiesignatur

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
- **Abtauen:** Ob die Wärmezähler von Bosch die beim Abtauen entzogene Wärme abziehen, ist nicht geklärt.
- **Rückblick:** Den Stillstand vor der Einrichtung schätzt Wärmewacht stundenweise (siehe [Bericht](#bericht)). In den Sensoren fehlt die angebrochene Stunde der Einrichtung: Die Langzeitstatistik hat für sie noch keinen Wert.
- **Lücken:** Lief Home Assistant nicht, bucht der erste Zählerwert danach den ganzen Zuwachs. Ob das Lauf oder Stillstand war, entscheidet die Wärme im selben Zeitraum.

## Fehlerbehebung

Wärmewacht meldet Probleme unter *Einstellungen → Reparaturen*. Das geschieht frühestens 10 Minuten nach dem Start, damit Entitäten nach einem Neustart Zeit haben.

- **Entität fehlt:** Eine zugeordnete Entität gibt es nicht mehr, z. B. nach Umbenennen. Unter *Wärmewacht → ⋮ → Neu konfigurieren* wieder auswählen.
- **Unbrauchbare Einheit:** Ein Energiezähler meldet nicht Wh, kWh oder MWh. Seine Werte werden nicht gezählt, bis die Einheit passt.
- **Zähler steht still:** Der Kompressor lief, aber ein Zähler der laufenden Betriebsart stieg nicht: 1 Stunde bei Zählern mit Nachkommastellen, 6 Stunden bei ganzen kWh oder Tageswerten. Meist liefert die Quelle keine Werte mehr, die Entität ist deaktiviert oder der falsche Zähler zugeordnet.
- **Quelle nicht erreichbar:** Eine zugeordnete Entität ist seit mehr als 60 Minuten `unavailable`. Quelle prüfen (EMS-ESP, MQTT, Cloud).
- **Außentemperatur unbrauchbar:** Sie hat sich 48 Stunden nicht verändert oder lag gestern Stunden außerhalb von −35 bis +45 °C. Davon hängen Kennlinie, Heizlast und der Gesundheits-Check ab.

Die Meldungen verschwinden von selbst, wenn das Problem behoben ist.

Weiteres:

- **Arbeitszahl bleibt unbekannt:** Im Zeitraum gab es keine Wärme oder weniger Strom als den Mindeststrom. Das ist im Sommer beim Heizen normal.
- **Keine Takte:** „Kompressor läuft“ ist nicht zugeordnet.
- **Kennlinie oder Heizlast leer:** Nach einem Neustart etwa 2 Minuten warten. Hat die Außentemperatur keine Langzeitstatistik, bleiben beide leer. Bei der Heizlast nennt das Attribut `reasons`, was fehlt.
- **Diagnose:** *Wärmewacht → Eintrag → ⋮ → Diagnosedaten herunterladen*. **Debug-Protokoll:** *Wärmewacht → ⋮ → Debug-Protokoll aktivieren*.

## Datenschutz

Wärmewacht rechnet lokal, liest nur die Entitäten, die du zuordnest, und fragt nichts im Netz ab. Gespeichert werden je Eintrag die gebuchte Energie und die Läufe der letzten 40 Tage. Die Diagnose-Datei enthält Zuordnung, Einstellungen, die aktuellen Zustände der Quell-Entitäten (also Zählerstände) und Energiesummen, aber nicht den Namen des Eintrags. Unter `source` listet sie alle Entitäten der Quellgeräte mit Hersteller, Modell und Firmware; Seriennummern und Eintrags-IDs darin sind durch erfundene Werte gleicher Länge ersetzt, Gerätenamen und Bereiche fehlen. Prüfe sie, bevor du sie öffentlich teilst.

## Entfernen

1. *Einstellungen → Geräte & Dienste → Wärmewacht* → beim Eintrag ⋮ → *Löschen*. Die gespeicherten Werte und Reparaturmeldungen dieses Eintrags werden mit gelöscht.
2. Optional: HACS → Wärmewacht → ⋮ → *Entfernen*, dann Home Assistant neu starten.

Die Langzeitstatistik der gelöschten Sensoren bleibt in Home Assistant erhalten, bis du sie unter *Einstellungen → Werkzeuge → Statistik* (früher *Entwicklerwerkzeuge*) entfernst.

## Fehler melden

Bitte als [Issue](https://github.com/waermewacht/integration/issues), am besten mit Diagnose-Datei, dem Modell der Wärmepumpe und den Versionen von Home Assistant, Wärmewacht und gegebenenfalls EMS-ESP. Sicherheitslücken bitte vertraulich melden, siehe [SECURITY.md](SECURITY.md).

**Wärmepumpe ohne Vorlage?** Richte Wärmewacht manuell ein (mindestens Wärme und Strom Heizen und „Kompressor läuft“) und hänge die Diagnose-Datei an ein Issue. Unter `source` stehen dann alle Entitäten der Geräte dahinter, mit Plattform, unique_id, Einheit und Zustand. Daraus lässt sich eine Vorlage bauen.

## Verwandte Projekte

- [home-assistant-heat-pump-performance](https://github.com/vandecook/home-assistant-heat-pump-performance): Arbeitszahlen aus Wärme- und Stromzähler, herstellerneutral.
- [daikin_cycle_ml](https://github.com/elRadix/daikin_cycle_ml): umfangreiche Auswertung für Daikin Altherma mit ESPAltherma. Für Daikin die passende Wahl.
- [heatpumpmonitor.org](https://heatpumpmonitor.org/): öffentlicher Vergleich vieler Anlagen. Wärmewacht nutzt dieselben Begriffe (SEPEMO-Bilanzgrenzen, Starts), damit sich Werte einordnen lassen.

## Lizenz

MIT
