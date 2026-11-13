"""The blueprint as a real automation: bell, phone, more actions, texts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import entity_sources
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

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
STATUS = "binary_sensor.wp_auffallige_statusmeldungen"
MESSAGES = {
    "friendly_name": "WP Auffällige Statusmeldungen",
    "device_class": "problem",
    "reason": None,
    "entries_7d": 15,
    "most_frequent": "Durchflussüberwachung",
    "most_frequent_count": 12,
    "days_observed": 7,
    "threshold_entries": 3,
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
    hass.states.async_set(STATUS, "off", MESSAGES)
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
                "input": {"checks": [EFFICIENCY, CYCLING, STATUS], **inputs},
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


@pytest.mark.parametrize(
    ("language", "message"),
    [
        (
            "de",
            "WP Auffällige Statusmeldungen: Durchflussüberwachung 12× in 7 Tagen, "
            "Schutz- und Störmeldungen zusammen 15×",
        ),
        (
            "en",
            "WP Auffällige Statusmeldungen: Durchflussüberwachung 12× in 7 days, "
            "protection and fault messages 15× in all",
        ),
    ],
)
async def test_status_messages_in_words(
    hass: HomeAssistant, language: str, message: str
) -> None:
    created, _, _ = await setup(hass, language=language)
    await change(hass, STATUS, "on", MESSAGES)
    assert created[0].data["message"] == message


def add_device(hass: HomeAssistant, domain: str, name: str, entity: str = "") -> str:
    """A device of `domain` named `name`, optionally with `entity` on it."""
    entry = MockConfigEntry(domain=domain, title=name)
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(domain, name)}, name=name
    )
    if entity:
        domain_, object_id = entity.split(".")
        registered = er.async_get(hass).async_get_or_create(
            domain_,
            domain,
            object_id,
            suggested_object_id=object_id,
            config_entry=entry,
            device_id=device.id,
        )
        assert registered.entity_id == entity
        # integration_entities() reads the loaded entities.
        entity_sources(hass)[entity] = {
            "domain": domain,
            "config_entry": entry.entry_id,
        }
    return device.id


def second_heat_pump(hass: HomeAssistant) -> None:
    """Another heat pump with a check, so the title names the device."""
    add_device(hass, "waermewacht", "Wärmepumpe Garage", "binary_sensor.wp2_takten")


async def test_one_heat_pump_no_name_in_the_title(hass: HomeAssistant) -> None:
    """A gas boiler (no checks) is not a second heat pump."""
    add_device(hass, "waermewacht", "Wärmepumpe Keller", EFFICIENCY)
    add_device(hass, "waermewacht", "Gaskessel", "sensor.gaskessel_verbrauch")
    created, _, _ = await setup(hass)
    await change(hass, EFFICIENCY, "on", DROP)
    assert created[0].data["title"] == "Wärmewacht: auffällig"


async def test_device_name_in_the_title(hass: HomeAssistant) -> None:
    add_device(hass, "waermewacht", "Wärmepumpe Keller", EFFICIENCY)
    second_heat_pump(hass)
    created, _, _ = await setup(hass)
    await change(hass, EFFICIENCY, "on", DROP)
    assert created[0].data["title"] == "Wärmewacht · Wärmepumpe Keller: auffällig"
    await change(hass, EFFICIENCY, "off", DROP)
    assert created[-1].data["title"] == (
        "Wärmewacht · Wärmepumpe Keller: wieder in Ordnung"
    )


async def test_phone_device_and_more_actions(hass: HomeAssistant) -> None:
    add_device(hass, "waermewacht", "Wärmepumpe Keller", EFFICIENCY)
    second_heat_pump(hass)
    phone_id = add_device(hass, "mobile_app", "Pixel von Max")
    app = async_mock_service(hass, "notify", "mobile_app_pixel_von_max")
    extra = async_mock_service(hass, "test", "extra")
    created, _, phone = await setup(
        hass,
        language="en",
        notify_device=phone_id,
        extra_actions=[
            {"action": "test.extra", "data": {"text": "{{ title }}: {{ message }}"}}
        ],
    )
    await change(hass, EFFICIENCY, "on", DROP)
    title = "Wärmewacht · Wärmepumpe Keller: conspicuous"
    message = (
        "WP Effizienz gesunken: COP heating 3.10 instead of 3.60 "
        "in the same weather last season"
    )
    assert [(c.data["title"], c.data["message"]) for c in app] == [(title, message)]
    assert [c.data["text"] for c in extra] == [f"{title}: {message}"]
    assert phone == []

    # Unknown after a restart -> conspicuous: same rule as the phone.
    await change(hass, CYCLING, "on", CYCLES)
    assert len(app) == 1
    assert len(extra) == 1

    # Fine again: the more actions get the fine texts.
    await change(hass, EFFICIENCY, "off", DROP)
    assert app[-1].data["title"] == "Wärmewacht · Wärmepumpe Keller: fine again"
    assert extra[-1].data["text"] == (
        "Wärmewacht · Wärmepumpe Keller: fine again: WP Effizienz gesunken: fine again"
    )
    assert len(created) == 3


async def test_more_actions_not_when_dismissed_silently(hass: HomeAssistant) -> None:
    extra = async_mock_service(hass, "test", "extra")
    _, dismissed, _ = await setup(
        hass, notify_fine=False, extra_actions=[{"action": "test.extra"}]
    )
    await change(hass, EFFICIENCY, "on", DROP)
    await change(hass, EFFICIENCY, "off", DROP)
    assert len(extra) == 1
    assert len(dismissed) == 1
