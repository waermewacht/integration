"""Heating curve check from the rooms (no Home Assistant). Made-up values."""

from __future__ import annotations

import pytest

from custom_components.waermewacht.rooms import (
    FITS,
    LOWER_POSSIBLE,
    NO_ROOMS,
    TOO_FEW_DAYS,
    TOO_LOW,
    RoomLog,
    check,
)
from custom_components.waermewacht.summary import (
    RoomCheck,
    RoomCheckLine,
    RoomLine,
    RoomSummary,
    rooms_check_text,
    rooms_text,
)


def day(outdoor: float, rooms: dict, heating_hours: float = 6.0) -> dict:
    return {
        "outdoor": outdoor,
        "activity_seconds": {"heating": heating_hours * 3600},
        "flow": {"weighted": 30.0 * 3600, "seconds": 3600},
        "rooms": rooms,
    }


def room(delta: float, valve: float | None = None, valve_max: float | None = None):
    return {
        "delta": delta,
        "valve": valve,
        "valve_max": valve if valve_max is None else valve_max,
        "hours": 24.0,
    }


def test_throttled_valves_mean_lower_possible() -> None:
    """All rooms hold their setpoint; the widest valve averages 15 %."""
    diary = [
        day(6.0, {"stairs": room(0.0, 15, 49), "bath": room(0.7, 0.0)})
        for _ in range(4)
    ]
    result = check(diary, ["stairs", "bath"])
    assert result.verdict == LOWER_POSSIBLE
    assert result.problem is True
    band = result.bands[0]
    assert band.band == "5_10"
    assert band.lead_room == "stairs"
    assert band.lead_valve == pytest.approx(15)
    assert band.estimate_k is None  # no kelvin figure with valves


def test_slightly_below_with_half_open_valve_fits() -> None:
    """Proportional control: 0.3 K below with the valve 60 % open is the
    controller at work, neither too high nor too low."""
    diary = [day(2.0, {"living": room(-0.3, 60, 70)}) for _ in range(3)]
    result = check(diary, ["living"])
    assert result.verdict == FITS
    assert result.problem is False


def test_clearly_below_with_valve_at_its_top_is_too_low() -> None:
    diary = [day(-3.0, {"living": room(-0.8, 58, 60)}) for _ in range(3)]
    result = check(diary, ["living"])
    assert result.verdict == TOO_LOW
    assert result.problem is False


def test_clearly_below_with_throttled_valve_is_not_too_low() -> None:
    """Far below the setpoint but the valve barely open: the thermostat's
    doing (window open, setback), not the curve."""
    diary = [day(-3.0, {"living": room(-0.8, 10, 60)}) for _ in range(3)]
    assert check(diary, ["living"]).verdict != TOO_LOW


def test_without_valves_warm_lead_rooms_give_an_estimate() -> None:
    """Thermometer rooms with open valves 1 K too warm at 0 °C, flow 30 °C:
    1 x (1 + 9 / 21) = 1.4 K lower."""
    diary = [day(0.0, {"living": room(1.0)}) for _ in range(3)]
    result = check(diary, ["living"])
    assert result.verdict == LOWER_POSSIBLE
    assert result.bands[0].estimate_k == pytest.approx(1.4)


def test_bands_and_too_few_days() -> None:
    diary = [day(6.0, {"living": room(0.0, 10, 30)}) for _ in range(2)]
    assert check(diary, ["living"]).reason == TOO_FEW_DAYS
    # Days without heating do not count.
    diary = [day(6.0, {"living": room(0.0, 10, 30)}, heating_hours=0.5)] * 5
    assert check(diary, ["living"]).reason == TOO_FEW_DAYS
    assert check(diary, []).reason == NO_ROOMS


def test_too_low_wins_over_lower_possible() -> None:
    mild = [day(8.0, {"living": room(0.0, 10, 70)}) for _ in range(3)]
    cold = [day(-4.0, {"living": room(-0.7, 69, 70)}) for _ in range(3)]
    result = check(mild + cold, ["living"])
    assert {b.verdict for b in result.bands} == {LOWER_POSSIBLE, TOO_LOW}
    assert result.verdict == TOO_LOW


def test_room_log_diary_entry() -> None:
    log = RoomLog()
    log.add("living", 0.4, 12.0, 1800)
    log.add("living", 0.2, 30.0, 1800)
    log.add("hall", None, 5.0, 3600)  # no temperature: not in the diary
    entry = log.diary_entry()
    assert entry == {
        "living": {"delta": 0.3, "valve": 21.0, "valve_max": 30.0, "hours": 1.0}
    }
    assert RoomLog.from_dict(log.as_dict()).diary_entry() == entry


def test_attributes_use_room_names() -> None:
    diary = [day(6.0, {"a1": room(0.0, 15, 49)}) for _ in range(3)]
    attributes = check(diary, ["a1"]).as_attributes({"a1": "Treppe"})
    assert attributes["bands"][0]["lead_room"] == "Treppe"
    assert attributes["bands"][0]["rooms"][0]["room"] == "Treppe"


def test_summary_text() -> None:
    rooms = RoomSummary(
        (
            RoomLine("Wohnzimmer", thermostats=1, valve_reported=True),
            RoomLine("Treppe", thermometers=1, valves=2),
        ),
        no_area=("sensor.flur",),
    )
    assert rooms_text(rooms, 1) == (
        "Wohnzimmer (Thermostat, Ventil mitgemeldet), Treppe (Thermometer, 2 Ventile)"
        " · ohne Bereich, zählt nicht: sensor.flur"
    )


def test_check_text_names_values_and_sources() -> None:
    check = RoomCheck(
        (
            RoomCheckLine(
                "Treppe",
                temp=21.1,
                temp_from=("climate.treppe",),
                target=21.5,
                target_from=("climate.treppe",),
                valve=40.0,
                valve_from=("climate.treppe",),
            ),
            RoomCheckLine(
                "Flur",
                temp=20.64,
                temp_from=("sensor.flur",),
                target=21.0,
            ),
            RoomCheckLine("Bad", off=True),
        ),
        no_area=("sensor.lose",),
        no_room=(("sensor.kanal_1", "Abstellraum"),),
    )
    assert rooms_check_text(check, 1).splitlines() == [
        "- **Treppe:** 21,1 °C, Soll 21,5 °C, Ventil 40 % · aus climate.treppe",
        "- **Flur:** 20,6 °C (aus sensor.flur), Soll 21 °C (Wunschtemperatur),"
        " kein Ventil bekannt: zählt als ganz offen (Leitraum)",
        "- **Bad:** Thermostat aus: der Raum zählt solange nicht",
        "- **Ohne Bereich, zählt nicht:** sensor.lose – der Entität oder ihrem"
        " Gerät einen Bereich geben",
        "- **Ventil ohne Raum:** sensor.kanal_1 – Bereich Abstellraum, dort ist"
        " kein Raum gewählt: dem Sensor selbst den Bereich seines Raums geben",
    ]
