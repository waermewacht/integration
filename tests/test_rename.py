"""Following renamed source entities: entry data and unique id."""

from __future__ import annotations

from custom_components.waermewacht.const import (
    CONF_ENTITIES,
    CONF_HISTORY,
    CONF_NAME,
    CONF_TEMPLATE,
)
from custom_components.waermewacht.rename import (
    renamed_data,
    renamed_unique_id,
    sources,
)

DATA = {
    CONF_NAME: "WP",
    CONF_TEMPLATE: "ems_esp",
    CONF_ENTITIES: {
        "heat_heating": "sensor.boiler_nrgheat",
        "elec_heating": "sensor.boiler_meterheat",
        "heat_dhw": "sensor.boiler_dhw_nrg",
        "outdoor_temp": None,
    },
    CONF_HISTORY: {"sensor.boiler_dhw_nrg": ["sensor.boiler_nrgww"]},
}


def test_sources_cover_signals_and_history() -> None:
    assert sources(DATA) == {
        "sensor.boiler_nrgheat",
        "sensor.boiler_meterheat",
        "sensor.boiler_dhw_nrg",
        "sensor.boiler_nrgww",
    }
    assert sources({CONF_NAME: "Gas", CONF_ENTITIES: {}}) == set()


def test_signal_renamed() -> None:
    data = renamed_data(DATA, "sensor.boiler_nrgheat", "sensor.wp_nrgheat")
    assert data[CONF_ENTITIES]["heat_heating"] == "sensor.wp_nrgheat"
    assert data[CONF_ENTITIES]["elec_heating"] == "sensor.boiler_meterheat"
    assert data[CONF_ENTITIES]["outdoor_temp"] is None
    assert data[CONF_HISTORY] == DATA[CONF_HISTORY]
    assert data[CONF_NAME] == "WP"
    # The original stays as it was (entry data is read-only).
    assert DATA[CONF_ENTITIES]["heat_heating"] == "sensor.boiler_nrgheat"


def test_history_key_and_alias_renamed() -> None:
    data = renamed_data(DATA, "sensor.boiler_dhw_nrg", "sensor.wp_dhw_nrg")
    assert data[CONF_ENTITIES]["heat_dhw"] == "sensor.wp_dhw_nrg"
    assert data[CONF_HISTORY] == {"sensor.wp_dhw_nrg": ["sensor.boiler_nrgww"]}
    data = renamed_data(DATA, "sensor.boiler_nrgww", "sensor.wp_nrgww")
    assert data[CONF_HISTORY] == {"sensor.boiler_dhw_nrg": ["sensor.wp_nrgww"]}
    assert data[CONF_ENTITIES] == DATA[CONF_ENTITIES]


def test_data_without_history() -> None:
    gas = {CONF_ENTITIES: {"gas_total": "sensor.gas"}, "kind": "gas"}
    assert renamed_data(gas, "sensor.gas", "sensor.gas_meter") == {
        CONF_ENTITIES: {"gas_total": "sensor.gas_meter"},
        "kind": "gas",
    }


def test_unique_id() -> None:
    # Manual mapping: the first energy entity.
    assert renamed_unique_id("sensor.a", "sensor.a", "sensor.b") == "sensor.b"
    # Gas boiler: the main counter with a prefix.
    assert renamed_unique_id("gas:sensor.a", "sensor.a", "sensor.b") == "gas:sensor.b"
    # Template entry: template and prefix, no entity id.
    assert renamed_unique_id("ems_esp:boiler", "sensor.a", "sensor.b") is None
    assert renamed_unique_id("sensor.c", "sensor.a", "sensor.b") is None
    assert renamed_unique_id(None, "sensor.a", "sensor.b") is None
