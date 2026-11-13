"""Static checks for the bundled automation blueprint (run locally and in CI)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import jinja2
import pytest
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.util import slugify
from homeassistant.util.yaml import load_yaml

ROOT = Path(__file__).parent.parent
BLUEPRINTS = ROOT / "blueprints" / "automation" / "waermewacht"
FILES = sorted(BLUEPRINTS.glob("*.yaml"))
BEFUND = BLUEPRINTS / "befund_melden.yaml"


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


def _blueprint() -> Blueprint:
    return Blueprint(
        load_yaml(BEFUND),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )


def test_inputs_keep_their_keys_and_only_checks_is_required() -> None:
    """Automations made before the sections and the phone keep working."""
    inputs = _blueprint().inputs
    assert set(inputs) == {
        "checks",
        "notify_device",
        "language",
        "notify_fine",
        "after_restart",
        "extra_actions",
        "notify_action",
    }
    assert [k for k, v in inputs.items() if "default" not in v] == ["checks"]
    assert inputs["notify_action"]["default"] == ""
    assert inputs["notify_fine"]["default"] is True
    assert inputs["after_restart"]["default"] is False
    assert inputs["language"]["default"] == "de"
    assert inputs["notify_device"]["default"] == ""
    raw = load_yaml(BEFUND)["blueprint"]["input"]["notify_device"]
    assert raw["selector"] == {"device": {"filter": {"integration": "mobile_app"}}}
    assert inputs["extra_actions"]["default"] == []
    assert inputs["extra_actions"]["selector"] == {"action": {}}


def test_more_actions_section_is_collapsed() -> None:
    section = load_yaml(BEFUND)["blueprint"]["input"]["more"]
    assert section["name"] == "Weitere Aktionen (optional) / More actions (optional)"
    assert section["collapsed"] is True
    assert list(section["input"]) == ["extra_actions", "notify_action"]
    description = section["input"]["extra_actions"]["description"]
    assert "{{ title }}" in description
    assert "{{ message }}" in description
    assert "telegram_bot.send_message" in description


def test_texts_are_german_and_english() -> None:
    data = load_yaml(BEFUND)["blueprint"]
    assert data["name"] == "Wärmewacht – Befund melden / Report a finding"
    # A German paragraph, then an English one.
    assert "Englisch.\n\nReports" in data["description"]
    for key, value in _blueprint().inputs.items():
        assert " / " in value["name"], key
        if "description" in value:
            assert " / " in value["description"], key
    assert data["input"]["language"]["name"] == (
        "Sprache der Nachricht / Language of the message"
    )


# The variables of the blueprint, rendered in order with plain Jinja and small
# stand-ins for HA's device functions; tests/ha/test_blueprints.py runs the
# blueprint as a real automation in CI. Names and values are made up.
DEVICES = {
    "phone1": {"name": "Pixel von Max"},
}
DEVICE_OF = {"binary_sensor.wp_effizienz_gesunken": "Wärmepumpe Keller"}
# The entities of Wärmewacht and their devices: two heat pumps with checks,
# and a gas boiler (no binary sensors), which does not count.
TWO_PUMPS = {
    "binary_sensor.wp_effizienz_gesunken": "dev_keller",
    "binary_sensor.wp_auffalliges_takten": "dev_keller",
    "sensor.wp_az_heizen": "dev_keller",
    "binary_sensor.wp2_effizienz_gesunken": "dev_garage",
    "sensor.gaskessel_verbrauch": "dev_gas",
    "button.gaskessel_bericht": "dev_gas",
}
ONE_PUMP = {k: v for k, v in TWO_PUMPS.items() if v != "dev_garage"}
DROP = {
    "friendly_name": "Wärmepumpe Keller Effizienz gesunken",
    "ratio_current": 3.1,
    "ratio_previous_same_weather": 3.6,
}


def _variables(
    *,
    entity: str,
    to: str,
    before: str | None,
    entities: dict[str, str | None] | None = None,
    **inputs: Any,
) -> dict[str, Any]:
    entities = TWO_PUMPS if entities is None else entities
    config = BlueprintInputs(
        _blueprint(),
        {
            "use_blueprint": {
                "path": BEFUND.name,
                "input": {"checks": [entity], **inputs},
            }
        },
    ).async_substitute()
    env = jinja2.Environment()
    env.filters["slugify"] = slugify
    env.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None
    env.globals["integration_entities"] = lambda domain: (
        list(entities) if domain == "waermewacht" else []
    )
    env.filters["device_id"] = entities.get
    env.globals["device_name"] = DEVICE_OF.get
    env.globals["device_attr"] = lambda d, a: DEVICES.get(d, {}).get(a)
    state = {"name": DROP["friendly_name"], "state": to, "attributes": DROP}
    values: dict[str, Any] = {
        "trigger": {
            "id": "problem" if to == "on" else "fine",
            "entity_id": entity,
            "to_state": state,
            "from_state": None if before is None else {"state": before},
        }
    }
    for key, value in config["variables"].items():
        if isinstance(value, str):
            value = env.from_string(value).render(values).strip()
            value = {"True": True, "False": False}.get(value, value)
        values[key] = value
    return values


def test_device_name_in_the_title_in_both_languages() -> None:
    entity = "binary_sensor.wp_effizienz_gesunken"
    de = _variables(entity=entity, to="on", before="off")
    assert de["title"] == "Wärmewacht · Wärmepumpe Keller: auffällig"
    assert de["message"] == (
        "Wärmepumpe Keller Effizienz gesunken: AZ Heizen 3,10 statt 3,60 bei "
        "gleichem Wetter in der Vorsaison"
    )
    assert de["fine_title"] == "Wärmewacht · Wärmepumpe Keller: wieder in Ordnung"
    en = _variables(entity=entity, to="on", before="off", language="en")
    assert en["title"] == "Wärmewacht · Wärmepumpe Keller: conspicuous"
    assert en["message"] == (
        "Wärmepumpe Keller Effizienz gesunken: COP heating 3.10 instead of 3.60 "
        "in the same weather last season"
    )
    assert en["fine_title"] == "Wärmewacht · Wärmepumpe Keller: fine again"


def test_one_heat_pump_the_title_names_waermewacht() -> None:
    """The gas boiler of a hybrid is not a second heat pump."""
    entity = "binary_sensor.wp_effizienz_gesunken"
    values = _variables(entity=entity, to="on", before="off", entities=ONE_PUMP)
    assert values["title"] == "Wärmewacht: auffällig"
    assert values["fine_title"] == "Wärmewacht: wieder in Ordnung"
    en = _variables(
        entity=entity, to="on", before="off", entities=ONE_PUMP, language="en"
    )
    assert en["title"] == "Wärmewacht: conspicuous"


def test_without_device_the_title_names_waermewacht() -> None:
    values = _variables(entity="binary_sensor.other", to="on", before="off")
    assert values["title"] == "Wärmewacht: auffällig"
    assert values["fine_title"] == "Wärmewacht: wieder in Ordnung"
    # Entities without a device do not count either.
    alone = {"binary_sensor.a": None, "binary_sensor.b": None}
    values = _variables(entity="binary_sensor.a", to="on", before="off", entities=alone)
    assert values["title"] == "Wärmewacht: auffällig"


def test_phone_action_from_the_device() -> None:
    entity = "binary_sensor.wp_effizienz_gesunken"
    assert _variables(entity=entity, to="on", before="off")["phone_action"] == ""
    values = _variables(entity=entity, to="on", before="off", notify_device="phone1")
    assert values["phone_action"] == "notify.mobile_app_pixel_von_max"
    # A device that is gone sends nothing instead of failing.
    gone = _variables(entity=entity, to="on", before="off", notify_device="gone")
    assert gone["phone_action"] == ""


@pytest.mark.parametrize(
    ("before", "to", "after_restart", "sent"),
    [
        ("off", "on", False, True),
        ("unknown", "on", False, False),
        ("unknown", "on", True, True),
        (None, "on", True, False),
        ("on", "off", False, True),
    ],
)
def test_phone_rules_unchanged(
    before: str | None, to: str, after_restart: bool, sent: bool
) -> None:
    values = _variables(
        entity="binary_sensor.wp_effizienz_gesunken",
        to=to,
        before=before,
        after_restart=after_restart,
    )
    assert values["to_phone"] is sent
