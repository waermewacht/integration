"""Masking identifiers for the diagnostics."""

from __future__ import annotations

from custom_components.waermewacht.anonymize import Masker


def test_same_identifier_same_fake_and_shape() -> None:
    mask = Masker()
    a = mask("102011489-dhw1")
    b = mask("sensor.boschcom_k40_102011489_dhw1_sensor")
    assert a == "100000001-dhw1"
    assert b == "sensor.boschcom_k40_100000001_dhw1_sensor"
    assert mask("sensor.luxtronik_2113_01267_dhw_temperature") == (
        "sensor.luxtronik_1002_10003_dhw_temperature"
    )


def test_entry_ids_keep_their_kind() -> None:
    mask = Masker()
    ulid = mask("01JZM7P2D4F6H8K0N3R5T7V9XA_produced_heating")
    assert ulid is not None
    prefix, _, key = ulid.partition("_")
    assert len(prefix) == 26 and prefix.isalnum() and key == "produced_heating"
    hexid = mask("0123456789abcdef0123456789abcdef_x")
    assert hexid == "00000000000000000000000000000002_x"


def test_keys_and_short_numbers_stay() -> None:
    mask = Masker()
    for text in ("boiler_hptc1", "TOP14", "eu08l_hp1_flow", "SET12", None):
        assert mask(text) == text
