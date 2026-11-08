"""Hourly prices of an electricity price sensor and the energy priced with
them (prices.py has the rules).

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

from .costs import ElectricityCost
from .energy import Totals
from .periods import local_midnight
from .prices import (
    PricedDay,
    day_mean_prices,
    floor_hour,
    hourly_means,
    hours_between,
    period_cost,
    price_days,
    to_eur_per_kwh,
)

_LOGGER = logging.getLogger(__name__)

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
        entity_id: str,
        tz: tzinfo,
        *,
        fixed: float | None,
        day_values: bool,
    ) -> None:
        self.hass = hass
        self.entity_id = entity_id
        self.tz = tz
        self.fixed = fixed  # €/kWh, for hours without a price of the sensor
        self.day_values = day_values  # a day's energy in one hour
        # Priced local days of the season up to `until` (None: not read yet).
        self.days: dict[datetime, PricedDay] | None = None
        self.until: datetime | None = None
        self.refreshed_at: datetime | None = None
        self.hours_from_states = 0  # hours priced from the states (diagnostics)
        self._start: datetime | None = None
        self._full_day: date | None = None
        self._tried = False
        self.refreshing = False

    def current(self) -> float | None:
        """The sensor's price now in €/kWh (None while unknown)."""
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
            if start >= until:
                hours: dict[datetime, Totals] = {}
                prices: dict[datetime, float] = {}
            else:
                hours = await hours_of(start, until)
                prices = await self._async_prices(start, until)
            if self.day_values:
                prices = day_mean_prices(prices, hours, self.tz)
            priced = price_days(hours, prices, self.fixed, self.tz)
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

    async def _async_prices(
        self, start: datetime, end: datetime
    ) -> dict[datetime, float]:
        """€/kWh per hour in [start, end): long-term statistics (mean), else
        the recorded states."""
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


def _number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None
