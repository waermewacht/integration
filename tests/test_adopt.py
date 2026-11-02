"""Signals a template learned after an entry was set up."""

from __future__ import annotations

from custom_components.waermewacht.adopt import (
    forget_offered_early,
    known_signals,
    own_match,
    preferred_entities,
    signals_to_adopt,
)
from custom_components.waermewacht.model import Signal
from custom_components.waermewacht.profiles import (
    BOSCH_HOMECOM,
    EMS_ESP,
    Match,
    RegistryEntry,
    find,
)

from .conftest import load_fixture

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


def test_homecom_entry_adopts_the_compressor_status() -> None:
    """An entry set up before bosch_homecom offered the compressor status
    takes it over once the template finds it."""
    known = [s.value for s in BOSCH_HOMECOM.signals if s is not Signal.ACTIVITY]
    configured = {"heat_heating": "sensor.heat", "elec_heating": "sensor.elec"}
    assert signals_to_adopt(BOSCH_HOMECOM.signals, known, configured) == [
        Signal.ACTIVITY
    ]


def test_a_signal_not_found_stays_unknown() -> None:
    """Up to 0.2.5 every signal of the template counted as known, found or
    not: bosch_homecom's compressor status, which came later, was never
    taken over. Now only signals with an entity on offer are known."""
    known = known_signals(BOSCH_HOMECOM.signals, [], CONFIGURED)
    assert known == ["compressor", "heat_heating"]
    assert Signal.ACTIVITY in signals_to_adopt(BOSCH_HOMECOM.signals, known, {})
    # Known before (the user removed it): stays known.
    again = known_signals(BOSCH_HOMECOM.signals, ["activity"], CONFIGURED)
    assert "activity" in again
    # Signals the template does not have are dropped.
    assert known_signals(BOSCH_HOMECOM.signals, ["gone"], {}) == []


def test_entry_from_before_b8_keeps_its_known_signals() -> None:
    known = known_signals(EMS_ESP.signals, None, CONFIGURED)
    assert Signal.DHW_TEMP.value not in known
    assert Signal.FLOW_RATE.value in known


def test_migration_forgets_the_compressor_status_offered_early() -> None:
    every = sorted(s.value for s in BOSCH_HOMECOM.signals)
    known = forget_offered_early("bosch_homecom", every, CONFIGURED)
    assert known is not None
    assert "activity" not in known
    assert signals_to_adopt(BOSCH_HOMECOM.signals, known, CONFIGURED) == [
        Signal.ACTIVITY
    ]
    # Configured: kept. Other templates and entries before b8: unchanged.
    configured = {**CONFIGURED, "activity": "sensor.status"}
    assert forget_offered_early("bosch_homecom", every, configured) == every
    assert forget_offered_early("ems_esp", every, CONFIGURED) == every
    assert forget_offered_early("bosch_homecom", None, CONFIGURED) is None


def ems_esp_with_dev23() -> Match:
    rows = [
        *load_fixture("ems_esp_cs6800i.json")["entities"],
        *load_fixture("ems_esp_dev23_heater.json")["entities"],
    ]
    (match,) = find(
        EMS_ESP, [RegistryEntry(r["entity_id"], "mqtt", r["unique_id"]) for r in rows]
    )
    return match


def test_entry_moves_to_the_backup_heater_in_hundredths() -> None:
    """EMS-ESP 3.9.0-dev.23 adds the backup heater per mode in 0.01 kWh: an
    entry with the whole-kWh counter moves to it, a hand-picked one stays."""
    match = ems_esp_with_dev23()
    configured = {
        **CONFIGURED,
        "aux_heating": "sensor.boiler_auxelecheatnrgconsheating",
        "aux_dhw": "sensor.boiler_auxelecheatnrgconsww",
    }
    assert preferred_entities(match, configured) == {
        "aux_heating": "sensor.boiler_metereheatheat",
        "aux_dhw": "sensor.boiler_dhw_metereheat",
    }
    moved = {**configured, **preferred_entities(match, configured)}
    assert preferred_entities(match, moved) == {}
    own = {**CONFIGURED, "aux_heating": "sensor.my_heater"}
    assert preferred_entities(match, own) == {}
