"""The blueprint as a real automation: bell, optional phone, texts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import async_mock_service

BLUEPRINT = (
    Path(__file__).parent.parent.parent
    / "blueprints"
    / "automation"
    / "waermewacht"
    / "befund_melden.yaml"
)
EFFICIENCY = "binary_sensor.wp_effizienz_gesunken"
CYCLING = "binary_sensor.wp_auffalliges_takten"
DROP = {
    "friendly_name": "WP Effizienz gesunken",
    "device_class": "problem",
    "reason": None,
    "ratio_current": 3.1,
    "ratio_previous_same_weather": 3.6,
    "drop_percent": 13.9,
}
CYCLES = {
    "friendly_name": "WP Auffälliges Takten",
    "device_class": "problem",
    "triggers": ["starts_per_day"],
    "max_starts_per_hour": 1,
    "starts_24h": 5,
    "critical_runs_24h": 0,
    "short_runs_24h": 0,
    "starts_per_hour_limit": 3,
    "starts_per_day_limit": 4,
}


async def setup(
    hass: HomeAssistant, **inputs: Any
) -> tuple[list[ServiceCall], list[ServiceCall], list[ServiceCall]]:
    hass.states.async_set(EFFICIENCY, "off", DROP)
    hass.states.async_set(CYCLING, STATE_UNKNOWN, CYCLES)
    blueprint = Blueprint(
        load_yaml(BLUEPRINT),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    config = BlueprintInputs(
        blueprint,
        {
            "use_blueprint": {
                "path": BLUEPRINT.name,
                "input": {"checks": [EFFICIENCY, CYCLING], **inputs},
            }
        },
    ).async_substitute()
    config.pop("use_blueprint", None)
    created = async_mock_service(hass, "persistent_notification", "create")
    dismissed = async_mock_service(hass, "persistent_notification", "dismiss")
    phone = async_mock_service(hass, "notify", "mobile_app_phone")
    assert await async_setup_component(hass, "automation", {"automation": [config]})
    await hass.async_block_till_done()
    return created, dismissed, phone


async def change(hass: HomeAssistant, entity: str, state: str, attrs: dict) -> None:
    hass.states.async_set(entity, state, attrs)
    await hass.async_block_till_done()


async def test_bell_and_phone_in_german(hass: HomeAssistant) -> None:
    created, dismissed, phone = await setup(
        hass, notify_action="notify.mobile_app_phone"
    )
    await change(hass, EFFICIENCY, "on", DROP)
    assert len(created) == 1
    assert created[0].data["notification_id"] == f"waermewacht_{EFFICIENCY}"
    assert created[0].data["title"] == "Wärmewacht: auffällig"
    message = (
        "WP Effizienz gesunken: AZ Heizen 3,10 statt 3,60 bei gleichem Wetter "
        "in der Vorsaison"
    )
    assert created[0].data["message"] == message
    assert [c.data["message"] for c in phone] == [message]

    # Unknown after a restart -> conspicuous: the bell again, not the phone.
    await change(hass, CYCLING, "on", CYCLES)
    assert created[-1].data["message"] == (
        "WP Auffälliges Takten: 5 Starts in 24 h (Grenze 4)"
    )
    assert len(phone) == 1

    # Fine again: said in the bell and on the phone.
    await change(hass, EFFICIENCY, "off", DROP)
    assert created[-1].data["title"] == "Wärmewacht: wieder in Ordnung"
    assert created[-1].data["message"] == "WP Effizienz gesunken: wieder in Ordnung"
    assert phone[-1].data["title"] == "Wärmewacht: wieder in Ordnung"
    assert dismissed == []


async def test_bell_only_in_english_dismissed_silently(hass: HomeAssistant) -> None:
    created, dismissed, phone = await setup(hass, notify_fine=False, language="en")
    await change(hass, EFFICIENCY, "on", DROP)
    assert created[0].data["title"] == "Wärmewacht: conspicuous"
    assert created[0].data["message"] == (
        "WP Effizienz gesunken: COP heating 3.10 instead of 3.60 "
        "in the same weather last season"
    )
    await change(hass, EFFICIENCY, "off", DROP)
    assert len(created) == 1
    assert [c.data["notification_id"] for c in dismissed] == [
        f"waermewacht_{EFFICIENCY}"
    ]
    assert phone == []


@pytest.mark.parametrize("after_restart", [True, False])
async def test_phone_after_a_restart_on_request(
    hass: HomeAssistant, after_restart: bool
) -> None:
    _, _, phone = await setup(
        hass, notify_action="notify.mobile_app_phone", after_restart=after_restart
    )
    await change(hass, CYCLING, "on", CYCLES)
    assert len(phone) == (1 if after_restart else 0)
