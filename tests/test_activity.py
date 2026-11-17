"""Activity from several entities: flags, valve plus set mode, unknown states."""

from __future__ import annotations

from custom_components.waermewacht.activity import (
    combine,
    cooling_mode,
    local_activity,
)
from custom_components.waermewacht.model import Activity, Signal

FLAGS = {Signal.DEFROST_FLAG, Signal.DHW_FLAG, Signal.COOLING_FLAG, Signal.HEATING_FLAG}


def test_only_the_activity_entity() -> None:
    assert combine(Activity.DHW, {}, {Signal.ACTIVITY}) is Activity.DHW
    assert combine(None, {}, {Signal.ACTIVITY}) is None


def test_flags_in_order_of_priority() -> None:
    """Stiebel: defrost while heating is requested, hot water before heating."""
    states = {
        Signal.DEFROST_FLAG: "on",
        Signal.DHW_FLAG: "off",
        Signal.COOLING_FLAG: "off",
        Signal.HEATING_FLAG: "on",
    }
    assert combine(None, states, FLAGS) is Activity.DEFROST
    states[Signal.DEFROST_FLAG] = "off"
    assert combine(None, states, FLAGS) is Activity.HEATING
    states[Signal.DHW_FLAG] = "on"
    assert combine(None, states, FLAGS) is Activity.DHW


def test_all_flags_off_is_off_and_unknown_is_unknown() -> None:
    off = dict.fromkeys(FLAGS, "off")
    assert combine(None, off, FLAGS) is Activity.OFF
    assert combine(None, {**off, Signal.DHW_FLAG: "unavailable"}, FLAGS) is None
    # A later flag that is unknown does not matter once an earlier one is on.
    assert (
        combine(
            None, {**off, Signal.DEFROST_FLAG: "on", Signal.HEATING_FLAG: None}, FLAGS
        )
        is Activity.DEFROST
    )


def test_flags_only_a_run_without_a_flag_is_heating() -> None:
    """Waterkotte, P1P2MQTT: the compressor runs, no flag is on."""
    configured = {Signal.DHW_FLAG, Signal.COOLING_FLAG}
    off = dict.fromkeys(configured, "off")
    assert combine(None, off, configured, compressor=True) is Activity.HEATING
    assert combine(None, off, configured, compressor=False) is Activity.OFF
    assert combine(None, off, configured, compressor=None) is Activity.OFF
    on = {**off, Signal.DHW_FLAG: "on"}
    assert combine(None, on, configured, compressor=True) is Activity.DHW
    unknown = {**off, Signal.DHW_FLAG: "unavailable"}
    assert combine(None, unknown, configured, compressor=True) is None
    # With an activity entity the entity decides, not the compressor.
    configured_activity = {Signal.ACTIVITY, Signal.DEFROST_FLAG}
    states = {Signal.DEFROST_FLAG: "off"}
    assert combine(Activity.OFF, states, configured_activity, True) is Activity.OFF


def test_valve_with_defrost_switch_and_set_mode() -> None:
    """HeishaMon: valve as activity, defrost switch, cooling from the set mode."""
    configured = {Signal.ACTIVITY, Signal.DEFROST_FLAG, Signal.COOLING_MODE}
    states = {Signal.DEFROST_FLAG: "off", Signal.COOLING_MODE: "Heat only"}
    assert combine(Activity.HEATING, states, configured) is Activity.HEATING
    states[Signal.COOLING_MODE] = "Auto(Cool)"
    assert combine(Activity.HEATING, states, configured) is Activity.COOLING
    assert combine(Activity.DHW, states, configured) is Activity.DHW
    states[Signal.DEFROST_FLAG] = "on"
    assert combine(Activity.HEATING, states, configured) is Activity.DEFROST
    # Defrost switch unknown: the valve still decides.
    states[Signal.DEFROST_FLAG] = "unavailable"
    assert combine(Activity.DHW, states, configured) is Activity.DHW


def test_cooling_mode_words() -> None:
    assert cooling_mode("Cool+DHW")
    assert cooling_mode("Kühlen")
    assert not cooling_mode("Heat+DHW")
    assert not cooling_mode(None)


def test_activity_entity_stands_in_for_a_missing_flag() -> None:
    """Hot water or cooling of the activity entity counts at the rank of its
    flag when that flag is not configured; a configured flag still decides."""
    configured = {Signal.ACTIVITY, Signal.HEATING_FLAG, Signal.DEFROST_FLAG}
    states = {Signal.HEATING_FLAG: "on", Signal.DEFROST_FLAG: "off"}
    assert combine(Activity.DHW, states, configured) is Activity.DHW
    assert combine(Activity.COOLING, states, configured) is Activity.COOLING
    assert combine(Activity.OFF, states, configured) is Activity.HEATING
    # With the hot water flag configured (and off) the flags decide as before.
    with_dhw = {*configured, Signal.DHW_FLAG}
    assert combine(Activity.DHW, {**states, Signal.DHW_FLAG: "off"}, with_dhw) is (
        Activity.HEATING
    )


def test_local_refrigerant_status_stands_in_safely() -> None:
    """The local status of a K40 gateway (bosch_homecom): words that mean the
    same in both vocabularies at once, "heating" only once it said "dhw"."""
    assert local_activity("defrost", speaks_dhw=False) is Activity.DEFROST
    assert local_activity("passive_defrost", speaks_dhw=False) is Activity.DEFROST
    assert local_activity("dhw", speaks_dhw=False) is Activity.DHW
    assert local_activity("off", speaks_dhw=False) is Activity.OFF
    assert local_activity("idle", speaks_dhw=False) is Activity.OFF
    assert local_activity("cooling", speaks_dhw=False) is Activity.COOLING
    # "heating" may include hot water where the gateway has no "dhw".
    assert local_activity("heating", speaks_dhw=False) is None
    assert local_activity("heating", speaks_dhw=True) is Activity.HEATING
    # Unknown, unavailable and words without a safe meaning stay unknown.
    for state in ("unknown", "unavailable", "", None, "startup", "alarm", "pool"):
        assert local_activity(state, speaks_dhw=True) is None
