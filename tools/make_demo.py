#!/usr/bin/env python3
"""Build the data of the demo (docs/demo/): a made-up heat pump, real logic.

Usage (from the repo root):
    uv run tools/make_demo.py

Everything here is invented: the weather, two houses with an air/water heat
pump of 8 kW (no vendor) and a third house that still heats with gas. A
small simulation runs the heat pump minute by minute from 1 July 2024:
heating demand from the outdoor temperature, a buffer with hysteresis,
hot water charges when the storage cools down, defrosts around 0 °C. It
yields what a source integration would report: energy counters, compressor
state, activity, temperatures and a start counter.

These signals go through the integration's own pure modules, as in Home
Assistant: RunTracker and ChargeTracker, PeriodMarks, the look-back of
backfill.py before the setup, cycling, curve, heat_load, heating_curve,
degree_days, costs, report, health and health_extra, and gas.analyse.

Rebuilt here, because they live in runtime.py next to Home Assistant:
- the booking of electricity as running or standby (`_book`/`_running`),
  per simulated step instead of per counter reading;
- the daily diary (`_write_diary`) the health rules read;
- the daily analysis (`_async_refresh_analysis`) and the hourly energy it
  reads (`_async_hours`: source counters before the setup, own sensors after);
- "Auffälliges Takten" (`cycling_problem`), the counting of status texts
  (`_note_status`, here none: the source reports only modes) and the sensor
  values and attributes of sensor.py and binary_sensor.py.
"""

from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from custom_components.waermewacht.activity import combine  # noqa: E402
from custom_components.waermewacht.averages import Mean  # noqa: E402
from custom_components.waermewacht.backfill import by_hour, energy_between  # noqa: E402
from custom_components.waermewacht.carnot import (  # noqa: E402
    EfficiencyFactor,
    FactorDay,
    efficiency_factor,
    factor_attributes,
    factor_spans,
    statistics_days,
)
from custom_components.waermewacht.charges import (  # noqa: E402
    Charge,
    ChargeTracker,
    DisinfectionSplit,
    charge_ratio,
    disinfection_split,
)
from custom_components.waermewacht.charges import prune as prune_charges  # noqa: E402
from custom_components.waermewacht.const import (  # noqa: E402
    DEFAULT_CRITICAL_RUN_MINUTES,
    DEFAULT_MIN_ELECTRICITY_KWH,
    DEFAULT_SEASON_START_MONTH,
    DEFAULT_SHORT_RUN_MINUTES,
    DEFAULT_STARTS_PER_HOUR,
    HISTORY_DAYS,
)
from custom_components.waermewacht.costs import (  # noqa: E402
    BOILER_EFFICIENCY_HS,
    CostComparison,
    compare_with_gas,
)
from custom_components.waermewacht.curve import (  # noqa: E402
    curve_as_dicts,
    daily_samples,
    performance_curve,
)
from custom_components.waermewacht.cycling import (  # noqa: E402
    PROJECTION_DAYS,
    CycleStats,
    activity_seconds,
    cycle_stats,
    cycling_triggers,
    max_starts_per_hour,
    prune,
    starts_projection,
)
from custom_components.waermewacht.degree_days import (  # noqa: E402
    change_percent,
    daily_degree_days,
    degree_days,
    year_before,
)
from custom_components.waermewacht.duty import (  # noqa: E402
    choose,
    day_classes,
    duty_attributes,
    duty_figures,
    duty_value,
    expected_continuous_below,
)
from custom_components.waermewacht.energy import (  # noqa: E402
    Kind,
    Totals,
    building_hours,
    combined_ratio,
    heat_pump_share,
    mode_ratio,
)
from custom_components.waermewacht.gas import analyse as analyse_gas  # noqa: E402
from custom_components.waermewacht.gas import window as gas_window  # noqa: E402
from custom_components.waermewacht.health import (  # noqa: E402
    AUX_KWH,
    BASIS_LIFT,
    Finding,
    aux_dhw_charges,
    aux_mild_weather,
    baseline_drop,
    dhw_efficiency_drop,
    lift_days,
    status,
    window_days,
)
from custom_components.waermewacht.health_extra import (  # noqa: E402
    compare_defrost_classes,
    defrost_classes,
    defrost_figures,
    oversizing,
    spread_figure,
    standby_rise,
)
from custom_components.waermewacht.heat_load import (  # noqa: E402
    CURRENT_SEASON,
    PREVIOUS_SEASON,
    choose_season,
    heat_load,
    heat_load_as_dict,
)
from custom_components.waermewacht.heating_curve import (  # noqa: E402
    flow_curve,
    flow_curve_as_dict,
)
from custom_components.waermewacht.model import Activity, Mode, Signal  # noqa: E402
from custom_components.waermewacht.periods import (  # noqa: E402
    Period,
    PeriodMarks,
    local_midnight,
    period_start,
)
from custom_components.waermewacht.report import (  # noqa: E402
    by_month,
    degree_day_figures,
    degree_days_by_month,
    figures,
    own_changes,
    own_hour,
)
from custom_components.waermewacht.runs import Defrost, Run, RunTracker  # noqa: E402
from custom_components.waermewacht.status_messages import (  # noqa: E402
    StatusCounter,
)

OUT = ROOT / "docs" / "demo" / "data"
TRANSLATIONS = ROOT / "custom_components" / "waermewacht" / "translations"
TZ = ZoneInfo("Europe/Berlin")
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)

START = datetime(2024, 7, 1, tzinfo=TZ)  # first statistics of the counters
# Wärmewacht set up after the summer: the look-back before it has hot water
# only. (In heating hours it keeps the minutes of standby as running, which
# would make a cycling unit's previous season look worse than it was.)
SETUP = datetime(2024, 9, 16, 10, 0, tzinfo=TZ)
WEATHER_END = datetime(2026, 11, 2, tzinfo=TZ)
DEVICE = "Beispiel-Wärmepumpe"

# Options as the config flow stores them; all invented.
DESIGN_TEMP = -12.0  # °C, design outdoor temperature
RATED_KW = 7.0  # heating power at A-7/W35 (data sheet)
MIN_KW = 2.4  # smallest heating power (data sheet)
ELECTRICITY_PRICE = 0.29  # €/kWh
GAS_PRICE = 0.11  # €/kWh (Hs)
GAS_BASE_PRICE = 160.0  # € per year
MIN_ELECTRICITY = DEFAULT_MIN_ELECTRICITY_KWH
SHORT_SECONDS = DEFAULT_SHORT_RUN_MINUTES * 60.0
CRITICAL_SECONDS = DEFAULT_CRITICAL_RUN_MINUTES * 60.0
STARTS_PER_HOUR = DEFAULT_STARTS_PER_HOUR
DROP_THRESHOLD = 15.0
AUX_MILD_FROM = 5.0
CRITICAL_RUNS_PER_DAY = 3  # runtime.CRITICAL_RUNS_PER_DAY

# The machine (made up, plausible for an 8 kW air/water monobloc).
STANDBY_KW = 0.016
DEFROST_KW = 1.6  # electricity while defrosting
DEFROST_PULL_KW = 2.0  # heat taken from the heating water while defrosting
RAMP_SECONDS = 120.0  # heat output builds up after a start
PUMP_LPH = 800.0
STORAGE_KWH_PER_K = 0.29  # 250 l
DHW_ON = 44.0  # °C storage: start a charge below
DHW_OFF = 52.0  # °C: end the charge
DHW_SET = 52.0
STARTS_AT_START = 4170  # start counter on 1 July 2024


@dataclass(frozen=True)
class House:
    """A house and how the heat pump is set up in it."""

    ua: float  # kW/K heat loss (with internal gains: limit below 20 °C)
    limit: float  # °C heating limit
    solar_kw: float  # gains at noon on a sunny day
    band_kwh: float  # half the hysteresis of the heating water (buffer)
    min_run: float  # s
    min_off: float  # s


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    house: House
    moment: datetime
    seed: int
    # Hybrid system: below this outdoor temperature a boiler heats instead of
    # the heat pump (bivalent alternative, e.g. Hybrid Manager HM200); hot
    # water stays with the heat pump.
    bivalent: float | None = None


SCENARIOS = [
    # A well set up unit with a buffer: long runs, defrosts around 0 °C.
    Scenario(
        "januar",
        "Kalte Januarwoche, gut eingestellt",
        House(ua=0.165, limit=15.0, solar_kw=1.2, band_kwh=0.6, min_run=600, min_off=900),
        datetime(2026, 1, 22, 17, 40, tzinfo=TZ),
        1,
    ),
    # The same unit in a small, well insulated house without a buffer:
    # far above the heat load, it cycles in mild weather.
    Scenario(
        "herbst",
        "Milder Herbst, zu groß",
        House(ua=0.085, limit=15.0, solar_kw=0.8, band_kwh=0.09, min_run=240, min_off=300),
        datetime(2025, 10, 29, 17, 40, tzinfo=TZ),
        2,
    ),
    # An older, larger house: a boiler takes over below -3 °C.
    Scenario(
        "hybrid",
        "Hybridanlage im Januar",
        House(ua=0.21, limit=16.0, solar_kw=1.0, band_kwh=0.6, min_run=600, min_off=900),
        datetime(2026, 1, 22, 17, 40, tzinfo=TZ),
        3,
        bivalent=-3.0,
    ),
]  # fmt: skip
GAS_MOMENT = datetime(2026, 10, 28, 18, 0, tzinfo=TZ)
GAS_HOUSE = House(ua=0.19, limit=15.5, solar_kw=1.0, band_kwh=0, min_run=0, min_off=0)
GAS_EFFICIENCY = 0.87


# ---- Made-up weather -------------------------------------------------------------


def _hours_of(day: date) -> list[datetime]:
    """UTC hour starts of a local day (23, 24 or 25)."""
    first, last = local_midnight(day, TZ), local_midnight(day + DAY, TZ)
    hours = []
    while first < last:
        hours.append(first)
        first += HOUR
    return hours


def _spell(day: date) -> float:
    """Weather the story needs: frost in Feb 2025, a mild autumn, a cold week."""
    if date(2025, 2, 3) <= day <= date(2025, 2, 11):
        return -6.0
    if date(2025, 10, 16) <= day <= date(2025, 10, 31):
        return 2.5
    if date(2026, 1, 13) <= day <= date(2026, 1, 22):
        return -7.0
    return 0.0


@dataclass
class Weather:
    temps: dict[datetime, float] = field(default_factory=dict)  # UTC hour -> °C
    means: dict[date, float] = field(default_factory=dict)
    sun: dict[date, float] = field(default_factory=dict)  # 0 cloudy … 1 sunny
    humid: dict[date, float] = field(default_factory=dict)  # frosting factor
    wind: dict[date, float] = field(default_factory=dict)  # extra heat loss


def weather(rng: random.Random) -> Weather:
    result = Weather()
    offset = wind = 0.0
    day = START.date()
    while day < WEATHER_END.date():
        offset = 0.72 * offset + rng.gauss(0, 1.9)
        sunny = rng.random()
        winter = math.cos(2 * math.pi * (day.timetuple().tm_yday - 18) / 365.25)
        mean = 9.6 - 9.4 * winter + offset + _spell(day)
        amplitude = (2.0 + 3.0 * (1 - winter) / 2) * (0.5 + 0.9 * sunny)
        values = []
        for hour in _hours_of(day):
            local = hour.astimezone(TZ).hour + 0.5
            value = mean + amplitude * math.sin(2 * math.pi * (local - 9) / 24)
            value = round(value + rng.gauss(0, 0.25), 2)
            result.temps[hour] = value
            values.append(value)
        result.means[day] = sum(values) / len(values)
        result.sun[day] = sunny
        result.humid[day] = 0.6 + 0.8 * (1 - sunny)
        wind = 0.5 * wind + rng.gauss(0.0, 0.1)
        result.wind[day] = max(-0.2, wind)
        day += DAY
    return result


def heating_on(w: Weather, day: date, limit: float) -> bool:
    """Summer/winter switch of the controller: the mean of the two days before."""
    before = [w.means.get(day - DAY * n) for n in (1, 2)]
    known = [v for v in before if v is not None]
    return not known or sum(known) / len(known) < limit + 0.5


def demand_kw(house: House, w: Weather, hour: datetime, local_hour: float) -> float:
    """Heat the house needs now (kW): losses minus sun."""
    day = hour.astimezone(TZ).date()
    effective = 0.5 * w.temps[hour] + 0.5 * w.means[day]
    sun = 0.0
    if 8 < local_hour < 17:
        sun = house.solar_kw * w.sun[day] * math.sin(math.pi * (local_hour - 8) / 9)
    loss = house.ua * (1 + w.wind[day]) * (house.limit - effective)
    return max(0.0, loss - sun)


def flow_target(outdoor: float) -> float:
    """Heating curve of the made-up installation (underfloor heating)."""
    return min(45.0, max(25.0, 27.0 + 0.4 * (15.0 - outdoor)))


def p_min(outdoor: float) -> float:
    return max(MIN_KW * 0.9, MIN_KW + 0.07 * (outdoor - 2.0))


def p_max(outdoor: float) -> float:
    return RATED_KW + 0.13 * (outdoor + 7.0)


def cop_heating(outdoor: float, flow: float) -> float:
    hot, cold = flow + 2.0 + 273.15, outdoor - 5.0 + 273.15
    return min(6.5, 0.52 * hot / max(hot - cold, 8.0))


def cop_dhw(outdoor: float, storage: float) -> float:
    hot, cold = storage + 8.0 + 273.15, outdoor - 6.0 + 273.15
    return min(4.2, 0.55 * hot / max(hot - cold, 8.0))


def defrost_interval(outdoor: float) -> float | None:
    """Run minutes between defrosts on an average day; None: no frost."""
    if outdoor > 7.0 or outdoor < -15.0:
        return None
    return 50.0 + 3.5 * (outdoor - 1.0) ** 2


def draws(rng: random.Random, day: date) -> list[tuple[float, float, float]]:
    """Hot water drawn on a day: (local hour, duration h, kWh)."""
    winter = math.cos(2 * math.pi * (day.timetuple().tm_yday - 18) / 365.25)
    f = 1 + 0.12 * winter
    return [
        (6.3 + rng.uniform(-0.4, 0.5), 0.5, 1.7 * f * rng.uniform(0.7, 1.3)),
        (12.4 + rng.uniform(-0.5, 0.5), 0.25, 0.35 * f * rng.uniform(0.5, 1.5)),
        (18.8 + rng.uniform(-0.6, 1.0), 0.9, 2.1 * f * rng.uniform(0.7, 1.3)),
    ]


# ---- The heat pump, minute by minute ---------------------------------------------------


class Sim:
    """Simulate one heat pump and feed what it reports to Wärmewacht's code."""

    def __init__(self, scenario: Scenario, w: Weather) -> None:
        self.sc = scenario
        self.house = scenario.house
        self.w = w
        self.rng = random.Random(scenario.seed)
        self.setup = SETUP.astimezone(UTC)
        self.now = scenario.moment.astimezone(UTC)
        # Machine state.
        self.on = False
        self.mode: Mode | None = None  # heating or dhw while on
        self.defrosting = False
        self.defrost_left = 0.0  # s
        self.frost = 0.0
        self.buf = 0.0  # kWh above the set point of the heating water
        self.storage = 50.0
        self.run_s = 1e9  # since the compressor started
        self.off_s = 1e9  # since it stopped
        self.starts = STARTS_AT_START
        self.heat_kw = self.elec_kw = 0.0
        self.flow = self.ret = 30.0
        self.speed = 0.0
        self.outdoor = 10.0
        self.demand = 0.0
        self.boiler_kw = 0.0
        self.day_draws: dict[date, list[tuple[float, float, float]]] = {}
        # What the recorder keeps: hourly changes and means.
        self.src: dict[Signal, dict[datetime, float]] = {
            s: {}
            for s in (
                Signal.HEAT_HEATING,
                Signal.HEAT_DHW,
                Signal.ELEC_HEATING,
                Signal.ELEC_DHW,
                Signal.AUX_HEATING,
                Signal.AUX_DHW,
                *(
                    (Signal.BOILER_HEAT_HEATING,)
                    if scenario.bivalent is not None
                    else ()
                ),
            )
        }
        self.own: dict[datetime, dict[str, float]] = {}
        self.flow_hours: dict[datetime, float] = {}
        self.ret_hours: dict[datetime, float] = {}
        self.starts_hours: dict[datetime, int] = {}  # counter at the hour's end
        # Wärmewacht (from the setup on).
        self.tracker = RunTracker()
        self.runs: list[Run] = []
        self.defrosts: list[Defrost] = []
        self.charge_tracker = ChargeTracker()
        self.charges: list[Charge] = []
        self.totals = Totals()
        self.marks = PeriodMarks(TZ, DEFAULT_SEASON_START_MONTH)
        self.diary: list[dict[str, Any]] = []
        self.spread, self.flow_mean, self.outdoor_mean = Mean(), Mean(), Mean()
        self.outdoor_heating = Mean()
        self.started = False
        self.analysis: dict[str, Any] = {}
        self.today: list[dict[str, Any]] = []
        self._sample: dict[str, float] = {}
        self.recording = False
        self.reported: Activity | None = None
        self.activity_changed: datetime | None = None

    # Signals as a source integration reports them.

    @property
    def activity(self) -> Activity:
        if not self.on:
            return Activity.OFF
        if self.defrosting:
            return Activity.DEFROST
        return Activity.DHW if self.mode is Mode.DHW else Activity.HEATING

    def _set_activity(self, at: datetime) -> None:
        if self.activity is not self.reported:
            self.reported, self.activity_changed = self.activity, at
        if not self.started:
            return
        activity = combine(self.activity, {}, {Signal.ACTIVITY})
        if (defrost := self.tracker.set_activity(activity, at)) is not None:
            self.defrosts.append(defrost)
        finished = self.charge_tracker.set_activity(activity, at, self.storage)
        if finished is not None:
            self.charges.append(finished)

    def _set_compressor(self, on: bool, at: datetime) -> None:
        if on and not self.on:
            self.starts += 1
            self.run_s = 0.0
        elif not on and self.on:
            self.off_s = 0.0
        self.on = on
        if not self.started:
            return
        if (run := self.tracker.set_compressor(on, at)) is not None:
            self.runs.append(run)

    def _start(self, mode: Mode, at: datetime) -> None:
        was_on = self.on
        self.mode = mode
        if not was_on:
            self._set_activity_before_start(at)
            self._set_compressor(True, at)
        else:
            self._set_activity(at)

    def _set_activity_before_start(self, at: datetime) -> None:
        # The source reports the new activity together with the compressor.
        self.on = True
        self._set_activity(at)
        self.on = False

    def _stop(self, at: datetime) -> None:
        self._set_compressor(False, at)
        self.mode = None
        self.defrosting, self.defrost_left = False, 0.0
        self._set_activity(at)

    # Control.

    def _boiler(self, heating: bool) -> bool:
        """Whether the boiler heats (hybrid system below the bivalent point)."""
        bivalent = self.sc.bivalent
        return bivalent is not None and heating and self.outdoor < bivalent

    def _decide(self, at: datetime, heating: bool) -> None:
        h = self.house
        if self.defrosting and self.defrost_left <= 1e-6:
            self.defrosting, self.defrost_left = False, 0.0
            self._set_activity(at)
        if self.mode is Mode.DHW and self.storage >= DHW_OFF - 1e-9:
            # The compressor stops after a charge; heating starts again
            # after the pause (heating -> hot water runs on without a stop).
            self._stop(at)
            return
        if self.mode is not Mode.DHW and self.storage <= DHW_ON + 1e-9:
            if self.defrosting:
                return  # after the defrost
            if self.on or self.off_s >= 120:
                self._start(Mode.DHW, at)
            return
        if self.on and self.mode is Mode.HEATING and not self.defrosting:
            if self._boiler(heating):
                self._stop(at)  # the boiler takes over
                return
            if self.frost >= 1.0 - 1e-9:
                minutes = 4.0 + 0.1 * max(0.0, -self.outdoor)
                self.defrosting = True
                self.defrost_left = minutes * 60 * self.rng.uniform(0.85, 1.2)
                self.frost = 0.0
                self._set_activity(at)
                return
            enough = self.buf >= h.band_kwh - 1e-9 or not heating
            if enough and self.run_s >= h.min_run - 1e-9:
                self._stop(at)
            return
        cooled = self.buf <= -h.band_kwh + 1e-9 and self.off_s >= h.min_off - 1e-9
        if not self.on and heating and cooled and not self._boiler(heating):
            self._start(Mode.HEATING, at)

    def _rates(self, heating: bool, draw_kw: float) -> dict[str, float]:
        """Power of everything in the current state (kW, kWh/h)."""
        outdoor, d = self.outdoor, self.demand
        curve = flow_target(outdoor)
        rates = {"buf": -d if heating else 0.0, "storage": -draw_kw / STORAGE_KWH_PER_K}
        # The boiler of a hybrid system covers the demand while it heats.
        self.boiler_kw = d if self._boiler(heating) else 0.0
        if self.boiler_kw:
            rates["buf"] = 0.0
        if not self.on:
            self.heat_kw, self.elec_kw, self.speed = 0.0, STANDBY_KW, 0.0
            self.flow = curve - 2.5 if heating else 24.0
            self.ret = self.flow - 0.3
            return rates
        ramp = min(1.0, self.run_s / RAMP_SECONDS)
        if self.defrosting:
            self.heat_kw, self.elec_kw, self.speed = 0.0, DEFROST_KW, 55.0
            self.flow, self.ret = curve - 4.0, curve - 2.0
            rates["buf"] -= DEFROST_PULL_KW
            return rates
        if self.mode is Mode.DHW:
            power = min(p_max(outdoor) * 0.8, 5.5)
            self.heat_kw = power * ramp
            self.elec_kw = power / cop_dhw(outdoor, self.storage)
            self.speed = 70.0
            self.flow, self.ret = self.storage + 6.0, self.storage + 1.0
            rates["storage"] += self.heat_kw / STORAGE_KWH_PER_K
            return rates
        lo, hi = p_min(outdoor), p_max(outdoor)
        power = min(hi, max(lo, d - self.buf / 1.5))
        # Above the demand the water heats up faster than the floor takes it.
        self.flow = curve + 1.5 * max(0.0, power - d)
        self.ret = self.flow - power * 1000 / (1.163 * PUMP_LPH)
        self.heat_kw = power * ramp
        self.elec_kw = power / cop_heating(outdoor, self.flow)
        self.speed = 25.0 + 65.0 * (power - lo) / max(hi - lo, 0.1)
        rates["buf"] = self.heat_kw - d
        return rates

    def _step(
        self, at: datetime, seconds: float, heating: bool, draw_kw: float
    ) -> float:
        """Advance up to `seconds` or to the next event; returns the time used."""
        h = self.house
        rates = self._rates(heating, draw_kw)
        # Time to the next event; thresholds only count before they are reached.
        times = [seconds]
        if self.on:
            if self.run_s < RAMP_SECONDS:
                times.append(RAMP_SECONDS - self.run_s)
            if self.run_s < h.min_run:
                times.append(h.min_run - self.run_s)
        else:
            for wait in (h.min_off, 120.0):
                if self.off_s < wait:
                    times.append(wait - self.off_s)
        if self.defrosting:
            times.append(self.defrost_left)
        buf_rate, st_rate = rates["buf"], rates["storage"]
        heating_up = self.on and self.mode is Mode.HEATING and buf_rate > 0
        if heating_up and self.buf < h.band_kwh:
            times.append((h.band_kwh - self.buf) / buf_rate * 3600)
        if not self.on and buf_rate < 0 and self.buf > -h.band_kwh:
            times.append((self.buf + h.band_kwh) / -buf_rate * 3600)
        if self.mode is Mode.DHW and st_rate > 0 and self.storage < DHW_OFF:
            times.append((DHW_OFF - self.storage) / st_rate * 3600)
        if self.mode is not Mode.DHW and st_rate < 0 and self.storage > DHW_ON:
            times.append((self.storage - DHW_ON) / -st_rate * 3600)
        frost_rate = 0.0
        interval = defrost_interval(self.outdoor)
        if self.on and self.mode is Mode.HEATING and not self.defrosting and interval:
            humid = self.w.humid[at.astimezone(TZ).date()]
            frost_rate = humid / (interval * 60)
            if self.frost < 1.0:
                times.append((1.0 - self.frost) / frost_rate)
        dt = min(max(min(times), 0.05), seconds)
        self.buf += buf_rate * dt / 3600
        self.storage += st_rate * dt / 3600
        self.frost += frost_rate * dt
        if self.on:
            self.run_s += dt
        else:
            self.off_s += dt
        if self.defrosting:
            self.defrost_left -= dt
        if not heating:
            self.buf = 0.0
        self._book(at, dt)
        return dt

    def _book(self, at: datetime, dt: float) -> None:
        hour = at.replace(minute=0, second=0, microsecond=0)
        heat = self.heat_kw * dt / 3600
        elec = self.elec_kw * dt / 3600
        running = self.on
        mode = self.mode if self.mode is not None else Mode.HEATING
        heat_signal = Signal.HEAT_DHW if mode is Mode.DHW else Signal.HEAT_HEATING
        elec_signal = Signal.ELEC_DHW if mode is Mode.DHW else Signal.ELEC_HEATING
        if heat:
            self.src[heat_signal][hour] = self.src[heat_signal].get(hour, 0.0) + heat
        # The source puts standby into the heating meter (like Bosch, EMS-ESP).
        self.src[elec_signal][hour] = self.src[elec_signal].get(hour, 0.0) + elec
        self.flow_hours[hour] = self.flow_hours.get(hour, 0.0) + self.flow * dt / 3600
        self.ret_hours[hour] = self.ret_hours.get(hour, 0.0) + self.ret * dt / 3600
        boiler = self.boiler_kw * dt / 3600
        if boiler:
            signal = Signal.BOILER_HEAT_HEATING
            self.src[signal][hour] = self.src[signal].get(hour, 0.0) + boiler
        if self.recording:
            sample = self._sample
            sample["heat"] = sample.get("heat", 0.0) + heat
            sample["elec"] = sample.get("elec", 0.0) + elec
        if not self.started:
            return
        # runtime._book/_running: electricity is running when the compressor
        # ran in its mode, else standby (booked to heating).
        own = self.own.setdefault(hour, {})
        if boiler:
            self.totals.add(Kind.BOILER, Mode.HEATING, boiler)
            own["boiler_heat_heating"] = own.get("boiler_heat_heating", 0.0) + boiler
        if heat:
            self.totals.add(Kind.HEAT, mode, heat)
            key = f"heat_{mode}"
            own[key] = own.get(key, 0.0) + heat
        if running:
            self.totals.add(Kind.ELEC, mode, elec)
            key = f"electricity_{mode}"
        else:
            self.totals.add(Kind.STANDBY, Mode.HEATING, elec)
            key = "standby"
        own[key] = own.get(key, 0.0) + elec
        if mode is Mode.DHW and running:
            self.charge_tracker.add(Kind.HEAT, heat, at)
            self.charge_tracker.add(Kind.ELEC, elec, at)
        if running and self.activity is Activity.HEATING:
            self.flow_mean.add(self.flow, dt)
            self.spread.add(self.flow - self.ret, dt)

    def _draw_kw(self, local: datetime) -> float:
        day = local.date()
        if day not in self.day_draws:
            self.day_draws[day] = draws(self.rng, day)
        x = local.hour + local.minute / 60
        kw = 0.05  # storage losses
        for start, length, kwh in self.day_draws[day]:
            if start <= x < start + length:
                kw += kwh / length
        return kw

    # Wärmewacht's minute tick and midnight (runtime._on_tick, rebuilt).

    def _begin(self, at: datetime) -> None:
        """Setup: the look-back from the statistics, then live."""
        self.started = True
        self.marks.initialize(
            at, lambda start: energy_between(self.src, start, at, tuple(Mode))
        )
        self.tracker.set_compressor(self.on, at)
        self._set_activity(at)

    def _tick(self, at: datetime) -> None:
        self.tracker.tick(at)
        if (charge := self.charge_tracker.tick(at)) is not None:
            self.charges.append(charge)
        self.charge_tracker.temperature(self.storage)
        day_changed = self.marks.starts.get(Period.TODAY) != period_start(
            Period.TODAY, at, TZ, self.marks.season_month
        )
        if self.marks.rollover(at, self.totals):
            if day_changed:
                self._write_diary(at)
            self.spread, self.flow_mean, self.outdoor_mean = Mean(), Mean(), Mean()
            self.outdoor_heating = Mean()
            prune(self.runs, self.defrosts, at - timedelta(days=HISTORY_DAYS))
            prune_charges(self.charges, at - timedelta(days=HISTORY_DAYS))
        self.outdoor_mean.add(self.outdoor, 60)
        if self.on and self.activity is Activity.HEATING:
            self.outdoor_heating.add(self.outdoor, 60)
        local = at.astimezone(TZ)
        if (
            local.date() == self.sc.moment.date()
            and local.hour == 3
            and local.minute == 0
        ):
            self.analysis = self._analyse(at)

    def window(self, name: str, now: datetime) -> tuple[datetime, datetime]:
        today = now.astimezone(TZ).date()
        tomorrow = local_midnight(today + DAY, TZ)
        if name == "yesterday":
            return local_midnight(today - DAY, TZ), local_midnight(today, TZ)
        if name == "week":
            return local_midnight(today - 6 * DAY, TZ), tomorrow
        if name == "month":
            return local_midnight(today.replace(day=1), TZ), tomorrow
        return local_midnight(today, TZ), tomorrow

    def cycles(self, name: str, now: datetime) -> CycleStats:
        start, end = self.window(name, now)
        return cycle_stats(
            self.runs,
            self.tracker.open_run,
            self.defrosts,
            self.tracker.open_defrost,
            start,
            end,
            now,
            short_seconds=SHORT_SECONDS,
            critical_seconds=CRITICAL_SECONDS,
        )

    def charge_split(self, now: datetime) -> DisinfectionSplit:
        return disinfection_split(
            self.charges,
            now - timedelta(days=30),
            now + timedelta(seconds=1),
            min_electricity=MIN_ELECTRICITY,
        )

    def _write_diary(self, now: datetime) -> None:
        """runtime._write_diary, rebuilt."""
        day = (now.astimezone(TZ) - DAY).date().isoformat()
        stats = self.cycles("yesterday", now)
        start, end = self.window("yesterday", now)
        seconds = activity_seconds(self.runs, self.tracker.open_run, start, end, now)
        energy = self.marks.energy(Period.YESTERDAY, self.totals)
        split = disinfection_split(
            self.charges, start, end, min_electricity=MIN_ELECTRICITY
        )
        outdoor = self.outdoor_mean.value
        self.diary.append(
            {
                "day": day,
                "outdoor": None if outdoor is None else round(outdoor, 1),
                "starts": stats.starts,
                "run_seconds": round(stats.runtime_seconds),
                "activity_seconds": {k: round(v) for k, v in seconds.items()},
                "short_runs": stats.short_runs,
                "defrosts": stats.defrosts,
                "defrost_seconds": round(stats.defrost_seconds),
                "spread": self.spread.as_dict(),
                "flow": self.flow_mean.as_dict(),
                "flow_rate": Mean().as_dict(),
                "outdoor_heating": self.outdoor_heating.as_dict(),
                "classes": day_classes(
                    self.runs,
                    self.tracker.open_run,
                    {h: v for h, v in self.w.temps.items() if start <= h < end},
                    min(now, end),
                ),
                "energy": None
                if energy is None
                else {k: round(v, 3) for k, v in energy.values.items() if v},
                "charges": {
                    "count": split.normal.count,
                    "heat_kwh": round(split.normal.heat_kwh, 3),
                    "input_kwh": round(split.normal.input_kwh, 3),
                    "disinfections": split.disinfection.count,
                },
            }
        )

    # Hourly data as the recorder has it (runtime._async_hours, rebuilt).

    def hours(self, start: datetime, end: datetime) -> dict[datetime, Totals]:
        """Energy per finished hour in [start, end): the source counters with
        standby estimated per hour before the first full hour after the
        setup, Wärmewacht's own sensors after it."""
        switch = self.setup + HOUR
        source = {
            s: {h: v for h, v in values.items() if start <= h < min(end, switch)}
            for s, values in self.src.items()
        }
        result = by_hour(source, tuple(Mode))
        for hour, changes in self.own.items():
            if max(start, switch) <= hour < end and hour + HOUR <= end:
                result[hour] = result.get(hour, Totals()) + own_hour(changes)
        return {h: t for h, t in result.items() if h + HOUR <= end}

    def outdoor_hours(self, start: datetime, end: datetime) -> dict[datetime, float]:
        return {h: v for h, v in self.w.temps.items() if start <= h and h + HOUR <= end}

    def seasons(self, now: datetime) -> tuple[datetime, datetime]:
        current = period_start(Period.SEASON, now, TZ, DEFAULT_SEASON_START_MONTH)
        assert current is not None
        previous = period_start(
            Period.SEASON, current - DAY, TZ, DEFAULT_SEASON_START_MONTH
        )
        assert previous is not None
        return current, previous

    def efficiency_drop(self, hours, outdoor, flow, now, current, previous):
        """4.1a as runtime._efficiency_drop: the previous season's baseline
        model of the lift against the complete days of the current one."""
        found = statistics_days(
            hours,
            flow,
            {h: v for h, v in self.ret_hours.items() if h in outdoor},
            outdoor,
            TZ,
            with_aux=True,
        )
        days = [d for d, _ in lift_days(found, daily_samples(hours, outdoor, TZ))]
        first, today = current.astimezone(TZ).date(), now.astimezone(TZ).date()
        start = previous.astimezone(TZ).date()
        return baseline_drop(
            [d for d in days if first <= d.day < today],
            [d for d in days if start <= d.day < first],
            basis=BASIS_LIFT,
            threshold=DROP_THRESHOLD,
        )

    def duty(
        self, now: datetime, current: datetime, previous: datetime, load: Any
    ) -> dict[str, Any]:
        """runtime._duty, rebuilt (diary only, no counters)."""
        yesterday = now.astimezone(TZ).date() - DAY
        short = SHORT_SECONDS / 60
        seasons = {
            "current": duty_figures(
                self.diary,
                current.astimezone(TZ).date(),
                yesterday,
                short_minutes=short,
            ),
            "previous": duty_figures(
                self.diary,
                previous.astimezone(TZ).date(),
                current.astimezone(TZ).date() - DAY,
                short_minutes=short,
            ),
        }
        return {
            **seasons,
            "season": choose(seasons["previous"], seasons["current"]),
            "expected_continuous_below": None
            if not (load.sufficient or load.preliminary)
            else expected_continuous_below(
                load.heating_limit, load.slope_kw_per_k, MIN_KW
            ),
            "short_run_minutes": short,
        }

    def efficiency_factors(
        self,
        now: datetime,
        current: datetime,
        previous: datetime,
        statistics: dict[date, FactorDay | str],
    ) -> dict[str, EfficiencyFactor]:
        """runtime._efficiency_factors, rebuilt."""
        yesterday = now.astimezone(TZ).date() - DAY
        month = period_start(Period.MONTH, now, TZ, DEFAULT_SEASON_START_MONTH)
        assert month is not None
        spans = factor_spans(
            current.astimezone(TZ).date(),
            previous.astimezone(TZ).date(),
            month.astimezone(TZ).date(),
            yesterday,
        )
        return {
            name: efficiency_factor(
                self.diary,
                first,
                last,
                min_days=min_days,
                min_electricity=MIN_ELECTRICITY,
                statistics=statistics,
            )
            for name, (first, last, min_days) in spans.items()
        }

    def _analyse(self, now: datetime) -> dict[str, Any]:
        """runtime._async_refresh_analysis and _health_findings, rebuilt."""
        current, previous = self.seasons(now)
        hours = self.hours(previous, now)
        outdoor = self.outdoor_hours(previous, now)

        def window(start: datetime, end: datetime) -> tuple[dict, dict]:
            return (
                {h: t for h, t in hours.items() if start <= h < end},
                {h: v for h, v in outdoor.items() if start <= h < end},
            )

        this_season, last_season = window(current, now), window(previous, current)
        # Heat load, signature and degree days describe the building: with
        # the boiler's heat (runtime.async_building_hours), ratios without.
        building = building_hours(hours, BOILER_EFFICIENCY_HS, ())
        this_building = (
            {h: t for h, t in building.items() if current <= h < now},
            this_season[1],
        )
        last_building = (
            {h: t for h, t in building.items() if previous <= h < current},
            last_season[1],
        )
        curves = {
            "current": curve_as_dicts(
                performance_curve(*this_season, TZ, min_electricity=MIN_ELECTRICITY)
            ),
            "previous": curve_as_dicts(
                performance_curve(*last_season, TZ, min_electricity=MIN_ELECTRICITY)
            ),
        }
        # The last complete season, without a usable one the current so far.
        loads = {
            PREVIOUS_SEASON: heat_load(*last_building, TZ, design_temp=DESIGN_TEMP),
            CURRENT_SEASON: heat_load(*this_building, TZ, design_temp=DESIGN_TEMP),
        }
        load_season = choose_season(loads[PREVIOUS_SEASON], loads[CURRENT_SEASON])
        load = loads[load_season]
        load_window = (
            (current, now) if load_season == CURRENT_SEASON else (previous, current)
        )
        today = now.astimezone(TZ).date()
        first = current.astimezone(TZ).date()
        flow = {h: v for h, v in self.flow_hours.items() if h in outdoor}
        flow_curves = {
            name: flow_curve(
                span[0], {h: v for h, v in flow.items() if s <= h < e}, span[1], TZ
            )
            for name, span, s, e in (
                ("current", this_season, current, now),
                ("previous", last_season, previous, current),
            )
        }
        lo, hi = window_days(today)
        mild_days = [d for d in daily_samples(hours, outdoor, TZ) if lo <= d.day <= hi]
        # Start counter at the season start, from its statistics.
        baseline = max(
            (h for h in self.starts_hours if h + HOUR <= current), default=None
        )
        return {
            "now": now,
            "current": current,
            "previous": previous,
            "curves": curves,
            "heat_load": load,
            "heat_load_season": load_season,
            "heat_load_window": load_window,
            "degree_days": degree_days(*this_building, TZ, first, today),
            "degree_days_previous": degree_days(
                *last_building, TZ, previous.astimezone(TZ).date(), first
            ),
            "degree_days_same_period": degree_days(
                *last_building,
                TZ,
                previous.astimezone(TZ).date(),
                max(previous.astimezone(TZ).date(), year_before(today)),
            ),
            "flow_curves": flow_curves,
            "efficiency_drop": self.efficiency_drop(
                hours, outdoor, flow, now, current, previous
            ),
            "aux_mild_weather": aux_mild_weather(
                mild_days, mild_from=AUX_MILD_FROM, threshold_kwh=AUX_KWH
            ),
            "spread_7d": spread_figure(self.diary, today),
            "duty": self.duty(now, current, previous, load),
            "efficiency_factors": self.efficiency_factors(
                now,
                current,
                previous,
                statistics_days(
                    hours,
                    flow,
                    {h: v for h, v in self.ret_hours.items() if h in outdoor},
                    outdoor,
                    TZ,
                ),
            ),
            "oversize": oversizing(load, RATED_KW, min_kw=MIN_KW),
            "standby_rise": standby_rise(self.diary, today, TZ),
            "dhw_efficiency_drop": dhw_efficiency_drop(
                self.diary, today, min_electricity=MIN_ELECTRICITY
            ),
            "defrost_week": defrost_figures(self.defrosts, outdoor, now - 7 * DAY, now),
            "defrost_classes": compare_defrost_classes(
                defrost_classes(self.diary, first, today - DAY),
                defrost_classes(
                    self.diary, previous.astimezone(TZ).date(), first - DAY
                ),
            ),
            "starts_baseline": None
            if baseline is None
            else (self.starts_hours[baseline], current),
        }

    # Run.

    def run(self) -> None:
        hour = START.astimezone(UTC)
        heating_cache: dict[date, bool] = {}
        while hour < self.now:
            local_start = hour.astimezone(TZ)
            day = local_start.date()
            if day not in heating_cache:
                heating_cache[day] = heating_on(self.w, day, self.house.limit)
            heating = heating_cache[day]
            self.outdoor = self.w.temps[hour]
            for minute in range(60):
                at = hour + timedelta(minutes=minute)
                if at >= self.now:
                    break
                if not self.started and at >= self.setup:
                    self._begin(at)
                if self.started:
                    self._tick(at)
                local = local_start + timedelta(minutes=minute)
                self.recording = local.date() == self.sc.moment.date()
                x = local.hour + minute / 60
                self.demand = demand_kw(self.house, self.w, hour, x)
                draw_kw = self._draw_kw(local)
                used = 0.0
                while used < 60.0 - 1e-6:
                    moment = at + timedelta(seconds=used)
                    self._decide(moment, heating)
                    used += self._step(moment, 60.0 - used, heating, draw_kw)
                if local.date() == self.sc.moment.date() and minute % 5 == 4:
                    self._record_today(at + timedelta(minutes=1))
            self.starts_hours[hour] = self.starts
            hour += HOUR
        self._tick(self.now)

    def _record_today(self, at: datetime) -> None:
        sample, self._sample = self._sample, {}
        self.today.append(
            {
                "t": at.astimezone(TZ).strftime("%H:%M"),
                "heat": round(sample.get("heat", 0.0) * 12, 2),  # kWh in 5 min -> kW
                "elec": round(sample.get("elec", 0.0) * 12, 3),
                "outdoor": round(self.outdoor, 1),
                "flow": round(self.flow, 1),
                "ret": round(self.ret, 1),
                "dhw": round(self.storage, 1),
                "speed": round(self.speed),
                "act": self.activity.value,
            }
        )


# ---- Sensors as sensor.py and binary_sensor.py show them ------------------------------------


def _r(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _minutes(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 60, 1)


def _finding(found: Finding) -> dict[str, Any]:
    state = {True: "on", False: "off", None: "unknown"}[found.problem]
    return {"s": state, "a": found.as_attributes()}


def sensors(sim: Sim) -> tuple[dict[str, Any], dict[str, Any]]:
    """Values and attributes of the entities at the moment of the scenario."""
    now = sim.now
    a = sim.analysis
    result: dict[str, Any] = {}

    def put(
        key: str,
        state: Any,
        unit: str | None = None,
        precision: int | None = None,
        **attributes: Any,
    ) -> None:
        result[key] = {"s": state, "u": unit, "p": precision, "a": attributes}

    scopes = {
        "heating": (
            (Mode.HEATING,),
            lambda t: mode_ratio(t, Mode.HEATING, MIN_ELECTRICITY),
        ),
        "dhw": ((Mode.DHW,), lambda t: mode_ratio(t, Mode.DHW, MIN_ELECTRICITY)),
        "combined": (
            (Mode.HEATING, Mode.DHW),
            lambda t: combined_ratio(t, MIN_ELECTRICITY),
        ),
    }
    for scope, (modes, compute) in scopes.items():
        for period in (
            Period.TODAY,
            Period.YESTERDAY,
            Period.MONTH,
            Period.SEASON,
            Period.TOTAL,
        ):
            totals = sim.marks.energy(period, sim.totals)
            if totals is None:
                put(f"ratio_{scope}_{period}", None, None, 2)
                continue
            attributes: dict[str, Any] = {
                "heat_kwh": round(totals.heat(*modes), 3),
                "electricity_kwh": round(totals.electricity(*modes), 3),
            }
            if scope == "combined":
                attributes["standby_kwh"] = round(totals.standby(), 3)
            start = sim.marks.starts.get(period)
            attributes["period_start"] = (
                start.astimezone(TZ).isoformat() if start else None
            )
            attributes["counter_step_kwh"] = 0.01
            attributes["reliable"] = totals.electricity(*modes) >= 20 * 0.01
            put(f"ratio_{scope}_{period}", _r(compute(totals)), None, 2, **attributes)

    for mode in (Mode.HEATING, Mode.DHW):
        put(f"heat_{mode}", round(sim.totals.get(Kind.HEAT, mode), 1), "kWh", 1)
        elec = sim.totals.get(Kind.ELEC, mode) + sim.totals.get(Kind.AUX, mode)
        put(f"electricity_{mode}", round(elec, 1), "kWh", 1)
    rise = a["standby_rise"]
    put(
        "standby",
        round(sim.totals.standby(), 1),
        "kWh",
        1,
        rising=rise.problem,
        **rise.as_attributes(),
    )
    put("standby_power_7d", rise.evidence.get("mean_power_w_7d"), "W", 0)
    if sim.sc.bivalent is not None:
        put(
            "boiler_heat_heating",
            round(sim.totals.get(Kind.BOILER, Mode.HEATING), 1),
            "kWh",
            1,
        )
        for period in (Period.MONTH, Period.SEASON):
            totals = sim.marks.energy(period, sim.totals)
            assert totals is not None
            share = heat_pump_share(totals, BOILER_EFFICIENCY_HS, (), Mode.HEATING)
            both = heat_pump_share(
                totals, BOILER_EFFICIENCY_HS, (), Mode.HEATING, Mode.DHW
            )
            start = sim.marks.starts.get(period)
            put(
                f"heat_pump_share_{period}",
                _r(share, 1),
                "%",
                0,
                with_dhw=_r(both, 1),
                boiler_from=None,
                heat_pump_heat_kwh=round(totals.heat(Mode.HEATING), 1),
                boiler_heat_kwh=round(totals.get(Kind.BOILER, Mode.HEATING), 1),
                heat_pump_heat_dhw_kwh=round(totals.heat(Mode.DHW), 1),
                boiler_heat_dhw_kwh=0.0,
                boiler_heat_from_fuel=[],
                boiler_efficiency=None,
                period_start=start.astimezone(TZ).isoformat() if start else None,
            )

    today, yesterday = sim.cycles("today", now), sim.cycles("yesterday", now)
    # Starts per year from the last 7 complete days (runtime.starts_projection).
    local_today = now.astimezone(TZ).date()
    days = [
        local_midnight(local_today - k * DAY, TZ) for k in range(PROJECTION_DAYS, 0, -1)
    ]
    projection = starts_projection(
        sim.runs,
        sim.tracker.open_run,
        days,
        local_midnight(local_today, TZ),
        sim.tracker.observed_since,
        sim.tracker.gaps,
    )
    put("starts_today", today.starts, **projection.as_attributes())
    put("starts_yesterday", yesterday.starts)
    put("starts_total", sim.starts, source="heat_pump")
    baseline = a["starts_baseline"]
    if baseline is not None:
        count = max(sim.starts - baseline[0], 0)
        days = (now - baseline[1]).total_seconds() / 86400
        put(
            "starts_season",
            count,
            since=baseline[1].astimezone(TZ).isoformat(),
            per_day=round(count / days, 1),
        )
    put("runtime_today", 5 * round(today.runtime_seconds / 300), "min", 0)
    for window in ("today", "week", "month"):
        put(
            f"run_minutes_{window}",
            _minutes(sim.cycles(window, now).seconds_per_run),
            "min",
            0,
        )
    put(
        "short_runs_today",
        today.short_runs,
        threshold_minutes=SHORT_SECONDS / 60,
        critical_runs=today.critical_runs,
        critical_threshold_minutes=CRITICAL_SECONDS / 60,
    )
    put("shortest_pause_today", _minutes(today.shortest_pause_seconds), "min", 0)
    put(
        "defrosts_today",
        today.defrosts,
        minutes=_minutes(today.defrost_seconds),
        yesterday=yesterday.defrosts,
        **a["defrost_week"].as_attributes(),
        classes=a["defrost_classes"],
    )
    put("spread_today", _r(sim.spread.value, 1), "K", 1)
    put("flow_temp_today", _r(sim.flow_mean.value, 1), "°C", 1)

    # Costs (sensor._comparison).
    def comparison(period: Period) -> CostComparison:
        totals = sim.marks.energy(period, sim.totals)
        start = sim.marks.starts[period]
        assert totals is not None and start is not None
        return compare_with_gas(
            {start: totals},
            start,
            now,
            TZ,
            electricity_price=ELECTRICITY_PRICE,
            gas_price=GAS_PRICE,
            gas_base_price_per_year=GAS_BASE_PRICE,
        )

    for period in (Period.MONTH, Period.SEASON):
        c = comparison(period)
        start = sim.marks.starts[period]
        assert c.electricity.cost_eur is not None and start is not None
        put(
            f"cost_{period}",
            round(c.electricity.cost_eur + c.electricity_base_cost_eur, 1),
            "€",
            2,
            period_start=start.astimezone(TZ).isoformat(),
            price_source="fixed",
            allocation="none",
        )
    season = comparison(Period.SEASON)
    season_start = sim.marks.starts[Period.SEASON]
    assert season_start is not None
    put(
        "heat_cost_season",
        _r(season.heat_cost_per_kwh, 3),
        "€/kWh",
        3,
        period_start=season_start.astimezone(TZ).isoformat(),
        price_source="fixed",
        allocation="none",
    )
    put(
        "gas_savings_season",
        _r(season.savings_eur, 0),
        "€",
        0,
        period_start=season_start.astimezone(TZ).isoformat(),
        price_source="fixed",
        allocation="none",
        heat_kwh=round(season.heat_kwh, 1),
        heat_pump_cost_eur=_r(season.heat_pump_cost_eur),
        electricity_base_cost_eur=_r(season.electricity_base_cost_eur),
        gas_kwh=round(season.gas_kwh, 1),
        gas_cost_eur=_r(season.gas_cost_eur),
        gas_base_cost_eur=_r(season.gas_base_cost_eur),
        boiler_efficiency=season.boiler_efficiency,
    )

    # Analysis.
    load = a["heat_load"]
    put(
        "performance_curve_heating",
        a["now"].astimezone(TZ).isoformat(),
        current_start=a["current"].astimezone(TZ).isoformat(),
        previous_start=a["previous"].astimezone(TZ).isoformat(),
        current=a["curves"]["current"],
        previous=a["curves"]["previous"],
    )
    sufficient = load.sufficient
    put(
        "heat_load_per_kelvin",
        round(-load.slope_kw_per_k * 1000) if sufficient else None,
        "W/K",
        0,
        start=a["heat_load_window"][0].astimezone(TZ).isoformat(),
        end=a["heat_load_window"][1].astimezone(TZ).isoformat(),
        season=a["heat_load_season"],
        **heat_load_as_dict(load),
    )
    put("heating_limit", _r(load.heating_limit, 1) if sufficient else None, "°C", 1)
    put("heat_load_design", _r(load.standard_kw, 2) if sufficient else None, "kW", 1)
    for key in ("continuous_below", "short_runs_from"):
        put(key, duty_value(a["duty"], key), "°C", 0, **duty_attributes(a["duty"], key))
    factors = a["efficiency_factors"]
    put(
        "efficiency_factor",
        _r(factors["season"].value, 2),
        None,
        2,
        **factor_attributes(factors, ELECTRICITY_PRICE),
    )
    spread_7d = a["spread_7d"]
    put("spread_7d", _r(spread_7d.value, 1), "K", 1, **spread_7d.as_attributes())
    oversize = a["oversize"]
    put("oversize_factor", _r(oversize.factor, 2), None, 2, **oversize.as_attributes())
    flow_now, flow_before = a["flow_curves"]["current"], a["flow_curves"]["previous"]
    flow_attributes = flow_curve_as_dict(flow_now)
    flow_attributes.pop("at_zero")
    put(
        "flow_at_zero",
        _r(flow_now.at_zero, 1),
        "°C",
        1,
        **flow_attributes,
        previous_season=_r(flow_before.at_zero, 1),
        previous_slope=_r(flow_before.slope, 2),
    )
    dd, ddp = a["degree_days"], a["degree_days_previous"]
    dds = a["degree_days_same_period"]
    put(
        "degree_days_season",
        round(dd.degree_days, 1),
        "K·d",
        0,
        base="G20/15",
        days_counted=dd.days_counted,
        days_missing=dd.days_missing,
        days_without_heating=len(dd.days_without_heating),
        degree_days_heating=round(dd.degree_days_heating, 1),
    )
    put(
        "heat_per_degree_day_season",
        _r(dd.kwh_per_degree_day),
        "kWh/K·d",
        2,
        previous_season=_r(ddp.kwh_per_degree_day),
        previous_same_period=_r(dds.kwh_per_degree_day),
        previous_same_period_until=None
        if dds.end <= dds.start
        else (dds.end - DAY).isoformat(),
        change_percent=change_percent(dd.kwh_per_degree_day, dds.kwh_per_degree_day),
    )

    # Hot water (no thermal disinfection on this page).
    last = sim.charges[-1]
    put(
        "ratio_dhw_last_charge",
        _r(charge_ratio(last)),
        None,
        2,
        start=last.start.astimezone(TZ).isoformat(),
        minutes=round(last.seconds(last.end or last.start) / 60),
        heat_kwh=round(last.heat_kwh, 2),
        electricity_kwh=round(last.electricity_kwh, 2),
        start_temp=_r(last.start_dhw_temp, 1),
        max_temp=_r(last.max_dhw_temp, 1),
        uncertain=last.uncertain,
    )
    split = sim.charge_split(now)
    normal = split.normal
    put(
        "ratio_dhw_charges_30d",
        _r(normal.ratio),
        None,
        2,
        charges=normal.count,
        uncertain=normal.uncertain,
        mean_minutes=_r(normal.mean_minutes, 0),
        mean_heat_kwh=_r(normal.mean_heat_kwh),
        mean_lift=_r(normal.mean_lift, 1),
    )

    # Problem sensors.
    start = now - DAY
    stats = cycle_stats(
        sim.runs,
        sim.tracker.open_run,
        [],
        None,
        start,
        now + timedelta(seconds=1),
        now,
        short_seconds=SHORT_SECONDS,
        critical_seconds=CRITICAL_SECONDS,
    )
    per_hour = max_starts_per_hour(sim.runs, sim.tracker.open_run, start, now)
    triggers = cycling_triggers(
        per_hour,
        stats.critical_runs,
        stats.starts,
        starts_per_hour=STARTS_PER_HOUR,
        critical_per_day=CRITICAL_RUNS_PER_DAY,
        starts_per_day=None,
    )
    problem = bool(triggers)
    dhw_charges = _finding(aux_dhw_charges(split))
    for key in (
        "disinfections",
        "aux_kwh_disinfections",
        "aux_kwh_defrost",
        "defrost_aux_charges",
    ):
        dhw_charges["a"].pop(key, None)
    binary = {
        "cycling_problem": {
            "s": "on" if problem else "off",
            "a": {
                "triggers": triggers,
                "max_starts_per_hour": per_hour,
                "starts_24h": stats.starts,
                "critical_runs_24h": stats.critical_runs,
                "short_runs_24h": stats.short_runs,
                "starts_per_hour_limit": STARTS_PER_HOUR,
                "starts_per_day_limit": None,
            },
        },
        "efficiency_drop": _finding(a["efficiency_drop"]),
        "aux_mild_weather": _finding(a["aux_mild_weather"]),
        "aux_dhw_charges": dhw_charges,
        "dhw_efficiency_drop": _finding(a["dhw_efficiency_drop"]),
        # The made-up source reports only modes as its activity: no status
        # text without a mode was entered (runtime._note_status).
        "status_messages": _finding(
            StatusCounter(since=sim.setup.astimezone(TZ).date()).finding(
                now.astimezone(TZ).date()
            )
        ),
    }
    # binary_sensor.HealthProblem: whether the heater counted at all
    # (runtime.aux_used); the card leaves a hybrid's heater checks out without.
    aux_used = any(sim.totals.get(Kind.AUX, mode) > 0 for mode in Mode)
    for key in ("aux_mild_weather", "aux_dhw_charges"):
        binary[key]["a"]["aux_used"] = aux_used
    # One status sensor per check in words (sensor.HealthStatus).
    for key, entity in binary.items():
        reason = None if key == "cycling_problem" else entity["a"].get("reason")
        known = entity["s"] in ("on", "off")
        put(f"{key}_status", status(entity["s"] == "on" if known else None, reason))
    return result, binary


def months(sim: Sim) -> list[dict[str, Any]]:
    """Statistics card "heat and electricity per month" over 365 days."""
    end = sim.now.replace(minute=0, second=0, microsecond=0)
    local = sim.sc.moment
    first = local.replace(year=local.year - 1, day=1, hour=0, minute=0) + timedelta(
        days=32
    )
    first = first.replace(day=1)
    hours = sim.hours(first.astimezone(UTC), end)
    rows = []
    for month, totals in by_month(hours, TZ).items():
        changes = own_changes(totals)
        rows.append(
            {
                "month": month,
                **{
                    k: round(changes[k], 1)
                    for k in (
                        "heat_heating",
                        "heat_dhw",
                        "electricity_heating",
                        "electricity_dhw",
                        "standby",
                    )
                },
                # Outdoor temperature of the month (the card's second axis):
                # mean, min and max of the hourly values, as the recorder's
                # monthly statistics of a sensor with state class measurement.
                **outdoor_month(sim, month, first.astimezone(UTC), end),
            }
        )
    return rows


def outdoor_month(
    sim: Sim, month: str, start: datetime, end: datetime
) -> dict[str, float]:
    """Mean, min and max of the hourly outdoor temperature in a local month."""
    values = [
        v
        for h, v in sim.outdoor_hours(start, end).items()
        if h.astimezone(TZ).strftime("%Y-%m") == month
    ]
    if not values:
        return {}
    return {
        "outdoor_mean": round(sum(values) / len(values), 1),
        "outdoor_min": round(min(values), 1),
        "outdoor_max": round(max(values), 1),
    }


def report(sim: Sim) -> dict[str, Any]:
    """Response of the action waermewacht.report (current season until now),
    as services.report and runtime.async_report build it."""
    now = sim.now
    start = period_start(Period.SEASON, now, TZ, DEFAULT_SEASON_START_MONTH)
    assert start is not None
    hours = sim.hours(start, now)
    switch = sim.setup + HOUR
    total = Totals()
    for totals in hours.values():
        total = total + totals
    modes = (Mode.HEATING, Mode.DHW)
    rows = [
        {"month": month, **figures(totals, MIN_ELECTRICITY, modes, modes)}
        for month, totals in by_month(hours, TZ).items()
    ]
    first = start.astimezone(TZ).date()
    last = (now - timedelta(microseconds=1)).astimezone(TZ).date()
    # Heat per degree day describes the building: with the boiler's heat.
    days, _, _ = daily_degree_days(
        building_hours(hours, BOILER_EFFICIENCY_HS, ()),
        sim.outdoor_hours(start, now),
        TZ,
        first,
        last + DAY,
    )
    per_month = degree_days_by_month(days)
    for row in rows:
        row["degree_days"] = per_month.get(row["month"])
    return {
        "start": start.astimezone(TZ).isoformat(),
        "end": now.astimezone(TZ).isoformat(),
        "data_until": (max(hours) + HOUR).astimezone(TZ).isoformat(),
        "estimated_until": min(switch, now).astimezone(TZ).isoformat()
        if start < switch
        else None,
        **figures(total, MIN_ELECTRICITY, modes, modes),
        "degree_days": {
            **degree_day_figures(days),
            **({"includes_boiler_heat": True} if sim.sc.bivalent is not None else {}),
        },
        "months": rows,
    }


def live(sim: Sim) -> dict[str, Any]:
    """What the source integration shows right now."""
    return {
        "activity": sim.activity.value,
        "activity_since": None
        if sim.activity_changed is None
        else sim.activity_changed.astimezone(TZ).isoformat(timespec="seconds"),
        "compressor": sim.on,
        "heat_w": round(sim.heat_kw * 1000),
        "elec_w": round(sim.elec_kw * 1000),
        "speed_hz": round(sim.speed),
        "flow": round(sim.flow, 1),
        "return": round(sim.ret, 1),
        "dhw": round(sim.storage, 1),
        "dhw_set": DHW_SET,
        "outdoor": round(sim.outdoor, 1),
        "flow_rate": PUMP_LPH if sim.on and sim.mode is Mode.HEATING else 0,
    }


def state_names(keys: list[str]) -> dict[str, dict[str, dict[str, str]]]:
    """Translated states of enum sensors: {lang: {key: {state: text}}}."""
    result = {}
    for lang in ("de", "en"):
        data = json.loads((TRANSLATIONS / f"{lang}.json").read_text(encoding="utf-8"))
        sensors = data["entity"]["sensor"]
        result[lang] = {k: sensors[k]["state"] for k in keys if "state" in sensors[k]}
    return result


def names(keys: dict[str, list[str]]) -> dict[str, dict[str, str]]:
    """Entity names from the integration's translations."""
    result = {}
    for lang in ("de", "en"):
        data = json.loads((TRANSLATIONS / f"{lang}.json").read_text(encoding="utf-8"))
        result[lang] = {
            key: data["entity"][platform][key]["name"]
            for platform, items in keys.items()
            for key in items
        }
    return result


# ---- Gas boiler before the switch -------------------------------------------------------


def gas_scenario(w: Weather) -> dict[str, Any]:
    """A gas boiler entry (gas.py): hourly gas of an invented older house."""
    rng = random.Random(3)
    house = GAS_HOUSE
    gas: dict[datetime, float] = {}
    hour = START.astimezone(UTC)
    end = GAS_MOMENT.astimezone(UTC).replace(minute=0)
    heating_cache: dict[date, bool] = {}
    while hour < end:
        local = hour.astimezone(TZ)
        day = local.date()
        if day not in heating_cache:
            heating_cache[day] = heating_on(w, day, house.limit)
        x = local.hour + 0.5
        heat = demand_kw(house, w, hour, x) if heating_cache[day] else 0.0
        if local.hour >= 22 or local.hour < 5:
            heat *= 0.75  # night setback
        elif 5 <= local.hour < 7:
            heat *= 1.3  # warming up again
        winter = math.cos(2 * math.pi * (day.timetuple().tm_yday - 18) / 365.25)
        if local.hour in (6, 19):  # the storage is reheated after the showers
            heat += (2.7 + 0.35 * winter) * rng.uniform(0.75, 1.25)
        gas[hour] = round(heat / GAS_EFFICIENCY * rng.uniform(0.95, 1.05), 3)
        hour += HOUR
    start, stop = gas_window(GAS_MOMENT.astimezone(UTC), TZ)
    analysis = analyse_gas(
        gas,
        w.temps,
        TZ,
        start,
        stop,
        includes_dhw=True,
        design_temp=DESIGN_TEMP,
        gas_price=GAS_PRICE,
        gas_base_price=GAS_BASE_PRICE,
    )
    load = analysis.heat_load
    ok = load.sufficient

    def entry(
        state: Any, unit: str | None, precision: int, **attributes: Any
    ) -> dict[str, Any]:
        return {"s": state, "u": unit, "p": precision, "a": attributes}

    window = {"start": start.isoformat(), "end": stop.isoformat()}
    gas_attributes = {
        **window,
        "days": analysis.gas_days,
        "complete": analysis.gas_days >= (stop - start).days,
        "heat_kwh": round(analysis.heat_kwh, 1),
        "boiler_efficiency": analysis.efficiency,
    }
    dd = analysis.degree_days
    split = analysis.split
    result = {
        "gas_heat_load_per_kelvin": entry(
            None if not ok else round(-round(load.slope_kw_per_k, 4) * 1000),
            "W/K",
            0,
            **window,
            boiler_efficiency=analysis.efficiency,
            dhw_method=split.method,
            **heat_load_as_dict(load),
        ),
        "gas_heat_load_design": entry(_r(load.standard_kw, 2) if ok else None, "kW", 1),
        "gas_heating_limit": entry(_r(load.heating_limit, 1) if ok else None, "°C", 1),
        "gas_heat_per_degree_day": entry(
            _r(dd.kwh_per_degree_day, 2),
            "kWh/K·d",
            2,
            base="G20/15",
            degree_days=round(dd.degree_days, 1),
            days_counted=dd.days_counted,
            days_missing=dd.days_missing,
            heating_kwh=round(dd.heating_kwh, 1),
        ),
        "gas_dhw_share": entry(
            _r(analysis.dhw_share, 1),
            "%",
            0,
            method=split.method,
            summer_days=split.summer_days,
            summer_base_kwh_per_day=_r(split.summer_base_kwh, 2),
            dhw_gas_kwh=round(analysis.dhw_kwh, 1),
            heating_gas_kwh=round(analysis.heating_kwh, 1),
        ),
        "gas_consumption_year": entry(
            round(analysis.gas_kwh, 1), "kWh", 0, **gas_attributes
        ),
        "gas_cost_year": entry(
            _r(analysis.cost_eur, 2),
            "€",
            0,
            **gas_attributes,
            gas_kwh=round(analysis.gas_kwh, 1),
            base_cost_eur=_r(analysis.base_cost_eur, 2),
        ),
    }
    month_rows: dict[str, dict[str, float]] = {}
    for part, values in (("heating", split.heating), ("dhw", split.dhw)):
        for h, kwh in values.items():
            row = month_rows.setdefault(
                h.astimezone(TZ).strftime("%Y-%m"), {"heating": 0.0, "dhw": 0.0}
            )
            row[part] += kwh
    rows = [
        {"month": m, "heating": round(v["heating"], 1), "dhw": round(v["dhw"], 1)}
        for m, v in sorted(month_rows.items())
    ]
    response = {
        "start": local_midnight(start, TZ).astimezone(TZ).isoformat(),
        "end": local_midnight(stop, TZ).astimezone(TZ).isoformat(),
        **heat_load_as_dict(load),
    }
    print(
        f"gas: {result['gas_heat_load_per_kelvin']['s']} W/K, "
        f"{result['gas_heat_load_design']['s']} kW bei {DESIGN_TEMP} °C, "
        f"Heizgrenze {result['gas_heating_limit']['s']} °C, R² {_r(load.r_squared, 3)}, "
        f"{len(load.weeks)} Wochen, Gas {result['gas_consumption_year']['s']} kWh, "
        f"WW-Anteil {result['gas_dhw_share']['s']} %, {result['gas_cost_year']['s']} €"
    )
    return {
        "key": "gas",
        "kind": "gas",
        "now": GAS_MOMENT.isoformat(),
        "device": "Beispiel-Gasheizung",
        "house": {
            "ua_w_per_k": round(GAS_HOUSE.ua * 1000),
            "heating_limit": GAS_HOUSE.limit,
        },
        "options": {
            "design_temp": DESIGN_TEMP,
            "boiler_efficiency": GAS_EFFICIENCY,
            "gas_price_ct": GAS_PRICE * 100,
            "gas_base_price": GAS_BASE_PRICE,
        },
        "sensors": result,
        "months": rows,
        "response": response,
        "names": names({"sensor": list(result)}),
    }


# ---- Main ---------------------------------------------------------------------------------


def heat_pump_scenario(scenario: Scenario, w: Weather) -> dict[str, Any]:
    sim = Sim(scenario, w)
    sim.run()
    values, binary = sensors(sim)
    data = {
        "key": scenario.key,
        "kind": "heat_pump",
        "now": scenario.moment.isoformat(),
        "setup": SETUP.isoformat(),
        "device": DEVICE,
        "options": {
            "rated_kw": RATED_KW,
            "min_kw": MIN_KW,
            "design_temp": DESIGN_TEMP,
            "electricity_price_ct": ELECTRICITY_PRICE * 100,
            "gas_price_ct": GAS_PRICE * 100,
            "gas_base_price": GAS_BASE_PRICE,
            "short_run_minutes": SHORT_SECONDS / 60,
            "critical_run_minutes": CRITICAL_SECONDS / 60,
            "starts_per_hour": STARTS_PER_HOUR,
            "bivalent": scenario.bivalent,
        },
        "house": {
            "ua_w_per_k": round(scenario.house.ua * 1000),
            "heating_limit": scenario.house.limit,
            "buffer": scenario.house.band_kwh >= 0.3,
        },
        "live": live(sim),
        "today": sim.today,
        "sensors": values,
        "binary": binary,
        "months": months(sim),
        "report": report(sim),
        "names": names({"sensor": list(values), "binary_sensor": list(binary)}),
        "states": state_names(list(values)),
    }
    s = values
    week = sim.diary[-7:]
    print(
        f"{scenario.key}: AZ Heizen Monat {s['ratio_heating_month']['s']}, "
        f"Saison {s['ratio_heating_season']['s']}; WW Monat {s['ratio_dhw_month']['s']}, "
        f"Saison {s['ratio_dhw_season']['s']}; JAZ Saison {s['ratio_combined_season']['s']}"
    )
    print(
        f"  Starts heute {s['starts_today']['s']}, gestern {s['starts_yesterday']['s']}, "
        f"7 Tage je Tag {[d['starts'] for d in week]}, "
        f"Laufzeit je Start heute/7 Tage {s['run_minutes_today']['s']}/{s['run_minutes_week']['s']} min, "
        f"Kurzläufe heute {s['short_runs_today']['s']}"
    )
    print(
        f"  Abtauungen heute {s['defrosts_today']['s']}, 7 Tage "
        f"{s['defrosts_today']['a']['defrosts_7d']} (Ø {s['defrosts_today']['a']['mean_minutes_7d']} min), "
        f"Außen 7 Tage {[d['outdoor'] for d in week]}"
    )
    print(
        f"  Heizlast {s['heat_load_per_kelvin']['s']} W/K, {s['heat_load_design']['s']} kW, "
        f"Heizgrenze {s['heating_limit']['s']} °C, Leistung je Heizlast {s['oversize_factor']['s']}, "
        f"Vorlauf bei 0 °C {s['flow_at_zero']['s']}, Spreizung 7 Tage {s['spread_7d']['s']}"
    )
    print(
        f"  Stillstand {s['standby_power_7d']['s']} W, Kosten Saison {s['cost_season']['s']} €, "
        f"Ersparnis {s['gas_savings_season']['s']} €, WW-Ladungen 30 Tage "
        f"{s['ratio_dhw_charges_30d']['a']['charges']} AZ {s['ratio_dhw_charges_30d']['s']}"
    )
    print(
        "  "
        + ", ".join(f"{k} {v['s']} ({v['a'].get('reason')})" for k, v in binary.items())
    )
    return data


def main() -> None:
    w = weather(random.Random(2009))  # RAL 2009, the brand colour
    OUT.mkdir(parents=True, exist_ok=True)
    results = [heat_pump_scenario(sc, w) for sc in SCENARIOS]
    results.append(gas_scenario(w))
    for data in results:
        path = OUT / f"{data['key']}.json"
        with path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(data, file, ensure_ascii=False, separators=(",", ":"))
        print(f"{path.relative_to(ROOT)}: {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
