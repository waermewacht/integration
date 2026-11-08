"""The cards repeat a few figures of the Python side; they must match.

The boiler card says what the energy signature still lacks ("2 of 8 weeks")
and names the sensors it reads by translation key.
"""

import re
from pathlib import Path

from custom_components.waermewacht import heat_load
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
