"""Consistency checks for manifest.json, hacs.json, pyproject.toml and translations."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from custom_components.waermewacht.config_flow import FORM_SIGNALS, MORE, SECTIONS
from custom_components.waermewacht.const import DOMAIN, VERSION
from custom_components.waermewacht.gas_sensor import GAS_DESCRIPTIONS, OIL_NAMES
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
    every = [*DESCRIPTIONS, *GAS_DESCRIPTIONS]
    keys = {d.key for d in every}
    assert len(keys) == len(every)
    checks = {
        "cycling_problem",
        "efficiency_drop",
        "aux_mild_weather",
        "aux_dhw_charges",
        "dhw_efficiency_drop",
        "status_messages",
    }
    # Each check also has a status sensor (sensor.HealthStatus).
    keys |= {f"{check}_status" for check in checks}
    # Names of their own for an oil boiler (gas_sensor.OIL_NAMES).
    keys |= set(OIL_NAMES.values())
    assert set(strings["sensor"]) == keys
    assert set(icons["sensor"]) == keys
    assert set(strings["binary_sensor"]) == set(icons["binary_sensor"]) == checks
    assert (
        set(strings["button"])
        == set(icons["button"])
        == {
            "issue_report",
            "restart_comparison",
            "rebuild_history",
        }
    )


def test_action_translated_and_has_an_icon() -> None:
    strings = load(INTEGRATION / "strings.json")
    icons = load(INTEGRATION / "icons.json")
    services = (INTEGRATION / "services.yaml").read_text(encoding="utf-8")
    actions = {
        "report",
        "performance_curve",
        "heat_load",
        "add_gas_reading",
        "remove_gas_reading",
        "add_oil_refill",
        "remove_oil_refill",
    }
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
    assert set(sections) == {*SECTIONS, MORE}
    for name, signals in SECTIONS.items():
        assert set(sections[name]["data"]) == {s.value for s in signals}, name
    # "more" may hold any field a template did not find.
    assert set(sections[MORE]["data"]) == {s.value for s in FORM_SIGNALS}


def test_settings_point_to_reconfigure() -> None:
    """Entities are not in the settings (gear) but under Reconfigure: both
    settings forms say so, users look for them there (issue #3)."""
    for lang, word in (("en", "Reconfigure"), ("de", "Neu konfigurieren")):
        steps = load(INTEGRATION / "translations" / f"{lang}.json")["options"]["step"]
        for step in ("init", "gas"):
            assert word in steps[step]["description"], (lang, step)
