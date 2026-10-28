"""Source template for iDM heat pumps (Navigator 2.0) via idm_heatpump.

Pure Python, no Home Assistant imports. Derived from the source code of the
HACS integration Xerolux/idm-heatpump-hass (domain `idm_heatpump`, 0.23.2-b4,
commit 385f8cc, 2026-10-26) and its library idm-heatpump-api 2.14.5b2 (PyPI);
not yet checked against a real installation, so experimental.

Unique ids are "<config entry id>_<key>" (`entity.build_entity_unique_id`):
the register name for Modbus entities, "web_<value>" for values of the local
web interface. The entry id (ULID, or UUID hex on old entries) has no "_",
so the id splits at the first "_". `Template.split` only knows "-"
(device=None) and the EMS-ESP format, hence `IdmTemplate` below.

Energy: the Modbus registers 1748-1762 (`energy_heating`, `energy_dhw`,
`energy_cooling`, `energy_total`, `energy_electric_heater`, ...) are heat
quantities ("Wärmemenge", adapter_names.py); Modbus has no electricity
counter, only the power `power_consumption_hp` (4122, Navigator 10 only).
Electricity per mode exists only in the Navigator 2.0 web statistics
(`/data/statistics.php`, types `amountofheat` and `baenergyhp`), which the
integration reads when the web interface (PIN) is configured: lifetime
totals in kWh per category heating, hot water, cooling and defrost
(`web_stat_genheat_total_*`, `web_stat_elcons_total_*`; state class
total_increasing, inferred from the unit). Heat is taken from the same
statistics first, so heat and electricity of a mode share one source.

Navigator 10 is not covered: its web statistics carry heat only, and the
integration's own `energy_electrical_total` (trapezoidal sum of 4122) is a
total over all modes. Defrosts are a category of their own: their
electricity goes to the mode running (mostly heating); their heat is left
out, as its sign is not documented.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Activity, Signal
from .profiles import Template, _words


@dataclass(frozen=True)
class IdmTemplate(Template):
    """Template whose unique ids are "<entry id>_<key>"."""

    def split(self, unique_id: str) -> tuple[str, str] | None:
        prefix, separator, key = unique_id.partition("_")
        return (prefix, key) if separator and prefix and key else None


# hp_operating_mode (Modbus 1090; 1501 on Navigator 1.7) is a UCHAR enum
# without a slug map: the sensor state is the English label of
# idm_heatpump.const.HP_OPERATING_MODE_OPTIONS. The German labels are those
# idm_heatpump uses if the register is decoded as a bit field
# (adapter_enums._HP_OPERATING_MODE_DE). Undocumented values (e.g. mixed
# bits) make the sensor unknown, never a combined label.
IDM_ACTIVITY = _words(
    {
        Activity.OFF: ("Standby", "Aus"),
        Activity.HEATING: ("Heating", "Heizbetrieb"),
        Activity.COOLING: ("Cooling", "Kühlbetrieb"),
        Activity.DHW: ("DHW", "Warmwasser"),
        Activity.DEFROST: ("Defrost", "Abtauen"),
    }
)

_S, _B = "sensor", "binary_sensor"
IDM = IdmTemplate(
    experimental=True,
    key="idm",
    label="iDM (Navigator 2.0)",
    platform="idm_heatpump",
    device=None,
    signals={
        # Web statistics first (same source as the electricity), the Modbus
        # heat quantities as fallback.
        Signal.HEAT_HEATING: (
            (_S, "web_stat_genheat_total_heating"),
            (_S, "energy_heating"),
        ),
        Signal.HEAT_DHW: (
            (_S, "web_stat_genheat_total_hotwater"),
            (_S, "energy_dhw"),
        ),
        Signal.HEAT_COOLING: (
            (_S, "web_stat_genheat_total_cooling"),
            (_S, "energy_cooling"),
        ),
        Signal.ELEC_HEATING: ((_S, "web_stat_elcons_total_heating"),),
        Signal.ELEC_DHW: ((_S, "web_stat_elcons_total_hotwater"),),
        Signal.ELEC_COOLING: ((_S, "web_stat_elcons_total_cooling"),),
        Signal.ELEC_DEFROST: ((_S, "web_stat_elcons_total_defrost"),),
        # No backup heater electricity: `energy_electric_heater` is its heat,
        # and whether the heat statistics include it is not documented.
        # Compressor 1 via Modbus (1100); some Navigator 2.0 report 0xFFFF
        # there and the integration hides it, then the web value.
        Signal.COMPRESSOR: (
            (_B, "compressor_status_1"),
            (_B, "web_compressor_1"),
        ),
        Signal.ACTIVITY: ((_S, "hp_operating_mode"),),
        # "Schaltzyklen Stufe 1" / "Starts Stage 1" of the web interface.
        Signal.STARTS_TOTAL: ((_S, "web_switch_cycles_stage_1"),),
        # Modbus first; the web duplicates exist only without Modbus.
        Signal.OUTDOOR_TEMP: (
            (_S, "outdoor_temp"),
            (_S, "web_outside_air_temperature"),
        ),
        Signal.FLOW_TEMP: ((_S, "hp_flow_temp"), (_S, "web_flow_temperature")),
        Signal.RETURN_TEMP: (
            (_S, "hp_return_temp"),
            (_S, "web_return_temperature"),
        ),
    },
    required=(Signal.COMPRESSOR, Signal.HEAT_HEATING, Signal.ELEC_HEATING),
    activity_values=IDM_ACTIVITY,
)
