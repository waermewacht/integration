"""Consistency checks for manifest.json, hacs.json, pyproject.toml and translations."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from custom_components.waermewacht.config_flow import SECTIONS
from custom_components.waermewacht.const import DOMAIN, VERSION
from custom_components.waermewacht.sensor import DESCRIPTIONS

ROOT = Path(__file__).parent.parent
INTEGRATION = ROOT / "custom_components" / DOMAIN


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def manifest() -> dict:
    return load(INTEGRATION / "manifest.json")


def test_versions_match() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert manifest()["version"] == VERSION == pyproject["project"]["version"]


def test_domain_matches_folder() -> None:
    assert manifest()["domain"] == DOMAIN == INTEGRATION.name


def test_manifest_key_order() -> None:
    # hassfest requires domain, name first, then the remaining keys sorted.
    keys = list(manifest())
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_hacs_json() -> None:
    hacs = load(ROOT / "hacs.json")
    assert hacs["name"] == manifest()["name"]
    assert hacs["filename"] == f"{DOMAIN}.zip"


def _keys(data: object, prefix: str = "") -> set[str]:
    if isinstance(data, dict):
        return {
            k for key, value in data.items() for k in _keys(value, f"{prefix}{key}.")
        }
    return {prefix.rstrip(".")}


def test_translations_complete() -> None:
    strings = load(INTEGRATION / "strings.json")
    assert load(INTEGRATION / "translations" / "en.json") == strings
    assert _keys(load(INTEGRATION / "translations" / "de.json")) == _keys(strings)


def test_every_sensor_translated_and_has_an_icon() -> None:
    strings = load(INTEGRATION / "strings.json")["entity"]
    icons = load(INTEGRATION / "icons.json")["entity"]
    keys = {d.key for d in DESCRIPTIONS}
    assert len(keys) == len(DESCRIPTIONS)
    assert set(strings["sensor"]) == keys
    assert set(icons["sensor"]) == keys
    assert (
        set(strings["binary_sensor"])
        == set(icons["binary_sensor"])
        == {"cycling_problem", "efficiency_drop", "aux_mild_weather", "aux_dhw_charges"}
    )
    assert set(strings["button"]) == set(icons["button"]) == {"restart_comparison"}


def test_action_translated_and_has_an_icon() -> None:
    strings = load(INTEGRATION / "strings.json")
    icons = load(INTEGRATION / "icons.json")
    services = (INTEGRATION / "services.yaml").read_text(encoding="utf-8")
    actions = {"report", "performance_curve", "heat_load"}
    assert set(strings["services"]) == set(icons["services"]) == actions
    for action in actions:
        assert f"{action}:\n" in services
        for field in strings["services"][action]["fields"]:
            assert f"    {field}:" in services


def test_issues_translated() -> None:
    from custom_components.waermewacht import ISSUES

    assert set(load(INTEGRATION / "strings.json")["issues"]) == set(ISSUES)


def test_entity_form_translated() -> None:
    sections = load(INTEGRATION / "strings.json")["config"]["step"]["entities"][
        "sections"
    ]
    assert set(sections) == set(SECTIONS)
    for name, signals in SECTIONS.items():
        assert set(sections[name]["data"]) == {s.value for s in signals}, name
