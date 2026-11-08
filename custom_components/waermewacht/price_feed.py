"""Hourly prices of an electricity price sensor and the energy priced with
them (prices.py has the rules); with grid, PV and battery meters also the
split into grid and own electricity (allocation.py).

Refreshed after each full hour from the recorder: the hourly energy of the
season (the same hours as the report: source counters before the setup,
own energy sensors after it) and the hourly means of the price sensor. The
whole season once a day and at the start, else the last two days again
(hours written late). In memory only: a restart reads it anew.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, tzinfo
from functools import partial

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.components.recorder.statistics import (
    get_metadata,
    statistics_during_period,
)
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from .allocation import PROPORTIONAL, Allocation, SplitSettings, rule_for
from .costs import ElectricityCost
from .energy import SEASONAL_MODES, Totals
from .model import Mode
from .periods import local_midnight
from .plausible import plausible_hours
from .prices import (
    PricedDay,
    day_mean_prices,
    floor_hour,
    hourly_means,
    hours_between,
    period_allocation,
    period_cost,
    price_days,
    to_eur_per_kwh,
)
from .solar import HourFlows, SolarSettings, detect_same_inverter

# Meters of the house (Meters keys) -> HourFlows field.
FLOW_FIELDS = {
    "purchase": "purchase",
    "feed_in": "feed_in",
    "pv": "pv",
    "charged": "charged",
    "discharged": "discharged",
}

_LOGGER = logging.getLogger(__name__)

# The largest plausible change of a house meter in one hour of the
# long-term statistics: 100 kW (a house connection with margin) x 1.5, the
# bound of Tarifwacht (lookback.MAX_HOURLY_KWH).
MAX_HOUSE_KWH = 150.0

# Hours read again on each refresh: sources and the recorder write late.
RECENT = timedelta(hours=48)
# Minute of the hour to refresh at: the recorder writes the hour's
# statistics a few seconds after it.
REFRESH_MINUTE = 5

type HoursFunction = Callable[[datetime, datetime], Awaitable[dict[datetime, Totals]]]


class PriceFeed:
    """Prices of one sensor and the season's electricity priced with them."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str | None,
        tz: tzinfo,
        *,
        fixed: float | None,
        day_values: bool,
        meters: dict[str, str] | None = None,
        feed_in_rate: float = 0.0,
    ) -> None:
        self.hass = hass
        self.entity_id = entity_id  # price sensor, None: the fixed price
        # Meters of the house by FLOW_FIELDS key; "purchase" enables the split.
        self.meters = dict(meters or {})
        self.feed_in_rate = feed_in_rate  # EUR/kWh
        battery = "charged" in self.meters and "discharged" in self.meters
        if not battery:
            self.meters.pop("charged", None)
            self.meters.pop("discharged", None)
        self.rule: str | None = (
            rule_for(pv="pv" in self.meters, feed_in="feed_in" in self.meters)
            if "purchase" in self.meters
            else None
        )
        # Battery behind the PV inverter, from the data (None: unclear, read
        # as a battery with its own inverter).
        self.same_inverter: bool | None = None
        self.tz = tz
        self.fixed = fixed  # €/kWh, for hours without a price of the sensor
        self.day_values = day_values  # a day's energy in one hour
        # Priced local days of the season up to `until` (None: not read yet).
        self.days: dict[datetime, PricedDay] | None = None
        self.until: datetime | None = None
        self.refreshed_at: datetime | None = None
        self.hours_from_states = 0  # hours priced from the states (diagnostics)
        # Hours of the house meters' statistics left out (plausible.py).
        self.implausible: set[datetime] = set()
        self._start: datetime | None = None
        self._full_day: date | None = None
        self._tried = False
        self.refreshing = False

    def current(self) -> float | None:
        """The sensor's price now in €/kWh (None while unknown)."""
        if self.entity_id is None:
            return None
        state = self.hass.states.get(self.entity_id)
        if state is None:
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        return to_eur_per_kwh(value, state.attributes.get(ATTR_UNIT_OF_MEASUREMENT))

    def due(self, now: datetime) -> bool:
        """Right after the start, then after each full hour (also after a
        failed attempt: no retry every minute)."""
        if self.refreshing:
            return False
        return not self._tried or now.minute == REFRESH_MINUTE

    async def async_refresh(
        self, now: datetime, season_start: datetime, hours_of: HoursFunction
    ) -> None:
        """Read the hours of the season (or the recent ones) and price them."""
        self.refreshing = True
        self._tried = True
        try:
            until = floor_hour(now)
            today = now.astimezone(self.tz).date()
            full = (
                self.days is None
                or self._full_day != today
                or self._start != season_start
            )
            start = season_start
            if not full:
                recent = (until - RECENT).astimezone(self.tz).date()
                start = max(season_start, local_midnight(recent, self.tz))
            flows: dict[datetime, HourFlows] = {}
            if start >= until:
                hours: dict[datetime, Totals] = {}
                prices: dict[datetime, float] = {}
            else:
                hours = await hours_of(start, until)
                prices = await self._async_prices(start, until)
                if self.rule is not None:
                    flows = await self._async_flows(start, until)
            if full and self.rule == PROPORTIONAL and "charged" in self.meters:
                self.same_inverter = detect_same_inverter(flows)
            if self.day_values:
                prices = day_mean_prices(prices, hours, self.tz)
                flows = _day_flows(flows, hours, self.tz)
            priced = price_days(
                hours, prices, self.fixed, self.tz, flows, self._split()
            )
            days = {} if full or self.days is None else dict(self.days)
            days = {day: p for day, p in days.items() if day < start}
            days.update(priced)
            self.days, self.until = days, until
            self._start = season_start
            if full:
                self._full_day = today
            self.refreshed_at = now
        finally:
            self.refreshing = False

    def _split(self) -> SplitSettings | None:
        if self.rule is None:
            return None
        return SplitSettings(
            self.rule,
            self.feed_in_rate,
            SolarSettings(
                same_inverter=bool(self.same_inverter),
                feed_in_rate=self.feed_in_rate,
            ),
        )

    async def _async_flows(
        self, start: datetime, end: datetime
    ) -> dict[datetime, HourFlows]:
        """Energy of the house meters per hour in [start, end), for the
        hours in which every meter the rule needs has statistics."""
        needed = {"purchase"}
        if self.rule == PROPORTIONAL:
            needed |= set(self.meters)
        ids = {self.meters[key]: key for key in needed}
        rows = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            end,
            set(ids),
            "hour",
            {"energy": "kWh"},
            {"change", "state"},
        )
        per_key: dict[str, dict[datetime, float]] = {}
        left_out: set[datetime] = set()
        for entity_id, key in ids.items():
            changes = []
            for row in rows.get(entity_id, []):
                if (change := row.get("change")) is None:
                    continue
                hour = row["start"]
                if not isinstance(hour, datetime):
                    hour = dt_util.utc_from_timestamp(hour)
                changes.append((hour, change, row.get("state")))
            # A meter reset, a unit glitch (Wh as kWh) and the fall back after
            # it: the hour is missing, so it counts as grid electricity.
            per_key[key], dropped = plausible_hours(changes, MAX_HOUSE_KWH)
            left_out.update(dropped)
        self.implausible = {h for h in self.implausible if not start <= h < end}
        self.implausible |= left_out
        common = set.intersection(*(set(v) for v in per_key.values()))
        return {
            hour: HourFlows(**{FLOW_FIELDS[k]: v[hour] for k, v in per_key.items()})
            for hour in common
        }

    def hours_implausible(self, start: datetime) -> int:
        """Hours from `start` left out of the house meters (plausible.py)."""
        return sum(1 for hour in self.implausible if hour >= start)

    def allocation(self, start: datetime, totals: Totals) -> Allocation | None:
        """Grid and own electricity of the period from `start` with the
        energy `totals`: what the priced days hold as own, the rest from the
        grid (the running hour included)."""
        if self.days is None:
            return None
        found = period_allocation(self.days, start)
        if found is None:
            return None
        total = (
            totals.electricity(*SEASONAL_MODES)
            + totals.standby()
            + totals.electricity(Mode.COOLING)
        )
        return Allocation(
            kwh_grid=max(0.0, total - found.kwh_own),
            kwh_own=found.kwh_own,
            hours_all_grid=found.hours_all_grid,
            saving_eur=found.saving_eur,
            heat_saving_eur=found.heat_saving_eur,
        )

    async def _async_prices(
        self, start: datetime, end: datetime
    ) -> dict[datetime, float]:
        """€/kWh per hour in [start, end): long-term statistics (mean), else
        the recorded states. None without a price sensor."""
        if self.entity_id is None:
            return {}
        recorder = get_instance(self.hass)
        rows = await recorder.async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            end,
            {self.entity_id},
            "hour",
            None,
            {"mean"},
        )
        state = self.hass.states.get(self.entity_id)
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if state else None
        stored = unit
        if rows.get(self.entity_id):
            metadata = await recorder.async_add_executor_job(
                partial(get_metadata, self.hass, statistic_ids={self.entity_id})
            )
            if self.entity_id in metadata:
                stored = metadata[self.entity_id][1].get("unit_of_measurement")
        prices: dict[datetime, float] = {}
        for row in rows.get(self.entity_id, []):
            hour = row["start"]
            if not isinstance(hour, datetime):
                hour = dt_util.utc_from_timestamp(hour)
            if (price := to_eur_per_kwh(row.get("mean"), stored)) is not None:
                prices[hour] = price
        missing = [h for h in hours_between(start, end) if h not in prices]
        self.hours_from_states = 0
        if missing:
            found = await recorder.async_add_executor_job(
                partial(
                    get_significant_states,
                    self.hass,
                    missing[0],
                    end,
                    [self.entity_id],
                    significant_changes_only=False,
                    no_attributes=True,
                )
            )
            samples = [
                (s.last_updated, to_eur_per_kwh(_number(s.state), unit))
                for s in found.get(self.entity_id, [])
                if isinstance(s, State)
            ]
            means = hourly_means(samples, missing[0], end)
            for hour in missing:
                if hour in means:
                    prices[hour] = means[hour]
                    self.hours_from_states += 1
        return prices

    def period(
        self, start: datetime, totals: Totals, now: datetime
    ) -> tuple[ElectricityCost, float] | None:
        """Electricity cost and heat of the period from `start` with the
        energy `totals`; None until the first refresh."""
        if self.days is None or self.until is None:
            return None
        return period_cost(
            self.days,
            start,
            totals,
            current=self.current(),
            fixed=self.fixed,
            at=max(self.until, start, floor_hour(now)),
        )


def _day_flows(
    flows: dict[datetime, HourFlows], hours: dict[datetime, Totals], tz: tzinfo
) -> dict[datetime, HourFlows]:
    """Day values book a day in one hour: the flows of its whole local day
    (the hours with statistics), for that hour."""
    days: dict[date, list[HourFlows]] = {}
    for hour, found in flows.items():
        days.setdefault(hour.astimezone(tz).date(), []).append(found)
    result: dict[datetime, HourFlows] = {}
    for hour in hours:
        if parts := days.get(hour.astimezone(tz).date()):
            result[hour] = HourFlows(
                purchase=sum(p.purchase for p in parts),
                feed_in=sum(p.feed_in for p in parts),
                pv=sum(p.pv for p in parts),
                charged=sum(p.charged for p in parts),
                discharged=sum(p.discharged for p in parts),
            )
    return result


def _number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None
