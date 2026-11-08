"""The cards repeat a few figures of the Python side; they must match.

The boiler card says what the energy signature still lacks ("2 of 8 weeks")
and names the sensors it reads by translation key.
"""

import json
import re
from pathlib import Path

from custom_components.waermewacht import cycling, heat_load
from custom_components.waermewacht.gas_sensor import GAS_DESCRIPTIONS, OIL_NAMES

CARD = (
    Path(__file__).parent.parent
    / "custom_components"
    / "waermewacht"
    / "frontend"
    / "waermewacht-card.js"
).read_text(encoding="utf-8")


def test_signature_needs_match_heat_load() -> None:
    match = re.search(
        r"SIGNATURE_NEEDS = \{ weeks: ([\d.]+), spread: ([\d.]+), frost_days: ([\d.]+) \}",
        CARD,
    )
    assert match, "SIGNATURE_NEEDS not found in the card"
    weeks, spread, frost = (float(v) for v in match.groups())
    assert weeks == heat_load.MIN_WEEKS
    assert spread == heat_load.MIN_SPREAD
    assert frost == heat_load.MIN_FROST_DAYS


def test_boiler_card_knows_every_gas_sensor() -> None:
    keys = {d.key for d in GAS_DESCRIPTIONS} | set(OIL_NAMES.values())
    for key in keys:
        assert f"{key}:" in CARD, f"no tile text for {key}"


def test_card_knows_the_heat_load_seasons() -> None:
    """The analysis card names the season of the heat load (attribute
    season of "Heizlast je Kelvin")."""
    assert f'season === "{heat_load.CURRENT_SEASON}"' in CARD
    assert f"{{ {heat_load.CURRENT_SEASON}: t.current, " in CARD
    assert f"{heat_load.PREVIOUS_SEASON}: t.previousSeason }}[a.season]" in CARD


def test_card_knows_the_starts_projection() -> None:
    """The cycling card shows the projection of starts per year from the
    attributes of "starts today", with a text for every field class."""
    assert f"const PROJECTION_DAYS = {cycling.PROJECTION_DAYS};" in CARD
    texts = re.findall(r"fieldClasses: \{([^}]*)\}", CARD)
    assert len(texts) == 2, "one per language"
    for found in texts:
        for key in cycling.FIELD_CLASSES:
            assert f"{key}:" in found, key
    assert f'{cycling.OBSERVATION_GAP}: "' in CARD
    assert f'"{cycling.TOO_FEW_DAYS}"' in CARD


def test_month_chart_reads_season_sensors_that_exist() -> None:
    """The month chart finds the season start in the attribute period_start
    of these sensors; each must be a sensor of the integration."""
    match = re.search(r"const SEASON_KEYS = \[([^\]]*)\];", CARD)
    assert match, "SEASON_KEYS not found in the card"
    keys = re.findall(r'"([a-z_]+)"', match.group(1))
    strings = json.loads(
        (
            Path(__file__).parent.parent
            / "custom_components"
            / "waermewacht"
            / "strings.json"
        ).read_text(encoding="utf-8")
    )
    assert keys
    for key in keys:
        assert key in strings["entity"]["sensor"], key
