"""Signals a template learned after an entry was set up."""

from __future__ import annotations

from custom_components.waermewacht.adopt import own_match, signals_to_adopt
from custom_components.waermewacht.model import Signal
from custom_components.waermewacht.profiles import EMS_ESP, Match

CONFIGURED = {"heat_heating": "sensor.boiler_nrgheat", "compressor": "binary_sensor.c"}


def test_entry_from_before_b8_adopts_the_later_signals() -> None:
    todo = signals_to_adopt(EMS_ESP.signals, None, CONFIGURED)
    assert Signal.DHW_TEMP in todo
    # Signals the template had back then were offered; missing ones were
    # left out on purpose.
    assert Signal.FLOW_RATE not in todo


def test_known_signals_are_not_adopted_again() -> None:
    known = [s.value for s in EMS_ESP.signals]
    assert signals_to_adopt(EMS_ESP.signals, known, CONFIGURED) == []
    without_dhw = [k for k in known if k != Signal.DHW_TEMP.value]
    assert signals_to_adopt(EMS_ESP.signals, without_dhw, CONFIGURED) == [
        Signal.DHW_TEMP
    ]
    # Already configured (by hand): nothing to do.
    configured = {**CONFIGURED, "dhw_temp": "sensor.x"}
    assert signals_to_adopt(EMS_ESP.signals, without_dhw, configured) == []


def test_own_match_is_the_heat_pump_of_the_entry() -> None:
    other = Match(EMS_ESP, "ems2", {Signal.HEAT_HEATING: "sensor.ems2_nrgheat"})
    mine = Match(
        EMS_ESP,
        "",
        {
            Signal.HEAT_HEATING: "sensor.boiler_nrgheat",
            Signal.DHW_TEMP: "sensor.boiler_dhw_curtemp",
        },
    )
    assert own_match([other, mine], CONFIGURED) is mine
    assert own_match([other], CONFIGURED) is None
