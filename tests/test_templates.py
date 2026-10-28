"""The template registry: every template once, each finds only its own fixture."""

from __future__ import annotations

import pytest

from custom_components.waermewacht.profiles import RegistryEntry, find
from custom_components.waermewacht.templates import TEMPLATES

from .conftest import load_fixture

# Fixture -> template key; the platform comes from the template.
FIXTURES = {
    "ems_esp_cs6800i.json": "ems_esp",
    "bosch_homecom_k40.json": "bosch_homecom",
    "luxtronik_lwd70a.json": "luxtronik",
    "stiebel_isg_wpmsystem.json": "stiebel_isg",
    "stiebel_isg_lwz.json": "stiebel_isg",
    "heishamon_wh_mdc07j3e5.json": "heishamon",
    "lambda_eu08l.json": "lambda",
    "idm_navigator20.json": "idm",
    "vicare_vitocal250a.json": "vicare",
    "vicare_vitocal333g.json": "vicare",
    "melcloud_ecodan.json": "melcloud",
    "vaillant_mypyllant_arotherm.json": "mypyllant",
    "f1p_ecodan.json": "f1p",
}


def entries(fixture: str, platform: str) -> list[RegistryEntry]:
    return [
        RegistryEntry(e["entity_id"], platform, e["unique_id"], e.get("original_name"))
        for e in load_fixture(fixture)["entities"]
    ]


def test_keys_and_platforms_are_unique() -> None:
    assert all(key == t.key for key, t in TEMPLATES.items())
    # Only EMS-ESP and the F1p bridge share a platform (both MQTT); their
    # keys keep them apart (test_each_fixture_found_by_its_template_only).
    platforms = [t.platform for t in TEMPLATES.values() if t.key != "f1p"]
    assert len(platforms) == len(set(platforms))
    assert TEMPLATES["f1p"].platform == TEMPLATES["ems_esp"].platform == "mqtt"


def test_only_the_bosch_templates_are_confirmed() -> None:
    confirmed = {k for k, t in TEMPLATES.items() if not t.experimental}
    assert confirmed == {"ems_esp", "bosch_homecom"}


@pytest.mark.parametrize(("fixture", "key"), FIXTURES.items())
def test_each_fixture_found_by_its_template_only(fixture: str, key: str) -> None:
    for other_key, template in TEMPLATES.items():
        found = find(template, entries(fixture, TEMPLATES[key].platform))
        assert bool(found) == (other_key == key), (fixture, other_key)
