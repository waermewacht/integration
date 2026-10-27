# Wärmewacht – Gesundheits-Check

Stand: 2026-10-27. Umgesetzt seit 0.1.0b7: 4.1, 4.2, 4.10 a–c und das Tagesbuch (4.11), dazu die Betriebsart aus mehreren Entitäten. Seit 0.1.0b8: 4.9 ohne Vorjahresvergleich (Ladungen, Heizstab bei normalen Ladungen, letzte Desinfektion). Der Rest ist Entwurf. Ergänzt `docs/ENTWICKLUNG.md`; Fachregeln und Quellen, die dort schon stehen, werden hier nur verwiesen.

Jede Schwelle hat eine Quelle oder ist als **eigene Annahme** markiert. Eigene Annahmen werden nach dem ersten Winter an echten Daten überprüft (Anlage des Inhabers, `CLAUDE.local.md`) und hier nachgetragen.

## 1. Ziel und Grundsätze

Der Gesundheits-Check meldet auffälliges Verhalten der Wärmepumpe aus Daten, die Wärmewacht ohnehin hat. Er sagt, **was** auffällt und **woran** das zu sehen ist, nicht **warum**. Wie im README gilt: Orientierung, keine Fachdiagnose.

- **Gleiches mit Gleichem vergleichen.** Arbeitszahl, Abtauen, Spreizung und Vorlauf hängen stark an der Außentemperatur. Verglichen wird deshalb nur innerhalb derselben Außentemperatur-Klasse (Kennlinie, `curve.py`) oder gegen eine Regel, die die Temperatur schon enthält.
- **Unbekannt statt falscher Alarm.** Reichen die Daten nicht, ist eine Prüfung `unknown` und nennt den Grund (wie `reasons` bei der Heizlast). Nie „aus“ mangels Daten.
- **Lieber spät als falsch.** Mindestmengen, Zeitfenster und Hysterese sind so gewählt, dass ein einzelner Tag, ein Neustart oder eine Lücke keinen Alarm auslöst.
- **Nur lesen, nie steuern.** Der Check schlägt nichts vor, was Wärmewacht selbst ausführt.
- **Kern ohne HA-Importe.** Jede Regel ist eine reine Funktion (neues Modul `health.py`) und wird gegen erfundene Werte getestet.

## 2. Anzeige in Home Assistant

Ein festes Muster für alle Prüfungen, nach Art des Befunds:

| Art | Beispiel | Anzeige | Begründung |
| --- | --- | --- | --- |
| **Datenfehler**: Wärmewacht kann nicht richtig messen, der Nutzer kann es beheben | Zähler steht bei laufendem Kompressor, Außentemperatur steht still | **Reparaturhinweis** (`ir.async_create_issue`, `WARNING`, nicht fixable, verschwindet von selbst) | HA-Regel `repair-issues`: „Repair issues must be actionable“; ein Hinweis nur, wenn der Nutzer etwas beheben kann ([Quality Scale](https://contributors.home-assistant.io/core/quality-scale/repair-issues/)). Gleiches Muster wie `missing_entity` und `energy_unit`. |
| **Befund an der Anlage**: die Wärmepumpe verhält sich auffällig | Heizstab bei milder Witterung, Arbeitszahl gesunken, Takten | **Binärsensor** mit `device_class: problem`, je Prüfung einer | Der Nutzer kann ihn in HA nicht „reparieren“, sondern muss nachsehen oder den Fachbetrieb fragen. Ein Zustand mit Verlauf ist das Übliche; Automationen lösen auf „an“ aus. Wie der bestehende Binärsensor „Auffälliges Takten“. |
| **Kennwert zur Einordnung**: kein Fehler, nur ein Maß | Vorlauf bei −3 °C, Leistung je Heizlast, Feldtest-Vergleich | **Sensor** bzw. **Attribut** | Kein Alarm, weil es keine belegte Grenze gibt. |

Festlegungen:

- **Keine Event-Entität.** Die Prüfungen haben einen Zustand, der Tage anhält. Ein Wechsel des Binärsensors auf „an“ ist für Automationen der gewohnte Auslöser (`state`-Trigger). Event-Entitäten sind für Augenblicksereignisse ohne Zustand gedacht (Tastendruck, Klingel).
- **Keine `persistent_notification`.** Benachrichtigen ist Sache des Nutzers (Automation auf den Binärsensor).
- **Unbekannt:** `is_on = None`, Attribut `reason` mit einem festen Schlüssel (z. B. `no_previous_season`, `too_few_days`, `no_outdoor_temp`), übersetzt im README.
- **Belege als Attribute:** jede Prüfung zeigt die Zahlen, die zur Entscheidung führten, und die verwendeten Schwellen. Große Listen (je Tag, je Klasse) kommen in `_unrecorded_attributes`, wie bei der Kennlinie (Schreiblast).
- **Entstehen nur mit den nötigen Signalen**, wie alle Wärmewacht-Entitäten. Standardmäßig aktiv.
- **Kategorie:** der bestehende Binärsensor hat keine `entity_category`. Neue Problem-Sensoren gleich halten (sichtbar auf automatisch erzeugten Dashboards). Siehe offene Fragen.
- **Diagnose-Datei** enthält die Ergebnisse aller Prüfungen samt `reason`.
- **Löschen des Eintrags** entfernt alle Reparaturhinweise; die Schlüssel kommen in die Liste in `async_remove_entry` (`__init__.py`).

Ein Sammel-Sensor („Gesundheit: 2 Auffälligkeiten“) ist verlockend, aber nicht im MVP: Er verdoppelt die Logik und verwässert Automationen. Später als Zusammenfassung denkbar.

## 3. Datenlage (was Wärmewacht schon hat)

| Daten | Wo | Reicht wie weit |
| --- | --- | --- |
| Stundenwerte Wärme, Strom, Heizstab, Stillstand je Modus | `runtime._async_hours` (Langzeitstatistik, vor der Einrichtung aus den Quell-Zählern) | so weit die Langzeitstatistik reicht, also meist auch die Vorsaison |
| Stundenmittel Außentemperatur | `runtime.async_outdoor_hours` (Langzeitstatistik, mit Min/Max) | ebenso |
| Kennlinie laufende und vorige Saison (2-K-Klassen, ≥ 7 Tage) | `runtime.curves`, täglich gegen 3 Uhr | zwei Saisons |
| Energiesignatur, Heizlast | `runtime.heat_load`, letzte volle Saison | eine Saison |
| Läufe (mit Sekunden je Betriebsart), Abtauungen (Beginn, Ende) | `runtime.runs`, `runtime.defrosts` | 40 Tage (`HISTORY_DAYS`) |
| Spreizung, Vorlauf im Heizbetrieb | `runtime.spread`, `runtime.flow` | **nur heute**, um Mitternacht verworfen |
| Heizstab-Anteil Monat, Saison | `energy.aux_share` | Perioden |
| Warmwasser-Ladungen, Legionellenschaltung | `charges.py` | **nur Kern**, noch nicht verdrahtet; kein Signal „Warmwasser-Temperatur“ in `model.Signal` |
| Durchfluss | Signal `flow_rate` | zugeordnet, aber nicht ausgewertet |
| Luftfeuchte | – | keine |

Folge: Prüfungen auf Stunden- und Kennlinienbasis gehen sofort. Für Spreizung, Vorlauf und Abtauen über mehr als 40 Tage fehlt ein **Tagesbuch** (Abschnitt 4.11).

## 4. Prüfungen

### 4.1 Arbeitszahl gesunken gegenüber der Vorsaison (gleiche Außentemperatur)

**Was und warum.** Die Arbeitszahl Heizen ist bei gleicher Außentemperatur deutlich schlechter als in der Vorsaison. Mögliche Ursachen: verschmutzter Verdampfer oder Filter, Kältemittelverlust, geänderte Heizkurve, Heizstab läuft mit. Das ist der wichtigste Befund, weil er Geld kostet und schleichend kommt.

**Regel.**

- Eingabe: `runtime.curves["current"]` und `["previous"]` (Umfang `heating`, ohne Stillstand, mit Heizstab = H3).
- Gemeinsame Bereiche: die kleinsten Außentemperatur-Bereiche, deren Grenzen in beiden Saisons Klassengrenzen sind (`health.common_ranges`). Hat eine Saison Klassen zusammengefasst, etwa die junge Saison im Oktober 6–12 °C bei 13 Tagen, werden die Klassen der anderen über denselben Bereich summiert (Wärme und Strom, daraus die AZ). Alle Klassen eines Bereichs nicht `sparse` und mit `ratio`; Bereiche mit Lücke fallen heraus. Bis 0.1.0b7 zählten nur Klassen mit gleichen Grenzen, damit blieb der Vergleich am Saisonanfang wochenlang unbekannt.
- Vergleichs-AZ: die Vorsaison mit der Wärmeverteilung der laufenden Saison gewichtet:
  `AZ_vergleich = Σ Wärme_akt,k / Σ (Wärme_akt,k / AZ_vor,k)` über die gemeinsamen Klassen k.
  `AZ_akt = Σ Wärme_akt,k / Σ Strom_akt,k` über dieselben Klassen.
  `Rückgang = 1 − AZ_akt / AZ_vergleich`. Anschaulich: so viel mehr Strom braucht die Anlage für dieselbe Wärme bei gleichem Wetter.
- **An** bei Rückgang ≥ 15 %, **aus** erst unter 10 % (Hysterese).
- Ausgewertet einmal täglich nach der Kennlinie (gegen 3 Uhr), kein eigener Recorder-Zugriff.

**Mindestdaten.** Gemeinsame Bereiche von zusammen ≥ 4 K (zwei Klassen breit) mit ≥ 14 Tagen der laufenden Saison; Strom der laufenden Saison in diesen Klassen ≥ 10 kWh und ≥ 20 Zählerschritte (`reliable`). Sonst `unknown` mit `reason`.

**Quelle.** Klassen-AZ streut um 0,14 bei n = 7 (Machbarkeit, `ENTWICKLUNG.md` §4). Bei AZ ≈ 4 sind das gut 3 %. 15 % liegt damit weit über dem Rauschen. Die Schwellen 15/10 % sind **eigene Annahme**. Zum Vergleich: Die JAZ von Luft/Wasser-Anlagen im Feld reicht von 2,6 bis 4,9 (Fraunhofer ISE WP-QS) – das ist Streuung zwischen Anlagen, kein Maß für eine Veränderung.

**Fehlalarme.**

- **Geänderte Heizkurve oder Raumtemperatur** (gewollt): höhere Vorlauftemperatur senkt die AZ. Der Text nennt das als erste Möglichkeit; ab Tagesbuch (4.11) zeigt ein Attribut die Vorlauftemperatur je Klasse in beiden Saisons.
- **Mehr Heizstab:** gehört zu H3 und senkt die AZ wirklich; 4.2 zeigt, ob das die Ursache ist. Attribut `aux_share` beider Saisons.
- **Firmware- oder Quellenwechsel** (Zählerbedeutung, neue Vorlage, Wechsel ganzzahlig ↔ 0,01 kWh): nicht erkennbar. Nennen.
- **Feuchter Winter mit vielen Abtauungen** senkt die AZ bei 0 … 5 °C. Wird erst mit dem Tagesbuch erkennbar.
- **Anfang der Saison:** wenige Klassen, milde Tage mit wenig Wärme. Die Mindestdaten fangen das ab.

**Anzeige.** Binärsensor „Effizienz gesunken“. Attribute: `ratio_current`, `ratio_previous_same_weather`, `drop_percent`, `classes` (je Klasse `lower`, `upper`, `days_current`, `days_previous`, `ratio_current`, `ratio_previous`; nicht aufgezeichnet), `aux_share_current`, `aux_share_previous`, `threshold_percent`, `reason`.

### 4.2 Heizstab im Heizbetrieb bei milder Witterung

**Was und warum.** Der Heizstab heizt an Tagen, an denen die Wärmepumpe allein reichen müsste. Mögliche Ursachen: Bivalenzpunkt oder Zuheizer-Freigabe zu hoch eingestellt, Estrichtrocknung, Störung des Verdichters. Heizstab-Strom hat AZ 1 und ist teuer.

**Regel.**

- Eingabe: Stundenwerte `AUX` im Modus Heizen und Stundenmittel der Außentemperatur (wie `curve.daily_samples`, Tage mit ≥ 20 gültigen Stunden).
- Milder Tag: Tagesmittel ≥ 5 °C.
- **An**, wenn in den letzten 7 vollen Tagen der Heizstab an milden Tagen zusammen ≥ 2 kWh fürs Heizen verbraucht hat. Das rollende Fenster ist die Hysterese: aus nach 7 Tagen ohne.
- Warmwasser zählt nicht: Legionellenschaltungen dürfen den Heizstab nutzen (dafür 4.9).
- Einmal täglich mit der Analyse.

**Mindestdaten.** Ein Heizstab-Zähler (je Modus oder gesamt) und eine Außentemperatur; mindestens 3 milde Tage im Fenster mit Wärme Heizen > 0, sonst `unknown`. 2 kWh sind bei ganzzahligen Zählern (EMS-ESP liefert den Heizstab je Modus nur in ganzen kWh, `ENTWICKLUNG.md` §4) zwei Schritte, also kein Rundungseffekt.

**Quelle.** Fraunhofer ISE (WP-QS): Heizstab-Anteil im Mittel ~1,3 %, Ausreißer 17 %/21 % waren Defekte; die Leistung bei A−7/W35 liegt im Mittel ~50 % über der Heizlast (`ENTWICKLUNG.md` §3). Eine so ausgelegte Wärmepumpe braucht bei +5 °C keinen Heizstab. Die Grenze 5 °C und die Menge 2 kWh/7 Tage sind **eigene Annahme** (deutlich über der Normaußentemperatur, in Deutschland etwa −9 … −16 °C).

**Fehlalarme.** Estrichtrocknung und Inbetriebnahme (gewollt), Notbetrieb nach einer Störung, Sperrzeit mit Zuheizer-Freigabe, falsch zugeordneter Gesamt-Heizstab (bei „Strom Heizstab gesamt“ bucht Wärmewacht ihn dem laufenden Modus zu; eine Legionellenschaltung direkt nach einem Heizlauf kann so ins Heizen rutschen).

**Anzeige.** Binärsensor „Heizstab bei milder Witterung“. Attribute: `aux_kwh_7d`, `mild_days_7d`, `days` (je Tag Datum, Mittel, Heizstab kWh; nicht aufgezeichnet), `min_outdoor_temp`, `threshold_kwh`, `reason`.

Ergänzend, ohne Alarm: Attribut `field_mean_percent: 1.3` am bestehenden Sensor „Heizstab-Anteil Saison“ zur Einordnung.

### 4.3 Abtauungen auffällig

**Was und warum.** Sehr viele oder sehr lange Abtauungen kosten Effizienz (OEM: ~0,1 JAZ/Jahr allein durchs Abtauen, `ENTWICKLUNG.md` §3). Zu häufig: vereister Verdampfer, Fühler, Luftführung. Abtauen über +10 °C: Fühler- oder Regelfehler.

**Regel (Vorschlag).**

- Abtauung bei Stundenmittel ≥ 10 °C: Zähler `warm_defrosts_7d`; Hinweis ab 3 in 7 Tagen.
- Dauer: eine Abtauung > 15 min oder Mittel > 8 min in 7 Tagen.
- Häufigkeit: Abtauungen je Laufstunde je 2-K-Klasse gegen die Vorsaison, Hinweis ab dem Doppelten. Braucht das Tagesbuch (4.11).

**Quelle.** Beobachtet 3–4 min je Abtauung an der Anlage des Inhabers (`ENTWICKLUNG.md` §4). Alle Schwellen **eigene Annahme**; für Häufigkeit und Dauer keine Quelle gefunden. Abtauen hängt stark an der **Luftfeuchte** (am meisten bei 0 … 5 °C und hoher Feuchte), und die hat Wärmewacht nicht.

**Fehlalarme.** Hoch: Nebel, Nieselregen, Schnee. Hersteller tauen auch zeitgesteuert ab. Nur EMS-ESP liefert Abtauen (`hpactivity`), HomeCom nicht.

**Anzeige.** Zunächst nur Attribute am Sensor „Abtauungen heute“ (`warm_defrosts_7d`, `mean_minutes_7d`, `longest_minutes_7d`). Kein Binärsensor, bis eine Quelle oder ein Winter Daten liefert.

### 4.4 Spreizung zu klein oder zu groß

**Was und warum.** Die Spreizung (Vorlauf − Rücklauf) im Heizbetrieb zeigt den Volumenstrom. Zu klein: Pumpe zu stark, Strom für Umwälzung, oft hydraulische Weiche/Puffer. Zu groß: zu wenig Durchfluss, höhere Vorlauftemperatur nötig, schlechtere AZ, Hochdruckstörungen.

**Regel (Vorschlag).** Zeitgewichtetes Mittel über 7 Tage, nur Zeit mit Kompressor im Heizbetrieb an Tagen mit Mittel < 5 °C (Volllast, geringe Modulation): Hinweis unter 3 K oder über 10 K. Mindestens 10 h Heizbetrieb im Fenster.

**Quelle.** WPsmart im Bestand (Fraunhofer ISE, Schlussbericht 2020, 29 Luft/Wasser-Anlagen): mittlere Spreizung 6,8 K. Die Normprüfbedingung W30/35 (5 K) nach EN 14511 stammt aus dem Gedächtnis und ist **vor Umsetzung zu belegen**. Grenzen 3/10 K **eigene Annahme**.

**Fehlalarme.** Hängt am Fühlerort (EMS-ESP-Vorlage `hptc1` = Vorlauf der Wärmepumpe; HomeCom `curflowtemp` = Systemvorlauf hinter Puffer/Mischer). Bei Modulation sinkt die Spreizung bei gleichem Durchfluss. Hydraulik ist Anlagenplanung, keine Störung.

**Anzeige.** Kennwert: Sensor „Spreizung 7 Tage“ (aus dem Tagesbuch). Kein Binärsensor. Sonderfall **negative Spreizung** siehe 4.10 (Fühler vertauscht).

### 4.5 Vorlauftemperatur hoch für die Außentemperatur (Heizkurve)

**Was und warum.** Die Vorlauftemperatur bestimmt die AZ stärker als jeder andere Einstellwert. Eine zu steile Heizkurve ist die häufigste vermeidbare Ineffizienz. Das ist kein Fehler, sondern ein Optimierungs-Hinweis.

**Regel (Vorschlag).**

- Je Heiztag: Tagesmittel Außentemperatur und zeitgewichtete mittlere Vorlauftemperatur bei Kompressor im Heizbetrieb (Tagesbuch, mindestens 2 h Heizbetrieb am Tag).
- Gerade Vorlauf über Außentemperatur der laufenden Saison (`heat_load.fit_line`), mindestens 14 Tage und 6 K Spanne.
- Kennwert: **Vorlauf bei −3 °C (geschätzt)** aus der Geraden; dazu derselbe Wert der Vorsaison (zeigt eine geänderte Heizkurve, Zusatznutzen für 4.1).

**Quelle.** WPsmart im Bestand (2020): maximale Vorlauftemperatur im Mittel ~43,6 °C bei −3 °C Außentemperatur. Als Vergleichswert im Attribut `field_reference`. Die genaue Definition (Tagesmittel? Maximum?) im Bericht nachlesen, bevor der Wert in der Oberfläche steht. Eine Hinweisschwelle (etwa > 50 °C) wäre **eigene Annahme** und kommt nicht ins MVP.

**Fehlalarme.** Heizkörper brauchen mehr als Fußbodenheizung; Altbau ist kein Fehler. Taktende Anlagen haben kurze Läufe mit Anlauf-Überschwingen.

**Anzeige.** Sensor „Vorlauf bei −3 °C“ (°C), Attribute `previous_season`, `days`, `r_squared`, `field_reference`. Kein Binärsensor.

### 4.6 Takten (bestehend) und Starts je Jahr

**Bestand.** Binärsensor „Auffälliges Takten“: mehr als 3 Starts in einer Stunde oder ≥ 3 kritische Läufe (< 6 min) in 24 h. Quellen in `ENTWICKLUNG.md` §3 (Verdichterhersteller 6–12 Starts/h, zitiert in WP-QS S. 98; Fraunhofer: Zyklen unter ~10 min gesondert ausweisen; Dimplex ~6 min Mindestlaufzeit). Eine verifizierte Primärquelle für Grenzen am Gebäude gibt es nicht; die Vorgaben sind weiche Schwellen. Fraunhofer ISE (Pressemitteilung WP-QS 2025): Schalthäufigkeit „bei einigen sehr hoch“.

**Ergänzung (Vorschlag).** Attribute `starts_per_day_7d` und `starts_per_year_projected` (7-Tage-Mittel × 365). Orientierung: 90 % der Luft/Wasser-Anlagen im Fraunhofer-Feld unter 5.500 Starts/Jahr (~15/Tag), ein Drittel ≤ 2.000 (`ENTWICKLUNG.md` §3). Kein neues Kriterium für „an“: eine Hochrechnung aus 7 Tagen im Herbst ist keine Jahreszahl.

### 4.7 Überdimensionierung (Leistung gegen Heizlast)

**Was und warum.** Eine zu große Wärmepumpe taktet in der Übergangszeit und läuft selten im effizienten Bereich. Fraunhofer ISE (Pressemitteilung WP-QS 2025): Überdimensionierung ist häufig.

**Regel (Vorschlag).**

- Neue optionale Einstellung **Nennleistung (kW) bei A−7/W35** (Datenblatt).
- Kennwert `Leistung / Heizlast = Nennleistung / Heizlast normgerecht bei Normaußentemperatur` (`heat_load.standard_kw`, braucht die Einstellung Normaußentemperatur und eine ausreichende Energiesignatur).
- Später, mit der Einstellung **kleinste Leistung (kW)**: Heizlast gemessen bei +7 °C (`a + b·7`) kleiner als die kleinste Leistung → Takten in der Übergangszeit zu erwarten. Das erklärt „Auffälliges Takten“, statt es nur zu melden.

**Quelle.** Fraunhofer ISE (WP-QS): Leistung bei A−7/W35 im Mittel ~50 % über der Heizlast, also Faktor ~1,5 im Feldmittel (`ENTWICKLUNG.md` §3). Das ist ein Mittelwert, keine Grenze: Ein Alarm ab 1,5 träfe die halbe Feldmenge. Keine Alarmschwelle (**eigene Entscheidung**).

**Fehlalarme.** Nennleistung je Datenblatt bei anderen Bedingungen (A2/W35, A7/W35); Heizlast aus nur einer Saison; Warmwasserbedarf und Sperrzeiten rechtfertigen Reserve.

**Anzeige.** Sensor „Leistung je Heizlast“ (Faktor), Attribute `rated_kw`, `heat_load_kw`, `field_mean: 1.5`. Als Hinweis-Attribut am Takt-Binärsensor (`oversized_factor`), wenn vorhanden.

### 4.8 Stillstand ungewöhnlich hoch

**Was und warum.** Strom bei stehendem Kompressor (Regelung, Kurbelwannenheizung, Pumpen im Stillstand) zählt in die JAZ. Ein Anstieg kann eine dauernd laufende Kurbelwannenheizung oder eine nicht abschaltende Pumpe sein.

**Regel (Vorschlag).** Mittlere Stillstandsleistung der letzten 7 Tage (Stillstand-kWh ÷ Stunden ohne Lauf) gegen den Median der 30 Tage davor: Hinweis bei +50 % **und** +10 W. Gleiche Außentemperatur-Klasse wäre besser (Kurbelwannenheizung läuft bei Kälte mehr), braucht das Tagesbuch.

**Quelle.** Keine. Schwellen **eigene Annahme**.

**Fehlalarme und Nutzen.** Bei Bosch/Buderus ist der Stillstand ein konstanter Modellwert der Firmware (~25 W, `ENTWICKLUNG.md` §4): Die Prüfung meldet dort nie etwas Echtes. Nützlich erst mit externem Stromzähler (H4). Nebennutzen: Weicht der Wert je von 25 W ab, ist das ein Hinweis auf Messung statt Modellwert (`NOTES.md`, offener Punkt 7) – als Attribut am Stillstand-Sensor (`mean_power_w_7d`), ohne Alarm.

### 4.9 Warmwasser: AZ je Ladung, Heizstab und Legionellenschaltung

**Was und warum.** Sinkt die AZ normaler Ladungen, steigt die Speichertemperatur oder der Wärmetauscher verkalkt. Heizstab bei normalen Ladungen (nicht bei der Legionellenschaltung) deutet auf eine Fehleinstellung.

**Regel (Vorschlag).**

- AZ normaler Ladungen (ohne Legionellenschaltung, `charges.disinfection_split`) der letzten 30 Tage gegen denselben Kalendermonat des Vorjahres (Kaltwassertemperatur schwankt mit der Jahreszeit): Hinweis ab 15 % Rückgang, mindestens 10 Ladungen.
- Heizstab-Anteil normaler Ladungen > 10 %: Hinweis.
- Kennwert: Tage seit der letzten Legionellenschaltung (≥ 60 °C nach DVGW W 551, schon in `charges.py`).

**Quelle.** Fraunhofer ISE (WP-QS): AZ Warmwasser im Feld 2,8 (n = 18) zur Einordnung. 60 °C nach DVGW W 551 (`charges.py`). 15 % und 10 % **eigene Annahme**.

**Umsetzung (0.1.0b8).** `charges.ChargeTracker` bildet Ladungen aus der Betriebsart (Abtauen beendet keine Ladung; Energie bis 5 Minuten nach dem Ende zählt noch). Signal `dhw_temp`. Problem-Sensor `aux_dhw_charges` für den Heizstab-Anteil normaler Ladungen (30 Tage, ab 10 Ladungen, > 10 %). „Letzte thermische Desinfektion“ hängt nur an der Speichertemperatur (Übergang über die Schwelle, neu erst nach 5 K darunter), damit sie auch ohne Betriebsart und bei Bosch HomeCom geht. Offen: der Vorjahresvergleich der AZ normaler Ladungen; er braucht ein Jahr Tagebuch (normale Ladungen je Tag stehen seit 0.1.0b8 darin).

### 4.10 Fühler- und Datenfehler

Diese Prüfungen schützen die Zahlen von Wärmewacht selbst. Sie sind robust (Physik statt Erfahrungswert) und der Nutzer kann sie beheben (Quelle prüfen, anders zuordnen). Deshalb **Reparaturhinweise**, mit Wartezeit `ISSUE_GRACE` (10 min) nach dem Start.

**a) Zähler steht bei laufendem Kompressor** (`counter_stuck`)

- Je Modus und Zähler (Wärme und Strom des Modus): Laufzeit des Kompressors in diesem Modus seit dem letzten Zuwachs des Zählers. Ohne Betriebsart: Laufzeit insgesamt gegen die Summe der Wärmezähler.
- Grenze: 60 min bei Zählern mit 0,01 kWh, 6 h bei ganzzahligen Zählern und Tageswerten aus der Cloud (HomeCom: bis 2 h Verzug, letzte 1–2 h des Tages fehlen, `ENTWICKLUNG.md` §4).
- Begründung 60 min: Bei kleinster Leistung (einige 100 W Strom) wächst ein 0,01-kWh-Zähler in einer Stunde um Dutzende Schritte. Werte **eigene Annahme** mit großer Reserve.
- Abtauen ist kein Zuwachs der Wärme (Höchststand gehalten), dauert aber nur 3–4 min.
- `unavailable`/`unknown` zählt nicht als Stillstand des Zählers; das deckt b) ab.
- Verschwindet beim nächsten Zuwachs. Laufzeit seit dem letzten Zuwachs je Zähler im Haupt-Store (wird ohnehin alle 10 min gespeichert).

**b) Quelle lange nicht verfügbar** (`source_unavailable`): Eine zugeordnete Entität ist länger als 60 min `unavailable` (z. B. EMS-ESP oder MQTT aus). Ergänzt `missing_entity` (Entität fehlt ganz). Grenze **eigene Annahme**; nach einem EMS-ESP-Neustart dauert es Minuten, bis alle Telegramme da sind.

**c) Außentemperatur steht still oder ist unplausibel** (`outdoor_temp`)

- Steht: In der Langzeitstatistik 48 aufeinanderfolgende Stunden mit Min = Max (über Neustarts hinweg; `last_changed` taugt nicht, weil ein Neustart ihn zurücksetzt).
- Unplausibel: Stundenmittel außerhalb −35 … +45 °C in mehr als 3 Stunden des Vortags. Diese Werte verwirft `curve.py` schon (Sommerspitzen bis 44 °C durch Sonne/Abwärme, `ENTWICKLUNG.md` §4).
- Warum wichtig: Kennlinie, Heizlast, 4.1 und 4.2 hängen an diesem Fühler.
- Eine zweite, unabhängige Quelle zum Vergleich gibt es bei EMS-ESP nicht (`thermostat_dampedoutdoortemp` ist derselbe Fühler gefiltert). Ein Vergleich mit einer Wetter-Entität wäre möglich, ist aber nicht im MVP.

**d) Vor- und Rücklauf vertauscht** (`flow_return_swapped`): Tagesmittel der Spreizung im Heizbetrieb < −1 K bei mindestens 60 min Heizbetrieb. Im Heizbetrieb hebt die Wärmepumpe die Wassertemperatur; der Vorlauf ist wärmer als der Rücklauf (Physik). Abtauen ist ausgenommen (gemessen wird nur bei Betriebsart Heizen). Fehlalarm möglich, wenn der Vorlauf hinter einem Mischer gemessen wird.

**e) Durchfluss 0 oder unplausibel bei laufendem Kompressor** (später): Durchfluss 0 über 15 min Heizbetrieb, oder Abweichung um mehr als den Faktor 10 von `Wärmeleistung / (1,163 Wh/(l·K) × Spreizung)` (spezifische Wärme von Wasser). Fängt Einheitenfehler wie bei HomeCom (l/h als „L/min“). Braucht eine Beobachtung, was `pc0flow` bei Warmwasser und Abtauen zeigt (Fixture), deshalb nicht im MVP.

### 4.11 Grundlage: Tagesbuch

Mehrere Prüfungen (4.3 Häufigkeit, 4.4, 4.5, 4.8 je Klasse, 4.9 Vorjahr, Vorlauf je Klasse in 4.1) brauchen Tageswerte über die 40 Tage der Lauf-Historie hinaus. Vorschlag: um Mitternacht je Tag ein Eintrag mit Außentemperatur-Mittel, Laufzeit je Betriebsart, Starts, Abtauungen (Anzahl, Minuten), Spreizung und Vorlauf (Summe und Sekunden aus `Mean`), Stillstand-kWh. Etwa 150 Bytes je Tag, ~55 KB je Jahr, gespeichert mit dem ohnehin anstehenden Mitternachts-Speichern der Datei `.history`. Keine neue Schreiblast.

Alternative ohne Speicher: Vorlauf und Spreizung aus der Langzeitstatistik der Temperatur-Entitäten. Verworfen, weil sie nicht nach „Kompressor im Heizbetrieb“ filtert (Warmwasser- und Stillstandszeiten mischen sich ein).

### 4.12 Einordnung gegen Feldtests (kein Alarm)

Attribut `field_reference` an „AZ Heizen+WW Saison“: Fraunhofer ISE WP-QS (Luft/Wasser JAZ 3 Mittel 3,4, Spanne 2,6–4,9), WPsmart im Bestand (Mittel 3,1, n = 29), heatpumpmonitor.org (Luft-Wärmepumpen, SEPEMO H4, 3,86 bei 170 Anlagen). Wichtig im Text: verschiedene Bilanzgrenzen (Wärmewacht etwa H1/H3, heatpumpmonitor H4, Fraunhofer JAZ 3 ≈ H3 mit Abtauwärme abgezogen). Gehört zu Stufe 3, nicht zum Gesundheits-Check im engeren Sinn.

## 5. Rangfolge

Bewertet nach Nutzen (Geld, Schaden, Häufigkeit) und Robustheit (Fehlalarme, Quellen, Datenbedarf).

| Rang | Prüfung | Nutzen | Robustheit | Daten heute | Anzeige |
| --- | --- | --- | --- | --- | --- |
| 1 | 4.10 a–c Zähler steht, Quelle weg, Außentemperatur | hoch (schützt alle Zahlen) | sehr hoch (Physik) | ja | Reparatur |
| 2 | 4.2 Heizstab bei milder Witterung | hoch | hoch (Energiezähler, Fraunhofer-Bezug) | ja | Binärsensor |
| 3 | 4.1 AZ-Rückgang ggü. Vorsaison | sehr hoch | mittel–hoch (gleiche Klasse; Heizkurve verfälscht) | ja, braucht Vorsaison in der Statistik | Binärsensor |
| 4 | 4.6 Takten (bestehend) + Starts/Jahr | mittel | mittel (weiche Schwellen) | ja | Binärsensor + Attribute |
| 5 | 4.10 d Vor-/Rücklauf vertauscht | mittel | hoch | ja | Reparatur |
| 6 | 4.5 Vorlauf bei −3 °C | hoch (Optimierung) | mittel | Tagesbuch | Sensor |
| 7 | 4.7 Leistung je Heizlast | mittel | mittel (eine Saison, Datenblatt) | nach einem Winter, zwei Einstellungen | Sensor |
| 8 | 4.4 Spreizung | mittel | niedrig–mittel (Hydraulik, Fühlerort) | Tagesbuch | Sensor |
| 9 | 4.3 Abtauungen | mittel | niedrig (keine Feuchte, keine Quelle) | teils | Attribute |
| 10 | 4.9 Warmwasser | mittel | mittel | nein (Ladungen nicht verdrahtet) | später |
| 11 | 4.8 Stillstand | niedrig (bei Bosch Modellwert) | niedrig | ja | Attribut |
| – | 4.10 e Durchfluss | mittel | unbekannt | Fixture fehlt | später |

## 6. MVP

Vier neue Prüfungen, dazu bleibt „Auffälliges Takten“ unverändert:

1. **Reparatur „Zähler steht“** (4.10 a), mit b) „Quelle nicht verfügbar“ in derselben Prüfroutine.
2. **Reparatur „Außentemperatur unbrauchbar“** (4.10 c).
3. **Binärsensor „Heizstab bei milder Witterung“** (4.2).
4. **Binärsensor „Effizienz gesunken“** (4.1).

Warum diese: Alle gehen mit den heutigen Daten, ohne neues Signal und ohne Tagesbuch. 1 und 2 sichern die Grundlage von 3 und 4. 4.1 nutzt die schon gerechnete Kennlinie, und durch den Rückblick aus der Langzeitstatistik ist die Vorsaison oft schon bei der Einrichtung da. Billiger Nachzug danach: 4.10 d und die Attribute aus 4.6.

## 7. Texte (Deutsch) für das MVP

Englisch entsteht wie immer über `tools/make_strings.py`.

### Reparaturhinweise

**`counter_stuck`**

- Titel: „Wärmewacht: Zähler steht still“
- Text: „Bei {name} lief der Kompressor {hours} Stunden im Betrieb {mode}, aber diese Zähler sind nicht gestiegen: {entities}. Wärmewacht kann in dieser Zeit nichts buchen. Prüfe, ob die Quelle (etwa EMS-ESP) noch Werte schickt und ob die Entität aktiviert ist. Ist es der falsche Zähler, wähle unter Geräte & Dienste → Wärmewacht → ⋮ → Neu konfigurieren einen anderen. Der Hinweis verschwindet, sobald der Zähler wieder steigt.“

**`source_unavailable`**

- Titel: „Wärmewacht: Quelle nicht erreichbar“
- Text: „Diese Entitäten von {name} sind seit mehr als {minutes} Minuten nicht verfügbar: {entities}. Solange fehlen Wärmewacht Werte. Prüfe die Quelle (etwa EMS-ESP, MQTT oder Bosch HomeCom). Der Hinweis verschwindet, sobald wieder Werte kommen.“

**`outdoor_temp`**

- Titel: „Wärmewacht: Außentemperatur unbrauchbar“
- Text (Platzhalter `{problem}` = einer der beiden Sätze): „Die Außentemperatur von {name} ({entity}) {problem}. Kennlinie, Heizlast und die Prüfungen „Effizienz gesunken“ und „Heizstab bei milder Witterung“ hängen an ihr. Prüfe den Fühler oder wähle unter Neu konfigurieren eine andere Entität.“
  - „hat sich seit {hours} Stunden nicht verändert“
  - „lag gestern {hours} Stunden außerhalb von −35 bis +45 °C“

### Binärsensoren

**„Heizstab bei milder Witterung“** (`aux_mild_weather`, Problem)

README: „An, wenn der Heizstab in den letzten 7 Tagen an Tagen mit einem Mittel von mindestens 5 °C zusammen mindestens 2 kWh fürs Heizen verbraucht hat. Eine passend ausgelegte Wärmepumpe heizt bei diesen Temperaturen allein; im Fraunhofer-Feldtest lag der Heizstab-Anteil im Mittel bei 1,3 %. Mögliche Gründe – keine Diagnose: Zuheizer-Freigabe oder Bivalenzpunkt zu hoch eingestellt, Estrichtrocknung, eine Störung. Warmwasser zählt nicht mit: Die Legionellenschaltung darf den Heizstab nutzen. Unbekannt ohne Außentemperatur oder mit weniger als 3 milden Heiztagen in der Woche.“

**„Effizienz gesunken“** (`efficiency_drop`, Problem)

README: „An, wenn die Arbeitszahl Heizen dieser Saison bei gleicher Außentemperatur mindestens 15 % unter der Vorsaison liegt; aus erst unter 10 %. Verglichen werden nur 2-K-Klassen der Kennlinie, die es in beiden Saisons gibt. Häufigster harmloser Grund: eine steilere Heizkurve oder höhere Raumtemperatur. Sonst lohnt ein Blick auf Heizstab-Anteil, Verdampfer (Laub, Schmutz) und Filter; bleibt es, frag deinen Fachbetrieb. Unbekannt ohne Vorsaison in der Langzeitstatistik oder mit weniger als 2 gemeinsamen Klassen und 14 Tagen.“

Gründe für „unbekannt“ (Attribut `reason`):

| Schlüssel | Text |
| --- | --- |
| `no_outdoor_temp` | keine Außentemperatur zugeordnet |
| `no_aux_counter` | kein Heizstab-Zähler zugeordnet |
| `no_previous_season` | keine Vorsaison in der Langzeitstatistik |
| `too_few_classes` | weniger als 2 gemeinsame Temperaturklassen |
| `too_few_days` | zu wenige Tage im Vergleich |
| `too_little_electricity` | zu wenig Strom für einen sicheren Vergleich |
| `not_analysed_yet` | noch nicht gerechnet (2 min nach dem Start, dann täglich gegen 3 Uhr) |

## 8. Einstellungen

Wenige, mit Vorgabe und Quelle wie die bestehenden:

| Einstellung | Vorgabe | Für | Begründung |
| --- | --- | --- | --- |
| Heizstab: milde Witterung ab | 5 °C | 4.2 | eigene Annahme; Anlagen mit hoher Normaußentemperatur (Küste) wollen eher höher |
| Effizienz gesunken ab | 15 % | 4.1 | eigene Annahme; die Rückstellung liegt fest 5 Punkte darunter |
| Nennleistung bei A−7/W35 (optional, später) | – | 4.7 | Datenblatt |

Nicht einstellbar: Mindestdaten, Zählergrenzen in 4.10 (Eigenschaften der Daten, nicht der Anlage) und die 2-kWh-Menge in 4.2. Abschalten einer Prüfung geht über das Deaktivieren der Entität; Reparaturhinweise lassen sich in HA ignorieren.

## 9. Umsetzungshinweise

- **Kern:** `health.py` ohne HA-Importe: `efficiency_drop(current, previous, …)` auf den Dicts aus `curve_as_dicts`, `aux_mild_weather(days, …)` auf `DaySample`, `outdoor_problem(hourly_min_max, …)`, `stuck_counters(…)`. Ergebnisse als Dataclass mit `problem: bool | None`, `reason`, Belegen.
- **Zeitpunkt:** 4.1, 4.2 und 4.10 c in `_async_refresh_analysis` (Daten liegen dort schon vor; für 4.10 c die Min/Max-Statistik der Außentemperatur mit abfragen). 4.10 a/b im Minuten-Takt neben `_check_issues`.
- **Speichern:** Ergebnisse von 4.1/4.2 nicht speichern (werden 2 min nach dem Start neu gerechnet; bis dahin `unknown` mit `not_analysed_yet`). Hysterese von 4.1 braucht den letzten Zustand: ein Bool im Haupt-Store. Laufzeit seit Zuwachs je Zähler im Haupt-Store.
- **Schreiblast:** Belege runden (AZ 0,01; Prozent 0,1; kWh 0,1), Listen nicht aufzeichnen.
- **Tests:** Je Regel Grenzfälle (genau an der Schwelle, eine Klasse zu wenig, Hysterese, DST-Tag, Neustart mitten in einem Lauf). HA-Test für das Anlegen und Entfernen der Hinweise.
- **README:** neuer Abschnitt „Gesundheits-Check“ unter „Takte“, Fehlerbehebung um die neuen Hinweise ergänzen.

## 10. Offene Fragen

- Schwellen 15 % (4.1) und 5 °C/2 kWh (4.2) nach dem ersten Winter an der Anlage des Inhabers prüfen.
- Problem-Sensoren mit `entity_category: diagnostic` (nicht auf automatischen Dashboards) oder ohne, wie „Auffälliges Takten“?
- Soll 4.1 auch Heizen + Warmwasser vergleichen? Warmwasser schwankt mit Kaltwassertemperatur und Verbrauch; deshalb vorerst nur Heizen.
- Braucht 4.1 eine Möglichkeit, den Vergleich nach einer gewollten Änderung der Heizkurve zurückzusetzen (Aktion oder Datum „Vergleich ab“)? Vorerst nur der Hinweis im Text.
- WPsmart im Bestand: Bericht-URL und genaue Definition der „maximalen Vorlauftemperatur bei −3 °C“ nachtragen (in `ENTWICKLUNG.md` §3).
- EN 14511 (W30/35) belegen, bevor 4.4 einen Text bekommt.
- Abtauen (4.3): Quelle für übliche Häufigkeit und Dauer suchen; ohne Feuchte bleibt es Attribut.
- Tagesbuch (4.11): mit dem Inhaber abstimmen, bevor Stufe 3 (Warmwasser je Ladung) gebaut wird – beide brauchen es.

## Quellen

- Fraunhofer ISE, WP-QS im Bestand: [Schlussbericht 25.11.2025](https://www.ise.fraunhofer.de/content/dam/ise/de/documents/projekte/WP-QS_Schlussbericht.pdf) (Werte in `ENTWICKLUNG.md` §3) und Pressemitteilung 2025 (77 Wärmepumpen; Luft/Wasser JAZ Mittel 3,4, Spanne 2,6–4,9; Heizstab 1,3 %; Schalthäufigkeit bei einigen sehr hoch; Überdimensionierung häufig).
- Fraunhofer ISE, WPsmart im Bestand, Schlussbericht 2020 (29 Luft/Wasser-Anlagen; JAZ Mittel 3,1; mittlere Spreizung 6,8 K; maximale Vorlauftemperatur ~43,6 °C bei −3 °C). URL nachtragen.
- [heatpumpmonitor.org](https://heatpumpmonitor.org/): Luft-Wärmepumpen, SEPEMO H4, 3,86 bei 170 Anlagen (Stand der Recherche Oktober 2026).
- Home Assistant Quality Scale, Regel [repair-issues](https://contributors.home-assistant.io/core/quality-scale/repair-issues/) (abgerufen 2026-10-27).
- DVGW W 551 (2004), 60 °C am Austritt des Trinkwassererwärmers (wie in `charges.py`).
- Übrige Werte (Takten, Abtauen, Kennlinie, Heizlast, Datenquellen): `docs/ENTWICKLUNG.md` §3 und §4.
