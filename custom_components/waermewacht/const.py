"""Constants for Wärmewacht. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "waermewacht"
VERSION: Final = "0.1.0b1"

# Config entry (one per heat pump).
CONF_NAME: Final = "name"
CONF_SOURCE: Final = "source"  # setup choice: "<template>:<prefix>" or "manual"
CONF_TEMPLATE: Final = "template"  # template key, or None for a manual mapping
CONF_ENTITIES: Final = "entities"  # {signal: entity_id}
SOURCE_MANUAL: Final = "manual"

# Options.
CONF_MIN_ELECTRICITY: Final = "min_electricity"
CONF_SHORT_RUN: Final = "short_run_minutes"
CONF_CRITICAL_RUN: Final = "critical_run_minutes"
CONF_STARTS_PER_HOUR: Final = "starts_per_hour"
CONF_SEASON_START: Final = "season_start_month"

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
