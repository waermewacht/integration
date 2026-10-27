# Wärmewacht – Marke & Bilddateien

## Idee

Das Außengerät einer Wärmepumpe: Gehäuse auf zwei Füßen mit einem Ventilator mit drei Flügeln, darüber zwei Wärmewellen und dazwischen das Wachlicht mit Halo. Kachel, Schutzzone, Amber-Wachlicht, Off-White und Schrift sind dieselben wie bei Streckenwacht, Eilwacht, Einspeisewacht und Tarifwacht – so bleiben die Integrationen als Geschwister erkennbar. Die Kachelfarbe ist **RAL 2009 Verkehrsorange** – Wärme.

**Slogan:** „Jede Kilowattstunde. Jeder Takt.“ (englisch „Every kilowatt-hour. Every cycle.“)

## Farben

| Rolle | Hex | Hinweis |
| --- | --- | --- |
| Kachel, Wortmarke | `#DE5E32` | RAL 2009 Verkehrsorange, umgerechnet aus CIE L\*a\*b\* 55,83 / 47,79 / 48,83 (D65, Quelle: de.wikipedia.org, Artikel „RAL-Farbe“) |
| Wachlicht | `#F5A623` | Amber, wie bei den Geschwistern |
| Motiv, Rand um das Wachlicht | `#FBF7EE` | warmes Off-White |
| Heller Hintergrund | `#FAF7F2` | README-Kopf, Social Preview |
| Dunkler Hintergrund | `#14181D` | README-Kopf (Dark Mode) |
| Tagline hell / dunkel | `#6B6357` / `#B9B2A6` | |

Halo: Amber-Ring mit 35 % Deckkraft. Kontrast Kachel zu Off-White 3,4 : 1 (für Grafik ≥ 3 : 1), zu Amber nur 1,8 : 1 – deshalb sitzt das Wachlicht auf einem schmalen Off-White-Rand. Umrechnung wie bei Tarifwacht (D65 → XYZ → sRGB); dieselbe Rechnung ergibt für RAL 5017 und RAL 4006 genau die Werte von Streckenwacht und Tarifwacht.

## Schrift

**Space Grotesk** (Google Fonts, SIL Open Font License), Bold 700 für die Wortmarke, Medium 500 für Tagline und Zusatzzeilen. In allen SVGs ist der Text in Pfade umgewandelt.

## Dateien

| Ort | Inhalt |
| --- | --- |
| `custom_components/waermewacht/brand/` | `icon(@2x)`, `dark_icon(@2x)`, `logo(@2x)`, `dark_logo(@2x)` – lädt Home Assistant ab 2026.3 aus der Integration |
| `assets/github/` | README-Kopf hell/dunkel (960×220, @2x), Social Preview 1280×640, Profilbild der Organisation 500/1024 |
| `assets/brand/svg/` | Vektor-Master: Icon, Mini-Icon, vollflächiges Icon, Motiv, Logo, README-Kopf, Social Preview |
| `assets/brand/png/` | Icon 16–2048 px, Motiv ohne Kachel, Logo hell/dunkel |
| `assets/brand/favicon/` | `favicon.ico` (16/32/48), `favicon.svg`, PNG, Apple-Touch- und Android-Icons |

Profilbild der Organisation und Social Preview lassen sich nicht per API setzen: von Hand hochladen (Organisation → Settings → Profile; Repo → Settings → General → Social preview).

## Regeln

- **≤ 32 px immer die Mini-Variante**: Gehäuse mit dickerem Rand, Lüfter als volle Scheibe, größeres Wachlicht auf Off-White-Rand, keine Wellen, Füße und kein Halo.
- Motiv ohne Kachel: auf hellem Grund in Verkehrsorange (`mark-on-light`), auf dunklem in Off-White (`mark-on-dark`).
- Farben nicht verändern, Motiv nicht verzerren, keine Schatten oder Verläufe.
- Um Logo und Icon mindestens ¼ der Kachelbreite frei lassen.

## Neu erzeugen

```bash
cd tools/brand
npm install
node build.mjs
```

Das Skript (von Tarifwacht übernommen) schreibt direkt an die Plätze oben; vorher werden diese Ordner geleert. Farben, Name, Slogan und Unterzeile stehen als Konstanten oben in `build.mjs`.

## Entstehung

Verglichen auf einer Design-Fläche (für Eingeladene: `https://claude.ai/artifact/FPhVMJQ35m3XzFKYwSB8qy`): Motive „1 kWh → 3 kWh“, „Außengerät“, „Takt-Linie“; Farben Verkehrsorange, Verkehrsrot (RAL 3020, zu nah am Signalrot der Eilwacht), Verkehrsgrau B (RAL 7043), Verkehrsschwarz (RAL 9017). Das erste Außengerät (Lüfter als Kreis, waagerechte Lamellen) wirkte wie ein altes Radio; daraus drei Varianten mit Lüfterflügeln. Gewählt am 2026-10-27: Variante 2a (Gerät mit Lüfter auf Füßen) in Verkehrsorange, mit Off-White-Rand um das Wachlicht.
