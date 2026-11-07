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


def test_text_and_utc() -> None:
    """Settings in plain text, not Python's spelling (same in all sister projects)."""
    from datetime import UTC, date, datetime, timedelta, timezone

    from custom_components.waermewacht.issue_report import text, utc

    assert text(True) == "yes"
    assert text(False) == "no"
    assert text(None) == "none"
    assert text([7.94, 8]) == "7.94, 8"
    assert text([]) == "none"
    assert text({"a": 1, "b": None}) == "a 1, b none"
    assert text(date(2026, 1, 1)) == "2026-01-01"
    assert text(0.5) == "0.5"
    moment = datetime(
        2026, 11, 7, 13, 39, 32, 639925, tzinfo=timezone(timedelta(hours=1))
    )
    assert text(moment) == utc(moment) == "2026-11-07 12:39 UTC"
    assert utc(datetime(2026, 11, 7, 12, 0, tzinfo=UTC)) == "2026-11-07 12:00 UTC"
    assert utc(None) == "-"
