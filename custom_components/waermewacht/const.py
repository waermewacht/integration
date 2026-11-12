"""Constants for Wärmewacht. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "waermewacht"
VERSION: Final = "0.7.1"

# Config entry (one per heat pump).
CONF_NAME: Final = "name"
CONF_SOURCE: Final = "source"  # setup choice: "<template>:<prefix>" or "manual"
CONF_TEMPLATE: Final = "template"  # template key, or None for a manual mapping
CONF_ENTITIES: Final = "entities"  # {signal: entity_id}
CONF_HISTORY: Final = "history"  # {entity_id: [same counter, other id format]}
# Signals the template knew at setup/reconfigure (adopt.py).
CONF_KNOWN_SIGNALS: Final = "template_signals"
SOURCE_MANUAL: Final = "manual"
# Gas boiler before the switch (gas.py): an entry of its own kind.
CONF_KIND: Final = "kind"  # absent: heat pump
KIND_GAS: Final = "gas"
SOURCE_GAS: Final = "gas"  # setup choice
GAS_TOTAL: Final = "gas_total"  # heating and hot water
GAS_HEATING: Final = "gas_heating"  # heating only
GAS_DHW: Final = "gas_dhw"
CONF_BOILER_EFFICIENCY: Final = "boiler_efficiency"  # η on Hs
CONF_CALORIFIC_VALUE: Final = "calorific_value"  # kWh/m³ (Hs), from the bill
CONF_Z_NUMBER: Final = "z_number"  # Zustandszahl, from the bill
VOLUME_UNIT: Final = "m³"  # gas meters; anything else must be energy
# Gas readings by hand (readings.py): the meter's unit, VOLUME_UNIT or "kWh".
CONF_MANUAL_UNIT: Final = "manual_unit"
# Form value -> unit (selector keys must be plain lower case).
LITRE_UNIT: Final = "L"  # oil meters and tank levels
TANK: Final = "tank"  # readings by hand of a tank level (oil.py)
MANUAL_UNITS: Final = {"m3": VOLUME_UNIT, "kwh": "kWh", "l": LITRE_UNIT, "tank": TANK}
GAS_MANUAL_UNITS: Final = ("m3", "kwh")
OIL_MANUAL_UNITS: Final = ("l", "tank", "kwh")
# Oil boiler (oil.py): a gas boiler entry with data.fuel = "oil".
CONF_FUEL: Final = "fuel"  # absent: gas
FUEL_GAS: Final = "gas"
FUEL_OIL: Final = "oil"
SOURCE_OIL: Final = "oil"  # setup choice
CONF_BOILER_TYPE: Final = "boiler_type"  # oil.BOILER_TYPES or oil.CUSTOM
CONF_OIL_PRICE: Final = "oil_price"  # EUR per 100 l, gross
CONF_KWH_PER_LITRE: Final = "kwh_per_litre"  # kWh (Hs) per litre of oil
# Gas or oil: the flow sensor sits in the heating circuit (after a buffer or
# a mixing valve), not at the boiler (data, only when set; gas.py).
CONF_FLOW_IN_CIRCUIT: Final = "flow_in_circuit"

# Options.
CONF_MIN_ELECTRICITY: Final = "min_electricity"
CONF_SHORT_RUN: Final = "short_run_minutes"
CONF_CRITICAL_RUN: Final = "critical_run_minutes"
CONF_STARTS_PER_HOUR: Final = "starts_per_hour"
# Optional: more starts within 24 hours count as conspicuous (unset: off).
CONF_STARTS_PER_DAY: Final = "starts_per_day"
# Starts total as of now, entered without a start counter of the heat
# pump (form field only); stored is the offset to the own count.
CONF_STARTS_NOW: Final = "starts_now"
CONF_STARTS_OFFSET: Final = "starts_offset"
CONF_SEASON_START: Final = "season_start_month"
# Health check (docs/GESUNDHEITSCHECK.md), own assumptions.
CONF_AUX_MILD_FROM: Final = "aux_mild_from"  # °C day mean
CONF_EFFICIENCY_DROP: Final = "efficiency_drop_percent"
CONF_DISINFECTION_TEMP: Final = "disinfection_temp"  # °C storage, DVGW W 551
# Data sheet values for "power per heat load" (health check 4.7), optional.
CONF_RATED_POWER: Final = "rated_power_kw"
CONF_MIN_POWER: Final = "min_power_kw"
# Optional (costs, gas comparison, heat load); absent means "not set".
CONF_ELECTRICITY_PRICE: Final = "electricity_price"  # ct/kWh
# A price sensor (dynamic tariff): ct/kWh, €/kWh or €/MWh (prices.py); hours
# without its price fall back to the fixed price.
CONF_ELECTRICITY_PRICE_ENTITY: Final = "electricity_price_entity"
# Own PV and battery electricity in the costs (allocation.py): the grid
# import meter enables it; the others make the house consumption known.
CONF_GRID_IMPORT_ENTITY: Final = "grid_import_entity"
CONF_FEED_IN_ENTITY: Final = "feed_in_entity"
CONF_PV_ENTITY: Final = "pv_entity"
CONF_BATTERY_CHARGED_ENTITY: Final = "battery_charged_entity"
CONF_BATTERY_DISCHARGED_ENTITY: Final = "battery_discharged_entity"
CONF_FEED_IN_TARIFF: Final = "feed_in_tariff"  # ct/kWh, own electricity
# EUR per year, only for a separate heat pump meter (heat pump tariff).
CONF_ELECTRICITY_BASE_PRICE: Final = "electricity_base_price"
CONF_GAS_PRICE: Final = "gas_price"  # ct/kWh on the gross calorific value (Hs)
CONF_GAS_BASE_PRICE: Final = "gas_base_price"  # EUR per year
# Price changes from a date on: [{"from": "YYYY-MM-DD", <price field>: value}]
# (dated.py); the price fields above are the prices from the start.
CONF_PRICE_CHANGES: Final = "price_changes"
CONF_DESIGN_TEMP: Final = "design_outdoor_temp"  # °C, DIN/TS 12831-1 by postcode

# Storage: written every few minutes when something changed, at the end of a
# run, at local midnight and on shutdown (SD cards: no write per reading).
STORAGE_VERSION: Final = 1
SAVE_INTERVAL_SECONDS: Final = 600

# Counter increments above this power (with margin) are glitches.
MAX_POWER_KW: Final = 50.0

# Defaults of the options; sources in docs/ENTWICKLUNG.md, section 3.
DEFAULT_MIN_ELECTRICITY_KWH: Final = 0.5
DEFAULT_SHORT_RUN_MINUTES: Final = 10  # Fraunhofer ISE: report cycles under ~10 min
DEFAULT_CRITICAL_RUN_MINUTES: Final = 6  # Dimplex: minimum compressor run time ~6 min
DEFAULT_STARTS_PER_HOUR: Final = 3  # more starts within one hour count as conspicuous
DEFAULT_SEASON_START_MONTH: Final = 7  # heating season July to June

# Without a known state for longer than this, a run's start or end is uncertain
# (Home Assistant or the source was down). Restarts take a few seconds.
GAP_TOLERANCE_SECONDS: Final = 300

# Finished runs and defrosts are kept this long (month statistics need 31 days).
HISTORY_DAYS: Final = 40
