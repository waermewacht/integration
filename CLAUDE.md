# Wärmewacht – Projektkontext für Claude

Home-Assistant-Custom-Integration (HACS), Domain `waermewacht`, Anzeigename „Wärmewacht“. Wertet aus vorhandenen Entitäten Effizienz und Betriebsverhalten einer Wärmepumpe aus: Arbeitszahlen je Modus und Zeitraum, Takte, Abtauungen, Warmwasser je Ladung, Kosten und Gasvergleich, AZ-Kennlinie, Heizlast, Gradtage und ein Gesundheits-Check (`docs/GESUNDHEITSCHECK.md`). Dazu ein Gas-Modus als eigener Eintragstyp für Gasheizungen vor dem Umstieg (Heizlast aus dem Gasverbrauch, `gas.py`, ENTWICKLUNG.md „Gas-Modus“). Vorlagen für EMS-ESP und Bosch HomeCom (erprobt) sowie als Beta für Luxtronik, Stiebel ISG, HeishaMon, Lambda, iDM, Viessmann ViCare, Mitsubishi Ecodan (MELCloud, F1p, ESPHome), Vaillant (mypyllant) und Waterkotte. **Nur lesen, nie steuern.** Schwesterprojekt von Streckenwacht (`../streckenwacht`), Eilwacht (`../eilwacht`), Einspeisewacht (`../einspeisewacht`) und Tarifwacht (`../tarifwacht`) – deren Muster übernehmen, wo es passt.

Stand: Betas 0.1.0b1–b8 ab 2026-10-27, **0.1.1 am 2026-10-28** als erstes Release ohne Beta (nicht 0.1.0, weil HACS 0.1.0bN davor einordnet). Arbeitsstand in `NOTES.md`.

## Dokumentation

- **`docs/ENTWICKLUNG.md`** – Umfang, Abgrenzung, Fachregeln mit Quellen, verifizierte Eigenheiten der Datenquellen (EMS-ESP, Bosch HomeCom), Entscheidungen, offene Fragen. Vor größeren Arbeiten lesen.
- **`NOTES.md`** (lokal, nicht im Repo) – Arbeitsstand, offene Punkte, Beobachtungen. Nach jeder Sitzung fortschreiben.
- **`CLAUDE.local.md`** (lokal, nicht im Repo) – Rechner und Testanlage des Inhabers (echte Entitäten, Werte, Eigenbau zum Vergleich).
- **`CHANGELOG.md`** – Versionsgeschichte und „Unveröffentlicht“.
- **`docs/BRAND.md`** – Farben, Schrift, Bilddateien, Regenerierung. Brand-Bilder nicht verändern oder neu erzeugen, außer auf ausdrücklichen Wunsch.

## Verbindliche Entscheidungen (2026-10-27)

- **Eigene Integration.** vandecook/home-assistant-heat-pump-performance wird nicht angefragt; im README fair nennen, ebenso daikin_cycle_ml (Daikin).
- `integration_type: service`, `iot_class: calculated`, keine `requirements`, **keine Netzabfragen**. Eigenes Gerät je Wärmepumpe.
- **Herstellerneutraler Kern ohne HA-Importe.** Quellen über **Vorlagen als Daten** (welche Entität welches Signal ist, welcher Zustandswert was bedeutet), keine Hersteller-Weichen im Kern. Fehlt ein Signal, entfällt die Kennzahl; die Diagnose sagt, warum.
- **Reihenfolge:** Vorlage EMS-ESP (Bosch/Buderus) vollständig, dann Bosch HomeCom (`bosch_homecom`), beides vor der ersten öffentlichen Version. Weitere Hersteller nur mit echtem Fixture.
- **Eine Quelle je Wärmepumpe**, kein Mischbetrieb im ersten Schritt. Erkennung über die Entitäten-Registry (Plattform + `unique_id`), nie über Entity-IDs (Nutzer benennen um, EMS-ESP kennt fünf ID-Formate).
- Ein Config-Entry je Wärmepumpe; Modi (Heizen, Warmwasser, Kühlen) als optionale Abschnitte, **keine Subentries**.
- **Arbeitszahl = Σ Wärme / Σ Strom.** Ohne Wärme oder unter dem Mindeststrom `unknown`, nie 0. Kühlen heißt „Leistungszahl Kühlen (EER)“ und zählt nie in eine JAZ.
- **Stillstand wird abgetrennt** (Strom bei stehendem Kompressor): Arbeitszahlen je Modus ohne, Gesamt-JAZ mit Stillstand, Stillstand als eigener Sensor (Vorgehen wie Fraunhofer ISE).
- **Bilanzgrenze nach SEPEMO (H1–H4)** wird in README und Doku benannt; ein Attribut am Ergebnis kommt mit der zweiten Grenze „System“ (H4, externer Zähler) – beim Inhaber keiner vorhanden.
- **Arbeitszahl-Sensoren mit `state_class: measurement`** (geändert 2026-10-27 auf Wunsch des Inhabers: ohne Einheit und `state_class` zeigt die HA-Oberfläche den Rohwert mit 14 Nachkommastellen und Punkt). Ihre Statistik ist ein Zeitmittel des Sensors, keine Bilanz – die Bilanz liefern die Wärme- und Strom-Sensoren je Modus (Langzeitstatistik) und die Aktion „Bericht“. Namen kurz: „AZ Heizen Monat“, „AZ Heizen+WW Saison“, „EER Kühlen gesamt“. Standardmäßig aktiv: Monat, Saison, gesamt; heute/gestern vorhanden, aber deaktiviert.
- **Saison ab 1. Juli**, einstellbar. Der Saisonbeginn wird beim Einrichten aus der Langzeitstatistik gelesen (Rückblick schon im MVP); ändert der Nutzer den Saisonbeginn, wird die Saison aus der Statistik neu berechnet.
- Außentemperatur: EMS-ESP-Vorlage nimmt `boiler_outdoortemp`; Plausibilitätsprüfung gegen eine zweite Quelle.
- CO₂ (Stufe 2): Vorgabe **mit Vorketten** (Strom UBA, Gas GEG), umschaltbar auf „nur direkt“; Strom- und Gasfaktor nie gemischt. Gas in kWh nach Brennwert, Kesselnutzungsgrad Vorgabe 0,87 (Hs).
- **Mindestversion HA 2026.4** (Entitätsauswahl mit Filter nach Einheit).
- Lizenz MIT. Repo: `github.com/waermewacht/integration` (Organisation legt der Inhaber an). `codeowners`: `@n42net`.

## Arbeitsregeln

1. **Formate nie raten.** Die Dateien in `tests/fixtures/` sind die Wahrheit über Entitäten, Attribute und Zustandswerte der Quellen (Herkunft in `tests/fixtures/_index.json`). Neue Hersteller nur mit Fixture; nur aus Quellcode abgeleitete Vorlagen stehen im README als „experimentell“.
2. **Fachwerte nie aus dem Gedächtnis.** Kennwerte, Emissionsfaktoren, Normwerte nur mit Quelle in `docs/ENTWICKLUNG.md`.
3. **Keine personenbezogenen Daten ins Repo:** keine Zählerstände, Verläufe, Arbeitszahlen oder Anlagendaten des Inhabers – auch nicht als Testwerte. Fixtures haben echtes Format und erfundene Werte. Rohdaten nur in `raw/`. **Einzige Ausnahme** (Freigabe des Inhabers 2026-10-28): die README-Screenshots in `assets/screenshots/` zeigen echte Werte seiner Anlage (Arbeitszahlen, Kosten, Heizlast) und nennen das Modell; Seriennummern und Gerätenummern bleiben unkenntlich.
4. Entwickelt wird gegen eine produktive Home-Assistant-Instanz. Logik (Läufe, Buchung, Arbeitszahl) erst als reines Python ohne HA-Importe testen. Ein Fehler (Quelle `unavailable`, Zähler springt) darf nie die Integration oder HA blockieren und nie still falsch buchen.
5. Code, Kommentare, Entity-IDs auf Englisch; UI-Texte über `strings.json` + `translations/de.json` und `en.json`. Doku auf Deutsch.
6. Tests gegen Fixtures. HA-Tests (`tests/ha/`, `pytest-homeassistant-custom-component`) nur in GitHub Actions.
7. **Branches:** Entwickelt wird auf `dev`; `main` erhält nur freigegebene Stände (Ablauf unter „Release“), weil die HACS-Installationen daran hängen. Ein Ruleset erzwingt grüne CI (`test`, `hassfest`, `compat`) für `main`. Kein Force-Push, Tags `v*` sind unveränderlich.
8. **Fehler in Quell-Integrationen** (EMS-ESP, `bosch_homecom`, später weitere) dort melden oder beheben, nicht in Wärmewacht wegtricksen (Wunsch des Inhabers 2026-10-27). Erst mit Beleg (Quellcode-Stelle, Verlauf, Fixture), dann Entwurf in `raw/upstream/<projekt>-<thema>.md` (Englisch, sachlich, ohne Anlagendaten des Inhabers außer bewusst freigegebenen); veröffentlicht wird nur nach Freigabe des Inhabers. Bis zur Behebung bleibt in Wärmewacht ein dokumentierter Umweg mit Verweis auf das Issue.
9. **Werkzeuge:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`. `homeassistant` (dev) und `pytest-homeassistant-custom-component` (ha-tests) immer gemeinsam anheben. Rechnerspezifisches und die Testanlage stehen in `CLAUDE.local.md`.

## Release

Gleicher Ablauf in allen Schwesterprojekten (Eilwacht, Einspeisewacht, Streckenwacht, Tarifwacht, Wärmewacht). Neue Erkenntnisse zum Ablauf hier eintragen und für die Schwestern melden.

1. Version in `manifest.json`, `const.py` und `pyproject.toml` anheben, `uv lock`; `tests/test_manifest.py` prüft die Gleichheit. „Unveröffentlicht“ in `CHANGELOG.md` zur Version machen.
2. `dev` pushen und auf den CI-Lauf **genau dieses Commits** warten (`gh run list --commit <sha>`): Push-CI startet manchmal Minuten verspätet, ein älterer grüner Lauf täuscht.
3. `main` vorspulen mit `git push origin dev:main` – **ohne Branch-Wechsel** im Arbeitsverzeichnis (auf dem Netzlaufwerk hat `git switch` schon Dateien verloren, ein Release entstand so auf altem Stand). Danach prüfen, dass `origin/main` auf dem Versions-Commit steht.
4. `gh release create vX --target main --latest --notes-file …` (Text aus dem Changelog). Ziel `main`, kein Kurz-SHA (gibt 422). Immer ein **reguläres** Release, auch für Betas, nie `--prerelease`: Sonst nimmt HACS den letzten Commit und sucht dort vergeblich die ZIP. Blockiert der Auto-Modus das Veröffentlichen: Befehl nennen, der Inhaber führt ihn aus – nie umgehen.
5. Workflow „Release-ZIP“ prüfen: `waermewacht.zip` muss am Release hängen. Der Workflow bricht ab, wenn Tag und `manifest.json` nicht passen; fehlt die ZIP, ihn per Hand mit dem Tag starten. Ohne ZIP scheitern HACS-Installationen.
6. Bricht eine Sitzung mitten im Release ab: erst den Stand prüfen (`git log origin/dev origin/main`, CI des Commits, `gh release list`), dann weitermachen.

„Unveränderliche Releases“ bleibt in GitHub aus, weil der Workflow die ZIP erst nach dem Veröffentlichen anhängt; die Tags `v*` schützt das Ruleset.

## Fallstricke (dauerhaft)

- **Zeitrechnung intern in UTC.** Tage und Monate als `[start_of_local_day(d), start_of_local_day(d+1))`, nie als +24 h (Umstellungstage haben 23 bzw. 25 Stunden).
- **Schreiblast:** `Store.async_delay_save` verschiebt den Termin bei jedem Aufruf – für häufig geänderte Daten eigene Intervalle (Muster der Schwestern). Speichern an Periodengrenzen und Laufende, nicht bei jedem Zählerwert.
- **Neustarts:** Quellen gehen `unavailable` → `unknown` → Wert. Das ist weder ein Start noch eine Abtauung noch ein Verbrauch.
- **EMS-ESP-Aktivitäten sind übersetzt** („Heizen“, „aus“, „Abtauen“ – Sprache in EMS-ESP eingestellt). Vorlagen kennen alle Sprachen bzw. das Index-Format.
- HA-Tests: Zeitzone ist US/Pacific → `hass.config.async_set_time_zone("Europe/Berlin")`. Recorder-Tests: `recorder_mock` vor `hass`/`enable_custom_integrations` anfordern (siehe Tarifwacht/Einspeisewacht).
- HA-Tests unter 2026.4 (`compat`): Die Testbibliothek feuert Zeit-Listener **vor** anstehenden Zustandsereignissen. Vor `async_fire_time_changed` immer `await hass.async_block_till_done()` (Helfer `tick` in `tests/ha/test_init.py`), sonst kommt der Minuten-Takt vor der Buchung.
- Git: Gearbeitet wird auf dem ausgecheckten Branch `dev`. Am 2026-10-27 landete ein Commit versehentlich auf `main`, weil nach `git branch dev` nicht gewechselt wurde – vor jedem Commit `git status -sb` prüfen.
- Home Assistant läuft auf diesem Windows-Rechner nicht (`fcntl`). HA-MCP ist nur lesend; der gesteuerte Browser braucht die Anmeldung des Inhabers.
- Shell-Heredocs mit Anführungszeichen scheitern: Bearbeitungsskripte als Datei in den Scratchpad schreiben. Python schreibt unter Windows mit `write_text` CRLF: `write_bytes(text.replace("\r\n", "\n").encode())` oder `newline="\n"`.
- **Nie committen, wenn ein Test rot ist.** Eine Kette `pytest | tail -1 && git commit` verschluckt den Fehlercode. Ergebnis in eine Datei schreiben, auf „ failed“ prüfen, erst dann committen (am 2026-10-27 einmal passiert).
- Bei Ersetzungen per Skript eindeutige Muster verwenden und nach jedem `cut`/`replace` alle Tests laufen lassen. Ein Schnitt bis zum nächsten `}` hat am 27.10. 14 Sensornamen gelöscht; der Manifest-Test hat es gefunden.
- **Statistik-Import für eigene Sensoren:** HA rechnet die Änderung der ersten Zeile gegen 0. Importierte Summen, die bei 0 enden, ergeben deshalb einen negativen ersten Balken. Lösung: erst importieren, dann (sobald Kurzzeitstatistik existiert) alle Zeilen ab der ersten importierten Stunde mit `async_adjust_statistics` anheben. Nur anheben, wenn die erste Zeile genau dem eigenen Import entspricht.
- `apexcharts-card` kennt nur eine Zeitachse. Für Temperatur auf der x-Achse: °C auf Stunden im Fenster abbilden (`graph_span: 40h`, `span: {end: day}`, x = Tagesende + (T − 25) h) und die Beschriftung per `EVAL:(v, ts) => …` zurückrechnen. `start` und `end` sind im `data_generator` vorbelegt, eigene Variablen anders nennen. Erprobte Konfiguration im README.
- Dashboard-Änderungen über den Browser: per WebSocket `lovelace/config` lesen, nur die eine Ansicht ersetzen, speichern, zurücklesen und prüfen, dass alle anderen Ansichten gleich geblieben sind. Vorher die Konfiguration sichern.
