"""The READMEs name the same tested and beta templates as the code.

A template is beta when ``experimental`` is set (the setup shows "(beta)").
Three places in README.md and README.en.md say which templates are tested:
the note at the top, the feature "templates for many makes" and the table
under requirements. All three must follow ``experimental``, and every
template needs a row in the table (found 2026-11-16: the note still named
three tested templates after six had been confirmed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.waermewacht.templates import TEMPLATES

ROOT = Path(__file__).resolve().parent.parent

# Per template: text that identifies its table row (first cell, the same in
# both languages, mostly the link) and the name used in the note and the
# feature list.
NAMES: dict[str, tuple[str, str]] = {
    "ems_esp": ("emsesp/EMS-ESP32", "EMS-ESP"),
    "ems_esp_heatpump": ("HM200", "HM200"),
    "bosch_homecom": ("serbanb11/bosch-homecom-hass", "Bosch HomeCom"),
    "luxtronik": ("BenPru/luxtronik", "Luxtronik"),
    "stiebel_isg": ("stiebel_eltron_isg_component", "Stiebel"),
    "heishamon": ("heishamon-homeassistant", "HeishaMon"),
    "lambda": ("lambda_heat_pumps", "Lambda"),
    "idm": ("idm-heatpump-hass", "iDM"),
    "vicare": ("integrations/vicare", "ViCare"),
    "melcloud": ("integrations/melcloud", "MELCloud"),
    "mypyllant": ("mypyllant-component", "myVAILLANT"),
    "f1p": ("F1p/Home-Assistant", "F1p"),
    "waterkotte": ("ha-waterkotte", "Waterkotte"),
    "esphome_ecodan": ("esphome-ecodan-hp", "ESPHome"),
    "buderus": ("BassXT/buderus", "MX300"),
    "bosch_buderus": ("ha-bosch-buderus-heating", "Home Comfort"),
    "p1p2mqtt": ("P1P2Serial", "P1P2MQTT"),
}

# Per README: start of the note, start of the feature, word that opens the
# beta part of the feature.
READMES = {
    "README.md": (
        "> **Vorlagen:**",
        "- **Vorlagen für viele Hersteller:**",
        "Als Beta",
    ),
    "README.en.md": ("> **Templates:**", "- **Templates for many makes:**", "As beta"),
}

TESTED = sorted(k for k, t in TEMPLATES.items() if not t.experimental)
BETA = sorted(k for k, t in TEMPLATES.items() if t.experimental)


def _line(text: str, start: str) -> str:
    lines = [line for line in text.splitlines() if line.startswith(start)]
    assert len(lines) == 1, f"expected one line starting with {start!r}"
    return lines[0]


def test_every_template_has_names() -> None:
    assert set(NAMES) == set(TEMPLATES), "add new templates to NAMES and the READMEs"


@pytest.mark.parametrize("readme", list(READMES))
def test_note_names_the_tested_templates(readme: str) -> None:
    note = _line((ROOT / readme).read_text(encoding="utf-8"), READMES[readme][0])
    missing = [NAMES[k][1] for k in TESTED if NAMES[k][1] not in note]
    beta = [NAMES[k][1] for k in BETA if NAMES[k][1] in note]
    assert not missing, f"{readme}: note misses tested templates {missing}"
    assert not beta, f"{readme}: note names beta templates {beta}"


@pytest.mark.parametrize("readme", list(READMES))
def test_feature_splits_tested_and_beta(readme: str) -> None:
    _, start, beta_word = READMES[readme]
    feature = _line((ROOT / readme).read_text(encoding="utf-8"), start)
    tested_part, _, beta_part = feature.partition(beta_word)
    assert beta_part, f"{readme}: no {beta_word!r} in the feature"
    missing = [NAMES[k][1] for k in TESTED if NAMES[k][1] not in tested_part]
    early = [NAMES[k][1] for k in BETA if NAMES[k][1] in tested_part]
    late = [NAMES[k][1] for k in BETA if NAMES[k][1] not in beta_part]
    assert not missing, f"{readme}: feature misses tested templates {missing}"
    assert not early, f"{readme}: beta templates among the tested {early}"
    assert not late, f"{readme}: beta part misses {late}"


@pytest.mark.parametrize("readme", list(READMES))
def test_table_marks_beta(readme: str) -> None:
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in (ROOT / readme).read_text(encoding="utf-8").splitlines()
        if line.startswith("|")
    ]
    problems = []
    for key, template in TEMPLATES.items():
        marker = NAMES[key][0]
        found = [row for row in rows if len(row) >= 2 and marker in row[0]]
        if len(found) != 1:
            problems.append(f"{key}: {len(found)} table rows with {marker!r}")
            continue
        is_beta = found[0][1].casefold().startswith("beta")
        if is_beta != template.experimental:
            problems.append(
                f"{key}: table says {'beta' if is_beta else 'tested'}, "
                f"code says {'beta' if template.experimental else 'tested'}"
            )
    assert not problems, f"{readme}:\n" + "\n".join(problems)
