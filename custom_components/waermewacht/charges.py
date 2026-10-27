"""Domestic hot water (DHW) charges and thermal disinfection. Pure Python, no HA imports.

Rules:
- A charge is one continuous period of the activity DHW. A compressor run may
  switch heating -> DHW without stopping; only the DHW part is the charge.
- Energy of a charge: heat delivered, compressor electricity while running and
  backup heater electricity during the charge. Standby is never part of a
  charge (Fraunhofer ISE, WP-QS final report 2025, ch. 5.2: partial ratios
  per mode without standby; docs/ENTWICKLUNG.md).
- Ratio = sum heat / sum (compressor + backup heater electricity), as in
  `energy.ratio`: None without heat or below the minimum electricity, never 0.
- A charge counts for the window it ended in, like runs in `cycling`. Running
  charges (end None) are left out unless `as_of` is given, which counts them
  as ending at `as_of` (view of the current charge).
- Totals and the ratio use every finished charge; durations, heat per charge
  and temperature lift only certain ones (no observation gap). Temperatures
  may be missing; a figure without data is None.
- Thermal disinfection: the highest DHW temperature of a charge reached the
  threshold, by default 60 degC. Source: DVGW W 551 (2004), "Trinkwasser-
  erwaermungs- und Trinkwasserleitungsanlagen; Technische Massnahmen zur
  Verminderung des Legionellenwachstums": at least 60 degC at the outlet of
  the water heater (required for large, recommended for small installations).
  The storage sensor of a heat pump is not the outlet, so the threshold is a
  parameter. Disinfection charges are where backup heater energy for hot water
  usually goes, so its share is split between them and normal charges.
- ChargeTracker forms charges from the activity: a charge starts with hot
  water and ends with any other known activity; a defrost does not end it.
  Counters report a moment late, so energy of hot water within LATE after
  the end still belongs to the charge, which is handed out only then.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .energy import Kind, ratio
from .model import Activity

# Smallest electricity of a single charge (or window) with a ratio (kWh).
MIN_CHARGE_ELECTRICITY_KWH = 0.2
# DVGW W 551 (2004): >= 60 degC at the water heater outlet against legionella.
DISINFECTION_TEMP_C = 60.0
SECONDS_PER_DAY = 86400.0
# Energy of hot water up to this long after the end still belongs to the
# charge (counters report late); a restart longer than this leaves a gap.
LATE = timedelta(minutes=5)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _float(value: Any) -> float | None:
    return float(value) if value is not None else None


@dataclass
class Charge:
    """One DHW charge: a continuous period of the activity hot water."""

    start: datetime
    end: datetime | None = None  # None while the charge is running
    heat_kwh: float = 0.0
    electricity_kwh: float = 0.0  # compressor while running, no standby
    aux_kwh: float = 0.0  # backup heater during the charge
    max_dhw_temp: float | None = None  # highest DHW temperature seen (degC)
    start_dhw_temp: float | None = None  # DHW temperature at the start (degC)
    uncertain: bool = False  # a gap hides part of the charge

    def seconds(self, now: datetime) -> float:
        return ((self.end or now) - self.start).total_seconds()

    @property
    def input_kwh(self) -> float:
        """Electricity of the charge: compressor plus backup heater."""
        return self.electricity_kwh + self.aux_kwh

    @property
    def lift(self) -> float | None:
        """Temperature lift in K (highest minus start temperature)."""
        if self.max_dhw_temp is None or self.start_dhw_temp is None:
            return None
        return self.max_dhw_temp - self.start_dhw_temp

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": _iso(self.end),
            "heat_kwh": self.heat_kwh,
            "electricity_kwh": self.electricity_kwh,
            "aux_kwh": self.aux_kwh,
            "max_dhw_temp": self.max_dhw_temp,
            "start_dhw_temp": self.start_dhw_temp,
            "uncertain": self.uncertain,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Charge:
        return cls(
            start=datetime.fromisoformat(data["start"]),
            end=_dt(data.get("end")),
            heat_kwh=float(data.get("heat_kwh", 0.0)),
            electricity_kwh=float(data.get("electricity_kwh", 0.0)),
            aux_kwh=float(data.get("aux_kwh", 0.0)),
            max_dhw_temp=_float(data.get("max_dhw_temp")),
            start_dhw_temp=_float(data.get("start_dhw_temp")),
            uncertain=data.get("uncertain", False),
        )


def charge_ratio(
    charge: Charge, min_electricity: float = MIN_CHARGE_ELECTRICITY_KWH
) -> float | None:
    """Ratio of one charge; None without heat or below the minimum electricity."""
    return ratio(charge.heat_kwh, charge.input_kwh, min_electricity)


def _share(part: float, whole: float, minimum: float) -> float | None:
    """`part` in % of `whole`; None below the minimum (never divide by 0)."""
    if whole <= 0 or whole < minimum:
        return None
    return 100 * part / whole


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


@dataclass(frozen=True)
class ChargeStats:
    """DHW charge figures for one time window."""

    count: int  # charges that ended in the window
    uncertain: int  # of them with an observation gap
    heat_kwh: float
    electricity_kwh: float  # compressor
    aux_kwh: float  # backup heater
    ratio: float | None  # heat / (compressor + backup heater)
    aux_share: float | None  # backup heater in % of the charge electricity
    mean_minutes: float | None  # certain charges only
    mean_heat_kwh: float | None  # certain charges only
    mean_lift: float | None  # K, certain charges with both temperatures
    lift_count: int  # charges behind `mean_lift`

    @property
    def uncertain_share(self) -> float | None:
        """Charges with an observation gap in % of all charges."""
        return 100 * self.uncertain / self.count if self.count else None


def _in_window(
    charges: Iterable[Charge],
    start: datetime,
    end: datetime,
    as_of: datetime | None,
) -> list[tuple[Charge, datetime]]:
    """Charges with the time they count at, if that lies in [start, end)."""
    chosen: list[tuple[Charge, datetime]] = []
    for charge in charges:
        until = charge.end or as_of
        if until is not None and start <= until < end:
            chosen.append((charge, until))
    return chosen


def charge_stats(
    charges: Iterable[Charge],
    start: datetime,
    end: datetime,
    *,
    min_electricity: float = MIN_CHARGE_ELECTRICITY_KWH,
    as_of: datetime | None = None,
) -> ChargeStats:
    """Figures for charges ending in [start, end).

    Running charges are left out; with `as_of` they count as ending then.
    """
    chosen = _in_window(charges, start, end, as_of)
    heat = sum(c.heat_kwh for c, _ in chosen)
    elec = sum(c.electricity_kwh for c, _ in chosen)
    aux = sum(c.aux_kwh for c, _ in chosen)
    certain = [(c, until) for c, until in chosen if not c.uncertain]
    lifts = [lift for c, _ in certain if (lift := c.lift) is not None]
    return ChargeStats(
        count=len(chosen),
        uncertain=len(chosen) - len(certain),
        heat_kwh=heat,
        electricity_kwh=elec,
        aux_kwh=aux,
        ratio=ratio(heat, elec + aux, min_electricity),
        aux_share=_share(aux, elec + aux, min_electricity),
        mean_minutes=_mean([c.seconds(until) / 60 for c, until in certain]),
        mean_heat_kwh=_mean([c.heat_kwh for c, _ in certain]),
        mean_lift=_mean(lifts),
        lift_count=len(lifts),
    )


def open_charge(charges: Iterable[Charge]) -> Charge | None:
    """The running charge (latest start without an end), if any."""
    running = [c for c in charges if c.end is None]
    return max(running, key=lambda c: c.start) if running else None


def is_disinfection(charge: Charge, threshold: float = DISINFECTION_TEMP_C) -> bool:
    """Whether the charge reached the disinfection temperature."""
    return charge.max_dhw_temp is not None and charge.max_dhw_temp >= threshold


def disinfections(
    charges: Iterable[Charge], *, threshold: float = DISINFECTION_TEMP_C
) -> list[Charge]:
    """Charges that reached the threshold, by start; a running one included."""
    found = [c for c in charges if is_disinfection(c, threshold)]
    return sorted(found, key=lambda c: c.start)


def last_disinfection(
    charges: Iterable[Charge], *, threshold: float = DISINFECTION_TEMP_C
) -> Charge | None:
    """The latest charge that reached the threshold."""
    found = disinfections(charges, threshold=threshold)
    return found[-1] if found else None


def days_since(
    charges: Iterable[Charge],
    now: datetime,
    *,
    threshold: float = DISINFECTION_TEMP_C,
) -> float | None:
    """Elapsed days (24 h each) since the last disinfection ended.

    0 while a disinfection charge is running; None without any. Elapsed time,
    not calendar days, so daylight saving changes do not matter.
    """
    last = last_disinfection(charges, threshold=threshold)
    if last is None:
        return None
    seconds = (now - (last.end or now)).total_seconds()
    return max(seconds, 0.0) / SECONDS_PER_DAY


@dataclass(frozen=True)
class DisinfectionSplit:
    """Charge figures for normal and disinfection charges of one window."""

    normal: ChargeStats
    disinfection: ChargeStats

    @property
    def aux_in_disinfection(self) -> float | None:
        """Share of the backup heater energy spent in disinfection charges, %."""
        total = self.normal.aux_kwh + self.disinfection.aux_kwh
        return _share(self.disinfection.aux_kwh, total, 0.0)


def disinfection_split(
    charges: Iterable[Charge],
    start: datetime,
    end: datetime,
    *,
    threshold: float = DISINFECTION_TEMP_C,
    min_electricity: float = MIN_CHARGE_ELECTRICITY_KWH,
    as_of: datetime | None = None,
) -> DisinfectionSplit:
    """`charge_stats` separately for normal and disinfection charges."""
    every = list(charges)
    hot = [c for c in every if is_disinfection(c, threshold)]
    normal = [c for c in every if not is_disinfection(c, threshold)]
    return DisinfectionSplit(
        normal=charge_stats(
            normal, start, end, min_electricity=min_electricity, as_of=as_of
        ),
        disinfection=charge_stats(
            hot, start, end, min_electricity=min_electricity, as_of=as_of
        ),
    )


def prune(charges: list[Charge], keep_from: datetime) -> None:
    """Drop charges that ended before `keep_from` (in place)."""
    charges[:] = [c for c in charges if c.end is None or c.end >= keep_from]


class ChargeTracker:
    """Charges from the activity, the hot water energy and temperature."""

    def __init__(self) -> None:
        self.open: Charge | None = None  # running
        self.closing: Charge | None = None  # ended, still taking late energy

    def set_activity(
        self, activity: Activity | None, at: datetime, temp: float | None
    ) -> Charge | None:
        """Note the activity; returns a charge that is finished now."""
        if activity is Activity.DHW:
            if self.open is not None:
                return None
            finished, self.closing = self.closing, None
            self.open = Charge(start=at, start_dhw_temp=temp, max_dhw_temp=temp)
            return finished
        if self.open is None or activity is Activity.DEFROST:
            return None
        if activity is None:  # unknown: the charge may have ended unseen
            self.open.uncertain = True
            return None
        self.open.end = at
        self.closing, self.open = self.open, None
        return None

    def add(self, kind: Kind, kwh: float, at: datetime) -> None:
        """Hot water energy (heat, compressor or backup heater electricity)."""
        charge = self.open
        closing = self.closing
        if charge is None and closing and closing.end and at <= closing.end + LATE:
            charge = closing
        if charge is None:
            return
        if kind is Kind.HEAT:
            charge.heat_kwh += kwh
        elif kind is Kind.ELEC:
            charge.electricity_kwh += kwh
        elif kind is Kind.AUX:
            charge.aux_kwh += kwh

    def temperature(self, value: float | None) -> None:
        if (charge := self.open) is None or value is None:
            return
        if charge.start_dhw_temp is None:
            charge.start_dhw_temp = value
        if charge.max_dhw_temp is None or value > charge.max_dhw_temp:
            charge.max_dhw_temp = value

    def tick(self, now: datetime) -> Charge | None:
        """The ended charge once its late energy is in."""
        if self.closing and self.closing.end and now >= self.closing.end + LATE:
            finished, self.closing = self.closing, None
            return finished
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "open": self.open.as_dict() if self.open else None,
            "closing": self.closing.as_dict() if self.closing else None,
        }

    def restore(self, data: dict[str, Any], saved_at: datetime, now: datetime) -> None:
        if data.get("open"):
            self.open = Charge.from_dict(data["open"])
            if now - saved_at > LATE:
                self.open.uncertain = True
        if data.get("closing"):
            self.closing = Charge.from_dict(data["closing"])
