<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/waermewacht/integration/main/assets/github/readme-header-dark@2x.png">
  <img alt="Wärmewacht – Jede Kilowattstunde. Jeder Takt." src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/github/readme-header-light@2x.png" width="640">
</picture>

[![Release](https://img.shields.io/github/v/release/waermewacht/integration?color=DE5E32)](https://github.com/waermewacht/integration/releases)
[![CI](https://github.com/waermewacht/integration/actions/workflows/ci.yml/badge.svg)](https://github.com/waermewacht/integration/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-F5A623.svg)](LICENSE)

**Deutsch** · [English](https://github.com/waermewacht/integration/blob/main/README.en.md)

> **Beta, im Aufbau.** Wärmewacht ist neu und noch nicht für den Alltag gedacht. Es gibt noch kein Release. Rückmeldungen sind willkommen – siehe [Fehler melden](#fehler-melden).

**Wie effizient arbeitet deine Wärmepumpe wirklich?** Wärmewacht berechnet in Home Assistant Arbeitszahlen je Betriebsart und Zeitraum, zählt Starts, Kurzläufe und Abtauungen und zeigt einige Diagnosewerte. Grundlage sind die Entitäten, die deine Wärmepumpe schon liefert. Wärmewacht liest nur und steuert nie. Keine Cloud, keine Netzabfragen.

> **Orientierung, keine Fachdiagnose.** Die Werte hängen davon ab, was die Zähler deiner Wärmepumpe messen – siehe [Bilanzgrenze und Grenzen der Aussage](#bilanzgrenze-und-grenzen-der-aussage).

Die Oberfläche gibt es auf Deutsch und Englisch; sie folgt der Sprache deines Home Assistant.

## Was Wärmewacht kann

- **Arbeitszahlen** für Heizen, Warmwasser und Heizen + Warmwasser, dazu die **Leistungszahl Kühlen (EER)** – jeweils für heute, gestern, Monat, Saison und gesamt.
- **Wärme- und Strom-Sensoren je Betriebsart** und ein Sensor für den **Stillstand**, mit Langzeitstatistik für Statistik-Karten.
- **Takte:** Starts, Laufzeit, Laufzeit pro Start, Kurzläufe, kürzeste Pause, Abtauungen und ein Binärsensor **Auffälliges Takten**.
- **Diagnose:** Heizstab-Anteil, Spreizung und mittlere Vorlauftemperatur im Heizbetrieb.
- **Bericht für einen beliebigen Zeitraum** per Aktion, je Monat aufgeschlüsselt – auch **vor der Einrichtung**, so weit die Langzeitstatistik deiner Zähler zurückreicht.
- **Vorlage für EMS-ESP:** findet Bosch/Buderus-Wärmepumpen selbst und füllt die Entitäten aus. Andere Wärmepumpen ordnest du von Hand zu.
- **Schont SD-Karten:** schreibt höchstens alle 10 Minuten, am Ende eines Laufs, um Mitternacht und beim Beenden. Die Sensoren aktualisieren sich einmal pro Minute und bei Ereignissen.

## Was Wärmewacht anders macht als Template-Sensoren

- **Arbeitszahl eines Zeitraums = Σ Wärme / Σ Strom**, nie der Mittelwert von Tageswerten.
- **Unbekannt statt 0:** Ohne Wärme oder unter dem Mindeststrom (Vorgabe 0,5 kWh) ist eine Arbeitszahl unbekannt. Nullen würden Mittelwerte und Statistiken nach unten ziehen.
- **Stillstand getrennt:** Strom bei stehendem Kompressor zählt nicht in die Arbeitszahl je Betriebsart, wohl aber in die Arbeitszahl Heizen + Warmwasser. So rechnet auch das Fraunhofer ISE in seinen Feldtests.
- **Kühlen nie in der Jahresarbeitszahl.** Es hat eine eigene Leistungszahl (EER).
- **Takte aus echten Läufen** des Kompressors: Ein Neustart von Home Assistant mitten im Lauf ist kein neuer Start. Wechselt die Wärmepumpe ohne Stopp von Heizen auf Warmwasser, bleibt es ein Lauf. Ein Lauf, der beim ersten Blick schon lief, zählt nicht als Start.
- **Zähler-Resets und Rücksprünge:** Rücksprünge – Rauschen und das Abtauen, bei dem die Wärmepumpe die entzogene Wärme abzieht – halten den Höchststand, gebucht wird nur Wärme darüber (netto). Erst ein Rückgang um mehr als 10 % und mehr als 1 kWh gilt als Reset mit neuer Basis, unplausible Sprünge werden nicht gebucht. `unknown` und `unavailable` gelten nie als 0.
- **Rückblick aus der Langzeitstatistik:** Heute, gestern, Monat, Saison und gesamt enthalten schon bei der Einrichtung die Werte der Zeit davor.

## Voraussetzungen

- Home Assistant 2026.4 oder neuer.
- Der Recorder (in Home Assistant standardmäßig an) für Rückblick und Bericht.
- Mindestens eine Betriebsart mit einem **Wärmezähler** und einem **Stromzähler des Kompressors**: fortlaufende Energiesensoren in Wh, kWh oder MWh.

| Quelle | Status |
| --- | --- |
| [EMS-ESP](https://github.com/emsesp/EMS-ESP32) (MQTT) mit Bosch/Buderus-Wärmepumpen, z. B. CS5800i/CS6800i, WLW176i/WLW186i | Vorlage, erprobt an einer CS5800i/CS6800i |
| Bosch HomeCom (`bosch_homecom`) | Vorlage folgt |
| beliebige Wärme- und Stromzähler | manuelle Zuordnung |

Die EMS-ESP-Vorlage erkennt die Wärmepumpe am Gerät `boiler`. Sie braucht Kompressorstatus (`hpcompon`) und die Zähler für Heizen. Sie findet die Entitäten über die Entitäten-Registry, nicht über die Entity-ID – Umbenennen und alle Namensformate von EMS-ESP sind kein Problem. Die Betriebsart (`hpactivity`) versteht sie in allen Sprachen von EMS-ESP und im Index-Format.

## Installation

Installierbar ab dem ersten Release.

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/waermewacht/integration`, Typ *Integration*.
2. Wärmewacht suchen und herunterladen. Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Wärmewacht*.

## Einrichtung

1. **Name und Quelle:** Der Name (Vorgabe „Wärmepumpe“) wird Gerätename und Präfix der Entity-IDs. Als Quelle stehen die gefundenen EMS-ESP-Wärmepumpen zur Wahl, bei mehreren EMS-ESP mit ihrem MQTT-Präfix, oder *Manuell*.
2. **Entitäten:** Mit einer Vorlage ist das Formular ausgefüllt; jedes Feld lässt sich ändern. Manuell wählst du selbst.

| Abschnitt | Feld | EMS-ESP (Standardformat) |
| --- | --- | --- |
| Heizen | Wärme Heizen (Zähler) | `sensor.boiler_nrgheat` |
| | Strom Kompressor Heizen | `sensor.boiler_meterheat` |
| | Strom Heizstab Heizen | `sensor.boiler_auxelecheatnrgconsheating` |
| Warmwasser | Wärme Warmwasser (Zähler) | `sensor.boiler_dhw_nrg` |
| | Strom Kompressor Warmwasser | `sensor.boiler_dhw_meter` |
| | Strom Heizstab Warmwasser | `sensor.boiler_dhw_auxelecheatnrgcons` |
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

- Die Stromzähler je Betriebsart sind die des **Kompressors ohne Heizstab**. Den Heizstab trägst du getrennt ein: entweder je Betriebsart oder als „Strom Heizstab gesamt“, nicht beides. Der Gesamtzähler wird der Betriebsart zugerechnet, die gerade läuft.
- Die Vorlage nimmt Zähler mit 0,01 kWh, wenn es sie gibt, sonst die ganzzahligen (z. B. `sensor.boiler_nrgsuppheating`). Den Heizstab je Betriebsart liefert EMS-ESP nur in ganzen kWh.
- Ohne „Kompressor läuft“ gibt es keine Takte. Ohne „Betriebsart“ keine Abtauungen. Bei manueller Zuordnung versteht Wärmewacht die Werte von EMS-ESP: `0`–`7` oder Texte wie „Heizen“, „Warmwasser“, „Abtauen“ bzw. `heating`, `hot water`, `defrost`.
- Außentemperatur und Durchfluss werden schon zugeordnet, aber erst in einer späteren Version ausgewertet.

Mehrere Wärmepumpen: je einen Eintrag anlegen.

### Einstellungen

*Wärmewacht → Eintrag → Zahnrad (Konfigurieren)*. Jede Änderung lädt den Eintrag neu.

| Einstellung | Vorgabe | Bedeutung |
| --- | --- | --- |
| Mindeststrom für eine Arbeitszahl | 0,5 kWh | Darunter ist die Arbeitszahl unbekannt statt zufällig. |
| Kurzlauf unter | 10 min | Fraunhofer ISE weist Zyklen unter etwa 10 Minuten gesondert aus. |
| Kritischer Lauf unter | 6 min | Mindestlaufzeit laut Dimplex-Projektierungshandbuch etwa 6 Minuten. |
| Auffällig ab Starts pro Stunde über | 3 | Mehr Starts innerhalb einer Stunde gelten als auffällig. Verdichterhersteller nennen 6 bis 12 Starts pro Stunde als Obergrenze. |
| Saison beginnt im | Juli | Beginn der Saison (Heizperiode Juli bis Juni). |

Quellen der Vorgaben in [docs/ENTWICKLUNG.md](docs/ENTWICKLUNG.md). Wird der Saisonbeginn geändert, berechnet Wärmewacht die laufende Saison aus der Langzeitstatistik neu (Stillstand vor der Einrichtung stundenweise geschätzt).

### Neu konfigurieren

*Wärmewacht → ⋮ → Neu konfigurieren* zeigt das Entitäten-Formular erneut, mit der bisherigen Zuordnung. Die bisher gebuchten Werte bleiben. Ein neu hinzugefügter Zähler zählt ab diesem Zeitpunkt.

## Entitäten

Alle Entitäten hängen an einem eigenen Gerät je Wärmepumpe. Welche entstehen, hängt von den zugeordneten Signalen ab.

### Arbeitszahlen

| Entität | Braucht |
| --- | --- |
| AZ Heizen *Zeitraum* | Wärme und Strom Heizen |
| AZ Warmwasser *Zeitraum* | Wärme und Strom Warmwasser |
| AZ Heizen+WW *Zeitraum* | Heizen oder Warmwasser vollständig |
| EER Kühlen *Zeitraum* (Leistungszahl) | Wärme und Strom Kühlen |

*Zeitraum* ist **heute**, **gestern**, **Monat**, **Saison** oder **gesamt** – zusammen bis zu 20 Sensoren ohne Einheit („AZ“ = Arbeitszahl). Ihr Verlauf erscheint auch in der Statistik – dort als Zeitmittel des Sensors, nicht als Bilanz; die Bilanz liefern die Energie-Sensoren und der Bericht. Heute und gestern schwanken stark und sind deshalb standardmäßig deaktiviert. „Gesamt“ reicht so weit zurück wie die Langzeitstatistik deiner Zähler bei der Einrichtung.

- Arbeitszahl je Betriebsart = Wärme / Strom (Kompressor plus Heizstab), **ohne** Stillstand.
- Heizen + Warmwasser = Wärme beider / (Strom beider + Stillstand). Das entspricht einer Jahresarbeitszahl.

Attribute:

| Attribut | Bedeutung |
| --- | --- |
| `heat_kwh` | Wärme im Zeitraum |
| `electricity_kwh` | Strom im Zeitraum (Kompressor plus Heizstab, ohne Stillstand) |
| `standby_kwh` | Stillstand im Zeitraum (nur Heizen + Warmwasser) |
| `period_start` | Beginn des Zeitraums (bei „gesamt“ leer) |
| `counter_step_kwh` | Auflösung des gröbsten beteiligten Zählers: 0,01 oder 1 kWh |
| `reliable` | `true`, wenn die Rundung der Zähler höchstens 5 % des Stroms ausmacht |

Die Sensoren haben bewusst keine Langzeitstatistik: Home Assistant würde Quotienten mitteln. Für Monats- oder Jahreswerte gibt es die Energie-Sensoren und den [Bericht](#bericht-für-einen-zeitraum).

### Energie

| Entität | Einheit | Bedeutung |
| --- | --- | --- |
| Wärme Heizen / Warmwasser / Kühlen | kWh | Wärme seit der Einrichtung (beim Kühlen: entzogene Wärme) |
| Strom Heizen / Warmwasser / Kühlen | kWh | Strom bei laufendem Kompressor, mit Heizstab, ohne Stillstand |
| Strom Stillstand | kWh | Strom bei stehendem Kompressor, alle Betriebsarten |

Alle mit Langzeitstatistik (`total_increasing`). Jeder Sensor entsteht nur, wenn der passende Zähler zugeordnet ist. Bitte nicht deaktivieren: Der Bericht liest ihre Statistik für die Zeit nach der Einrichtung.

**Stillstand:** Strom einer Betriebsart gilt als Stillstand, wenn seit dem letzten Zählerwert weder Wärme dieser Betriebsart kam noch der Kompressor in ihr lief. Ohne Kompressorstatus entscheidet nur die Wärme.

### Takte

Nur mit „Kompressor läuft“; Abtauungen brauchen die Betriebsart.

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

### Diagnose

| Entität | Einheit | Bedeutung | Braucht |
| --- | --- | --- | --- |
| Heizstab-Anteil Monat, Saison | % | Anteil des Heizstabs am Strom für Heizen und Warmwasser (mit Stillstand) | Heizstab-Zähler |
| Spreizung heute | K | Vorlauf minus Rücklauf, zeitgewichtet über die Zeit mit Kompressor im Heizbetrieb | Vor- und Rücklauf |
| Vorlauftemperatur heute | °C | mittlere Vorlauftemperatur, ebenso gewichtet | Vorlauf |

## Statistik-Karte: Wärme und Strom je Monat

Eine Arbeitszahl je Monat liefert der [Bericht](#bericht-für-einen-zeitraum). Wärme und Strom je Monat zeigt eine Statistik-Karte (*Dashboard bearbeiten → Karte hinzufügen → Manuell*); die Entity-IDs hängen von deinem Namen ab:

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

## Bericht für einen Zeitraum

*Einstellungen → Werkzeuge → Aktionen* (früher *Entwicklerwerkzeuge → Aktionen*) → **Wärmewacht: Bericht**, Wärmepumpe und Zeitraum wählen, „Antwort anzeigen“:

```yaml
action: waermewacht.report
data:
  config_entry: <Eintrag auswählen>
  start: "2026-09-01 00:00:00"
```

Ohne Beginn: Beginn der laufenden Saison. Ohne Ende: jetzt. Zeiten ohne Zeitzone gelten als Ortszeit deines Home Assistant. Beispiel-Antwort (erfundene Werte):

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
- `data_until`: bis wann Stundenwerte vorlagen. `estimated_until`: bis wann aus den Zählern der Wärmepumpe gerechnet wurde (siehe unten); `null`, wenn der Zeitraum erst nach der Einrichtung beginnt.
- **Vor der Einrichtung** rechnet Wärmewacht aus der Langzeitstatistik deiner Zähler. Dort gibt es keinen Kompressorstatus. Deshalb gilt der Strom einer Betriebsart in einer Stunde ohne Wärme dieser Betriebsart als Stillstand. Stunden mit Lauf behalten ihre Minuten Stillstand als Lauf; die Arbeitszahl je Betriebsart fällt dort etwas niedriger aus.
- **Ab der ersten vollen Stunde nach der Einrichtung** nutzt der Bericht die Statistik der eigenen [Energie-Sensoren](#energie).

Die Antwort lässt sich auch in Skripten und Automationen verwenden (`response_variable`).

## Bilanzgrenze und Grenzen der Aussage

- **Bilanzgrenze:** Eine Arbeitszahl gilt immer für die Zähler, aus denen sie stammt. Üblich sind die Grenzen nach SEPEMO: H1 Wärmepumpe bzw. Verdichter, H2 plus Ventilator bzw. Solepumpe, H3 plus Heizstab, H4 plus Umwälz- und Ladepumpen. Mit den Kompressor-Stromzählern von EMS-ESP entspricht Wärmewacht **etwa H1**, mit Heizstab **H3**. Umwälzpumpen, Regelung und Speicherladepumpen fehlen. Eine System-Arbeitszahl mit externem Stromzähler (wie bei [heatpumpmonitor.org](https://heatpumpmonitor.org/), H4) liegt deshalb niedriger.
- **Stillstand laut Wärmepumpe:** Bosch-Wärmepumpen buchen bei stehendem Kompressor gleichmäßig Strom in den Heizen-Zähler, beobachtet etwa 25 W, auch im Sommer. Der konstante Wert deutet auf einen Modellwert der Firmware, nicht auf eine Messung. Ob er stimmt, zeigt nur ein externer Zähler. Die Arbeitszahlen je Betriebsart hängen davon nicht ab; die Arbeitszahl Heizen + Warmwasser schon.
- **Ganzzahlige Zähler:** Nicht jedes Modell liefert Zähler mit 0,01 kWh. Bei ganzen kWh ist eine kurze Zeitspanne ungenau (1 kWh von 5 kWh sind 20 %). Das Attribut `reliable` ist erst `true`, wenn der Strom mindestens das 20-Fache der Zählerauflösung erreicht.
- **Abtauen:** Ob die Wärmezähler von Bosch die beim Abtauen entzogene Wärme abziehen, ist nicht geklärt.
- **Rückblick:** Den Stillstand vor der Einrichtung schätzt Wärmewacht stundenweise (siehe [Bericht](#bericht-für-einen-zeitraum)). In den Sensoren fehlt die angebrochene Stunde der Einrichtung: Die Langzeitstatistik hat für sie noch keinen Wert.
- **Lücken:** Lief Home Assistant nicht, bucht der erste Zählerwert danach den ganzen Zuwachs. Ob das Lauf oder Stillstand war, entscheidet die Wärme im selben Zeitraum.
- **Noch nicht enthalten:** Kennlinie über der Außentemperatur, Kosten und CO₂ im Vergleich zum Gaskessel, Heizlast.

## Fehlerbehebung

Wärmewacht meldet Probleme unter *Einstellungen → Reparaturen* (frühestens 10 Minuten nach dem Start, damit Entitäten nach einem Neustart Zeit haben):

- **Entität fehlt:** Eine zugeordnete Entität gibt es nicht mehr, z. B. nach Umbenennen. Unter *Wärmewacht → ⋮ → Neu konfigurieren* wieder auswählen.
- **Unbrauchbare Einheit:** Ein Energiezähler meldet nicht Wh, kWh oder MWh. Seine Werte werden nicht gezählt, bis die Einheit passt.

Die Meldungen verschwinden von selbst, wenn das Problem behoben ist.

Weiteres:

- **Arbeitszahl bleibt unbekannt:** Im Zeitraum gab es keine Wärme oder weniger Strom als den Mindeststrom. Das ist im Sommer beim Heizen normal.
- **Keine Takte:** „Kompressor läuft“ ist nicht zugeordnet.
- **Diagnose:** *Wärmewacht → Eintrag → ⋮ → Diagnosedaten herunterladen*. **Debug-Protokoll:** *Wärmewacht → ⋮ → Debug-Protokoll aktivieren*.

## Datenschutz

Wärmewacht rechnet lokal, liest nur die Entitäten, die du zuordnest, und fragt nichts im Netz ab. Gespeichert werden je Eintrag die gebuchte Energie und die Läufe der letzten 40 Tage. Die Diagnose-Datei enthält Zuordnung, Einstellungen, die aktuellen Zustände der Quell-Entitäten (also Zählerstände) und Energiesummen, aber nicht den Namen des Eintrags. Prüfe sie, bevor du sie öffentlich teilst.

## Entfernen

1. *Einstellungen → Geräte & Dienste → Wärmewacht* → beim Eintrag ⋮ → *Löschen*. Die gespeicherten Werte und Reparaturmeldungen dieses Eintrags werden mit gelöscht.
2. Optional: HACS → Wärmewacht → ⋮ → *Entfernen*, dann Home Assistant neu starten.

Die Langzeitstatistik der gelöschten Sensoren bleibt in Home Assistant erhalten, bis du sie unter *Einstellungen → Werkzeuge → Statistik* (früher *Entwicklerwerkzeuge*) entfernst.

## Fehler melden

Bitte als [Issue](https://github.com/waermewacht/integration/issues) – am besten mit Diagnose-Datei, dem Modell der Wärmepumpe und den Versionen von Home Assistant, Wärmewacht und gegebenenfalls EMS-ESP. Sicherheitslücken bitte vertraulich, siehe [SECURITY.md](SECURITY.md).

## Verwandte Projekte

- [home-assistant-heat-pump-performance](https://github.com/vandecook/home-assistant-heat-pump-performance) – Arbeitszahlen aus Wärme- und Stromzähler, herstellerneutral.
- [daikin_cycle_ml](https://github.com/elRadix/daikin_cycle_ml) – umfangreiche Auswertung für Daikin Altherma mit ESPAltherma. Für Daikin die passende Wahl.
- [heatpumpmonitor.org](https://heatpumpmonitor.org/) – öffentlicher Vergleich vieler Anlagen. Wärmewacht nutzt dieselben Begriffe (SEPEMO-Bilanzgrenzen, Starts), damit sich Werte einordnen lassen.

## Lizenz

MIT
