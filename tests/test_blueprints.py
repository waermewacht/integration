"""Static checks for the bundled automation blueprint (run locally and in CI)."""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.util.yaml import load_yaml

ROOT = Path(__file__).parent.parent
BLUEPRINTS = ROOT / "blueprints" / "automation" / "waermewacht"
FILES = sorted(BLUEPRINTS.glob("*.yaml"))


def test_blueprints_exist() -> None:
    assert [f.name for f in FILES] == ["befund_melden.yaml"]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_blueprint_is_valid(path: Path) -> None:
    blueprint = Blueprint(
        load_yaml(path),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    meta = blueprint.metadata
    assert meta["name"].startswith("Wärmewacht")
    # The import button and HA's "re-import" use this URL.
    url = (
        "https://github.com/waermewacht/integration/blob/main/"
        f"blueprints/automation/waermewacht/{path.name}"
    )
    assert meta["source_url"] == url
    assert meta["homeassistant"]["min_version"] == "2026.4.0"
    # Both READMEs link the import button to it.
    encoded = url.replace(":", "%3A").replace("/", "%2F")
    for readme in ("README.md", "README.en.md"):
        assert encoded in (ROOT / readme).read_text(encoding="utf-8"), readme


def test_blueprint_offers_only_problem_sensors_of_waermewacht() -> None:
    data = load_yaml(BLUEPRINTS / "befund_melden.yaml")
    selector = data["blueprint"]["input"]["checks"]["selector"]["entity"]
    assert selector["multiple"] is True
    assert selector["filter"] == {
        "integration": "waermewacht",
        "domain": "binary_sensor",
        "device_class": "problem",
    }
