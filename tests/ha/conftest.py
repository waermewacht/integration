"""Fixtures for Home Assistant tests.

pytest-homeassistant-custom-component needs Linux (fcntl). Without it (local
Windows development) these tests are not collected; CI runs them.
Entity names follow EMS-ESP; all values are made up.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

from custom_components.waermewacht.const import CONF_ENTITIES, CONF_NAME, CONF_TEMPLATE

HEAT_HEATING = "sensor.boiler_nrgheat"
ELEC_HEATING = "sensor.boiler_meterheat"
HEAT_DHW = "sensor.boiler_dhw_nrg"
ELEC_DHW = "sensor.boiler_dhw_meter"
COMPRESSOR = "binary_sensor.boiler_hpcompon"
ACTIVITY = "sensor.boiler_hpactivity"
FLOW = "sensor.boiler_hptc1"
RETURN = "sensor.boiler_hptc0"

ENTITIES = {
    "heat_heating": HEAT_HEATING,
    "elec_heating": ELEC_HEATING,
    "heat_dhw": HEAT_DHW,
    "elec_dhw": ELEC_DHW,
    "compressor": COMPRESSOR,
    "activity": ACTIVITY,
    "flow_temp": FLOW,
    "return_temp": RETURN,
}
ENERGY = {
    "unit_of_measurement": "kWh",
    "device_class": "energy",
    "state_class": "total_increasing",
}
TEMPERATURE = {"unit_of_measurement": "°C", "device_class": "temperature"}


def entry_data(**changes: Any) -> dict[str, Any]:
    return {
        CONF_NAME: "WP",
        CONF_TEMPLATE: "ems_esp",
        CONF_ENTITIES: dict(ENTITIES),
        **changes,
    }


if importlib.util.find_spec("pytest_homeassistant_custom_component") is None:
    collect_ignore_glob = ["test_*.py"]
else:

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
        """Allow loading custom_components/waermewacht in every test."""
