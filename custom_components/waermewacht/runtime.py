"""Runtime of one heat pump: follows the source entities and keeps the books.

All logic lives in the pure modules (counter, runs, cycling, energy, periods,
backfill); this class feeds them with state changes, a minute tick and the
recorder statistics, stores their state and notifies the entities.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import date, datetime, time, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    UnitOfEnergy,
    UnitOfTemperature,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_utc_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .activity import combine
from .averages import Mean
from .backfill import HourlyChanges, bookable_hours, by_hour, energy_between
from .charges import (
    COARSE_LATE,
    DISINFECTION_TEMP_C,
    LATE,
    Charge,
    ChargeTracker,
    DisinfectionSplit,
    disinfection_split,
)
from .charges import prune as prune_charges
from .const import (
    CONF_AUX_MILD_FROM,
    CONF_CRITICAL_RUN,
    CONF_DESIGN_TEMP,
    CONF_DISINFECTION_TEMP,
    CONF_EFFICIENCY_DROP,
    CONF_ELECTRICITY_BASE_PRICE,
    CONF_ELECTRICITY_PRICE,
    CONF_ENTITIES,
    CONF_GAS_BASE_PRICE,
    CONF_GAS_PRICE,
    CONF_HISTORY,
    CONF_MIN_ELECTRICITY,
    CONF_MIN_POWER,
    CONF_RATED_POWER,
    CONF_SEASON_START,
    CONF_SHORT_RUN,
    CONF_STARTS_PER_HOUR,
    CONF_TEMPLATE,
    DEFAULT_CRITICAL_RUN_MINUTES,
    DEFAULT_MIN_ELECTRICITY_KWH,
    DEFAULT_SEASON_START_MONTH,
    DEFAULT_SHORT_RUN_MINUTES,
    DEFAULT_STARTS_PER_HOUR,
    DOMAIN,
    HISTORY_DAYS,
    MAX_POWER_KW,
    SAVE_INTERVAL_SECONDS,
    STORAGE_VERSION,
)
from .counter import UNIT_FACTORS, Counter, CounterEvent, to_kwh
from .curve import curve_as_dicts, daily_samples, performance_curve
from .cycling import (
    CycleStats,
    activity_seconds,
    cycle_stats,
    max_starts_per_hour,
    prune,
    season_starts_baseline,
)
from .day_counters import async_wrong_counters, wrong_kind
from .degree_days import DegreeDays, daily_degree_days, degree_days
from .energy import Kind, Totals
from .health import (
    AUX_KWH,
    CHARGE_DAYS,
    DROP_PERCENT,
    MILD_FROM,
    NO_AUX,
    NOT_ANALYSED,
    RESTARTED,
    Finding,
    aux_dhw_charges,
    aux_mild_weather,
    dhw_efficiency_drop,
    efficiency_drop,
    outdoor_problem,
    window_days,
)
from .health_extra import (
    DefrostFigures,
    OversizeFigure,
    SpreadFigure,
    ZeroFlow,
    compare_defrost_classes,
    defrost_classes,
    defrost_figures,
    flow_plausibility,
    oversizing,
    spread_figure,
    standby_rise,
    to_lph,
)
from .heat_load import HeatLoad, heat_load
from .heating_curve import FlowCurve, flow_curve
from .model import (
    ACTIVITY_PARTS,
    AUX_SIGNALS,
    ELEC_SIGNALS,
    ENERGY_SIGNALS,
    HEAT_SIGNALS,
    Activity,
    Mode,
    Signal,
    has_elec,
)
from .periods import Period, PeriodMarks, local_midnight, period_start
from .profiles import EMS_ESP, RegistryEntry, Template, find, parse_compressor
from .report import (
    OWN_KEYS,
    by_month,
    degree_day_figures,
    degree_days_by_month,
    figures,
    own_hour,
    own_totals,
    statistics_rows,
)
from .runs import ACTIVITY, COMPRESSOR, Defrost, Run, RunTracker, replay
from .templates import TEMPLATES

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

MODE_OF: dict[Signal, Mode] = {
    **{s: m for m, s in HEAT_SIGNALS.items()},
    **{s: m for m, s in ELEC_SIGNALS.items()},
    **{s: m for m, s in AUX_SIGNALS.items()},
}
# Critical runs within 24 hours from which cycling counts as conspicuous.
CRITICAL_RUNS_PER_DAY = 3
# Start of the statistics query for "everything".
EARLIEST = datetime(2000, 1, 1, tzinfo=dt_util.UTC)
# Hourly statistics of the source (Vaillant): look back for the signals to
# expect, catch up at most this far, warn when nothing new came this long.
HOURLY_LOOKBACK = timedelta(hours=48)
HOURLY_CATCH_UP = timedelta(days=10)
HOURLY_STALE = timedelta(hours=30)
# Statistic rows above MAX_POWER_KW times this in one hour are glitches.
HOURLY_MARGIN = 1.5
DAY = timedelta(days=1)
# Flow and return swapped (docs/GESUNDHEITSCHECK.md 4.10 d): the daily mean
# spread while heating below this, after at least an hour of heating.
SWAPPED_SPREAD_K = -1.0
SWAPPED_MIN_SECONDS = 3600.0
# Below the disinfection temperature by this much, the next rise counts
# as a new disinfection.
DISINFECTION_RELEASE_K = 5.0
# A ratio is reliable when one counter step is at most 5 % of the electricity.
RELIABLE_STEPS = 20
# Entities may appear late after a restart; issues only after this grace time.
ISSUE_GRACE = timedelta(minutes=10)
# Health check (docs/GESUNDHEITSCHECK.md, 4.10): a counter of the running
# mode that does not rise for this long is stuck; whole-kWh counters and cloud
# day values (hours late) get more time. Own assumptions with a wide margin.
STUCK_DECIMAL = timedelta(minutes=60)
STUCK_COARSE = timedelta(hours=6)
# Previous-day values move once a day: more than a day of running.
STUCK_PREVIOUS_DAY = timedelta(hours=30)
UNAVAILABLE_LIMIT = timedelta(minutes=60)
# After "restart comparison" the first weeks are the new reference.
RESTART_BASELINE = timedelta(days=28)
# Daily diary kept in the history file (about 150 bytes a day).
DIARY_DAYS = 1100
# Performance curve and heat load: shortly after the start, then daily.
ANALYSIS_DELAY = timedelta(minutes=2)
ANALYSIS_HOUR = 3  # local time
# Imported sums are shifted once the own sensors have short-term statistics
# (compiled every 5 minutes), so the recorder continues from shifted sums.
ADJUST_DELAY = timedelta(minutes=15)
# Day values of a cloud: the electricity of a fetch waits this long for the
# heat of the same fetch (the entities update one after another), and heat
# up to SAME_FETCH before the electricity belongs to the same fetch.
PENDING_DELAY = timedelta(seconds=10)
SAME_FETCH = timedelta(seconds=30)


def _per_kwh(cents: float | None) -> float | None:
    return None if cents is None else cents / 100


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _hour(moment: datetime) -> datetime:
    """Start of the hour."""
    return moment.replace(minute=0, second=0, microsecond=0)


def _float(state: State | None) -> float | None:
    if state is None:
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


class HeatPumpRuntime:
    """Books energy and runs of one heat pump."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.entities: dict[Signal, str] = {
            Signal(k): v for k, v in entry.data[CONF_ENTITIES].items() if v
        }
        self._signal_of = {v: k for k, v in self.entities.items()}
        self.template: Template = TEMPLATES.get(
            entry.data.get(CONF_TEMPLATE) or "", EMS_ESP
        )
        options = entry.options
        self.min_electricity: float = options.get(
            CONF_MIN_ELECTRICITY, DEFAULT_MIN_ELECTRICITY_KWH
        )
        self.short_seconds = 60 * options.get(CONF_SHORT_RUN, DEFAULT_SHORT_RUN_MINUTES)
        self.critical_seconds = 60 * options.get(
            CONF_CRITICAL_RUN, DEFAULT_CRITICAL_RUN_MINUTES
        )
        self.starts_per_hour: int = options.get(
            CONF_STARTS_PER_HOUR, DEFAULT_STARTS_PER_HOUR
        )
        self.tz = dt_util.get_default_time_zone()
        # Prices are entered in ct/kWh; the cost module works in €/kWh.
        self.electricity_price: float | None = _per_kwh(
            options.get(CONF_ELECTRICITY_PRICE)
        )
        self.electricity_base_price: float | None = options.get(
            CONF_ELECTRICITY_BASE_PRICE
        )
        self.gas_price: float | None = _per_kwh(options.get(CONF_GAS_PRICE))
        self.design_temp: float | None = options.get(CONF_DESIGN_TEMP)
        self.aux_mild_from: float = options.get(CONF_AUX_MILD_FROM, MILD_FROM)
        self.drop_threshold: float = options.get(CONF_EFFICIENCY_DROP, DROP_PERCENT)
        # Activity from the activity entity and/or flags (activity.py).
        self._activity_configured = {
            s for s in (Signal.ACTIVITY, *ACTIVITY_PARTS) if s in self.entities
        }
        # Modes with a heat counter; without one (ViCare) there are no ratios
        # and no standby can be told, the electricity counts as running.
        self.heat_modes = frozenset(m for m in Mode if HEAT_SIGNALS[m] in self.entities)
        # The activity entity showed a value that carries no activity here.
        self._activity_foreign = False
        # Health check: daily findings (memory only), their state across
        # restarts, and the minute checks of the repair issues.
        self.findings: dict[str, Finding] = {
            "standby_rise": Finding(None, NOT_ANALYSED),
            "efficiency_drop": Finding(None, NOT_ANALYSED),
            "aux_mild_weather": Finding(None, NOT_ANALYSED),
            "aux_dhw_charges": Finding(None, NOT_ANALYSED),
            "dhw_efficiency_drop": Finding(None, NOT_ANALYSED),
        }
        self._efficiency_on = False
        self.comparison_reset_at: datetime | None = None
        self._stuck_seconds: dict[str, float] = {}  # running time without rise
        self._unavailable_since: dict[str, datetime] = {}
        self._last_tick: datetime | None = None
        self.outdoor = Mean()  # outdoor temperature today, for the diary
        # Figures of the daily analysis (health_extra.py) and the data sheet.
        self.rated_power: float | None = options.get(CONF_RATED_POWER)
        self.min_power: float | None = options.get(CONF_MIN_POWER)
        self.spread_7d: SpreadFigure | None = None
        self.oversize: OversizeFigure | None = None
        self.defrost_week: DefrostFigures | None = None
        # Defrosts per run hour per outdoor class, against the previous season.
        self.defrost_classes: list[dict[str, Any]] = []
        # Flow rate while the compressor heats (l/h), today; the daily verdict
        # on its plausibility (evidence while implausible) and the heating
        # time with a flow of 0.
        self.flow_rate = Mean()
        self._flow_rate_lph: float | None = None
        self._flow_verdict: dict[str, Any] | None = None
        self._zero_flow = ZeroFlow()
        # Daily verdict on the spread (None: not enough heating yet); kept,
        # because the repair issue is rebuilt from it after a restart.
        self._swapped: float | None = None
        self.diary: list[dict[str, Any]] = []
        # Hot water charges (charges.py): finished ones in the history file,
        # the running one in the live file; disinfection from the storage
        # temperature alone.
        self.disinfection_temp: float = options.get(
            CONF_DISINFECTION_TEMP, DISINFECTION_TEMP_C
        )
        self.charges: list[Charge] = []
        self.charge_tracker = ChargeTracker()
        self.last_disinfection: datetime | None = None
        self._hot = False
        self._dhw_temp: float | None = None
        # Performance curves (current and previous season) and heat load of
        # the last complete season; recomputed daily, kept in memory only.
        self.curves: dict[str, list[dict[str, Any]]] = {}
        self.curve_starts: dict[str, datetime] = {}
        self.heat_load: HeatLoad | None = None
        self.heat_load_window: tuple[datetime, datetime] | None = None
        # Degree days G20/15 of the current season up to yesterday, and the
        # heat per degree day of the previous season for comparison.
        self.degree_days: DegreeDays | None = None
        # Counter of starts at the start of the season (or the earliest
        # value in the statistics), for "Starts season".
        self.starts_baseline: tuple[int, datetime] | None = None
        # First counter value seen this season, for a counter without
        # statistics (no state class): entity id, value, time.
        self._starts_seen: tuple[str, int, datetime] | None = None
        # Flow temperature over outdoor temperature (heating_curve.py), the
        # current and the previous season.
        self.flow_curves: dict[str, FlowCurve] = {}
        self.degree_days_previous: DegreeDays | None = None
        self.analysed_at: datetime | None = None
        self._analysis_day: date | None = None
        self._counter_check_day: date | None = None  # last check of counter kinds
        self._analysing = False
        self.gas_base_price: float | None = options.get(CONF_GAS_BASE_PRICE)
        day_tz = None
        if self.template.day_values:
            zone = self.template.day_timezone
            day_tz = dt_util.get_time_zone(zone) if zone else self.tz
        # Energy signals; booked from state changes (counters) or, for
        # sources that write hourly statistics themselves, hour by hour.
        self.hourly = self.template.hourly_statistics
        self._energy = [s for s in ENERGY_SIGNALS if s in self.entities]
        self.counters = (
            {}
            if self.hourly
            else {
                s: Counter(
                    max_kw=MAX_POWER_KW,
                    day_tz=day_tz,
                    previous_day=self.template.previous_day,
                )
                for s in self._energy
            }
        )
        self._statistic_ids = self._source_statistic_ids()
        self.booked_until: datetime | None = None  # hourly: next hour to book
        # Hourly: end of the backfill, the boundary of the history import.
        self.backfill_until: datetime | None = None
        self._booking = False
        self._mapping_ok = True
        self.tracker = RunTracker()
        self.totals = Totals()
        # The options form stores the month as text ("7").
        self.marks = PeriodMarks(
            self.tz, int(options.get(CONF_SEASON_START, DEFAULT_SEASON_START_MONTH))
        )
        self.runs: list[Run] = []
        self.defrosts: list[Defrost] = []
        self.own_starts = 0  # observed starts since setup
        self.spread = Mean()  # flow minus return, compressor heating, today
        self.flow = Mean()  # flow temperature, compressor heating, today
        self.since: datetime | None = None  # first setup
        # The hours before the setup are in the own sensors' statistics, and
        # their sums were shifted to start at 0.
        self.history_imported = False
        self.history_adjusted = False
        self._adjusting = False
        self.events: dict[str, int] = {}  # counter events, unknown units (diagnostics)
        # Counters seen with decimals; the others count in whole kWh.
        self.decimal: set[Signal] = set()
        self._started_at = dt_util.utcnow()
        self._issues: dict[str, str] = {}  # issue id -> placeholder text
        self._flow_temp: float | None = None
        self._return_temp: float | None = None
        self._sample_at: datetime | None = None
        self._sampling = False
        self._mode_seen: dict[Mode, datetime] = {}
        self._heat_at: dict[Mode, datetime] = {}
        # Electricity of day values waiting for the heat of its fetch.
        self._pending: list[tuple[Mode, float, datetime]] = []
        # Two files (SD cards): a small live file (counters, totals, marks)
        # every few minutes when changed, and the run history (up to 40 days
        # of runs and defrosts) only when a run ends and at midnight.
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._history_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.history"
        )
        self._dirty = False
        self._history_dirty = False
        self._saved_at: datetime | None = None
        self._listeners: list[CALLBACK_TYPE] = []
        # Own tasks -> cancel on stop (False: a write, awaited instead).
        self._tasks: dict[asyncio.Task, bool] = {}
        self._stopped = False
        self._unsubscribe: list[CALLBACK_TYPE] = []

    # Lifecycle.

    async def async_start(self) -> None:
        """Restore or backfill, read current states, start listening."""
        now = dt_util.utcnow()
        history = None
        if data := await self._store.async_load():
            self._restore(data)
            history = await self._history_store.async_load()
            if self.marks.stored_season_month not in (None, self.marks.season_month):
                await self._async_rebase(Period.SEASON, now)
            if Period.YEAR not in self.marks.marks:
                # Update from 0.1.0b3: the calendar year (season of cooling).
                await self._async_rebase(Period.YEAR, now)
        else:
            self.since = now
            await self._async_backfill(now)
            self._dirty = True
        if history is not None:
            self._restore_history(history)
        else:
            # First setup, or an update from 0.1.0b1 (runs in the live file):
            # rebuild runs and defrosts from the recorded states.
            if not await self._async_backfill_runs(now) and data and "runs" in data:
                self._restore_history(data)
            self._history_dirty = True
        self.marks.rollover(now, self.totals)
        if self.hourly:
            self._mapping_ok = self._mapping_still_fits()
        if self.has_charges:
            self._update_charge_finding(now)
        for entity_id in sorted(self._signal_of):
            if state := self.hass.states.get(entity_id):
                # A counter value is dated by its own change: a cloud day value
                # of yesterday must not count as today's after a restart.
                counter = self._signal_of[entity_id] in self.counters
                self._handle(entity_id, state, state.last_updated if counter else now)
        self._unsubscribe = [
            async_track_state_change_event(
                self.hass, sorted(self._signal_of), self._on_state_change
            ),
            async_track_utc_time_change(self.hass, self._on_tick, second=0),
        ]
        await self.async_save()

    async def async_stop(self) -> None:
        self._stopped = True
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = []
        # No task of this runtime may outlive it: an analysis would set
        # repair issues of an unloaded (or removed) entry, a late write
        # would follow the final save. Writes finish, the rest is cancelled.
        tasks = list(self._tasks.items())
        for task, cancel in tasks:
            if cancel:
                task.cancel()
        if tasks:
            await asyncio.gather(*(task for task, _ in tasks), return_exceptions=True)
        self._resolve_pending(dt_util.utcnow(), final=True)
        await self.async_save()

    @callback
    def spawn(
        self,
        job: Coroutine[Any, Any, Any],
        name: str,
        *,
        cancel: bool = True,
        background: bool = False,
    ) -> None:
        """Run `job` as a task of this runtime (see async_stop); after the
        stop it does not run at all. A background task (long, once) is not
        waited for by Home Assistant's own task tracking."""
        if self._stopped:
            job.close()
            return
        task = (
            self.entry.async_create_background_task(
                self.hass, job, f"waermewacht_{name}"
            )
            if background
            else self.hass.async_create_task(job, f"waermewacht_{name}")
        )
        self._tasks[task] = cancel
        task.add_done_callback(lambda done: self._tasks.pop(done, None))

    async def async_remove(self) -> None:
        await self._store.async_remove()
        await self._history_store.async_remove()

    @callback
    def follow_rename(self, old: str, new: str) -> None:
        """A source entity was renamed; the entry reloads shortly.

        Until then statistics are read under the new id, and the books
        written on unload name it: verdicts and the seen starts are kept
        instead of being dropped as made for another entity.
        """
        for mapping in (self.entities, self._statistic_ids):
            for signal, entity_id in mapping.items():
                if entity_id == old:
                    mapping[signal] = new
        self._signal_of = {v: k for k, v in self.entities.items()}
        if self._starts_seen and self._starts_seen[0] == old:
            self._starts_seen = (new, *self._starts_seen[1:])
        self._dirty = True

    @callback
    def add_listener(self, listener: CALLBACK_TYPE) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # Backfill from the long-term statistics (first setup only).

    async def _async_backfill(self, now: datetime) -> None:
        hourly: HourlyChanges = {}
        # Previous-day values: Home Assistant's statistics of the source book
        # a day in the hour after midnight, a higher next day only as the
        # difference: no look back.
        if "recorder" in self.hass.config.components and not self.template.previous_day:
            try:
                hourly = await self._async_source_hours(EARLIEST, now)
            except Exception:  # never block the setup
                _LOGGER.exception("Reading the statistics for the backfill failed")
        until = now
        if self.hourly:
            # Hours the source has not written completely yet are booked by
            # the tick, into the period they belong to; which series to wait
            # for is judged from the last 48 hours, as the tick does.
            window = _hour(now) - HOURLY_LOOKBACK
            recent = {
                s: {h: v for h, v in values.items() if h >= window}
                for s, values in hourly.items()
            }
            _, until = bookable_hours(recent, window, _hour(now))
            self.booked_until = until
            self.backfill_until = until
        self.marks.initialize(
            now,
            lambda start: energy_between(
                hourly,
                start,
                until,
                self.heat_modes,
                self.template.heat_includes_electricity,
            ),
        )

    async def _async_backfill_runs(self, now: datetime) -> bool:
        """Runs and defrosts of the recorded history (about 10 days)."""
        compressor = self.entities.get(Signal.COMPRESSOR)
        if compressor is None or "recorder" not in self.hass.config.components:
            return False
        parts = {self.entities[s]: s for s in self._activity_configured}
        ids = [compressor, *sorted(parts)]
        try:
            states = await get_instance(self.hass).async_add_executor_job(
                partial(
                    get_significant_states,
                    self.hass,
                    now - timedelta(days=HISTORY_DAYS),
                    now,
                    ids,
                    significant_changes_only=False,
                    no_attributes=True,
                )
            )
        except Exception:  # never block the setup
            _LOGGER.exception("Reading the state history for the runs failed")
            return False
        events: list[tuple[datetime, str, bool | Activity | None]] = []
        switches = [
            (state.last_updated, parse_compressor(state.state))
            for state in states.get(compressor, [])
            if isinstance(state, State)
        ]
        events.extend((at, COMPRESSOR, on) for at, on in switches)
        # The activity at each change of one of its entities (with flags
        # only also at each compressor switch, see activity.combine).
        changes: list[tuple[datetime, Signal | None, str | None]] = [
            (state.last_updated, parts[entity_id], state.state)
            for entity_id in parts
            for state in states.get(entity_id, [])
            if isinstance(state, State)
        ]
        if self._activity_needs_compressor:
            # An unknown compressor state keeps the last known one (RunTracker).
            changes.extend(
                (at, None, "on" if on else "off")
                for at, on in switches
                if on is not None
            )
        current: dict[Signal, str | None] = {}
        running: bool | None = None
        for at, signal, raw in sorted(changes, key=lambda c: c[0]):
            if signal is None:
                running = raw == "on"
            else:
                current[signal] = raw
            events.append((at, ACTIVITY, self._activity_of(current, running)))
        if not events:
            return False
        self.tracker, self.runs, self.defrosts = replay(events)
        return True

    async def async_import_history(self) -> None:
        """Once per entry: write the hours before the setup into the
        statistics of the own energy sensors, so statistics cards show the
        months before the setup as well.

        Only hours before the first row Home Assistant recorded itself are
        written, with sums ending at 0 where its own sum starts (see
        report.statistics_rows): no recorded row changes. A sensor that
        already has rows from before the setup is left alone.
        """
        if self.history_imported or self.since is None:
            return
        if "recorder" not in self.hass.config.components:
            return
        if self.template.previous_day:
            # No usable source statistics (see _async_backfill).
            self.history_imported = self.history_adjusted = True
            self._dirty = True
            return
        # One attempt, also on failure: never run twice into the same rows.
        self.history_imported = True
        self._dirty = True
        before = self._history_end()
        ids = self._own_ids()
        try:
            recorded = await self.async_hourly(set(ids.values()), EARLIEST, before)
            rows = statistics_rows(
                by_hour(
                    await self._async_source_hours(EARLIEST, before),
                    self.heat_modes,
                    self.template.heat_includes_electricity,
                )
            )
        except Exception:  # never block the setup
            _LOGGER.exception("Reading the statistics for the history import failed")
            return
        for key, entity_id in ids.items():
            if recorded.get(entity_id) or not rows.get(key):
                continue
            metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=None,
                source="recorder",
                statistic_id=entity_id,
                unit_class="energy",
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            )
            async_import_statistics(
                self.hass,
                metadata,
                [StatisticData(start=hour, sum=kwh) for hour, kwh in rows[key]],
            )
        _LOGGER.debug("Imported the statistics before %s for %s", before, ids)

    def _history_end(self) -> datetime:
        """End of the hours written before the setup: the setup hour, or for
        hourly statistics the end of the backfill (later hours are booked)."""
        assert self.since is not None
        if self.hourly and self.backfill_until is not None:
            return self.backfill_until
        return _hour(self.since)

    def _own_ids(self) -> dict[str, str]:
        registry = er.async_get(self.hass)
        return {
            key: entity_id
            for key in OWN_KEYS
            if (
                entity_id := registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{self.entry.entry_id}_{key}"
                )
            )
        }

    async def _async_adjust_history(self) -> None:
        """Shift the imported sums up by the imported energy, once.

        Home Assistant takes the change of a sensor's earliest row against 0:
        imported sums ending at 0 would show the whole past as one negative
        step in the first hour. Shifted, the sum starts at 0 and every
        change stays the same. Only a sensor whose earliest row is exactly
        the first imported one is shifted (never twice, never other data).
        """
        self._adjusting = True
        try:
            if self.since is None:
                return
            before = self._history_end()
            ids = self._own_ids()
            hours = by_hour(
                await self._async_source_hours(EARLIEST, before),
                self.heat_modes,
                self.template.heat_includes_electricity,
            )
            rows, totals = statistics_rows(hours), own_totals(hours)
            first = await get_instance(self.hass).async_add_executor_job(
                partial(
                    statistics_during_period,
                    self.hass,
                    EARLIEST,
                    before,
                    set(ids.values()),
                    "hour",
                    None,
                    {"sum"},
                )
            )
            for key, entity_id in ids.items():
                if not rows.get(key) or not first.get(entity_id):
                    continue
                hour, imported_sum = rows[key][0]
                row = first[entity_id][0]
                start = row["start"]
                if not isinstance(start, datetime):
                    start = dt_util.utc_from_timestamp(start)
                recorded_sum = row.get("sum")
                if (
                    start != hour
                    or recorded_sum is None
                    or abs(recorded_sum - imported_sum) > 0.01
                ):
                    continue
                get_instance(self.hass).async_adjust_statistics(
                    entity_id, hour, totals[key], UnitOfEnergy.KILO_WATT_HOUR
                )
        except Exception:  # keep running; the first bar then stays negative
            _LOGGER.exception("Shifting the imported statistics failed")
        finally:
            # One attempt: never shift twice.
            self.history_adjusted = True
            self._adjusting = False
            self._dirty = True

    async def async_outdoor_hours(
        self, start: datetime, end: datetime
    ) -> dict[datetime, float]:
        """Hourly mean outdoor temperature from the long-term statistics."""
        return await self._async_mean_hours(Signal.OUTDOOR_TEMP, start, end)

    async def _async_mean_hours(
        self, signal: Signal, start: datetime, end: datetime
    ) -> dict[datetime, float]:
        """Hourly means of a temperature from the long-term statistics."""
        entity_id = self.entities.get(signal)
        if entity_id is None or start >= end:
            return {}
        rows = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            end,
            {entity_id},
            "hour",
            {"temperature": UnitOfTemperature.CELSIUS},
            {"mean"},
        )
        outdoor: dict[datetime, float] = {}
        for row in rows.get(entity_id, []):
            if (mean := row.get("mean")) is None:
                continue
            hour = row["start"]
            if not isinstance(hour, datetime):
                hour = dt_util.utc_from_timestamp(hour)
            outdoor[hour] = mean
        return outdoor

    async def async_analysis_data(
        self, start: datetime, end: datetime
    ) -> tuple[dict[datetime, Totals], dict[datetime, float]]:
        """Hourly energy (standby apart) and outdoor means of [start, end)."""
        return await self._async_hours(start, end), await self.async_outdoor_hours(
            start, end
        )

    def seasons(self, now: datetime) -> tuple[datetime, datetime]:
        """Starts of the current and the previous heating season."""
        current = period_start(Period.SEASON, now, self.tz, self.marks.season_month)
        assert current is not None
        previous = period_start(
            Period.SEASON, current - timedelta(days=1), self.tz, self.marks.season_month
        )
        assert previous is not None
        return current, previous

    async def _async_refresh_analysis(self, now: datetime) -> None:
        """Performance curve of the current and the previous season (never
        mixed: a changed heating curve would blur both) and the heat load of
        the last complete season."""
        self._analysing = True
        try:
            current, previous = self.seasons(now)
            hours, outdoor = await self.async_analysis_data(previous, now)

            def window(start: datetime, end: datetime) -> tuple[dict, dict]:
                return (
                    {h: t for h, t in hours.items() if start <= h < end},
                    {h: v for h, v in outdoor.items() if start <= h < end},
                )

            this_season, last_season = window(current, now), window(previous, current)
            self.curves = {
                "current": curve_as_dicts(
                    performance_curve(
                        *this_season, self.tz, min_electricity=self.min_electricity
                    )
                ),
                "previous": curve_as_dicts(
                    performance_curve(
                        *last_season, self.tz, min_electricity=self.min_electricity
                    )
                ),
            }
            self.curve_starts = {"current": current, "previous": previous}
            self.heat_load = heat_load(
                *last_season, self.tz, design_temp=self.design_temp
            )
            self.heat_load_window = (previous, current)
            today = now.astimezone(self.tz).date()
            first = current.astimezone(self.tz).date()
            self.degree_days = degree_days(*this_season, self.tz, first, today)
            self.degree_days_previous = degree_days(
                *last_season, self.tz, previous.astimezone(self.tz).date(), first
            )
            self.analysed_at = now
            self.starts_baseline = await self._async_starts_baseline(current, now)
            if (entity_id := self.entities.get(Signal.STARTS_TOTAL)) is not None:
                seen = self._starts_seen
                kept = seen[1:] if seen and seen[0] == entity_id else None
                self.starts_baseline, kept = season_starts_baseline(
                    self.starts_baseline, kept, self.starts_total()[0], current, now
                )
                self._starts_seen = (entity_id, *kept) if kept else None
            flow = await self._async_mean_hours(Signal.FLOW_TEMP, previous, now)
            if flow:
                self.flow_curves = {
                    name: flow_curve(
                        span[0],
                        {h: v for h, v in flow.items() if start <= h < end},
                        span[1],
                        self.tz,
                    )
                    for name, span, start, end in (
                        ("current", this_season, current, now),
                        ("previous", last_season, previous, current),
                    )
                }
            self._health_findings(now, hours, outdoor, current, previous)
            today = now.astimezone(self.tz).date()
            self.spread_7d = spread_figure(self.diary, today)
            self.oversize = oversizing(
                self.heat_load, self.rated_power, min_kw=self.min_power
            )
            self.findings["standby_rise"] = standby_rise(self.diary, today, self.tz)
            self.findings["dhw_efficiency_drop"] = dhw_efficiency_drop(
                self.diary, today, min_electricity=self.min_electricity
            )
            self.defrost_week = defrost_figures(
                self.defrosts, outdoor, now - timedelta(days=7), now
            )
            first = current.astimezone(self.tz).date()
            self.defrost_classes = compare_defrost_classes(
                defrost_classes(self.diary, first, today - timedelta(days=1)),
                defrost_classes(
                    self.diary,
                    previous.astimezone(self.tz).date(),
                    first - timedelta(days=1),
                ),
            )
            await self._async_check_outdoor(now)
        except Exception:  # keep running; the sensors stay as they were
            _LOGGER.exception("Computing performance curve and heat load failed")
        finally:
            self._analysis_day = now.astimezone(self.tz).date()
            self._analysing = False
            self._notify()

    def _counter_check_due(self, now: datetime) -> bool:
        """Shortly after the start, then daily (as the analysis, but also
        without an outdoor temperature)."""
        if (
            wrong_kind(self.template) is None
            or "recorder" not in self.hass.config.components
        ):
            return False
        if self._counter_check_day is None:
            return now - self._started_at >= ANALYSIS_DELAY
        local = now.astimezone(self.tz)
        return local.date() != self._counter_check_day and local.hour >= ANALYSIS_HOUR

    async def _async_check_counters(self) -> None:
        """Repair issue for counters of the wrong kind (entries made before
        the check): a day counter booked as lifetime counter books nothing
        on days below 1 kWh, a lifetime counter booked as day values too
        much or nothing."""
        if (kind := wrong_kind(self.template)) is None:
            return
        found = await async_wrong_counters(
            self.hass,
            [self.entities[s] for s in self._energy],
            kind,
            previous_day=self.template.previous_day,
        )
        self._set_issue(kind, found)

    def _health_findings(
        self,
        now: datetime,
        hours: dict[datetime, Totals],
        outdoor: dict[datetime, float],
        current: datetime,
        previous: datetime,
    ) -> None:
        """Efficiency drop and backup heater on mild days (health.py)."""

        def curve(start: datetime, end: datetime) -> list[dict[str, Any]]:
            return curve_as_dicts(
                performance_curve(
                    {h: t for h, t in hours.items() if start <= h < end},
                    {h: v for h, v in outdoor.items() if start <= h < end},
                    self.tz,
                    min_electricity=self.min_electricity,
                )
            )

        reset = self.comparison_reset_at
        if reset is not None and reset < previous:
            reset = self.comparison_reset_at = None  # older than both seasons
            self._dirty = True
        if reset is None:
            drop = efficiency_drop(
                self.curves["current"],
                self.curves["previous"],
                threshold=self.drop_threshold,
                was_on=self._efficiency_on,
            )
        elif reset >= current and now < reset + RESTART_BASELINE:
            drop = Finding(None, RESTARTED)
        else:
            # After a deliberate change: the weeks after the reset are the
            # reference (or the rest of the previous season after it).
            end = reset + RESTART_BASELINE if reset >= current else current
            drop = efficiency_drop(
                curve(end, now),
                curve(reset, end),
                threshold=self.drop_threshold,
                was_on=self._efficiency_on,
            )
        if drop.problem is not None:
            self._efficiency_on = drop.problem
            self._dirty = True
        self.findings["efficiency_drop"] = drop

        if not any(
            s in self.entities for s in (*AUX_SIGNALS.values(), Signal.AUX_TOTAL)
        ):
            self.findings["aux_mild_weather"] = Finding(None, NO_AUX)
            return
        first, last = window_days(now.astimezone(self.tz).date())
        days = [
            d for d in daily_samples(hours, outdoor, self.tz) if first <= d.day <= last
        ]
        self.findings["aux_mild_weather"] = aux_mild_weather(
            days, mild_from=self.aux_mild_from, threshold_kwh=AUX_KWH
        )

    async def _async_starts_baseline(
        self, season: datetime, now: datetime
    ) -> tuple[int, datetime] | None:
        """Start counter at the start of the season from the statistics: the
        last hour before it, else the earliest hour after it."""
        entity_id = self.entities.get(Signal.STARTS_TOTAL)
        if entity_id is None:
            return None

        async def rows(start: datetime, end: datetime) -> list[dict[str, Any]]:
            found = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                start,
                end,
                {entity_id},
                "hour",
                None,
                {"state"},
            )
            return [r for r in found.get(entity_id, []) if r.get("state") is not None]

        before = await rows(season - timedelta(days=2), season)
        if before:
            return int(before[-1]["state"]), season
        after = await rows(season, now)
        if not after:
            return None
        first = after[0]
        start = first["start"]
        if not isinstance(start, datetime):
            start = dt_util.utc_from_timestamp(start)
        return int(first["state"]), start

    async def _async_check_outdoor(self, now: datetime) -> None:
        """Repair issue when the outdoor temperature stands still or is
        implausible (from the hourly min/max statistics, so restarts do not
        hide a stuck sensor)."""
        entity_id = self.entities.get(Signal.OUTDOOR_TEMP)
        if entity_id is None:
            return
        today = self._local_day(now)
        yesterday = self._local_day(now, -1)
        start = min(yesterday, now - timedelta(hours=50))
        rows = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            now,
            {entity_id},
            "hour",
            {"temperature": UnitOfTemperature.CELSIUS},
            {"mean", "min", "max"},
        )
        stats: dict[datetime, tuple[float | None, float | None, float | None]] = {}
        for row in rows.get(entity_id, []):
            hour = row["start"]
            if not isinstance(hour, datetime):
                hour = dt_util.utc_from_timestamp(hour)
            stats[hour] = (row.get("mean"), row.get("min"), row.get("max"))
        hours_of_yesterday = [h for h in stats if yesterday <= h < today]
        found = outdoor_problem(stats, hours_of_yesterday)
        for kind in ("stuck", "implausible"):
            self._set_issue(
                f"outdoor_temp_{kind}",
                [entity_id] if found and found.kind == kind else [],
                hours=str(found.hours) if found else "",
            )

    async def async_rebuild_history(self) -> None:
        """Button: the energy before the setup anew from the statistics,
        with today's entities and rules (meters added under Reconfigure, a
        corrected rule after an update). What was booked since the setup
        stays; the imported statistics of the own sensors stay as well."""
        if "recorder" not in self.hass.config.components:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_recorder"
            )
        if self.since is None or self.template.previous_day:
            # Previous-day values: no usable statistics (see _async_backfill).
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_look_back"
            )
        until = (
            self.backfill_until if self.hourly and self.backfill_until else self.since
        )
        try:
            hourly = await self._async_source_hours(EARLIEST, until)
        except Exception as err:
            _LOGGER.exception("Reading the statistics for the look-back failed")
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="look_back_failed"
            ) from err
        self.marks.rebuild(
            self.since,
            lambda start: energy_between(
                hourly,
                start,
                until,
                self.heat_modes,
                self.template.heat_includes_electricity,
            ),
        )
        self._dirty = True
        await self.async_save()
        self._notify()

    async def async_restart_comparison(self) -> None:
        """Button: compare efficiency anew from now (after a deliberate
        change such as a new heating curve)."""
        self.comparison_reset_at = dt_util.utcnow()
        self._efficiency_on = False
        self.findings["efficiency_drop"] = Finding(None, RESTARTED)
        self._dirty = True
        await self.async_save()
        self._notify()

    def _check_stuck(self, now: datetime) -> None:
        """Running time per counter since it last rose; repair issues for
        stuck counters and long unavailable sources."""
        elapsed = (now - self._last_tick).total_seconds() if self._last_tick else 0.0
        self._last_tick = now
        mode = self.tracker.mode
        if self.tracker.compressor and elapsed > 0:
            if self.has_activity and mode is not None:
                keys = [
                    s.value
                    for s in (HEAT_SIGNALS[mode], ELEC_SIGNALS[mode], Signal.ELEC_TOTAL)
                    if s in self.counters
                ]
            else:
                keys = (
                    ["heat"]
                    if any(s in self.counters for s in HEAT_SIGNALS.values())
                    else []
                )
            for key in keys:
                self._stuck_seconds[key] = self._stuck_seconds.get(key, 0.0) + elapsed
        stuck = []
        for key, seconds in sorted(self._stuck_seconds.items()):
            if key == "heat":
                signals = [s for s in HEAT_SIGNALS.values() if s in self.counters]
            else:
                signals = [Signal(key)]
            coarse = self.template.day_values or any(
                s not in self.decimal for s in signals
            )
            limit = STUCK_COARSE if coarse else STUCK_DECIMAL
            if self.template.previous_day:
                limit = STUCK_PREVIOUS_DAY
            if seconds >= limit.total_seconds():
                stuck.extend(self.entities[s] for s in signals)
        longest = max(self._stuck_seconds.values(), default=0.0)
        self._set_issue("counter_stuck", stuck, hours=f"{longest / 3600:.1f}")
        unavailable = sorted(
            entity_id
            for entity_id, since in self._unavailable_since.items()
            if now - since >= UNAVAILABLE_LIMIT
        )
        self._set_issue(
            "source_unavailable",
            unavailable,
            minutes=str(int(UNAVAILABLE_LIMIT.total_seconds() // 60)),
        )

    def _write_diary(self, now: datetime) -> None:
        """One entry for the day that just ended (health check, Stufe 3)."""
        day = (now.astimezone(self.tz) - timedelta(days=1)).date().isoformat()
        if self.diary and self.diary[-1].get("day") == day:
            return
        stats = self.cycles("yesterday", now)
        start, end = self.window("yesterday", now)
        seconds = activity_seconds(self.runs, self.tracker.open_run, start, end, now)
        energy = self.marks.energy(Period.YESTERDAY, self.totals)
        split = disinfection_split(
            self.charges,
            start,
            end,
            threshold=self.disinfection_temp,
            min_electricity=self.min_electricity,
        )
        self.diary.append(
            {
                "day": day,
                "outdoor": None
                if self.outdoor.value is None
                else round(self.outdoor.value, 1),
                "starts": stats.starts,
                "run_seconds": round(stats.runtime_seconds),
                "activity_seconds": {k: round(v) for k, v in seconds.items()},
                "short_runs": stats.short_runs,
                "defrosts": stats.defrosts,
                "defrost_seconds": round(stats.defrost_seconds),
                "spread": self.spread.as_dict(),
                "flow": self.flow.as_dict(),
                "flow_rate": self.flow_rate.as_dict(),
                # Late sources (hourly statistics, previous-day values)
                # have not booked the day yet at midnight.
                "energy": None
                if energy is None or self.hourly or self.template.previous_day
                else {k: round(v, 3) for k, v in energy.values.items() if v},
                # Normal hot water charges, for a comparison with last year.
                "charges": {
                    "count": split.normal.count,
                    "heat_kwh": round(split.normal.heat_kwh, 3),
                    "input_kwh": round(
                        split.normal.electricity_kwh + split.normal.aux_kwh, 3
                    ),
                    "disinfections": split.disinfection.count,
                }
                if self.has_charges
                else None,
            }
        )
        del self.diary[:-DIARY_DAYS]

    def _judge_spread(self) -> None:
        """At midnight: was yesterday's spread while heating negative?"""
        if self.spread.seconds < SWAPPED_MIN_SECONDS or self.spread.value is None:
            return  # too little heating: keep the last verdict
        value = round(self.spread.value, 1)
        self._swapped = value if value < SWAPPED_SPREAD_K else None
        self._dirty = True

    def _verdict_entities(self) -> dict[str, str | None]:
        return {
            "activity": self.entities.get(Signal.ACTIVITY),
            "flow": self.entities.get(Signal.FLOW_TEMP),
            "return": self.entities.get(Signal.RETURN_TEMP),
            "rate": self.entities.get(Signal.FLOW_RATE),
        }

    def _judge_flow(self) -> None:
        """At midnight: did yesterday's flow fit heat and spread?"""
        if Signal.FLOW_RATE not in self.entities:
            return
        energy = self.marks.energy(Period.YESTERDAY, self.totals)
        heat = 0.0 if energy is None else energy.get(Kind.HEAT, Mode.HEATING)
        found = flow_plausibility(heat, self.spread, self.flow_rate)
        if found.problem is None:
            return  # too little heating: keep the last verdict
        self._flow_verdict = found.evidence if found.problem else None
        self._dirty = True

    def _analysis_due(self, now: datetime) -> bool:
        if (
            self._analysing
            or Signal.OUTDOOR_TEMP not in self.entities
            or "recorder" not in self.hass.config.components
        ):
            return False
        if self._analysis_day is None:
            return now - self._started_at >= ANALYSIS_DELAY
        local = now.astimezone(self.tz)
        return local.date() != self._analysis_day and local.hour >= ANALYSIS_HOUR

    async def async_hourly(
        self, entity_ids: set[str], start: datetime, end: datetime
    ) -> dict[str, dict[datetime, float]]:
        """Hourly change (kWh) of energy entities from the long-term statistics."""
        if not entity_ids or start >= end:
            return {}
        rows = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            end,
            entity_ids,
            "hour",
            {"energy": "kWh"},
            {"change"},
        )
        hourly: dict[str, dict[datetime, float]] = {}
        for entity_id, entity_rows in rows.items():
            for row in entity_rows:
                if (change := row.get("change")) is None:
                    continue
                hour = row["start"]
                if not isinstance(hour, datetime):
                    hour = dt_util.utc_from_timestamp(hour)
                hourly.setdefault(entity_id, {})[hour] = change
        return hourly

    def _source_statistic_ids(self) -> dict[Signal, str]:
        """Statistic id of each energy signal: the template's own (hourly
        statistics of the source), else the entity's."""
        registry = er.async_get(self.hass)
        ids = {}
        for signal in self._energy:
            entity_id = self.entities[signal]
            entry = registry.async_get(entity_id)
            own = (
                self.template.statistic_id(entry.unique_id)
                if entry is not None and entry.platform == self.template.platform
                else None
            )
            ids[signal] = own or entity_id
        return ids

    def _mapping_still_fits(self) -> bool:
        """Whether every configured energy entity is still the same signal
        for its template (Vaillant: the position of a series in the cloud's
        list may change, and with it what an entity measures)."""
        registry = er.async_get(self.hass)
        entries = [
            RegistryEntry(e.entity_id, e.platform, e.unique_id, e.original_name)
            for e in registry.entities.values()
            if e.platform == self.template.platform
        ]
        now_mapped = {
            entity_id: signal
            for match in find(self.template, entries)
            for signal, entity_id in match.entities.items()
        }
        for signal in self._energy:
            entity_id = self.entities[signal]
            entry = registry.async_get(entity_id)
            if entry is None or entry.platform != self.template.platform:
                continue  # chosen by hand: not the template's to judge
            if now_mapped.get(entity_id) not in (None, signal):
                _LOGGER.warning(
                    "%s no longer looks like %s; not booking until reconfigured",
                    entity_id,
                    signal,
                )
                return False
        return True

    async def _async_book_hours(self, now: datetime) -> None:
        """Book the hours the source wrote completely since the last time,
        each into the period it belongs to."""
        self._booking = True
        try:
            end = _hour(now)
            start = max(self.booked_until or end, end - HOURLY_CATCH_UP)
            if not self._mapping_still_fits():
                # The cloud reordered its series since the start: stop.
                self._mapping_ok = False
                return
            plausible = await self._async_source_hours(start - HOURLY_LOOKBACK, end)
            hours, next_start = bookable_hours(plausible, start, end)
            booked = by_hour(
                plausible, self.heat_modes, self.template.heat_includes_electricity
            )
            for hour in hours:
                self.totals = self.totals + booked[hour]
                self.marks.book_late(hour, booked[hour])
            if next_start != start or self.booked_until is None:
                self.booked_until = next_start
                self._dirty = True
                self._notify()
        except Exception:  # keep running; the next tick tries again
            _LOGGER.exception("Booking the hourly statistics failed")
        finally:
            self._booking = False

    async def _async_source_hours(
        self, start: datetime, end: datetime
    ) -> HourlyChanges:
        """Hourly changes of the source counters, by signal.

        A counter may also exist under an older id with longer statistics
        (EMS-ESP after a change of its id format): its hours fill in where
        the configured entity has none.
        """
        history: dict[str, list[str]] = self.entry.data.get(CONF_HISTORY, {})
        ids = {
            s: [self._statistic_ids[s], *history.get(self.entities[s], [])]
            for s in self._energy
        }
        rows = await self.async_hourly(
            {i for group in ids.values() for i in group}, start, end
        )
        result: HourlyChanges = {}
        for signal, (primary, *older) in ids.items():
            merged: dict[datetime, float] = {}
            for entity_id in older:
                merged.update(rows.get(entity_id, {}))
            merged.update(rows.get(primary, {}))
            # A sum started anew (meter replaced; mypyllant after a week
            # without a fetch) or more than a heat pump can do in an hour.
            plausible = {
                hour: kwh
                for hour, kwh in merged.items()
                if 0 <= kwh <= MAX_POWER_KW * HOURLY_MARGIN
            }
            if len(plausible) < len(merged):
                self._count(f"hour_rejected:{signal}")
            if plausible:
                result[signal] = plausible
        return result

    # Report for any period.

    @property
    def elec_modes(self) -> list[Mode]:
        """Modes with electricity (own counter or the common one)."""
        return [m for m in Mode if has_elec(self.entities, m)]

    @property
    def modes(self) -> list[Mode]:
        """Modes with a heat counter and electricity."""
        return [m for m in self.elec_modes if HEAT_SIGNALS[m] in self.entities]

    async def async_report(self, start: datetime, end: datetime) -> dict[str, Any]:
        """Figures for [start, end) from the long-term statistics.

        Before the first full hour after setup: source counters (standby
        estimated per hour); from then on: Wärmewacht's own energy sensors.
        """
        hours = await self._async_hours(start, end)
        switch = self._switch()
        total = Totals()
        for totals in hours.values():
            total = total + totals
        months = [
            {
                "month": month,
                **figures(totals, self.min_electricity, self.modes, self.elec_modes),
            }
            for month, totals in by_month(hours, self.tz).items()
        ]
        degrees: dict[str, Any] = {}
        if Signal.OUTDOOR_TEMP in self.entities and Mode.HEATING in self.modes:
            # Whole local days only; a partial first or last day is missing.
            first = start.astimezone(self.tz).date()
            last = (end - timedelta(microseconds=1)).astimezone(self.tz).date()
            days, _, _ = daily_degree_days(
                hours,
                await self.async_outdoor_hours(start, end),
                self.tz,
                first,
                last + timedelta(days=1),
            )
            degrees = {"degree_days": degree_day_figures(days)}
            per_month = degree_days_by_month(days)
            for row in months:
                row["degree_days"] = per_month.get(row["month"])
        return {
            "data_until": dt_util.as_local(max(hours) + timedelta(hours=1)).isoformat()
            if hours
            else None,
            "estimated_until": dt_util.as_local(min(switch, end)).isoformat()
            if start < switch
            else None,
            **figures(total, self.min_electricity, self.modes, self.elec_modes),
            **degrees,
            "months": months,
        }

    def _switch(self) -> datetime:
        """First full hour of Wärmewacht's own energy sensors (never for
        sources with hourly statistics: theirs are exact, ours late)."""
        if self.hourly:
            return datetime.max.replace(tzinfo=dt_util.UTC)
        since = self.since or EARLIEST
        return since.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    async def _async_hours(
        self, start: datetime, end: datetime
    ) -> dict[datetime, Totals]:
        """Energy per hour in [start, end): source counters before the switch
        (standby estimated per hour), own energy sensors after it."""
        switch = self._switch()
        hours: dict[datetime, Totals] = {}
        if self.template.previous_day:
            # The own sensors book a day's total just after the next
            # midnight: a day later, back onto its day.
            own = await self._async_own_hours(max(start, switch) + DAY, end + DAY)
            return {hour - DAY: totals for hour, totals in own.items()}
        if start < switch:
            source = await self._async_source_hours(start, min(end, switch))
            hours.update(
                by_hour(
                    source, self.heat_modes, self.template.heat_includes_electricity
                )
            )
        if end > switch:
            own = await self._async_own_hours(max(start, switch), end)
            for hour, totals in own.items():
                hours[hour] = hours.get(hour, Totals()) + totals
        return hours

    async def _async_rebase(self, period: Period, now: datetime) -> None:
        """Recompute a period from the statistics instead of starting it anew
        now (season start month changed, or a period new in this version)."""
        start = period_start(period, now, self.tz, self.marks.season_month)
        energy = Totals()
        # Hourly statistics: hours from booked_until on are booked by the tick.
        end = self.booked_until if self.hourly and self.booked_until else now
        if start is not None and "recorder" in self.hass.config.components:
            try:
                for totals in (await self._async_hours(start, end)).values():
                    energy = energy + totals
            except Exception:  # keep running; the period then starts now
                _LOGGER.exception(
                    "Recomputing the %s from the statistics failed", period
                )
        self.marks.marks[period] = self.totals - energy
        self.marks.starts[period] = start
        self._dirty = True

    async def _async_own_hours(
        self, start: datetime, end: datetime
    ) -> dict[datetime, Totals]:
        registry = er.async_get(self.hass)
        keys = {
            entity_id: key
            for key in (
                *(f"heat_{m}" for m in Mode),
                *(f"electricity_{m}" for m in Mode),
                "standby",
            )
            if (
                entity_id := registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{self.entry.entry_id}_{key}"
                )
            )
        }
        rows = await self.async_hourly(set(keys), start, end)
        changes: dict[datetime, dict[str, float]] = {}
        for entity_id, values in rows.items():
            for hour, change in values.items():
                changes.setdefault(hour, {})[keys[entity_id]] = change
        return {hour: own_hour(values) for hour, values in changes.items()}

    # State changes.

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        if (state := event.data["new_state"]) is None:
            return
        self._handle(state.entity_id, state, state.last_updated)

    @property
    def has_activity(self) -> bool:
        """Whether an activity is known (entity or flags)."""
        return bool(self._activity_configured)

    @property
    def standby_separable(self) -> bool:
        """Whether standby can be told apart for a metered mode: from its
        heat, or from the compressor with live counters."""
        return any(
            has_elec(self.entities, m)
            and (
                m in self.heat_modes
                or (not self.template.day_values and Signal.COMPRESSOR in self.entities)
            )
            for m in Mode
        )

    @property
    def has_charges(self) -> bool:
        """Hot water charges need the activity and live hot water counters
        (day values arrive too late to belong to a charge)."""
        return (
            self.has_activity
            and not self.template.day_values
            and not self.hourly
            and HEAT_SIGNALS[Mode.DHW] in self.entities
            and has_elec(self.entities, Mode.DHW)
        )

    def charge_split(self, now: datetime) -> DisinfectionSplit:
        """Normal and disinfection charges of the last CHARGE_DAYS days."""
        return disinfection_split(
            self.charges,
            now - timedelta(days=CHARGE_DAYS),
            now + timedelta(seconds=1),
            threshold=self.disinfection_temp,
            min_electricity=self.min_electricity,
        )

    def _finish_charge(self, charge: Charge | None) -> None:
        if charge is None:
            return
        self.charges.append(charge)
        self._update_charge_finding(charge.end or dt_util.utcnow())
        self._dirty = self._history_dirty = True
        self._notify()

    def _update_charge_finding(self, now: datetime) -> None:
        self.findings["aux_dhw_charges"] = aux_dhw_charges(self.charge_split(now))

    def _note_hot(self, at: datetime) -> None:
        """A thermal disinfection starts when the storage reaches the
        threshold; it may start again after cooling down by the release."""
        if (value := self._dhw_temp) is None:
            return
        if value >= self.disinfection_temp and not self._hot:
            self._hot = True
            self.last_disinfection = at
            self._dirty = True
        elif value < self.disinfection_temp - DISINFECTION_RELEASE_K and self._hot:
            self._hot = False
            self._dirty = True

    def _activity_of(
        self, states: dict[Signal, str | None], compressor: bool | None
    ) -> Activity | None:
        """Activity from raw states of the activity entity and its parts."""
        base = (
            self.template.parse_activity(states.get(Signal.ACTIVITY))
            if Signal.ACTIVITY in self._activity_configured
            else None
        )
        return combine(base, states, self._activity_configured, compressor)

    @property
    def _activity_needs_compressor(self) -> bool:
        """Flags only: a run without a flag is heating (activity.combine)."""
        return Signal.ACTIVITY not in self._activity_configured and bool(
            self._activity_configured
        )

    def _apply_activity(
        self, at: datetime, changed: tuple[Signal, str] | None = None
    ) -> None:
        """Work out the activity from the current states and hand it on."""
        current = {
            s: st.state
            for s in self._activity_configured
            if (st := self.hass.states.get(self.entities[s])) is not None
        }
        if changed is not None:
            current[changed[0]] = changed[1]
        activity = self._activity_of(current, self.tracker.compressor)
        if changed is None and activity == self.tracker.activity:
            return
        if (defrost := self.tracker.set_activity(activity, at)) is not None:
            self.defrosts.append(defrost)
            self._dirty = self._history_dirty = True
            self._notify()
        if self.has_charges:
            self._finish_charge(
                self.charge_tracker.set_activity(activity, at, self._dhw_temp)
            )
            self._dirty = True

    def _handle(self, entity_id: str, state: State, at: datetime) -> None:
        signal = self._signal_of.get(entity_id)
        if signal is None:
            return
        if state.state == "unavailable":
            self._unavailable_since.setdefault(entity_id, at)
        else:
            self._unavailable_since.pop(entity_id, None)
        self._note_mode(at)
        self._sample(at)
        if signal in self.counters:
            self._handle_counter(signal, state, at)
        elif signal is Signal.COMPRESSOR:
            on = parse_compressor(state.state)
            had_open = self.tracker.open_run is not None
            run = self.tracker.set_compressor(on, at)
            if not had_open and self.tracker.open_run and self.tracker.open_run.counted:
                self.own_starts += 1
            if run is not None:
                self.runs.append(run)
                self._history_dirty = True
                self.spawn(self.async_save(), "save", cancel=False)
                self._notify()
            if self._activity_needs_compressor:
                self._apply_activity(at)
        elif signal in self._activity_configured:
            if signal is Signal.ACTIVITY and self.template.is_foreign_activity(
                state.state
            ):
                if not self._activity_foreign:
                    self._activity_foreign = self._dirty = True
                self._count("activity:foreign")
            elif (
                signal is Signal.ACTIVITY
                and self.template.parse_activity(state.state) is Activity.OTHER
            ):
                self._count(f"activity:{state.state}")
            self._apply_activity(at, (signal, state.state))
        elif signal is Signal.FLOW_TEMP:
            self._flow_temp = _float(state)
        elif signal is Signal.RETURN_TEMP:
            self._return_temp = _float(state)
        elif signal is Signal.FLOW_RATE:
            value = _float(state)
            try:
                self._flow_rate_lph = (
                    None
                    if value is None
                    else to_lph(value, state.attributes.get(ATTR_UNIT_OF_MEASUREMENT))
                )
            except KeyError:
                self._flow_rate_lph = None
                self._count("unit:flow_rate")
        elif signal is Signal.DHW_TEMP:
            self._dhw_temp = _float(state)
            self.charge_tracker.temperature(self._dhw_temp)
            self._note_hot(at)
        self._sampling = self._sample_condition()

    def _handle_counter(self, signal: Signal, state: State, at: datetime) -> None:
        if (value := _float(state)) is None:
            return
        try:
            kwh = to_kwh(value, state.attributes.get(ATTR_UNIT_OF_MEASUREMENT))
        except KeyError:
            self._count(f"unit:{signal}")
            return
        if kwh != round(kwh):
            self.decimal.add(signal)
        counter = self.counters[signal]
        previous = counter.last_time
        rose = counter.last_value is not None and kwh > counter.last_value
        update = counter.update(kwh, at)
        if rose or update.event is CounterEvent.RESET:
            self._stuck_seconds.pop(signal.value, None)
            if signal in HEAT_SIGNALS.values():
                self._stuck_seconds.pop("heat", None)
        if update.event not in (None, CounterEvent.FIRST):
            self._count(f"{update.event}:{signal}")
        if update.delta <= 0:
            return
        self._book(signal, update.delta, previous, at)
        self._dirty = True

    def _book(
        self, signal: Signal, kwh: float, previous: datetime | None, at: datetime
    ) -> None:
        if signal is Signal.AUX_TOTAL:
            mode = self.tracker.mode or Mode.HEATING
            kind = Kind.AUX
        elif signal is Signal.ELEC_TOTAL:
            # One meter for all modes: the mode running, else heating.
            mode = self.tracker.mode
            if mode is None or not has_elec(self.entities, mode):
                mode = Mode.HEATING
            kind = Kind.ELEC if self._running(mode, previous) else Kind.STANDBY
        elif signal is Signal.ELEC_DEFROST:
            # A defrost serves the mode that ran (Lambda, iDM count it apart).
            mode = self.tracker.mode or Mode.HEATING
            kind = Kind.ELEC
        elif signal is Signal.ELEC_STANDBY:
            mode, kind = Mode.HEATING, Kind.STANDBY
        else:
            mode = MODE_OF[signal]
            if signal in HEAT_SIGNALS.values():
                kind = Kind.HEAT
                self._heat_at[mode] = at
            elif signal in ELEC_SIGNALS.values():
                if self.template.day_values:
                    self._pending.append((mode, kwh, at))
                    return
                kind = Kind.ELEC if self._running(mode, previous) else Kind.STANDBY
            else:
                kind = Kind.AUX
        self._add(kind, mode, kwh, at)
        if mode is Mode.DHW:
            self._set_charge_late()
            self.charge_tracker.add(kind, kwh, at)

    def _set_charge_late(self) -> None:
        """How long a charge takes late energy: longer for whole kWh."""
        coarse = self.resolution(Mode.DHW) >= 1
        self.charge_tracker.late = COARSE_LATE if coarse else LATE

    def _add(self, kind: Kind, mode: Mode, kwh: float, at: datetime) -> None:
        """Book energy that arrived at `at`; a previous-day value goes into
        the previous day (and its month and season)."""
        self.totals.add(kind, mode, kwh)
        if self.template.previous_day:
            day = at.astimezone(self.tz).date() - timedelta(days=1)
            noon = datetime.combine(day, time(12), tzinfo=self.tz)
            booked = Totals()
            booked.add(kind, mode, kwh)
            self.marks.book_late(noon, booked)

    def _resolve_pending(self, now: datetime, final: bool = False) -> None:
        """Book waiting electricity of day values: standby when the same
        fetch brought no heat of its mode (the compressor state cannot tell,
        the values are up to two hours late)."""
        waiting = []
        for mode, kwh, at in self._pending:
            if not final and now - at < PENDING_DELAY:
                waiting.append((mode, kwh, at))
                continue
            if mode not in self.heat_modes:
                # No heat to tell standby from: running electricity.
                self._add(Kind.ELEC, mode, kwh, at)
                self._dirty = True
                continue
            heat_at = self._heat_at.get(mode)
            running = heat_at is not None and heat_at >= at - SAME_FETCH
            if self.template.previous_day and not running:
                # The same day total twice brings no state change: the heat
                # counter itself says whether the day had heat.
                counter = self.counters.get(HEAT_SIGNALS[mode])
                running = bool(counter and (counter.last_value or 0) > 0)
            self._add(Kind.ELEC if running else Kind.STANDBY, mode, kwh, at)
            self._dirty = True
        self._pending = waiting

    def _running(self, mode: Mode, previous: datetime | None) -> bool:
        """Whether electricity of `mode` since `previous` came from a run.

        Standby: the mode delivered no heat and (with a compressor state) the
        compressor did not run in that mode.
        """
        if self._heat_moved(mode, previous):
            return True
        if Signal.COMPRESSOR not in self.entities:
            return HEAT_SIGNALS[mode] not in self.entities
        if not self.tracker.was_running_since(previous):
            return False
        if Signal.ACTIVITY not in self.entities:
            return True
        seen = self._mode_seen.get(mode)
        return seen is not None and (previous is None or seen > previous)

    def _heat_moved(self, mode: Mode, previous: datetime | None) -> bool:
        if (at := self._heat_at.get(mode)) and previous and at > previous:
            return True
        # The heat counter may report its increase a moment later.
        heat_signal = HEAT_SIGNALS[mode]
        counter = self.counters.get(heat_signal)
        state = self.hass.states.get(self.entities.get(heat_signal, ""))
        if counter is None or counter.last_value is None or state is None:
            return False
        if (value := _float(state)) is None:
            return False
        try:
            kwh = to_kwh(value, state.attributes.get(ATTR_UNIT_OF_MEASUREMENT))
        except KeyError:
            return False
        return kwh > counter.last_value + 1e-6

    def _note_mode(self, at: datetime) -> None:
        """Remember until when each mode was active with the compressor on."""
        if self.tracker.compressor and (mode := self.tracker.mode) is not None:
            self._mode_seen[mode] = at

    def _sample_condition(self) -> bool:
        """Compressor heating; without an activity hot water runs would mix in."""
        if Signal.COMPRESSOR in self.entities and not self.tracker.compressor:
            return False
        return self.tracker.activity is Activity.HEATING

    def _sample(self, at: datetime) -> None:
        """Add the time since the last sample to today's means."""
        if self._sample_at is not None and self._sampling and at > self._sample_at:
            seconds = (at - self._sample_at).total_seconds()
            if self._flow_temp is not None:
                self.flow.add(self._flow_temp, seconds)
                if self._return_temp is not None:
                    self.spread.add(self._flow_temp - self._return_temp, seconds)
            if self._flow_rate_lph is not None:
                self.flow_rate.add(self._flow_rate_lph, seconds)
            self._zero_flow.add(self._flow_rate_lph, seconds)
        self._sample_at = at

    def _count(self, key: str) -> None:
        self.events[key] = self.events.get(key, 0) + 1

    # Minute tick: period boundaries, sensor updates, throttled saving.

    @callback
    def _on_tick(self, now: datetime) -> None:
        self._note_mode(now)
        self._sample(now)
        self.tracker.tick(now)
        self._set_charge_late()
        self._finish_charge(self.charge_tracker.tick(now))
        # Before a period boundary, book all waiting electricity in the period
        # its heat went to.
        self._resolve_pending(now, final=self.marks.due(now))
        if now - self._started_at >= ISSUE_GRACE:
            self._check_issues()
            self._check_stuck(now)
        else:
            self._last_tick = now
        if (entity_id := self.entities.get(Signal.OUTDOOR_TEMP)) and (
            value := _float(self.hass.states.get(entity_id))
        ) is not None:
            self.outdoor.add(value, 60)
        if (
            self.hourly
            and now.minute % 10 == 2
            and not self._booking
            and self._mapping_ok
            and "recorder" in self.hass.config.components
        ):
            self.spawn(self._async_book_hours(now), "book_hours")
        if self._analysis_due(now):
            self.spawn(self._async_refresh_analysis(now), "analysis")
        if self._counter_check_due(now):
            self._counter_check_day = now.astimezone(self.tz).date()
            self.spawn(self._async_check_counters(), "counter_kinds")
        if (
            self.history_imported
            and not self.history_adjusted
            and not self._adjusting
            and now - self._started_at >= ADJUST_DELAY
            and "recorder" in self.hass.config.components
        ):
            self.spawn(self._async_adjust_history(), "adjust_history", cancel=False)
        day_changed = self.marks.starts.get(Period.TODAY) != period_start(
            Period.TODAY, now, self.tz, self.marks.season_month
        )
        if self.marks.rollover(now, self.totals):
            if day_changed:
                self._write_diary(now)
                self._judge_spread()
                self._judge_flow()
            self.spread, self.flow, self.outdoor = Mean(), Mean(), Mean()
            self.flow_rate = Mean()
            prune(self.runs, self.defrosts, now - timedelta(days=HISTORY_DAYS))
            prune_charges(self.charges, now - timedelta(days=HISTORY_DAYS))
            if self.has_charges:
                self._update_charge_finding(now)
            self._dirty = self._history_dirty = True
            self.spawn(self.async_save(), "save", cancel=False)
        elif self._dirty and (
            self._saved_at is None
            or (now - self._saved_at).total_seconds() >= SAVE_INTERVAL_SECONDS
        ):
            self.spawn(self.async_save(), "save", cancel=False)
        self._notify()

    # Repair issues: a source entity is gone or reports an unusable unit.

    def _check_issues(self) -> None:
        missing, wrong_unit = [], []
        for signal, entity_id in sorted(self.entities.items()):
            state = self.hass.states.get(entity_id)
            if state is None:
                missing.append(entity_id)
            elif (
                signal in self.counters
                and state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) not in UNIT_FACTORS
            ):
                wrong_unit.append(entity_id)
        self._set_issue("missing_entity", missing)
        self._set_issue("energy_unit", wrong_unit)
        stale = (
            self.hourly
            and self.booked_until is not None
            and dt_util.utcnow() - self.booked_until > HOURLY_STALE
        )
        energy = [self.entities[s] for s in self._energy]
        self._set_issue("energy_stale", energy[:1] if stale else [])
        self._set_issue(
            "source_changed",
            [] if self._mapping_ok else energy,
        )
        flow = self.entities.get(Signal.FLOW_RATE)
        verdict = self._flow_verdict or {}
        self._set_issue(
            "flow_implausible",
            [flow] if flow and self._flow_verdict else [],
            measured=str(verdict.get("measured_lph", "")),
            expected=str(verdict.get("expected_lph", "")),
        )
        self._set_issue(
            "flow_zero",
            [flow] if flow and self._zero_flow.problem else [],
            minutes=str(round(self._zero_flow.seconds / 60)),
        )
        activity = self.entities.get(Signal.ACTIVITY)
        self._set_issue(
            "activity_foreign",
            [activity] if activity and self._activity_foreign else [],
        )
        swapped = self._swapped is not None and all(
            s in self.entities for s in (Signal.FLOW_TEMP, Signal.RETURN_TEMP)
        )
        self._set_issue(
            "flow_return_swapped",
            [self.entities[Signal.FLOW_TEMP], self.entities[Signal.RETURN_TEMP]]
            if swapped
            else [],
            spread=f"{abs(self._swapped or 0.0):.1f}" if swapped else "",
        )

    def _set_issue(self, key: str, entity_ids: list[str], **placeholders: str) -> None:
        if self._stopped:
            return  # unloaded or removed: the next runtime decides
        issue_id = f"{self.entry.entry_id}_{key}"
        text = ", ".join(entity_ids)
        # The first call after a (re)load always writes: the registry may
        # still hold the issue of the previous runtime (fixed under
        # Reconfigure, which reloads the entry).
        if self._issues.get(issue_id) == text:
            return
        if entity_ids:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=key,
                translation_placeholders={
                    "name": self.entry.title,
                    "entities": text,
                    **placeholders,
                },
            )
            self._issues[issue_id] = text
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            self._issues[issue_id] = ""

    # Figures for the entities.

    def energy(self, period: Period) -> Totals | None:
        return self.marks.energy(period, self.totals)

    def resolution(self, *modes: Mode) -> float:
        """Step of the coarsest counter of the modes, in kWh."""
        if self.hourly:
            return 0.01  # unrounded hourly statistics
        signals = [
            s
            for m in modes
            for s in (HEAT_SIGNALS[m], ELEC_SIGNALS[m], Signal.ELEC_TOTAL)
        ]
        coarse = any(s in self.entities and s not in self.decimal for s in signals)
        return 1.0 if coarse else 0.01

    def reliable(self, totals: Totals, *modes: Mode) -> bool:
        """Whether rounding of the counters stays within 5 % of the electricity."""
        return totals.electricity(*modes) >= RELIABLE_STEPS * self.resolution(*modes)

    def _local_day(self, now: datetime, offset: int = 0) -> datetime:
        today = now.astimezone(self.tz).date()
        return local_midnight(date.fromordinal(today.toordinal() + offset), self.tz)

    def window(self, name: str, now: datetime) -> tuple[datetime, datetime]:
        """[start, end) in UTC of today, yesterday, week (7 days) or month."""
        tomorrow = self._local_day(now, 1)
        if name == "yesterday":
            return self._local_day(now, -1), self._local_day(now)
        if name == "week":
            return self._local_day(now, -6), tomorrow
        if name == "month":
            start = period_start(Period.MONTH, now, self.tz, self.marks.season_month)
            return start or tomorrow, tomorrow
        return self._local_day(now), tomorrow

    def cycles(self, name: str, now: datetime | None = None) -> CycleStats:
        now = now or dt_util.utcnow()
        start, end = self.window(name, now)
        return cycle_stats(
            self.runs,
            self.tracker.open_run,
            self.defrosts,
            self.tracker.open_defrost,
            start,
            end,
            now,
            short_seconds=self.short_seconds,
            critical_seconds=self.critical_seconds,
        )

    def starts_total(self) -> tuple[int | None, str]:
        """Starts since commissioning (counter of the heat pump) or since setup."""
        if entity_id := self.entities.get(Signal.STARTS_TOTAL):
            value = _float(self.hass.states.get(entity_id))
            return (int(value) if value is not None else None), "heat_pump"
        return self.own_starts, "since_setup"

    def cycling_problem(self, now: datetime | None = None) -> dict[str, Any]:
        """Conspicuous cycling within the last 24 hours."""
        now = now or dt_util.utcnow()
        start = now - timedelta(days=1)
        stats = cycle_stats(
            self.runs,
            self.tracker.open_run,
            [],
            None,
            start,
            now + timedelta(seconds=1),
            now,
            short_seconds=self.short_seconds,
            critical_seconds=self.critical_seconds,
        )
        per_hour = max_starts_per_hour(self.runs, self.tracker.open_run, start, now)
        return {
            "problem": per_hour > self.starts_per_hour
            or stats.critical_runs >= CRITICAL_RUNS_PER_DAY,
            "max_starts_per_hour": per_hour,
            "critical_runs_24h": stats.critical_runs,
            "short_runs_24h": stats.short_runs,
        }

    # Storage.

    def as_dict(self) -> dict[str, Any]:
        return {
            "saved_at": dt_util.utcnow().isoformat(),
            "since": self.since.isoformat() if self.since else None,
            "history_imported": self.history_imported,
            "history_adjusted": self.history_adjusted,
            "counters": {s.value: c.as_dict() for s, c in self.counters.items()},
            "tracker": self.tracker.as_dict(),
            "totals": self.totals.as_dict(),
            "marks": self.marks.as_dict(),
            "own_starts": self.own_starts,
            "spread": self.spread.as_dict(),
            "flow": self.flow.as_dict(),
            "events": dict(self.events),
            "decimal": sorted(s.value for s in self.decimal),
            # Electricity of a fetch still waiting for its heat (day values).
            "pending": [[m.value, kwh, at.isoformat()] for m, kwh, at in self._pending],
            "heat_at": {m.value: at.isoformat() for m, at in self._heat_at.items()},
            "efficiency_on": self._efficiency_on,
            "comparison_reset_at": _iso(self.comparison_reset_at),
            "starts_seen": (
                [*self._starts_seen[:2], self._starts_seen[2].isoformat()]
                if self._starts_seen
                else None
            ),
            "stuck_seconds": {k: round(v) for k, v in self._stuck_seconds.items()},
            "outdoor": self.outdoor.as_dict(),
            "charge": self.charge_tracker.as_dict(),
            "last_disinfection": _iso(self.last_disinfection),
            "hot": self._hot,
            "swapped": self._swapped,
            "activity_foreign": self._activity_foreign,
            "verdict_entities": self._verdict_entities(),
            "backfill_until": _iso(self.backfill_until),
            "booked_until": _iso(self.booked_until),
            "flow_rate": self.flow_rate.as_dict(),
            "flow_verdict": self._flow_verdict,
            "zero_flow_seconds": round(self._zero_flow.seconds),
        }

    def _restore(self, data: dict[str, Any]) -> None:
        saved_at = (
            dt_util.parse_datetime(data.get("saved_at") or "") or dt_util.utcnow()
        )
        since = data.get("since")
        self.since = dt_util.parse_datetime(since) if since else None
        self.history_imported = data.get("history_imported", False)
        self.history_adjusted = data.get("history_adjusted", False)
        for key, counter in data.get("counters", {}).items():
            if (signal := Signal(key)) in self.counters:
                self.counters[signal].restore(counter)
        self.tracker.restore(data.get("tracker", {}), saved_at)
        self.totals = Totals.from_dict(data.get("totals"))
        self.marks.restore(data.get("marks", {}))
        self.own_starts = data.get("own_starts", 0)
        self.spread = Mean.from_dict(data.get("spread"))
        self.flow = Mean.from_dict(data.get("flow"))
        self.events = dict(data.get("events", {}))
        self.decimal = {Signal(s) for s in data.get("decimal", [])}
        self._pending = [
            (Mode(m), kwh, datetime.fromisoformat(at))
            for m, kwh, at in data.get("pending", [])
        ]
        self._heat_at = {
            Mode(m): datetime.fromisoformat(at)
            for m, at in data.get("heat_at", {}).items()
        }
        self._efficiency_on = data.get("efficiency_on", False)
        if seen := data.get("starts_seen"):
            self._starts_seen = (seen[0], int(seen[1]), datetime.fromisoformat(seen[2]))
        reset = data.get("comparison_reset_at")
        self.comparison_reset_at = datetime.fromisoformat(reset) if reset else None
        self._stuck_seconds = {
            k: float(v) for k, v in data.get("stuck_seconds", {}).items()
        }
        self.outdoor = Mean.from_dict(data.get("outdoor"))
        self.charge_tracker.restore(data.get("charge", {}), saved_at, dt_util.utcnow())
        last = data.get("last_disinfection")
        self.last_disinfection = datetime.fromisoformat(last) if last else None
        self._hot = data.get("hot", False)
        self._swapped = data.get("swapped")
        self._activity_foreign = data.get("activity_foreign", False)
        self.flow_rate = Mean.from_dict(data.get("flow_rate"))
        self._flow_verdict = data.get("flow_verdict")
        self._zero_flow.seconds = float(data.get("zero_flow_seconds", 0.0))
        backfill = data.get("backfill_until")
        self.backfill_until = datetime.fromisoformat(backfill) if backfill else None
        # Verdicts made for other entities (reconfigured since) are dropped.
        before = data.get("verdict_entities")
        if before is not None:
            now_ids = self._verdict_entities()
            if before.get("activity") != now_ids["activity"]:
                self._activity_foreign = False
            if any(before.get(k) != now_ids[k] for k in ("flow", "return")):
                self._swapped = None
            if any(before.get(k) != now_ids[k] for k in ("flow", "return", "rate")):
                self._flow_verdict = None
                self._zero_flow.seconds = 0.0
        booked = data.get("booked_until")
        self.booked_until = datetime.fromisoformat(booked) if booked else None

    def history_dict(self) -> dict[str, Any]:
        return {
            "runs": [r.as_dict() for r in self.runs],
            "defrosts": [d.as_dict() for d in self.defrosts],
            "diary": self.diary,
            "charges": [c.as_dict() for c in self.charges],
        }

    def _restore_history(self, data: dict[str, Any]) -> None:
        self.runs = [Run.from_dict(r) for r in data.get("runs", [])]
        self.defrosts = [Defrost.from_dict(d) for d in data.get("defrosts", [])]
        self.diary = list(data.get("diary", []))
        self.charges = [Charge.from_dict(c) for c in data.get("charges", [])]

    async def async_save(self) -> None:
        self._saved_at = dt_util.utcnow()
        self._dirty = False
        await self._store.async_save(self.as_dict())
        if self._history_dirty:
            self._history_dirty = False
            await self._history_store.async_save(self.history_dict())
