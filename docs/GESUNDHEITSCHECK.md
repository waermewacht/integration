# Wärmewacht – Gesundheits-Check

Stand: 2026-10-28. Umgesetzt seit 0.1.0b7: 4.1, 4.2, 4.10 a–c und das Tagesbuch (4.11), dazu die Betriebsart aus mehreren Entitäten. Seit 0.1.0b8: 4.9 (Vorjahresvergleich seit 0.2.0) (Ladungen, Heizstab bei normalen Ladungen, letzte Desinfektion). Für 0.1.1 (noch unveröffentlicht): 4.5 als „Vorlauf bei 0 °C“ (aus der Langzeitstatistik statt dem Tagebuch, Stunden mit Heizwärme ohne Warmwasser; 0 °C statt −3 °C, weil dort meist ohne Hochrechnung gemessen), 4.6 als „Starts Saison“ mit Starts je Tag, 4.10 d (`flow_return_swapped`, Urteil um Mitternacht, gespeichert), dazu 4.3 (nur Attribute), 4.4, 4.7, 4.8 und 4.10 e (Anfang von Abschnitt 4). Der Rest ist Entwurf; die Abschnitte 4 bis 10 beschreiben den Entwurf, wo nicht anders vermerkt. Ergänzt `docs/ENTWICKLUNG.md`; Fachregeln und Quellen, die dort schon stehen, werden hier nur verwiesen.

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
| Spreizung, Vorlauf im Heizbetrieb | `runtime.spread`, `runtime.flow` | **nur heute**, um Mitternacht verworfen (Tagesmittel seit 0.1.0b7 im Tagebuch) |
| Heizstab-Anteil Monat, Saison | `energy.aux_share` | Perioden |
| Warmwasser-Ladungen, Legionellenschaltung | `charges.py` | damals nur Kern; seit 0.1.0b8 verdrahtet (Signal `dhw_temp`), 40 Tage |
| Durchfluss | Signal `flow_rate` | damals nicht ausgewertet; ab 0.1.1 Tagesmittel im Heizbetrieb (Tagebuch) für 4.10 e |
| Luftfeuchte | – | keine |

Folge: Prüfungen auf Stunden- und Kennlinienbasis gehen sofort. Für Spreizung, Vorlauf und Abtauen über mehr als 40 Tage fehlt ein **Tagesbuch** (Abschnitt 4.11).

## 4. Prüfungen

**Umsetzung 0.1.1 (`health_extra.py`):**

- **4.3:** Attribute am Sensor „Abtauungen heute“: Abtauungen, warme Abtauungen (Stundenmittel ab 10 °C, eigene Annahme), mittlere und längste Dauer der letzten 7 Tage. Dazu Attribut `classes`: Abtauungen je Laufstunde je 2-K-Klasse aus dem Tagebuch, laufende gegen vorige Saison (`defrost_classes`, `compare_defrost_classes`), ohne Schwelle. Kein Binärsensor.
- **4.4:** Sensor „Spreizung 7 Tage“: Mittel der Heizzeit an Tagen unter 5 °C, ab 10 Stunden (beides eigene Annahme). Attribut `all_days` für alle Tage, Feldwert 6,8 K (WPsmart).
- **4.7:** Einstellungen „Heizleistung bei A−7/W35“ und „Kleinste Heizleistung“ im Abschnitt „Heizleistung laut Datenblatt“. Der Faktor bezieht sich auf die normgerechte Heizlast; `measured_factor` auf die gemessene; `cycling_expected`, wenn die gemessene Heizlast bei +7 °C unter der kleinsten Leistung liegt. Feldmittel 1,5, keine Schwelle.
- **4.8:** Attribute am Stillstand-Sensor: mittlere Leistung 7 Tage, kleinster und größter Tag, Median der 30 Tage davor, `rising` ab +50 % und +10 W (eigene Annahme). Stunden ohne Lauf je Tag aus dem Tagebuch, Umstellungstage mit 23/25 h.
- **4.10 e:** Die Wärmeleistung kommt aus dem Zuwachs des Wärmezählers Heizen über die Heizzeit eines Tages, weil die Vorlagen kein Leistungssignal mehr zuordnen. Unplausibel ab Faktor 10, mindestens 1 Stunde Heizen, 1 kWh und 2 K (eigene Annahmen). Durchfluss 0: 15 Minuten Heizbetrieb ohne einen Wert über 0. Nicht bei Quellen ohne Betriebsart, also nicht bei HomeCom.

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

**Mindestdaten.** Gemeinsame Bereiche von zusammen ≥ 4 K (zwei Klassen breit) mit ≥ 14 Tagen der laufenden Saison; Strom der laufenden Saison in diesen Klassen ≥ 10 kWh. Sonst `unknown` mit `reason`. (Entwurf: zusätzlich ≥ 20 Zählerschritte wie `reliable`; nicht umgesetzt.)

**Quelle.** Klassen-AZ streut um 0,14 bei n = 7 (Machbarkeit, `ENTWICKLUNG.md` §4). Bei AZ ≈ 4 sind das gut 3 %. 15 % liegt damit weit über dem Rauschen. Die Schwellen 15/10 % sind **eigene Annahme**. Zum Vergleich: Die JAZ von Luft/Wasser-Anlagen im Feld reicht von 2,6 bis 4,9 (Fraunhofer ISE WP-QS) – das ist Streuung zwischen Anlagen, kein Maß für eine Veränderung.

**Fehlalarme.**

- **Geänderte Heizkurve oder Raumtemperatur** (gewollt): höhere Vorlauftemperatur senkt die AZ. Der Text nennt das als erste Möglichkeit; ab Tagesbuch (4.11) zeigt ein Attribut die Vorlauftemperatur je Klasse in beiden Saisons.
- **Mehr Heizstab:** gehört zu H3 und senkt die AZ wirklich; 4.2 zeigt, ob das die Ursache ist. Attribut `aux_share` beider Saisons.
- **Firmware- oder Quellenwechsel** (Zählerbedeutung, neue Vorlage, Wechsel ganzzahlig ↔ 0,01 kWh): nicht erkennbar. Nennen.
- **Feuchter Winter mit vielen Abtauungen** senkt die AZ bei 0 … 5 °C. Wird erst mit dem Tagesbuch erkennbar.
- **Anfang der Saison:** wenige Klassen, milde Tage mit wenig Wärme. Die Mindestdaten fangen das ab.
- **Rückblick vor der Einrichtung** (seit 0.2.7): Vor der Einrichtung kommt die Energie aus den Stundenwerten der Quellzähler, Stillstand nur in Stunden ganz ohne Wärme (`backfill.hour_totals`); danach aus den eigenen Sensoren, Stillstand über den Kompressor. Bei oft taktenden Anlagen (Wärme in fast jeder Stunde) wirkte die Vorsaison dadurch schlechter und versteckte einen echten Verlust (Test `test_cycling_unit_compared_with_one_method`: 20 % Verlust erschienen als 9,3 %). Reichen die verglichenen Zeiträume über die Einrichtung (`backfill.compare_on_source`), rechnet der Vergleich beide Seiten aus den Quellzählern (`runtime._async_comparison_hours`); die angezeigten Kennlinien bleiben. Genauer wäre ein Stillstandsanteil je Stunde aus Laufzeitzählern (EMS-ESP `uptimecomp…`), offen.

**Anzeige.** Binärsensor „Effizienz gesunken“. Attribute: `ratio_current`, `ratio_previous_same_weather`, `drop_percent`, `classes` (je gemeinsamem Bereich `lower`, `upper`, `days_current`, `days_previous`, `ratio_current`, `ratio_previous`; nicht aufgezeichnet), `threshold_percent`, `reason`. Die im Entwurf vorgesehenen `aux_share_current` und `aux_share_previous` gibt es nicht.

#### 4.1a Umbau: Basismodell aus Wetter und Vorlauf, ohne Schaltfläche (Entwurf und Umsetzung 2026-11-11, `health.baseline_drop`)

**Anlass.** Die Schaltfläche „Effizienzvergleich neu starten“ wird als „aktualisieren“ verstanden. Im Forum wurde sie zusammen mit „Rückblick neu berechnen“ gedrückt, ohne dass sich an der Anlage etwas geändert hatte. Danach war die Prüfung 28 Tage lang blind. Wie lange, zeigte nirgends ein Datum, und rückgängig machen ließ es sich nicht. Außerdem muss der Nutzer selbst wissen, dass eine gewollte Änderung der Heizkurve den Vergleich verfälscht. Das widerspricht „erst Erkennung, dann Feld“.

**Schritt 0 (geprüft 2026-11-11, Langzeitstatistik der Anlage des Inhabers, Saison 2025/26 und 2026/27, Skript und Rohdaten lokal in `raw/`, nicht im Repo; Zahlen nur in `NOTES.md`).** Als Probe dienten alle 31 Fenster von 28 Tagen der Vorsaison, jeweils gegen den Rest derselben Saison. Echte Defekte gab es dort keine, jeder Ausschlag ist also Rauschen oder Fehlalarm. In der Vorsaison wurde die Heizkurve im Herbst um gut 8 K gesenkt.

| Variante | Streuung | größter Ausschlag | Tage im Vergleich | Fenster mit hoher Heizkurve |
|---|---|---|---|---|
| AZ je Außentemperatur-Klasse (heute) | ± 5 % | gut zwei Drittel der Schwelle | alle | beinahe Fehlalarm |
| Gütegrad je Klasse | ± 5 % | ähnlich | alle | **überkorrigiert** (erscheint ähnlich viel besser, wie die AZ schlechter erscheint) |
| AZ je Zelle Außentemperatur × Senke (je 2 K) | ± 2 % | ein Viertel der Schwelle | ⅓–½ | keine Zelle, also unbekannt |
| **Basismodell `1/AZ = a + b · Hub`** | **± 2 %** | **ein Fünftel der Schwelle** | **fast alle** | **richtig eingeordnet** |

- **Gütegrad verworfen:** Die Anlage verlor durch den höheren Vorlauf nur gut die Hälfte dessen, was Carnot vorhersagt (passt zu 4.14, „Grenzen“). Eine deutlich gesenkte Heizkurve sähe damit wie ein Verlust aus, also ein Fehlalarm für den, der alles richtig gemacht hat.
- **Basismodell gewählt:** `1/AZ = a + b · Hub`, Hub = Senke − Außentemperatur in den Heizstunden. Physikalisch begründet: Auch für Carnot ist 1/COP = Hub / T_Senke, also nahezu linear im Hub. Die Steigung `b` lernt das Modell aber von der Anlage selbst. Ein Modell mit Außentemperatur und Senke getrennt (`AZ = a + b · T_außen + c · T_Senke`) war nicht besser. Vorgehen wie beim Nachweis von Energieeinsparungen: Regressionsmodell auf der Vergleichszeit anpassen, auf die laufende Zeit anwenden, Abweichung zwischen Messung und Vorhersage auswerten. Die FEMP-Richtlinie nennt das „routine adjustments“: Energieverbrauch per Regression auf unabhängige Größen wie das Wetter normalisieren, damit beide Zeiträume unter denselben Bedingungen verglichen werden (FEMP M&V Guidelines 5.0, Abschnitt 2.1.3, IPMVP Optionen B und C). Für Wärmepumpen im Feld: Brudermueller u. a. (2025) passen je Anlage ein lineares COP-Modell an, auf Tageswerte von 708 Wärmepumpen (Mixed-Effects-Modell mit eigener Steigung und eigenem Achsenabschnitt je Anlage). Am besten war `COP = a · T_außen + b · T_Vorlauf + c`; Modelle mit der Differenz Vorlauf − außen als einziger Größe nennen sie als gängige Alternative. Ein Carnot-basiertes Modell lehnen sie ab, weil es bei kleinem Temperaturabstand unrealistisch hohe Werte liefert. Das passt zur Probe oben: Der Gütegrad überkorrigierte. Ihre Form (Außentemperatur und Vorlauf getrennt, COP linear) war in der Probe oben etwas schlechter als `1/AZ` linear im Hub, beide streuten um etwa 2 %.

**Regel (Vorschlag).**

- **Tage:** wie der Gütegrad-Sensor (`carnot.factor_day`, `statistics_days`) mit Wärme, Strom, Senke und Außentemperatur in den Heizstunden. Abweichungen:
  - Heizstab-Tage zählen mit, ihr Heizstab-Strom kommt zum Strom (H3 wie bisher in 4.1; „Heizstab läuft mit“ ist eine der gesuchten Ursachen).
  - Hat eine Seite ≥ `FLOW_ONLY_NOTE_SHARE` der Wärme ohne Rücklauf, nehmen beide Seiten als Senke nur den Vorlauf.
  - Energie aus `_async_comparison_hours`: gleiche Methode auf beiden Seiten, wie heute.
- **Modell:** gewichtete kleinste Quadrate über die Tage der Vorsaison, Gewicht = Wärme des Tages. Zwei Unbekannte, reines Python (2×2-Normalgleichungen; `heat_load.fit_line` prüfen).
- **Vorhersage:** nur für Tage der laufenden Saison, deren Hub im Bereich der Vorsaison liegt (± 1 K). Keine Hochrechnung über den Bereich hinaus. Erwarteter Strom = Σ Wärme_d · (a + b · Hub_d). `Rückgang = 1 − erwarteter Strom / gemessener Strom`. Anschaulich: so viel mehr Strom braucht die Anlage, als sie bei diesem Wetter und diesem Vorlauf früher gebraucht hätte.
- **Schwellen** 15 % an, 10 % aus unverändert. Bei einer Streuung von rund 2 % ließe sich die Schwelle später senken; erst nach dem Winter an weiteren Anlagen entscheiden.
- **Mindestdaten:** Vorsaison ≥ 30 Tage und Hub-Spanne ≥ 4 K (sonst ist die Steigung kaum bestimmt). Laufende Saison ≥ 14 Tage im Bereich und ≥ 10 kWh Strom.
- **Neuer Grund `outside_previous_range`** (unbekannt, „Vorlauf oder Wetter anders als Vorsaison“): Die laufende Saison hat genug Tage, aber zu wenige davon im Hub-Bereich der Vorsaison. Typisch nach einer deutlich geänderten Heizkurve oder in einem viel kälteren Winter. Der Text sagt sinngemäß: „Vorlauf oder Wetter außerhalb dessen, was die Vorsaison kennt; Vergleich, sobald es genug vergleichbare Tage gibt“.
- **Ohne Vorlauf-Sensor** (oder ohne Vorlauf-Statistik und ohne Tagebuch-Tage): dasselbe Modell mit der Außentemperatur statt des Hubs (`1/AZ = a + b · T_außen`). Eine geänderte Heizkurve bleibt dann unsichtbar, der Text nennt sie als erste mögliche Ursache. Keine Schaltfläche, kein neues Feld (Einfache Einrichtung). Die bisherige Klassenrechnung (`common_ranges`) entfällt damit ganz, wenn die Probe ohne Senke nicht schlechter ist als heute (bei der Umsetzung prüfen).
- **Später, offen:** Statt „Saison bis gestern“ die letzten 28 Heiztage gegen die 12 Monate davor. Das ist unabhängig vom Saisonbeginn und reagiert schneller auf einen plötzlichen Defekt mitten im Winter; die Probe oben ist genau dieser Fall. Nach dem Umbau entscheiden.

**Schaltfläche entfernen.**

- `button.py`: `RestartComparison` weg. Beim Laden die Entität `restart_comparison` aus der Entitäten-Registry entfernen, sonst bleibt sie als „nicht mehr bereitgestellt“ stehen.
- `comparison_reset_at`: beim Laden ignorieren und beim nächsten Speichern weglassen. Ein laufender Neustart endet damit sofort.
- `RESTARTED` aus `STATUS_REASONS`, Übersetzungen und Karte entfernen, `outside_previous_range` ergänzen. Dazu `tests/test_manifest.py`, `tests/ha/test_health.py`, README („Effizienzvergleich neu starten“), Demo.

**Anzeige.**

- Attribute `basis` (`lift` oder `outdoor`), `ratio_current`, `ratio_expected` (AZ, die das Modell für dieselben Tage erwartet; ersetzt `ratio_previous_same_weather`), `drop_percent`, `threshold_percent`, `days_compared`, `days_current`, `days_previous`, `x_range` (Hub bzw. Außentemperatur der Vorsaison) und `model` (`a`, `b`).
- `classes` entfällt. Ersatz zum Nachvollziehen: `by_outdoor` mit gemessener und erwarteter AZ je 2-K-Klasse der laufenden Saison (nicht aufgezeichnet).
- Karte, Zeile „Effizienz“: wie bisher („In Ordnung“, „−18 % gegenüber Vorsaison“). Bei `outside_previous_range`: „Vorlauf oder Wetter anders als Vorsaison“.

**Last.** Keine neue Abfrage: Vorlauf, Rücklauf, außen und die Stunden liegen im täglichen Lauf schon vor (Kennlinie gegen 3 Uhr). Rechenaufwand: zwei Schleifen über die Tage zweier Saisons. Kein neues Speichern; mit `comparison_reset_at` fällt sogar ein Feld weg.

**Schritte.**

1. `health.py`: neue Funktion für das Basismodell, reines Python mit Tests. Fälle:
   - Heizkurve gesenkt bzw. gehoben (kein Fehlalarm)
   - echter Verlust von 20 % bei gleicher Heizkurve und bei gleichzeitig gesenkter Heizkurve (Alarm)
   - Hub außerhalb des Bereichs (`different_flow`)
   - zu kleine Hub-Spanne, eine Seite ohne Rücklauf, Heizstab-Tag, Hysterese
2. `carnot.py`: Tage auch mit Heizstab liefern (heute fallen sie mit `SKIP_AUX` vorher heraus), Variante „nur Vorlauf“.
3. `runtime.py`: Modell statt `common_ranges`. Schaltfläche und `comparison_reset_at` entfernen, Registry aufräumen, HA-Test für das Entfernen der Entität.
4. Karte, `strings.json`/Übersetzungen (`tools/make_strings.py`), README, Demo (`tools/make_demo.py`, `docs/demo/index.html`), Quellen unten (FEMP 5.0, Brudermueller u. a. 2025), CHANGELOG unter „Geändert“: „Effizienz gesunken rechnet Wetter und Vorlauf heraus; die Schaltfläche ‚Effizienzvergleich neu starten‘ entfällt“.
5. Vor dem Release mit dem Code noch einmal gegen die Statistik der Anlage des Inhabers rechnen (Skript aus Schritt 0) und die Probe ohne Senke wiederholen.

**Umgesetzt (2026-11-11).** Wie oben, mit drei Abweichungen:
- Tagebuch-Tage gehen nicht ein, nur Statistik-Tage. Ohne Vorlauf-Statistik gilt deshalb die Außentemperatur-Basis, auch wenn das Tagebuch einen Vorlauf kennt.
- Der Grund heißt `outside_previous_range` statt `different_flow`, weil er auch bei der Außentemperatur-Basis gilt.
- Die Hub-Basis gilt, sobald die Vorsaison 30 Hub-Tage hat oder auch die Außentemperatur-Basis keine 30 Tage hätte.

**Probe mit dem Code der Integration** an der Anlage des Inhabers, dieselben 31 Fenster:
- Hub-Basis: Streuung etwa 2 %, kein Fenster über einem Viertel der Schwelle, kein Fehlalarm.
- Außentemperatur-Basis: Streuung knapp 5 % wie bisher, das Fenster mit der hohen Heizkurve bei gut neun Zehnteln der Schwelle, kein Fehlalarm. Sie ist so blind für die Heizkurve wie die bisherige Klassenrechnung. Die Klassenrechnung (`common_ranges`) ist entfernt.

### 4.2 Heizstab im Heizbetrieb bei milder Witterung

**Was und warum.** Der Heizstab heizt an Tagen, an denen die Wärmepumpe allein reichen müsste. Mögliche Ursachen: Bivalenzpunkt oder Zuheizer-Freigabe zu hoch eingestellt, Estrichtrocknung, Störung des Verdichters. Heizstab-Strom hat AZ 1 und ist teuer.

**Regel.**

- Eingabe: Stundenwerte `AUX` im Modus Heizen und Stundenmittel der Außentemperatur (wie `curve.daily_samples`, Tage mit ≥ 20 gültigen Stunden).
- Milder Tag: Tagesmittel ≥ 5 °C.
- **An**, wenn in den letzten 7 vollen Tagen der Heizstab an milden Tagen zusammen ≥ 2 kWh fürs Heizen verbraucht hat. Das rollende Fenster ist die Hysterese: aus nach 7 Tagen ohne.
- Warmwasser zählt nicht: Legionellenschaltungen dürfen den Heizstab nutzen (dafür 4.9).
- Heizstab während einer Abtauung zählt nicht (siehe 4.9, „Heizstab beim Abtauen“), er steht getrennt in `aux_kwh_defrost_7d`.
- Einmal täglich mit der Analyse.

**Mindestdaten.** Ein Heizstab-Zähler (je Modus oder gesamt) und eine Außentemperatur; mindestens 3 milde Tage im Fenster mit Wärme Heizen > 0, sonst `unknown`. 2 kWh sind bei ganzzahligen Zählern (EMS-ESP liefert den Heizstab je Modus nur in ganzen kWh, `ENTWICKLUNG.md` §4) zwei Schritte, also kein Rundungseffekt.

**Quelle.** Fraunhofer ISE (WP-QS): Heizstab-Anteil im Mittel ~1,3 %, Ausreißer 17 %/21 % waren Defekte; die Leistung bei A−7/W35 liegt im Mittel ~50 % über der Heizlast (`ENTWICKLUNG.md` §3). Eine so ausgelegte Wärmepumpe braucht bei +5 °C keinen Heizstab. Die Grenze 5 °C und die Menge 2 kWh/7 Tage sind **eigene Annahme** (deutlich über der Normaußentemperatur, in Deutschland etwa −9 … −16 °C).

**Fehlalarme.** Estrichtrocknung und Inbetriebnahme (gewollt), Notbetrieb nach einer Störung, Sperrzeit mit Zuheizer-Freigabe, falsch zugeordneter Gesamt-Heizstab (bei „Strom Heizstab gesamt“ bucht Wärmewacht ihn dem laufenden Modus zu; eine Legionellenschaltung direkt nach einem Heizlauf kann so ins Heizen rutschen).

**Anzeige.** Binärsensor „Heizstab bei milder Witterung“. Attribute: `aux_kwh_7d` (ohne Abtauen), `aux_kwh_defrost_7d`, `mild_days_7d`, `days` (je Tag Datum, Mittel, Heizstab kWh, ggf. `aux_kwh_defrost`; nicht aufgezeichnet), `min_outdoor_temp`, `threshold_kwh`, `reason`.

Ergänzend, ohne Alarm: Attribut `field_mean_percent: 1.3` am bestehenden Sensor „Heizstab-Anteil Saison“ zur Einordnung (umgesetzt in 0.8.0).

### 4.3 Abtauungen auffällig

**Was und warum.** Sehr viele oder sehr lange Abtauungen kosten Effizienz (OEM: ~0,1 JAZ/Jahr allein durchs Abtauen, `ENTWICKLUNG.md` §3). Zu häufig: vereister Verdampfer, Fühler, Luftführung. Abtauen über +10 °C: Fühler- oder Regelfehler.

**Regel (Vorschlag).**

- Abtauung bei Stundenmittel ≥ 10 °C: Zähler `warm_defrosts_7d`; Hinweis ab 3 in 7 Tagen.
- Dauer: eine Abtauung > 15 min oder Mittel > 8 min in 7 Tagen.
- Häufigkeit: Abtauungen je Laufstunde je 2-K-Klasse gegen die Vorsaison, Hinweis ab dem Doppelten. Braucht das Tagesbuch (4.11).

**Quelle.** Beobachtet 3–4 min je Abtauung an der Anlage des Inhabers (`ENTWICKLUNG.md` §4). Alle Schwellen **eigene Annahme**; für Häufigkeit und Dauer keine Quelle gefunden. Abtauen hängt stark an der **Luftfeuchte** (am meisten bei 0 … 5 °C und hoher Feuchte), und die hat Wärmewacht nicht.

**Fehlalarme.** Hoch: Nebel, Nieselregen, Schnee. Hersteller tauen auch zeitgesteuert ab. Abtauen liefern nur Quellen mit Betriebsart (EMS-ESP `hpactivity` und mehrere Beta-Vorlagen), HomeCom nicht.

**Anzeige.** Zunächst nur Attribute am Sensor „Abtauungen heute“ (`defrosts_7d`, `warm_defrosts_7d`, `mean_minutes_7d`, `longest_minutes_7d`, `warm_from`, `classes`). Kein Binärsensor, bis eine Quelle oder ein Winter Daten liefert.

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

**Anzeige.** Sensor „Vorlauf bei −3 °C“ (°C), Attribute `previous_season`, `days`, `r_squared`, `field_reference`. Kein Binärsensor. Umgesetzt als „Vorlauf bei 0 °C“ mit `slope`, `r_squared`, `days`, `spread`, `reasons`, `previous_season`, `previous_slope`, ohne `field_reference` (Definition des WPsmart-Werts noch offen).

### 4.6 Takten (bestehend) und Starts je Jahr

**Bestand.** Binärsensor „Auffälliges Takten“: mehr als 3 Starts in einer Stunde oder ≥ 3 kritische Läufe (< 6 min) in 24 h. Quellen in `ENTWICKLUNG.md` §3 (Verdichterhersteller 6–12 Starts/h, zitiert in WP-QS S. 98; Fraunhofer: Zyklen unter ~10 min gesondert ausweisen; Dimplex ~6 min Mindestlaufzeit). Eine verifizierte Primärquelle für Grenzen am Gebäude gibt es nicht; die Vorgaben sind weiche Schwellen. Fraunhofer ISE (Pressemitteilung WP-QS 2025): Schalthäufigkeit „bei einigen sehr hoch“.

**Ergänzung (umgesetzt in 0.4.6; seit 0.8.0 eigener Sensor „Starts pro Jahr“, gezählt über 12 Monate oder mit Heiztagen hochgerechnet, siehe ENTWICKLUNG.md).** Attribute an „Starts heute“ (nicht am Binärsensor, damit niemand sie für ein Kriterium hält): `starts_per_day_7d` und `starts_per_year_projected` (Starts der letzten 7 vollständigen Tage je beobachteter Stunde × 24 bzw. × 24 × 365; seit 0.4.7 ohne die Zeit ohne Kompressorstatus, vorher unbekannt ab 1 h Lücke), `starts_field_class` (`low_third` ≤ 2.000, `typical` ≤ 5.500, `top_10_percent` darüber), `starts_7d_days`, `starts_7d_observed_hours`, `starts_7d_reason` (`too_few_days`, `too_few_hours` unter 144 beobachteten Stunden). Orientierung: 90 % der Luft/Wasser-Anlagen im Fraunhofer-Feld unter 5.500 Starts/Jahr (~15/Tag), ein Drittel ≤ 2.000 (`ENTWICKLUNG.md` §3). Kein neues Kriterium für „an“: eine Hochrechnung aus 7 Tagen im Herbst ist keine Jahreszahl. Die Karte „Takte“ zeigt sie als Kachel.

**Grenze je Tag (optional, seit 0.4.6).** Einstellung „Auffällig ab Starts pro Tag über“, Vorgabe aus: mehr Starts in den letzten 24 Stunden (dasselbe Fenster wie die übrigen Kriterien) schalten „Auffälliges Takten“ und „Befund Takten“ auf auffällig. Für Wärmepumpen, die nur ein- und ausschalten. **Keine Quelle**, der Nutzer wählt die Grenze; deshalb keine Vorgabe. Attribute `triggers`, `starts_24h`, `starts_per_day_limit`.

### 4.7 Überdimensionierung (Leistung gegen Heizlast)

**Was und warum.** Eine zu große Wärmepumpe taktet in der Übergangszeit und läuft selten im effizienten Bereich. Fraunhofer ISE (Pressemitteilung WP-QS 2025): Überdimensionierung ist häufig.

**Regel (Vorschlag).**

- Neue optionale Einstellung **Nennleistung (kW) bei A−7/W35** (Datenblatt).
- Kennwert `Leistung / Heizlast = Nennleistung / Heizlast normgerecht bei Normaußentemperatur` (`heat_load.standard_kw`, braucht die Einstellung Normaußentemperatur und eine ausreichende Energiesignatur).
- Später, mit der Einstellung **kleinste Leistung (kW)**: Heizlast gemessen bei +7 °C (`a + b·7`) kleiner als die kleinste Leistung → Takten in der Übergangszeit zu erwarten. Das erklärt „Auffälliges Takten“, statt es nur zu melden.

**Quelle.** Fraunhofer ISE (WP-QS): Leistung bei A−7/W35 im Mittel ~50 % über der Heizlast, also Faktor ~1,5 im Feldmittel (`ENTWICKLUNG.md` §3). Das ist ein Mittelwert, keine Grenze: Ein Alarm ab 1,5 träfe die halbe Feldmenge. Keine Alarmschwelle (**eigene Entscheidung**).

**Fehlalarme.** Nennleistung je Datenblatt bei anderen Bedingungen (A2/W35, A7/W35); Heizlast aus nur einer Saison; Warmwasserbedarf und Sperrzeiten rechtfertigen Reserve.

**Anzeige.** Sensor „Leistung je Heizlast“ (Faktor), Attribute `rated_kw`, `heat_load_kw`, `field_mean: 1.5`. Als Hinweis-Attribut am Takt-Binärsensor (`oversized_factor`), wenn vorhanden (noch nicht umgesetzt).

### 4.8 Stillstand ungewöhnlich hoch

**Was und warum.** Strom bei stehendem Kompressor (Regelung, Kurbelwannenheizung, Pumpen im Stillstand) zählt in die JAZ. Ein Anstieg kann eine dauernd laufende Kurbelwannenheizung oder eine nicht abschaltende Pumpe sein.

**Regel (Vorschlag).** Mittlere Stillstandsleistung der letzten 7 Tage (Stillstand-kWh ÷ Stunden ohne Lauf) gegen den Median der 30 Tage davor: Hinweis bei +50 % **und** +10 W. Gleiche Außentemperatur-Klasse wäre besser (Kurbelwannenheizung läuft bei Kälte mehr), braucht das Tagesbuch.

**Quelle.** Keine. Schwellen **eigene Annahme**.

**Fehlalarme und Nutzen.** Bei Bosch/Buderus ist der Stillstand ein konstanter Modellwert der Firmware (~25 W, `ENTWICKLUNG.md` §4): Die Prüfung meldet dort nie etwas Echtes. Nützlich erst mit externem Stromzähler (H4). Nebennutzen: Weicht der Wert je von 25 W ab, ist das ein Hinweis auf Messung statt Modellwert (`NOTES.md`, offener Punkt 7) – als Attribut am Stillstand-Sensor (`mean_power_w_7d`), ohne Alarm.

### 4.9 Warmwasser: AZ je Ladung, Heizstab und Legionellenschaltung

**Was und warum.** Sinkt die AZ normaler Ladungen, steigt die Speichertemperatur oder der Wärmetauscher verkalkt. Heizstab bei normalen Ladungen (nicht bei der Legionellenschaltung) deutet auf eine Fehleinstellung.

**Regel (Vorschlag).**

- AZ normaler Ladungen (ohne Legionellenschaltung, `charges.disinfection_split`) der letzten 30 vollen Tage gegen dieselben 30 Tage des Vorjahres (Kaltwassertemperatur schwankt mit der Jahreszeit; gleitendes Fenster statt Kalendermonat, damit der Vergleich jeden Tag gilt): Hinweis ab 15 % Rückgang, mindestens 10 Ladungen je Seite.
- Heizstab-Anteil normaler Ladungen > 10 %: Hinweis.
- Kennwert: Tage seit der letzten Legionellenschaltung (≥ 60 °C nach DVGW W 551, schon in `charges.py`).

**Quelle.** Fraunhofer ISE (WP-QS): AZ Warmwasser im Feld 2,8 (n = 18) zur Einordnung. 60 °C nach DVGW W 551 (`charges.py`). 15 % und 10 % **eigene Annahme**.

**Umsetzung (0.1.0b8).** `charges.ChargeTracker` bildet Ladungen aus der Betriebsart (Abtauen beendet keine Ladung; Energie bis 5 Minuten nach dem Ende zählt noch, bei ganzen kWh bis 2 Stunden oder bis zur nächsten Ladung, seit 0.1.6). Signal `dhw_temp`. Problem-Sensor `aux_dhw_charges` für den Heizstab-Anteil normaler Ladungen (30 Tage, ab 10 Ladungen, > 10 %). „Letzte thermische Desinfektion“ hängt nur an der Speichertemperatur (Übergang über die Schwelle, neu erst nach 5 K darunter), damit sie auch ohne Betriebsart und bei Bosch HomeCom geht. Vorjahresvergleich (2026-10-30, `health.dhw_efficiency_drop`): Problem-Sensor `dhw_efficiency_drop`, beide Seiten aus dem Tagebuch (normale Ladungen je Tag seit 0.1.0b8), bewertet in der Tagesanalyse; 29. Februar zählt als 28. Ohne Speichertemperatur kein Sensor (Desinfektion nicht trennbar). Greift frühestens ab Ende Oktober 2027.

**Heizstab beim Abtauen (seit 0.2.8).** Beobachtet an einer Bosch Compress (EMS-ESP, 05.11.2026, ~0 °C): Abtauung mitten in einer Warmwasserladung, der Heizstab lief nur während der Abtauung (`auxheaterstatus` = „Abtauen“), Bosch buchte ihn auf den Warmwasser-Heizstabzähler. Die Ladung selbst brauchte ihn nicht. Deshalb gehört Heizstab-Energie, die während einer Abtauung oder bis `runs.DEFROST_LATE` (2 min) danach eintrifft, zur Abtauung (`Defrost.aux_kwh` je Modus) und bei einer Ladung zu `Charge.aux_defrost_kwh`. Sie bleibt im Strom der Ladung und des Modus (AZ nach H3, Abtauen ist Aufwand des Modus), zählt aber nicht in den Heizstab-Anteil von `aux_dhw_charges` und nicht in `aux_mild_weather`; beide zeigen sie getrennt (`aux_kwh_defrost`, `defrost_aux_charges` bzw. `aux_kwh_defrost_7d`). Der Anteil bezieht sich weiter auf den ganzen Strom der Ladungen. 2 min sind **eigene Annahme**: Beim beobachteten Fall kam der letzte Zählerschritt 50 s nach dem Abschalten des Heizstabs, in derselben Sekunde wie der Wechsel zurück auf Warmwasser (Werte alle 20–40 s). Nur mit laufendem Zähler in 0,01 kWh; ganze kWh, Tages- und Stundenwerte (Bosch HomeCom, ViCare, MELCloud …) sind zu grob oder zu spät, dort bleibt alles beim Modus. Ohne Betriebsart mit Abtauen ebenso. Nur live: Der Rückblick bildet keine Ladungen, und in Abtauungen aus dem Verlauf (`replay`) steht kein Heizstab. Eine eigene Prüfung „Heizstab beim Abtauen“ gibt es nicht (keine Quelle für eine Grenze, bisher ein Fall); erst nach einem Winter mit Daten entscheiden.

**Befund in Worten (seit 0.2.8).** Je Prüfung ein Enum-Sensor `<prüfung>_status` (`sensor.HealthStatus`) mit den Zuständen `ok`, `problem` und den Gründen aus `health.STATUS_REASONS`; Home Assistant übersetzt sie (strings.json, `state`). Gleiche Bedingungen wie die Binärsensoren (`binary_sensor.health_checks`). Ein Grund außerhalb der Liste ergibt *unbekannt*, damit ein neuer Grund nie als falscher Text erscheint; wer einen neuen Grund einführt, nimmt ihn in `STATUS_REASONS` und die Übersetzungen auf (Test `test_status_states_are_translated`).

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

**c) Außentemperatur steht still oder ist unplausibel** (`outdoor_temp_stuck`, `outdoor_temp_implausible`; im Entwurf ein Schlüssel `outdoor_temp`)

- Steht: In der Langzeitstatistik 48 aufeinanderfolgende Stunden mit Min = Max (über Neustarts hinweg; `last_changed` taugt nicht, weil ein Neustart ihn zurücksetzt).
- Unplausibel: Stundenmittel außerhalb −35 … +45 °C in mehr als 3 Stunden des Vortags. Diese Werte verwirft `curve.py` schon (Sommerspitzen bis 44 °C durch Sonne/Abwärme, `ENTWICKLUNG.md` §4).
- Warum wichtig: Kennlinie, Heizlast, 4.1 und 4.2 hängen an diesem Fühler.
- Eine zweite, unabhängige Quelle zum Vergleich gibt es bei EMS-ESP nicht (`thermostat_dampedoutdoortemp` ist derselbe Fühler gefiltert). Ein Vergleich mit einer Wetter-Entität wäre möglich, ist aber nicht im MVP.

**d) Vor- und Rücklauf vertauscht** (`flow_return_swapped`): Tagesmittel der Spreizung im Heizbetrieb < −1 K bei mindestens 60 min Heizbetrieb. Im Heizbetrieb hebt die Wärmepumpe die Wassertemperatur; der Vorlauf ist wärmer als der Rücklauf (Physik). Abtauen ist ausgenommen (gemessen wird nur bei Betriebsart Heizen). Fehlalarm möglich, wenn der Vorlauf hinter einem Mischer gemessen wird.

**e) Durchfluss 0 oder unplausibel bei laufendem Kompressor** (`flow_zero`, `flow_implausible`; umgesetzt für 0.1.1, siehe Anfang von Abschnitt 4): Durchfluss 0 über 15 min Heizbetrieb, oder Abweichung um mehr als den Faktor 10 von `Wärmeleistung / (1,163 Wh/(l·K) × Spreizung)` (spezifische Wärme von Wasser). Fängt Einheitenfehler wie bei HomeCom (l/h als „L/min“). Braucht eine Beobachtung, was `pc0flow` bei Warmwasser und Abtauen zeigt (Fixture), deshalb nicht im MVP; gemessen wird nur bei Betriebsart Heizen.

### 4.11 Grundlage: Tagesbuch

Mehrere Prüfungen (4.3 Häufigkeit, 4.4, 4.5, 4.8 je Klasse, 4.9 Vorjahr, Vorlauf je Klasse in 4.1) brauchen Tageswerte über die 40 Tage der Lauf-Historie hinaus. Vorschlag: um Mitternacht je Tag ein Eintrag mit Außentemperatur-Mittel, Laufzeit je Betriebsart, Starts, Abtauungen (Anzahl, Minuten), Spreizung und Vorlauf (Summe und Sekunden aus `Mean`), Stillstand-kWh. Etwa 150 Bytes je Tag, ~55 KB je Jahr, gespeichert mit dem ohnehin anstehenden Mitternachts-Speichern der Datei `.history`. Keine neue Schreiblast.

Alternative ohne Speicher: Vorlauf und Spreizung aus der Langzeitstatistik der Temperatur-Entitäten. Verworfen, weil sie nicht nach „Kompressor im Heizbetrieb“ filtert (Warmwasser- und Stillstandszeiten mischen sich ein).

### 4.12 Einordnung gegen Feldtests (kein Alarm)

Attribut `field_reference` an „AZ Heizen+WW Saison“: Fraunhofer ISE WP-QS (Luft/Wasser JAZ 3 Mittel 3,4, Spanne 2,6–4,9), WPsmart im Bestand (Mittel 3,1, n = 29), heatpumpmonitor.org (Luft-Wärmepumpen, SEPEMO H4, 3,86 bei 170 Anlagen). Wichtig im Text: verschiedene Bilanzgrenzen (Wärmewacht etwa H1/H3, heatpumpmonitor H4, Fraunhofer JAZ 3 ≈ H3 mit Abtauwärme abgezogen). Gehört zu Stufe 3, nicht zum Gesundheits-Check im engeren Sinn.

### 4.13 Auffällige Statusmeldungen (umgesetzt, `status_messages.py`)

**Was und warum.** Manche Betriebsart-Entitäten melden neben den Betriebsarten auch Schutzfunktionen, Störungen und Wartezeiten, vor allem eigene Status-Templates bei manueller Zuordnung („Durchflussüberwachung“, „Hochdrucksicherung“, „Schaltspielsperre“), aber auch Bosch PointT `alarm`. Wärmewacht ordnet sie keiner Betriebsart zu („sonstige“, der Strom bleibt beim Modus davor). Anlass (simon42-Forum, 2026-11): eine Anlage meldete tagelang bei jedem Heiztakt „Durchflussüberwachung“ – ein Hinweis auf zu wenig Volumenstrom (Filter, Luft, Pumpe, Ventil), den bisher nur die Diagnose-Datei (`events`) zeigte.

**Regel.**

- Gezählt wird das **Annehmen** eines Textes ohne Betriebsart (`Activity.OTHER`): Der Text der Betriebsart-Entität wechselt von einem anderen bekannten Text zu ihm. `unknown`/`unavailable` dazwischen ändern nichts, ein Neustart ist also keine Meldung, der erste Text nach der Einrichtung auch nicht. Attributänderungen mit gleichem Text zählen nicht.
- **Vor dem Abtauen** zählt eine Schutz- oder Störmeldung nicht: Beginnt binnen 10 Minuten nach dem Annehmen (`BEFORE_DEFROST`, eigene Annahme) eine Abtauung (Betriebsart oder Abtau-Signal ergibt `defrost`), gehört die Meldung zur Abtauung. Anlass (simon42-Forum, 2026-11): eine Dimplex-artige Regelung meldet „Durchflussüberwachung“ in etwa 95 % der Fälle direkt vor „Abtauen“, bei laufendem Kompressor – eine normale Schutzphase vor dem Abtauen, sonst schlüge der Befund bei jeder Abtauung an; die übrigen etwa 5 % mitten im Heiztakt sind die interessanten. Dafür wartet je Text höchstens eine Meldung im Speicher, bis die 10 Minuten um sind (dann zählt sie, auf den Tag des Annehmens) oder die Abtauung beginnt (dann entfällt sie, Diagnose `status:before_defrost`). Kommt derselbe Text vorher erneut, zählt die erste (der Status endete ohne Abtauung). Eine beim Neustart noch wartende Meldung entfällt (nicht gespeichert). Warten und nicht eingeordnete Texte zählen wie bisher sofort.
- Je lokalem Tag, die letzten 7 Tage (heute mitgezählt), je Tag höchstens 20 Texte (weitere unter „…“) zu höchstens 60 Zeichen.
- Einteilung nach Wörtern (klein, Umlaute als ae/oe/ue, `-` und `_` als Leerzeichen), in dieser Reihenfolge: **Warten** (EVU, Netzbelastung, SG Ready, Schaltspielsperre, Mindeststandzeit, Spülen, Primärpumpenvorlauf, Nachlauf, Standby, utility, anti cycling, start delay, purge …), **Schutz/Störung** (Störung, Alarm, Fehler, Durchfluss, Niederdruck, Hochdruck, Druck, Frostschutz, Taupunkt, Einsatzgrenze, Sicherung, Abschaltung, Notbetrieb, error, fault, failure, pressure, low flow, flow switch, dew point, frost protection, lockout …), dann eine einfache **Sperre**/Pause (Warten). Warten zuerst, damit „EVU-Abschaltung“ kein Befund ist; die einfache Sperre zuletzt, damit „Hochdrucksperre“ einer ist. Alles andere ist nicht eingeordnet (`unclassified`), wird gezeigt, nie gezählt. Englisch nicht bloß `flow`, weil „flow temperature limit“ eine Vorlaufgrenze ist.
- **An** ab 3 Schutz- oder Störmeldungen in den 7 Tagen, alle Texte zusammen. Kein Hysterese-Wert: das rollende Fenster ist die Hysterese.
- **Unbekannt** (`too_few_days`), solange weniger als 7 Tage beobachtet sind (Zählbeginn = erster Start mit dieser Version; kein Rückblick aus dem Recorder) und es nicht an ist.
- Bewertet bei jeder gezählten Meldung (eine Schutzmeldung also erst 10 Minuten nach dem Annehmen), beim Start und um Mitternacht.

**Quelle.** Keine: Die Schwelle 3 in 7 Tagen und die 10 Minuten vor dem Abtauen sind **eigene Annahmen** (einmal ist Zufall, eine Meldung je Takt ein Muster; eine Anlage, die je Takt meldet, ist binnen eines Tages darüber). Die Wortlisten stammen aus dem echten Status-Template des Anlasses und gängigen Bezeichnungen der Hersteller; sie sind kein vollständiges Fehlerverzeichnis.

**Fehlalarme.** Eigene Templates können Wörter anders benutzen (ein Text „Druck ok“ wäre Schutz). Herstellertexte, die Schutzfunktionen im Normalbetrieb melden (Frostschutz bei Kälte), zählen mit. Deshalb steht der häufigste Text im Befund, und `protection`/`waiting`/`unclassified` zeigen jede Zuordnung.

**Datenhaltung.** `StatusCounter` (Tage, Zählbeginn, letzter Text; die wartenden Schutzmeldungen nur im Speicher, geprüft im Minutentakt ohne Arbeit, solange keine wartet) in der kleinen Live-Datei, gespeichert mit deren ohnehin laufendem Intervall (`_dirty`), kein eigenes Speichern, kein Lesen aus dem Recorder. Wechselt die Betriebsart-Entität (Neu konfigurieren), beginnt die Zählung neu (`verdict_entities`).

**Anzeige.** Binärsensor „Auffällige Statusmeldungen“ (`status_messages`) und „Befund Statusmeldungen“, nur mit Betriebsart-Entität. Attribute: `entries_7d`, `most_frequent`, `most_frequent_count`, `protection`, `waiting`, `unclassified` (je Text die Anzahl; nicht aufgezeichnet), `days_observed`, `threshold_entries`, `reason`. Gesundheitskarte und Blueprint: „Durchflussüberwachung 12× in 7 Tagen“.

### 4.14 Gütegrad und „Was bringt weniger Vorlauf?“ (Entwurf 2026-11-09; umgesetzt in `carnot.py`: Gütegrad in 0.5.0, „weniger Vorlauf“ danach als `lower_flow_kwh`/`lower_flow_percent` am Gütegrad-Sensor, Kachel in der Karte „Analyse“, Euro nur mit festem Strompreis; ein Tag, dessen tiefere Senke unter den kleinsten Hub fällt, spart nichts)

**Umsetzung (Entscheidungen des Inhabers 2026-11-09):** erst nur der Gütegrad; als Zahl mit 2 Nachkommastellen wie Fraunhofer; ohne Rücklauf mit dem Vorlauf rechnen, Attribut `sink: flow_only`, die Karte zeigt dann statt des Feldbereichs „ohne Rücklauf, eher zu hoch“. Abweichend vom Entwurf zählen **Tage mit Heizstab (über 0,1 kWh) gar nicht**, statt den Heizstab abzuziehen: Ob ein Wärmezähler die Heizstabwärme enthält, hängt von der Quelle ab. Die Außentemperatur im Heizbetrieb wird im Minutentakt gemittelt, wenn der Kompressor im Heizbetrieb läuft (dieselbe Bedingung wie Vorlauf und Spreizung). Sensor `efficiency_factor`, Attribute wie unten, dazu `skipped_days` (je Grund: `no_energy`, `little_heating`, `aux`, `no_outdoor`, `small_lift`); Kachel in der Karte „Analyse“. Diagnose `efficiency_factors`.

**Rückblick aus der Langzeitstatistik (Andys Ja 2026-11-09, `carnot.statistics_days`):** Tage ohne Tagebucheintrag mit `outdoor_heating` (vor der Einrichtung, vor dem Update) kommen aus den Stundenmitteln von Vorlauf, Rücklauf und Außentemperatur, nur Stunden mit ≥ 0,3 kWh Heizwärme und ohne Warmwasser oder Kühlen (`heating_curve.heating_weights`, wie „Vorlauf bei 0 °C“), mindestens 2 je Tag; COP_Carnot des Tages wärmegewichtet über diese Stunden, Energie des Tages aus allen Stunden. Vorrang: Tagebuchtag mit `outdoor_heating` > Statistiktag > Tagebuchtag mit Tagesmittel. Den Rücklauf liest die tägliche Auswertung in derselben Abfrage wie den Vorlauf (eine Reihe mehr, keine neue Abfrage). Attribut `days_from_statistics`. **Winter (Entscheidung 2026-11-09):** Der Sensor zeigt die ganze Saison, dazu `winter` und `previous_winter` (November bis März des Heizjahrs Juli bis Juni von gestern und des davor, bis gestern; `carnot.winter_year`, `carnot.winter_span`; seit 2026-11-10 unabhängig vom Saisonbeginn: bei Saisonbeginn Januar fielen sonst Januar bis März aus beiden heraus, simon42 95035 #126; begrenzt auf den Beginn der Vorsaison, ab dem die Statistik gelesen wird), und die Karte vergleicht den Winter mit dem Feldbereich. Grund: Fraunhofer wertete November 2023 bis März 2024 aus; an der Anlage des Inhabers fiel der Monatswert der Vorsaison von 0,30 (Januar) auf 0,24 (Mai), die Übergangsmonate mit wenig Last, Takten und kleinem Hub drücken die ganze Saison unter den Wintervergleich. **Prüfung vor dem Einbau** an der Anlage des Inhabers (30.10.–9.11.2026, 10 Tage mit 7–19 h Heizbetrieb, Referenz: Rohverlauf von Kompressor, Betriebsart, Vor-/Rücklauf und Außentemperatur, gemittelt nur im Heizbetrieb wie das Tagebuch): COP_Carnot je Tag aus der Statistik −0,4 % bis +1,4 % gegenüber der Referenz, Mittel +0,5 % (Gütegrad 0,390 statt 0,392). Strengere Filter (Nachbarstunden ebenfalls Heizen: −1,4 … +4,0 %; zusätzlich ≥ 70 % der stärksten Stunde des Tages: bis +21,5 %) ließen zu wenige Stunden übrig und waren schlechter. **Offen:** an einer stark taktenden Anlage prüfen (Übergangszeit, Frühjahr): dort enthält ein Stundenmittel Pausenminuten, die Senke wird zu niedrig, COP_Carnot zu groß, der Gütegrad zu klein.

**Was und warum.** Die Arbeitszahl hängt vor allem an zwei Temperaturen: draußen (Wetter) und im Heizkreis (Heizkurve). Ein schlechter Monat sagt deshalb wenig über die Maschine. Der **Gütegrad** nimmt beide heraus: gemessene Arbeitszahl ÷ bestmögliche Arbeitszahl bei denselben Temperaturen (Carnot). Er zeigt, wie gut die Wärmepumpe aus ihren Bedingungen etwas macht, und ist über Monate, Saisons und Anlagen vergleichbar. Auf ihm baut die zweite Kennzahl auf: wie viel Strom eine um 1, 2 oder 3 K tiefere Heizkurve gespart hätte. Das ist der häufigste Rat zur Effizienz, aber kaum jemand weiß, was er der eigenen Anlage bringt.

**Definition (wie Fraunhofer ISE, WP-QS im Bestand).** COP_Carnot = T_Senke / (T_Senke − T_Quelle), Temperaturen in Kelvin. **Senke = Mittel aus Vor- und Rücklauf, Quelle = Eintritt der Quelle**, bei Luft also die Außentemperatur. Nur Heizbetrieb; Strom von Verdichter, Regelung und Quellenantrieb (SPF 2); Wärme vor dem Speicher (Günther u. a. 2026, Abschnitt 4.2). Gemessen aus Jahreswerten (November 2023 bis März 2024): **Luft/Wasser 0,32 bis 0,44, Mittel 0,39 (36 Anlagen)**, Sole/Wasser 0,44 bis 0,52, Mittel 0,46 (9 Anlagen). Gegenüber der Feldmessung 2008/09 im Mittel +30 % bei Luft/Wasser. Fixed-Speed- und zweistufige Geräte liegen eher unten; mit der Temperaturdifferenz hängt der Wert in der Stichprobe nicht zusammen. Abtauungen, Teillast und Takte stecken mit drin (Jahreswert, kein Prüfstandspunkt).

Nicht verwechseln: heatpumpmonitor.org rechnet „% of Carnot“ mit Aufschlägen (Kondensation = Vorlauf + 2 K, Verdampfung = außen − 6 K) und kommt so meist auf 45 bis 55 % (OpenEnergyMonitor, „% of ideal Carnot COP“). Die Aufschläge verkleinern die Carnot-Arbeitszahl, der Gütegrad wird größer. Wärmewacht rechnet ohne Aufschläge wie Fraunhofer, damit 0,39 als Vergleich gilt.

**Rechnung (Vorschlag).**

- Grundlage ist das Tagesbuch (4.11): je Tag Wärme, Strom und Heizstab Heizen (`energy`), Vorlauf- und Spreizungsmittel im Heizbetrieb (`flow`, `spread`). T_Senke = Vorlauf − Spreizung/2.
- **Neu im Tagesbuch:** `outdoor_heating`, das Mittel der Außentemperatur unter derselben Bedingung wie Vorlauf und Spreizung (Kompressor im Heizbetrieb), als `Mean` wie `flow`. Das Tagesmittel `outdoor` mischt Stunden ohne Lauf ein. Einträge ohne das Feld nehmen `outdoor` (Attribut `source_temp: day_mean`). Ein paar Bytes je Tag, kein zusätzliches Speichern.
- **Heizstab heraus:** Wärme und Strom der Wärmepumpe = Heizen minus Heizstab (Heizstabwärme = Heizstabstrom, Wirkungsgrad 1). Sonst zieht ein Heizstabtag den Gütegrad nach unten, obwohl die Wärmepumpe gut lief.
- **Gütegrad eines Zeitraums = Σ (Q_Tag / COP_Carnot,Tag) ÷ Σ W_Tag**, also Strom einer idealen Maschine ÷ Strom der echten. Wärmegewichtet: Kalte Tage mit viel Wärme zählen stärker, milde Tage mit wenig Wärme und großem COP_Carnot verzerren nicht. Fraunhofer bildet den Wert aus Jahreswerten; die Rechnung je Tag ist **eigene Wahl** (genauer, weil COP_Carnot nicht linear in der Temperatur ist). Der Unterschied ist klein; im README steht trotzdem „Vergleichswert, kein Prüfstandswert“.
- **Welche Tage:** mindestens 2 h Heizbetrieb (wie 4.5), Strom Heizen ab dem Mindeststrom, T_Senke − T_Quelle ab 10 K (**eigene Annahme**: darunter wird COP_Carnot sehr groß, und 0,5 K Fühlerfehler ändern den Tag um über 5 %). Zeiträume: Monat ab 7 Tagen, Saison ab 14 Tagen (wie 4.5), sonst unbekannt mit `reason` (`too_few_days`, `no_flow_temp`, `no_activity`, `no_daily_energy`).
- **Ohne Rücklauf:** Senke = Vorlauf. Die Carnot-Arbeitszahl wird damit zu klein und der Gütegrad zu groß (Vorlauf 35 °C, Spreizung 5 K, außen 0 °C: COP_Carnot 8,80 statt 9,40, Gütegrad 6,8 % zu hoch). Attribut `sink: flow_only`, in der Karte dann kein Vergleich mit dem Feldwert. Alternative: unbekannt (offene Frage). **Seit 2026-11-10** (Anlass simon42 95035 #117/#119: EMS-ESP mit Rücklauf zeigte „ohne Rücklauf“) zählt der Anteil: `flow_only_days` (Tage mit Wärme ohne Rücklauf) und `flow_only_percent` (Anteil der Wärme), `sink: flow_only` erst ab 10 % der Wärme (`FLOW_ONLY_NOTE_SHARE`, eigene Annahme: darunter höchstens ~0,7 % zu hoch, weniger als die Abweichung des Rückblicks). Vorher markierte ein einziger Tag oder eine einzige Stunde (Rückblick: Rücklauf ohne Stundenmittel oder über dem Vorlauf) die ganze Saison. Im Rückblick zählt je Tag die Wärme der Stunden ohne Rücklauf, nicht mehr „Tag ganz oder gar nicht“.
- **Kein Rückblick:** Vorlauf im Heizbetrieb gibt es nur im Tagesbuch, also ab der Einrichtung (die Langzeitstatistik der Vorlauf-Entität mischt Warmwasser und Stillstand ein, verworfen wie in 4.11). Erste Werte nach 7 bzw. 14 Heiztagen. Quellen ohne Tagesenergie im Tagebuch (Stundenstatistik, Vortageswerte wie HomeCom und MELCloud) und ohne Betriebsart bekommen keinen Gütegrad.

**Was bringt weniger Vorlauf (Vorschlag).**

- Mit dem eigenen Gütegrad g des Zeitraums: Strom bei k Kelvin tieferer Heizkurve W_k = Σ Q_Tag / (g × COP_Carnot(T_Senke − k, T_Quelle)), Ersparnis = W − W_k, für k = 1, 2, 3, in kWh, Prozent und Euro (fester Strompreis bzw. Mittel des Preis-Sensors wie bei den Kosten). Für die laufende Saison bisher und die Vorsaison, **keine Hochrechnung auf ein Jahr**.
- Annahmen, im README genannt: gleiche Wärme (die Räume bleiben warm, sonst geht es nicht), gleicher Gütegrad, Spreizung unverändert (die ganze Senke wandert um k).
- **Gegenprobe mit Feldwerten.** Die Carnot-Formel allein ergibt je Kelvin tiefer eine um 2,6 % höhere Arbeitszahl bei 35 °C Senke und 0 °C draußen, um 2,0 % bei 45 °C. Brudermueller u. a. (2025; 708 Wärmepumpen, Heizkurve 1 K parallel tiefer, eigenes COP-Modell je Anlage): **SCOP im Mittel +0,11, Strom −2,61 %**; sie zitieren Lämmle u. a. mit +0,10 bis 0,13 je Kelvin (49 Anlagen). Die Rechnung liegt also im belegten Bereich.
- **Grenzen.** Ob die Räume warm bleiben, weiß Wärmewacht nicht; deshalb nur 1 bis 3 K und keine Empfehlung „stell auf X °C“. Bei sehr tiefem Vorlauf kann der Gütegrad sinken (Teillast, mehr Takte), die Zahl ist eher eine obere Grenze. Nur lesen, nie steuern: Wärmewacht ändert die Heizkurve nicht.
- Warum es sich lohnt: In 57 % der Fälle ist die Heizkurve zu hoch eingestellt, und 68 % der befragten Nutzer wünschen sich Rückmeldung zu Ersparnis und Effizienz (beides zitiert in Brudermueller u. a. 2025, Diskussion).

**Anzeige (Vorschlag).**

- Sensor **„Gütegrad Heizen Saison“** (Zahl mit 2 Nachkommastellen wie bei Fraunhofer, `state_class: measurement`; Prozent siehe offene Fragen). Attribute: `month`, `previous_season`, `days`, `sink_temp`, `source_temp`, `carnot_cop`, `reason`, `field_reference` (Mittel 0,39, Spanne 0,32–0,44, n = 36, Quelle), `savings` je k mit `kwh`, `percent`, `eur`. Große Attribute nicht aufzeichnen.
- Gesundheitskarte: eine Zeile „Gütegrad 0,41 (Feldtest Luft/Wasser 0,32–0,44)“, darunter „Heizkurve 2 K tiefer: ≈ 120 kWh, 35 € weniger in dieser Saison“. Kein Binärsensor, kein Alarm: kein Fehler, nur eine Einordnung.
- Demo mitziehen (`tools/make_demo.py` kennt Vorlauf, Spreizung und Tagesbuch schon).

**Last.** Gerechnet im täglichen Lauf gegen 3 Uhr aus dem Tagebuch: keine zusätzliche Statistik-Abfrage, keine neue Datei, kein zusätzliches Speichern. Rechenaufwand: eine Schleife über die Tage von höchstens zwei Saisons.

**Später.** ~~4.1 „Effizienz gesunken“ könnte den Gütegrad statt der Arbeitszahl je Klasse vergleichen.~~ Geprüft 2026-11-11 und verworfen: Der Gütegrad überkorrigiert eine geänderte Heizkurve, eine gesenkte Kurve sähe wie ein Verlust aus (4.1a, Schritt 0).

### 4.16 Anlagendruck gesunken (umgesetzt 2026-11-13, `health.pressure_drop`)

**Was und warum.** Sinkt der Druck des Heizungswassers über Wochen, verliert die Anlage Wasser (Undichtigkeit) oder das Ausdehnungsgefäß Luft. Viele Wärmepumpen schalten erst bei sehr niedrigem Druck mit einer Störung ab; ein schleichender Verlust fällt vorher niemandem auf. Wunsch aus der Umfrage im simon42-Forum (95035 #152, 12.11.2026).

**Regel.**

- Quelle: der Anlagendruck in bar (Signal `system_pressure`, EMS-ESP `syspress`), nur aus der **Langzeitstatistik** (Stundenmittel), einmal am Tag mit der täglichen Auswertung; kein Listener, keine eigene Speicherdatei.
- Je lokalem Tag das Mittel der Stundenmittel (ab 12 Stunden, `MIN_PRESSURE_HOURS`), nie Minima: An einer Anlage gab es Stundenausreißer auf 0,3 und 0,7 bar bei kaum verändertem Tagesmittel.
- **Jetzt:** Median der Tageswerte der letzten 7 vollen Tage (ab 5 Tagen). **Vergleich:** der höchste solche 7-Tage-Median in den 90 Tagen davor (`reference_week` = sein erster Tag).
- **An** ab 0,3 bar Abfall (`PRESSURE_DROP_BAR`). Nachfüllen hebt den Druck wieder: Der Befund geht von selbst aus. Das rollende Fenster ist die Hysterese.
- **Unbekannt** (`too_few_days`) ohne 5 Tageswerte in der letzten Woche oder mit weniger als 21 Tageswerten in den 90 Tagen davor.

**Quelle der Grenze: eigene Annahme**, an einer Anlage geprüft (Andys Bosch CS5800iAW, EMS-ESP `syspress` in 0,1-bar-Schritten, 512 Tage ab Juni 2025, `raw/druck-2026-11-13/`): Die Wochenmittel schwankten ohne Leck um bis zu 0,17 bar (Sommer 2026 bis 1,99 bar, Winter 1,80), ein Nachfüllen brachte etwa 0,1 bar (bestätigt 18./19.12.2025 und 26.05.2026; das im Dezember hielt nur vier Tage). Die Temperatur des Heizungswassers erklärt die Schwankung nicht (R² 0,01 gegen Vor- und Rücklauf). Tag für Tag nachgerechnet hätte die Regel dort nie angeschlagen, der größte Abfall war 0,10 bar. 0,3 bar ist das Dreifache davon und das Dreifache der Auflösung. Bosch nennt in der Installationsanleitung der Compress 5800i AW (6721872430, 2023/06, Abschnitt 7.5) einen Fülldruck von 2 bar, einen Vordruck des Ausdehnungsgefäßes von 0,75 bar und: „Wenn der Druck nicht konstant bleibt, prüfen, ob die Heizungsanlage und das Ausdehnungsgefäß dicht sind.“ Eine feste Untergrenze nennt der Text nicht; Wärmewacht prüft deshalb nur den Verlauf, keinen Absolutwert.

**Verworfen: „Nachgefüllt am …“ erkennen.** Eine Sprung-Regel auf den Tagesmitteln (3 Tage davor gegen 3 Tage danach, ab 0,06–0,07 bar) fand an derselben Anlage 5–7 Sprünge, davon nur 2 echte Nachfüllungen; die Sommerschwankung sieht genauso aus.

**Anzeige.** Binärsensor „Anlagendruck gesunken“ (`pressure_drop`) und „Befund Anlagendruck“, nur mit zugeordnetem Anlagendruck. Attribute `current_bar`, `reference_bar`, `reference_week`, `drop_bar`, `threshold_bar`, `days`, `reference_days`. Karte „Gesundheit“: „1,90 bar in 7 Tagen, höchster Wochenwert 1,99 bar“.

### 4.15 Laufzeit und Takten je Außentemperatur (Entwurf 2026-11-09; umgesetzt in `duty.py`)

**Umsetzung (Entscheidungen des Inhabers 2026-11-09):** Rückblick über die Zähler: Signale `runtime_heating` und `starts_heating`, von den Vorlagen gefüllt (EMS-ESP `uptimecompheating`, `heatingstarts`; nicht die Hybrid-Vorlage, dort zählen `boiler_*` den Kessel), sonst Felder im eingeklappten Abschnitt „Sonderzähler“; die Zusammenfassung nennt sie nur, wenn eingetragen. Abweichend vom Entwurf: ohne Warmwasser-Spalte (die Zähler kennen sie nicht); „Läuft durch unter“ = Obergrenze der **wärmsten** Klasse mit ≥ 90 % statt der zusammenhängenden von der kältesten aufwärts – bei einer Hybridanlage (Kessel allein unter −4 °C) und mit einer Übergangsklasse kam sonst „läuft nirgends durch“ heraus. Ein Start zählt als Heizen, wenn der Lauf überwiegend heizt; Stunden mit mehr als 10 min ohne bekannten Kompressorstatus fallen heraus. Saisonwahl wie die Heizlast (`duty.choose`). Sensoren `continuous_below`, `short_runs_from`, Diagnose `duty`. **Ohne Startzähler Heizen** (seit 10.11.2026, Anlass Daikin/P1P2MQTT: nur `Hours_Compressor_Heating`, Starts nur gesamt): Der Rückblick läuft mit der Laufzeit allein; diese Tage zählen für Laufzeitanteil und „Läuft durch unter“, nicht für Starts je Tag und Minuten je Start. Jede Klasse führt dafür Stunden und Sekunden mit bekannten Starts getrennt (`statistics_classes`: fünf Werte, Tagebuch weiter drei); „Kurzläufe ab“ braucht 24 solche Stunden. Ein Zähler ohne Summe (`state_class: measurement`, P1P2MQTT in ganzen Stunden) hat keine `change`-Statistik: die Stundenänderung ist der Schritt des Stunden-Maximums zur Stunde davor (nur Nachbarstunden, nie negativ; `duty.hour_steps`), in derselben Abfrage. Ganze Stunden runden je Stunde; über die mindestens 24 Stunden einer Klasse gleicht sich das aus (eigene Annahme, an keiner echten Anlage geprüft). Starts gesamt als Ersatz sind bewusst nicht genommen: Sie enthalten Warmwasser. **Prüfung** an der Anlage des Inhabers (31.10.–9.11., 215 Stunden): Laufzeit Heizen aus `uptimecompheating` 129,4 h gegen 129,7 h aus dem Rohverlauf (Kompressor an, Betriebsart nicht Warmwasser), je Klasse ±1 %; Starts `heatingstarts` 23 = 23 Starts aus „aus → an“ mit Betriebsart Heizen (dazu `wwstartshp` 10 = 10 Warmwasser, `totalcompstarts` 33). Eine naive Zählung jeder Flanke ergab 60, weil auch „nicht verfügbar → an“ zählte; die Lauferkennung der Integration zählt das nicht. Demo: Januar läuft durch unter 2 °C (erwartet −0,3 °C), Herbst (Ein/Aus, taktend) unter −8 °C mit Kurzläufen ab 4 °C, Hybrid unter 4 °C.

**Was und warum.** Ob und warum eine Wärmepumpe taktet, hängt fast nur an der Außentemperatur: Ist der Wärmebedarf kleiner als die kleinste Leistung, muss sie ein- und ausschalten. Heute zeigt Wärmewacht Takte nur je Tag und je Woche („Starts heute“, „Auffälliges Takten“, Hochrechnung „Starts pro Jahr“), nicht wo auf der Temperaturskala sie entstehen. Neu: je Außentemperatur-Klasse der **Laufzeitanteil im Heizbetrieb**, **Starts je Tag** und **Minuten je Start**, daraus zwei Kennwerte: **„Läuft durch unter“** (die wärmste Klasse, in der sie praktisch durchläuft) und **„Kurzläufe ab“** (die kälteste Klasse, in der die Läufe im Mittel unter der Kurzlauf-Grenze liegen). Das erklärt Takten statt es nur zu zählen: „taktet ab 10 °C mit 25-Minuten-Läufen“ führt direkt zu Heizgrenze, Hysterese oder Sommerbetrieb.

**Beispiel (Anlage des Inhabers, Vorsaison 2025/26 und Saison bis 9.11., Stundenwerte aus Laufzeit- und Startzählern von EMS-ESP):** Laufzeitanteil Heizen −10/−8 °C 92–93 %, −4/−2 °C ~70 %, +2/+4 °C ~50 %, +8/+10 °C 17–24 %, +14…+18 °C 3–9 %; Starts je Tag in allen Klassen ~3–5, Minuten je Start von über 1000 (unter −8 °C) bis 30–55 (+14…+18 °C). „Läuft durch unter“ läge bei etwa −6 °C (Schwelle 90 %). Gegenprobe mit Heizlast (~100 W/K, Heizgrenze ~15 °C) und kleinster Leistung (1,8 kW laut Datenblatt): Durchlauf erwartet unter 15 − 1800/100 = −3 °C; gemessen ~70 % bei −4/−2 °C (Warmwasser und Abtauen unterbrechen). Passt in der Richtung.

**Grenze: keine Leistungsgrenze aus der Laufzeit.** Bei modulierenden Wärmepumpen heißt 100 % Laufzeit nur „taktet nicht“, nicht „volle Leistung“: Sie läuft durch und regelt herunter. Ein Bivalenzpunkt oder „zu klein“ lässt sich daraus nur bei Ein/Aus-Geräten ablesen. Dafür bräuchte es die Modulation (Verdichterdrehzahl, Leistung in %); nicht Teil dieses Entwurfs.

**Daten (Vorschlag).**

- **Ab jetzt, für alle Quellen mit Kompressor:** Das Tagebuch bekommt je Tag ein kleines Histogramm `classes`: je 2-K-Klasse des Stundenmittels draußen die Stunden, die Laufsekunden im Heizbetrieb und die Starts (Heizen). Quelle sind die Läufe (`runs`, sekundengenau) und das Außentemperatur-Mittel je Stunde, das Wärmewacht im Minutentakt ohnehin bildet; geschrieben mit dem Tagebuch um Mitternacht. Typisch 2–5 Klassen je Tag, etwa 60 Bytes. Klassen nach Stunden statt nach dem Tagesmittel, weil ein Tag mit −2 °C nachts und +8 °C mittags sonst in einer Klasse verschwimmt.
- **Rückblick, nur wo die Wärmepumpe Zähler hat:** Laufzeit Heizen (Minuten oder Stunden) und Starts Heizen mit Langzeitstatistik, je Stunde die Änderung. EMS-ESP (`uptimecompheating`, `heatingstarts`), Luxtronik, Lambda, Stiebel ISG und andere führen solche Zähler; heute sind sie keine Signale. **Entscheidung nötig** (siehe offene Fragen): als Signal in den Vorlagen, ohne eigenes Formularfeld (nur Vorlage) oder im eingeklappten Abschnitt „Sonderzähler“. Ohne Zähler beginnt die Tabelle mit dem Update.
- Klassen zählen ab 24 Stunden (**eigene Annahme**, ein Tag), Starts nur im Heizbetrieb (sonst mischen sich Warmwasser-Ladungen ein: bei der Anlage des Inhabers 7–15 % Laufzeit Warmwasser in jeder Klasse).

**Kennwerte (Vorschlag).**

- **„Läuft durch unter“** (°C, Obergrenze der wärmsten Klasse mit Laufzeitanteil Heizen ≥ 90 %; **eigene Annahme**, Warmwasser und Abtauen nehmen auch bei Dauerbedarf ein paar Prozent). Unbekannt mit `never_continuous`, wenn keine Klasse 90 % erreicht (dann läuft sie auch an den kältesten beobachteten Tagen nicht durch).
- **„Kurzläufe ab“** (°C, Untergrenze der kältesten Klasse, ab der die mittlere Laufzeit je Start unter der eingestellten Kurzlauf-Grenze liegt; dieselbe Einstellung wie „Kurzläufe heute“). Unbekannt mit `no_short_runs`, wenn keine Klasse darunter liegt.
- **Erwartung aus Heizlast und kleinster Leistung** (nur mit Heizlast und Einstellung „Kleinste Heizleistung“): Heizgrenze − kleinste Leistung / Heizlast je Kelvin, als Attribut `expected_continuous_below` neben dem gemessenen Wert. Weicht der gemessene Wert deutlich nach unten ab, taktet sie mehr, als die Planung erwarten lässt (Hysterese, Mindestlaufzeit, Pufferspeicher). Kein Alarm.
- Laufende Saison und Vorsaison getrennt (wie die Kennlinie), nie gemischt.

**Anzeige (Vorschlag).** Zwei Sensoren (°C) mit der Klassentabelle als Attribut (`classes`: untere Grenze, Stunden, Laufzeitanteil Heizen und Warmwasser in %, Starts je Tag, Minuten je Start; nicht aufgezeichnet). Karte „Takte“: ein Säulendiagramm Laufzeitanteil über der Außentemperatur, darüber die Minuten je Start, wie die Kennlinie in der Karte „Analyse“. Kein Binärsensor.

**Last.** Die Klassen entstehen beim Mitternachts-Eintrag aus Daten im Speicher; die tägliche Auswertung rechnet sie aus dem Tagebuch. Der Rückblick über Zähler liest zwei Reihen mehr in der täglichen Statistik-Abfrage (oder einmal beim Rückblick und dann im Tagebuch, siehe offene Fragen).

**Später.** Mit Modulation (Verdichterdrehzahl in %) die Leistungsgrenze und den Bivalenzpunkt; „Heizkurve k K tiefer“ (4.14) könnte zeigen, ob eine tiefere Kurve das Takten verschiebt.

## 5. Rangfolge

Bewertet nach Nutzen (Geld, Schaden, Häufigkeit) und Robustheit (Fehlalarme, Quellen, Datenbedarf). Bewertung vor der Umsetzung; was inzwischen umgesetzt ist, steht oben unter „Stand“.

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
| – | 4.10 e Durchfluss | mittel | unbekannt | Tagesbuch + neues Mittel Durchfluss | Reparatur |
| – | 4.14 Gütegrad, weniger Vorlauf | hoch (Optimierung mit Zahl) | mittel–hoch (Physik und zwei Feldstudien; Fühlerorte) | Tagesbuch + `outdoor_heating` | Sensor + Attribute |

## 6. MVP

Vier neue Prüfungen, dazu bleibt „Auffälliges Takten“ unverändert:

1. **Reparatur „Zähler steht“** (4.10 a), mit b) „Quelle nicht verfügbar“ in derselben Prüfroutine.
2. **Reparatur „Außentemperatur unbrauchbar“** (4.10 c).
3. **Binärsensor „Heizstab bei milder Witterung“** (4.2).
4. **Binärsensor „Effizienz gesunken“** (4.1).

Warum diese: Alle gehen mit den heutigen Daten, ohne neues Signal und ohne Tagesbuch. 1 und 2 sichern die Grundlage von 3 und 4. 4.1 nutzt die schon gerechnete Kennlinie, und durch den Rückblick aus der Langzeitstatistik ist die Vorsaison oft schon bei der Einrichtung da. Billiger Nachzug danach: 4.10 d und die Attribute aus 4.6.

## 7. Texte (Deutsch) für das MVP

Englisch entsteht wie immer über `tools/make_strings.py`. Die Texte hier sind der Entwurf; maßgeblich sind die in `tools/make_strings.py` (dort u. a. ohne `{mode}` und mit zwei Hinweisen für die Außentemperatur).

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

README: „An, wenn die Arbeitszahl Heizen dieser Saison bei gleicher Außentemperatur mindestens 15 % unter der Vorsaison liegt; aus erst unter 10 %. Verglichen werden nur Außentemperatur-Bereiche der Kennlinie, die es in beiden Saisons gibt. Häufigster harmloser Grund: eine steilere Heizkurve oder höhere Raumtemperatur. Sonst lohnt ein Blick auf Heizstab-Anteil, Verdampfer (Laub, Schmutz) und Filter; bleibt es, frag deinen Fachbetrieb. Unbekannt ohne Vorsaison in der Langzeitstatistik oder mit weniger als 4 K gemeinsamem Bereich und 14 Tagen.“

Gründe für „unbekannt“ (Attribut `reason`):

| Schlüssel | Text |
| --- | --- |
| `no_outdoor_temp` | keine Außentemperatur zugeordnet |
| `no_aux_counter` | kein Heizstab-Zähler zugeordnet |
| `no_previous_season` | keine Vorsaison in der Langzeitstatistik |
| `too_few_classes` | weniger als 4 K gemeinsamer Temperaturbereich (seit 0.1.0b8; vorher 2 gemeinsame Klassen) |
| `too_few_days` | zu wenige Tage im Vergleich |
| `too_little_electricity` | zu wenig Strom für einen sicheren Vergleich |
| `not_analysed_yet` | noch nicht gerechnet (2 min nach dem Start, dann täglich gegen 3 Uhr) |
| `comparison_restarted` | Vergleich neu gestartet (Schaltfläche), die neue Basis sammelt noch 28 Tage |
| `too_few_charges` | „Heizstab bei Warmwasserladungen“, „Warmwasser-Effizienz unter Vorjahr“: weniger als 10 normale Ladungen in 30 Tagen |
| `no_previous_year` | „Warmwasser-Effizienz unter Vorjahr“: weniger als 10 normale Ladungen in denselben 30 Tagen des Vorjahres |

## 8. Einstellungen

Wenige, mit Vorgabe und Quelle wie die bestehenden:

| Einstellung | Vorgabe | Für | Begründung |
| --- | --- | --- | --- |
| Heizstab: milde Witterung ab | 5 °C | 4.2 | eigene Annahme; Anlagen mit hoher Normaußentemperatur (Küste) wollen eher höher |
| Effizienz gesunken ab | 15 % | 4.1 | eigene Annahme; die Rückstellung liegt fest 5 Punkte darunter |
| Thermische Desinfektion ab | 60 °C | 4.9 | DVGW W 551; einstellbar, weil der Speicherfühler nicht der Austritt ist |
| Heizleistung bei A−7/W35 (optional, Abschnitt „Heizleistung laut Datenblatt“) | – | 4.7 | Datenblatt |
| Kleinste Heizleistung (optional, Abschnitt „Heizleistung laut Datenblatt“) | – | 4.7 | Datenblatt |

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
- ~~Problem-Sensoren mit `entity_category: diagnostic` oder ohne?~~ Entschieden 2026-10-27: ohne, wie „Auffälliges Takten“ (`ENTWICKLUNG.md` §6).
- Soll 4.1 auch Heizen + Warmwasser vergleichen? Warmwasser schwankt mit Kaltwassertemperatur und Verbrauch; deshalb vorerst nur Heizen.
- ~~Braucht 4.1 eine Möglichkeit, den Vergleich nach einer gewollten Änderung der Heizkurve zurückzusetzen?~~ Umgesetzt in 0.1.0b7: Schaltfläche „Effizienzvergleich neu starten“ (die nächsten 28 Tage werden die Vergleichsbasis). Entfällt mit 4.1a (2026-11-11).
- 4.1a: Braucht es für Anlagen ohne Vorlauf-Sensor ein eingeklapptes Feld „Vergleich ab“ (Datum der Heizkurvenänderung)? Vorschlag: nein, solange sich niemand meldet. Der Text nennt die Heizkurve als erste Ursache.
- WPsmart im Bestand: Bericht-URL und genaue Definition der „maximalen Vorlauftemperatur bei −3 °C“ nachtragen (in `ENTWICKLUNG.md` §3).
- EN 14511 (W30/35) belegen, bevor 4.4 einen Text bekommt.
- Abtauen (4.3): Quelle für übliche Häufigkeit und Dauer suchen; ohne Feuchte bleibt es Attribut.
- 4.15: Rückblick über Laufzeit- und Startzähler – als Signal nur in den Vorlagen, mit Feld im eingeklappten Abschnitt „Sonderzähler“ oder gar nicht (nur ab dem Update)? Rückblick täglich aus der Statistik oder einmal ins Tagebuch übernehmen? Schwelle 90 % für „läuft durch“ an weiteren Anlagen prüfen.
- 4.14: Gütegrad als Zahl (0,39 wie Fraunhofer) oder als Prozent (39 %, wie heatpumpmonitor, dort aber mit Aufschlägen)? Ohne Rücklauf rechnen (Senke = Vorlauf, Wert zu hoch) oder unbekannt? Warmwasser getrennt (eigener Gütegrad mit Speicher-Ist-Temperatur) erst später. Seit 0.8.0 „Warmwasser 2 K kälter“ (`carnot.colder_dhw`): je Ladung aus den Carnot-Leistungszahlen, der Gütegrad kürzt sich heraus, ein Warmwasser-Gütegrad ist dafür nicht nötig.
- ~~Tagesbuch (4.11) mit dem Inhaber abstimmen~~ Erlaubt 2026-10-27 (`ENTWICKLUNG.md` §6), umgesetzt in 0.1.0b7.

## Quellen

- Fraunhofer ISE, WP-QS im Bestand: [Schlussbericht 25.11.2025](https://www.ise.fraunhofer.de/content/dam/ise/de/documents/projekte/WP-QS_Schlussbericht.pdf) (Werte in `ENTWICKLUNG.md` §3) und Pressemitteilung 2025 (77 Wärmepumpen; Luft/Wasser JAZ Mittel 3,4, Spanne 2,6–4,9; Heizstab 1,3 %; Schalthäufigkeit bei einigen sehr hoch; Überdimensionierung häufig).
- Fraunhofer ISE, WPsmart im Bestand, Schlussbericht 2020 (29 Luft/Wasser-Anlagen; JAZ Mittel 3,1; mittlere Spreizung 6,8 K; maximale Vorlauftemperatur ~43,6 °C bei −3 °C). URL nachtragen.
- Günther, D., Wapler, J., Helmling, S.: Detailed efficiency analysis for heat pumps in existing single-family houses within a large-scale field test. 15th IEA Heat Pump Conference 2026, BRE1.1, [doi:10.23697/xxqr-vx51](https://doi.org/10.23697/xxqr-vx51) (Abschnitt 4.2: Gütegrad „Carnot Efficiency Factor“, Definition und Werte; abgerufen 2026-11-09).
- Brudermueller, T. u. a.: Estimation of energy efficiency of heat pumps in residential buildings using real operation data. Nature Communications 16, 2834 (2025), [doi:10.1038/s41467-025-58014-y](https://doi.org/10.1038/s41467-025-58014-y) (Heizkurve 1 K tiefer: SCOP +0,11, Strom −2,61 %; Lämmle u. a. +0,10–0,13 je K; Heizkurve in 57 % zu hoch; abgerufen 2026-11-09. COP-Modell je Anlage, Gleichung 4: linear in Außen- und Vorlauftemperatur, Mixed-Effects auf Tageswerten, 708 von 1023 Anlagen; Carnot-Modell verworfen; nachgelesen im PDF 2026-11-11).
- U.S. Department of Energy, Federal Energy Management Program: M&V Guidelines: Measurement and Verification for Performance-Based Contracts, Version 5.0, September 2024, [energy.gov](https://www.energy.gov/sites/default/files/2024-10/mv_guide_5_0.pdf) (Abschnitt 2.1.3 „Routine Adjustments“: Regression auf unabhängige Größen wie Wetter, gleiche Bedingungen für Basis- und Vergleichszeit, IPMVP Optionen B und C; abgerufen 2026-11-11).
- OpenEnergyMonitor: [% of ideal Carnot COP](https://docs.openenergymonitor.org/heatpumpmonitor/prc_carnot.html) (Rechnung mit Aufschlägen +2 K/−6 K, meist 45–55 %; abgerufen 2026-11-09).
- [heatpumpmonitor.org](https://heatpumpmonitor.org/): Luft-Wärmepumpen, SEPEMO H4, 3,86 bei 170 Anlagen (Stand der Recherche Oktober 2026).
- Home Assistant Quality Scale, Regel [repair-issues](https://contributors.home-assistant.io/core/quality-scale/repair-issues/) (abgerufen 2026-10-27).
- DVGW W 551 (2004), 60 °C am Austritt des Trinkwassererwärmers (wie in `charges.py`).
- Übrige Werte (Takten, Abtauen, Kennlinie, Heizlast, Datenquellen): `docs/ENTWICKLUNG.md` §3 und §4.
