"""The report for a bug report: plain text, empty sections left out."""

from __future__ import annotations

from custom_components.waermewacht.issue_report import render, settings


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
