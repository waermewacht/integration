"""The report for a bug report: plain text, empty sections left out."""

from __future__ import annotations

from custom_components.waermewacht.issue_report import issue_key, render, settings


def test_render_sections_and_lines() -> None:
    text = render(
        "Wärmewacht 0.2.8, Home Assistant 2026.11.0",
        [
            ("entry", [("kind", "gas boiler")]),
            ("sources", []),
            ("settings", settings({"gas_price": 12.0, "design_temp": -12.0})),
        ],
    )
    assert text == (
        "Wärmewacht 0.2.8, Home Assistant 2026.11.0\n"
        "\n"
        "[entry]\n"
        "kind: gas boiler\n"
        "\n"
        "[settings]\n"
        "design_temp: -12.0\n"
        "gas_price: 12.0"
    )


def test_issue_key_front_end_or_other_entry() -> None:
    entry = "01JZENTRY"
    assert issue_key(f"{entry}_missing_entity", entry) == "missing_entity"
    assert issue_key(f"own_entity_{entry}", entry) == "own_entity"
    assert issue_key(f"{entry}_price_unit_sensor.x", entry) == "price_unit_sensor.x"
    assert issue_key("01JZOTHER_missing_entity", entry) is None
    assert issue_key("source_failed_news", entry) is None
