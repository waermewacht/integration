"""Carnot efficiency factor ("Gütegrad") while heating, health check 4.14.

Pure Python, no Home Assistant imports. Design and sources:
docs/GESUNDHEITSCHECK.md 4.14.

The factor is the measured performance over the best one possible at the
same temperatures: COP_Carnot = T_sink / (T_sink - T_source) in kelvin, the
sink the mean of flow and return, the source the outdoor air, heating only
(Fraunhofer ISE, WP-QS im Bestand; Günther et al., HPC 2026, section 4.2:
air/water 0.32-0.44, mean 0.39, 36 units, annual values). It takes the
weather and the heating curve out of the performance factor.

From the diary, per day with heating: heat and electricity of heating
("energy"), flow and spread while the compressor heats ("flow", "spread"),
the outdoor temperature under the same condition ("outdoor_heating"; older
entries fall back to the day mean "outdoor"). A period's factor is the
electricity an ideal machine would have needed over the electricity used,
sum(heat / COP_Carnot) / sum(electricity): heat-weighted, so mild days with
little heat and a huge Carnot COP do not distort it (own choice; Fraunhofer
forms it from annual values).

Look-back from the long-term statistics, for days without a diary entry
that knows the outdoor temperature while heating (before the setup, before
this was added): hourly means of flow, return and outdoor temperature, only
the heating-only hours with at least 0.3 kWh of heating heat (the hours of
"flow at 0 °C", heating_curve.heating_weights), the day's Carnot COP
weighted with their heat; the day's energy from all its hours. An hourly
mean includes the minutes the compressor stood still, which would lower
the sink. Checked on the owner's heat pump (2026-11-09, 10 days, 7-19 h of
heating a day, raw history while heating as reference): the day's Carnot
COP differed by -0.4 to +1.4 %, mean +0.5 %. Stricter filters (neighbour
hours heating too, near-full hours only) left too few hours and did worse.
Not yet checked on a heat pump that cycles a lot (spring).

Brine/water and water/water heat pumps (Signal.SOURCE_TEMP mapped, the
source SOURCE_BRINE): the source is the temperature of the brine entering
the heat pump, not the outdoor air. A diary day takes its mean while
heating ("source_heating"); a day without it (before the field was set)
comes from the look-back with the hourly means of that entity. Such an
entry never falls back to the outdoor temperature (air and brine mixed
would be wrong), and an entry without it never uses the brine. The
field values above are for air/water only: with the brine the
attributes leave them out (`field_reference: None`, `source_signal`).

Lower heating curve (health check 4.14, second part): with the period's
own factor g, the electricity at a sink k kelvin lower is
sum(heat / (g * COP_Carnot(sink - k, source))); the saving is the
difference to sum(heat / (g * COP_Carnot(sink, source))), which equals the
electricity used. Same heat (the rooms stay warm), same factor, the whole
sink moves by k. A day whose lower sink falls below the smallest lift
keeps its electricity (no saving counted). Checked against field values:
Carnot alone gives +2.6 % per kelvin at 35 °C sink and 0 °C outside, +2.0 %
at 45 °C; Brudermueller et al. 2025 found SCOP +0.11 and -2.61 %
electricity per kelvin on average (708 heat pumps). At a small lift the
factor tends to fall, so the figure is rather an upper bound.

Days with backup heater electricity are left out: whether a heat counter
holds the heater's heat depends on the source, and Fraunhofer's SPF 2 is
the heat pump alone. Without a return temperature the sink is the flow
temperature, which makes the Carnot COP smaller and the factor too high
(flow 35 °C, spread 5 K, outdoor 0 °C: 6.8 %). The attributes give the
days and the share of the heat counted that way (`flow_only_days`,
`flow_only_percent`); `sink: flow_only` (and the card's note) only from
FLOW_ONLY_NOTE_SHARE of the heat on. In the look-back an hour counts
without a return when the return has no hourly mean or lies above the
flow; before, a single such hour in the season marked the whole of it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from .averages import Mean
from .energy import Kind, Totals
from .heating_curve import FLOW_MAX, FLOW_MIN, heating_weights
from .model import Mode

KELVIN = 273.15
# Fraunhofer ISE WP-QS, air/water heat pumps, space heating, annual values.
FIELD_FACTOR = 0.39
FIELD_RANGE = (0.32, 0.44)
FIELD_UNITS = 36
# A day counts with this much heating time (as the flow temperature of 4.5).
MIN_HEATING_SECONDS = 2 * 3600.0
# Own assumption: below this lift the Carnot COP grows so large that 0.5 K
# of sensor error moves a day by more than 5 %.
MIN_LIFT_K = 10.0
# Own assumption: a few counter steps of a heater are no heater day.
MAX_AUX_KWH = 0.1
# Heating-only hours a statistics day needs (as heating_curve).
MIN_STATISTICS_HOURS = 2
# Kelvin a lower heating curve is shown for.
LOWER_FLOW_KELVINS = (1, 2, 3)
# Own assumption: from this share of the heat counted without a return the
# attribute (and the card) says "flow only". Below it the factor is at most
# ~0.7 % too high (6.8 % at the whole heat, see the module), less than the
# look-back's own error; a single hour or day without a return (a gap in
# the return's statistics, a defrost hour) no longer marks the season.
FLOW_ONLY_NOTE_SHARE = 0.1
MONTH_MIN_DAYS = 7
SEASON_MIN_DAYS = 14
# Fraunhofer's reference period: November to March (Günther et al. 2026).
WINTER_FIRST_MONTH = 11
WINTER_LAST_MONTH = 3

TOO_FEW_DAYS = "too_few_days"
TOO_LITTLE_ELECTRICITY = "too_little_electricity"

# Why a diary day did not count (counted per period, diagnostics only).
SKIP_NO_ENERGY = "no_energy"
SKIP_LITTLE_HEATING = "little_heating"
SKIP_AUX = "aux"
SKIP_NO_OUTDOOR = "no_outdoor"
SKIP_SMALL_LIFT = "small_lift"
# Brine as the source, but the diary day has no brine mean while heating
# (the look-back fills it in when the statistics have it).
SKIP_NO_SOURCE = "no_source"

# What the Carnot source is (attribute `source_signal`): the outdoor air,
# or the brine of Signal.SOURCE_TEMP (same value).
SOURCE_OUTDOOR = "outdoor"
SOURCE_BRINE = "source_temp"


def carnot_cop(sink: float, source: float) -> float | None:
    """Carnot COP of heating between the temperatures in °C; None below the
    smallest lift."""
    lift = sink - source
    if lift < MIN_LIFT_K:
        return None
    return (sink + KELVIN) / lift


@dataclass(frozen=True)
class FactorDay:
    """What one diary day adds to the factor."""

    heat: float  # kWh heating
    electricity: float  # kWh heating, compressor while running
    sink: float  # °C
    source: float  # °C
    cop: float  # Carnot
    # Share of the heat whose sink is the flow temperature alone (no
    # spread, no return in the hour): 0 … 1.
    flow_only_share: float
    day_mean_source: bool  # no outdoor mean while heating
    from_statistics: bool = False  # hourly means, not the diary

    @property
    def flow_only(self) -> bool:
        """Part of the day counted without a return temperature."""
        return self.flow_only_share > 0


def factor_day(
    entry: Mapping[str, Any], source_signal: str = SOURCE_OUTDOOR
) -> FactorDay | str:
    """The day's contribution, or the reason it does not count. With
    `source_signal` SOURCE_BRINE the brine mean while heating, never the
    outdoor temperature."""
    energy = entry.get("energy") or {}
    heat = float(energy.get(f"{Kind.HEAT.value}_{Mode.HEATING.value}", 0.0))
    electricity = float(energy.get(f"{Kind.ELEC.value}_{Mode.HEATING.value}", 0.0))
    aux = float(energy.get(f"{Kind.AUX.value}_{Mode.HEATING.value}", 0.0))
    if heat <= 0 or electricity <= 0:
        return SKIP_NO_ENERGY
    flow = Mean.from_dict(entry.get("flow"))
    if flow.seconds < MIN_HEATING_SECONDS or flow.value is None:
        return SKIP_LITTLE_HEATING
    if aux > MAX_AUX_KWH:
        return SKIP_AUX
    spread = Mean.from_dict(entry.get("spread"))
    # A negative spread means swapped sensors (repair issue of its own).
    flow_only = spread.value is None or spread.seconds <= 0 or spread.value < 0
    sink = flow.value if flow_only else flow.value - spread.value / 2
    if source_signal == SOURCE_BRINE:
        brine = Mean.from_dict(entry.get("source_heating")).value
        if brine is None:
            return SKIP_NO_SOURCE
        day_mean, value = False, brine
    else:
        outdoor = Mean.from_dict(entry.get("outdoor_heating"))
        day_mean = outdoor.value is None
        value = entry.get("outdoor") if day_mean else outdoor.value
        if value is None:
            return SKIP_NO_OUTDOOR
    cop = carnot_cop(sink, float(value))
    if cop is None:
        return SKIP_SMALL_LIFT
    return FactorDay(
        heat, electricity, sink, float(value), cop, float(flow_only), day_mean
    )


def statistics_days(
    hours: Mapping[datetime, Totals],
    flow: Mapping[datetime, float],
    ret: Mapping[datetime, float],
    sources: Mapping[datetime, float],
    tz: tzinfo,
    *,
    with_aux: bool = False,
    flow_only: bool = False,
) -> dict[date, FactorDay | str]:
    """Days from the hourly statistics (look-back, see the module): the
    day's energy from all its hours, sink and source from its heating-only
    hours, weighted with their heat. `sources`: hourly means of the Carnot
    source, the outdoor temperature or, with SOURCE_BRINE, the brine.

    For the efficiency comparison (health.baseline_drop): `with_aux` keeps
    the days with backup heater electricity and adds it to the electricity
    (boundary H3); `flow_only` takes the flow alone as the sink on every
    day, so both seasons count alike when one of them lacks the return."""
    energy: dict[date, list[float]] = {}
    for hour, totals in hours.items():
        day = energy.setdefault(hour.astimezone(tz).date(), [0.0, 0.0, 0.0])
        day[0] += totals.get(Kind.HEAT, Mode.HEATING)
        day[1] += totals.get(Kind.ELEC, Mode.HEATING)
        day[2] += totals.get(Kind.AUX, Mode.HEATING)
    # Per day: heat, heat / Carnot COP, heat * sink, heat * source, hours,
    # heat of the hours without a return temperature.
    sums: dict[date, list[float]] = {}
    for hour, heat in heating_weights(hours).items():
        value, source = flow.get(hour), sources.get(hour)
        if value is None or source is None or not FLOW_MIN <= value <= FLOW_MAX:
            continue
        back = ret.get(hour)
        no_return = flow_only or back is None or back > value
        sink = value if no_return else (value + back) / 2
        if (cop := carnot_cop(sink, source)) is None:
            continue
        row = sums.setdefault(hour.astimezone(tz).date(), [0.0] * 6)
        row[0] += heat
        row[1] += heat / cop
        row[2] += heat * sink
        row[3] += heat * source
        row[4] += 1
        if no_return:
            row[5] += heat
    days: dict[date, FactorDay | str] = {}
    for day, (heat, electricity, aux) in energy.items():
        if heat <= 0 or electricity <= 0:
            days[day] = SKIP_NO_ENERGY
        elif aux > MAX_AUX_KWH and not with_aux:
            days[day] = SKIP_AUX
        elif (row := sums.get(day)) is None or row[4] < MIN_STATISTICS_HOURS:
            days[day] = SKIP_LITTLE_HEATING
        else:
            weight, ideal, sink, source, _, without_return = row
            days[day] = FactorDay(
                heat=heat,
                electricity=electricity + (aux if with_aux else 0.0),
                sink=sink / weight,
                source=source / weight,
                cop=weight / ideal,
                flow_only_share=without_return / weight,
                day_mean_source=False,
                from_statistics=True,
            )
    return days


@dataclass(frozen=True)
class EfficiencyFactor:
    """Carnot efficiency factor of a period; value None with a reason."""

    value: float | None
    days: int
    heat_kwh: float
    electricity_kwh: float
    sink: float | None  # °C, heat-weighted
    source: float | None  # °C, heat-weighted
    carnot_cop: float | None  # heat over ideal electricity
    flow_only_days: int  # days with at least some heat without a return
    day_mean_days: int
    statistics_days: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    reason: str | None = None
    # Heat counted without a return temperature (kWh, of heat_kwh).
    flow_only_kwh: float = 0.0
    # kWh a heating curve k kelvin lower would have saved (with a value).
    lower_flow_kwh: dict[int, float] = field(default_factory=dict)
    # SOURCE_OUTDOOR or SOURCE_BRINE (the module).
    source_signal: str = SOURCE_OUTDOOR

    @property
    def flow_only_share(self) -> float:
        """Share of the heat counted without a return temperature."""
        return self.flow_only_kwh / self.heat_kwh if self.heat_kwh > 0 else 0.0

    def as_attributes(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "days": self.days,
            "sink_temp": _round(self.sink, 1),
            "source_temp": _round(self.source, 1),
            "carnot_cop": _round(self.carnot_cop, 2),
            # "mean_flow_return" or "flow_only" (factor too high, see module),
            # the latter from FLOW_ONLY_NOTE_SHARE of the heat on.
            "sink": "flow_only"
            if self.flow_only_share >= FLOW_ONLY_NOTE_SHARE
            else "mean_flow_return",
            "flow_only_days": self.flow_only_days,
            "flow_only_percent": round(100 * self.flow_only_share, 1),
            "source": "day_mean" if self.day_mean_days else "while_heating",
            # "outdoor" or "source_temp" (brine/water, water/water).
            "source_signal": self.source_signal,
            # Days from the hourly statistics (look-back) among `days`.
            "days_from_statistics": self.statistics_days,
            "skipped_days": dict(sorted(self.skipped.items())),
            **self.lower_flow_attributes(),
        }

    def lower_flow_attributes(self) -> dict[str, Any]:
        """Saving of a heating curve 1, 2, 3 K lower: kWh and percent of the
        heating electricity (keys as strings for JSON)."""
        if self.value is None or not self.lower_flow_kwh:
            return {"lower_flow_kwh": None, "lower_flow_percent": None}
        return {
            "lower_flow_kwh": {
                str(k): round(v, 1) for k, v in self.lower_flow_kwh.items()
            },
            "lower_flow_percent": {
                str(k): round(100 * v / self.electricity_kwh, 1)
                for k, v in self.lower_flow_kwh.items()
            },
        }


def efficiency_factor(
    entries: Iterable[Mapping[str, Any]],
    first: date,
    last: date,
    *,
    min_days: int,
    min_electricity: float = 0.0,
    statistics: Mapping[date, FactorDay | str] | None = None,
    source_signal: str = SOURCE_OUTDOOR,
) -> EfficiencyFactor:
    """Factor over the days first … last (both included): a diary day that
    knows the outdoor temperature while heating, else the statistics day
    (`statistics_days`), else the diary day with the day mean. With
    `source_signal` SOURCE_BRINE: a diary day with the brine while heating, else
    the statistics day (built from the brine's hourly means by the
    caller); no day mean."""
    diary = {
        day: entry
        for entry in entries
        if first <= (day := date.fromisoformat(entry["day"])) <= last
    }
    statistics = statistics or {}
    counted: list[FactorDay] = []
    heat = electricity = ideal = sink = source = flow_only_kwh = 0.0
    days = flow_only = day_mean = from_statistics = 0
    skipped: dict[str, int] = {}
    for day in _dates(first, last):
        entry = diary.get(day)
        found: FactorDay | str | None = (
            None if entry is None else factor_day(entry, source_signal)
        )
        if found is None or found == SKIP_NO_SOURCE:
            found = statistics.get(day, found)
        elif (
            isinstance(found, FactorDay)
            and found.day_mean_source
            and isinstance(better := statistics.get(day), FactorDay)
        ):
            found = better
        if found is None:
            continue
        if isinstance(found, str):
            skipped[found] = skipped.get(found, 0) + 1
            continue
        days += 1
        counted.append(found)
        heat += found.heat
        electricity += found.electricity
        ideal += found.heat / found.cop
        sink += found.heat * found.sink
        source += found.heat * found.source
        flow_only += found.flow_only
        flow_only_kwh += found.heat * found.flow_only_share
        day_mean += found.day_mean_source
        from_statistics += found.from_statistics
    reason = None
    if days < min_days:
        reason = TOO_FEW_DAYS
    elif electricity < min_electricity:
        reason = TOO_LITTLE_ELECTRICITY
    value = None if reason else ideal / electricity
    return EfficiencyFactor(
        value=value,
        days=days,
        heat_kwh=heat,
        electricity_kwh=electricity,
        sink=sink / heat if heat else None,
        source=source / heat if heat else None,
        carnot_cop=heat / ideal if ideal else None,
        flow_only_days=flow_only,
        day_mean_days=day_mean,
        statistics_days=from_statistics,
        skipped=skipped,
        reason=reason,
        flow_only_kwh=flow_only_kwh,
        lower_flow_kwh={} if value is None else lower_flow_savings(counted, value),
        source_signal=source_signal,
    )


def lower_flow_savings(days: Iterable[FactorDay], factor: float) -> dict[int, float]:
    """kWh saved by a sink k kelvin lower, for each k of LOWER_FLOW_KELVINS
    (see the module)."""
    days = list(days)
    result: dict[int, float] = {}
    for kelvin in LOWER_FLOW_KELVINS:
        saved = 0.0
        for day in days:
            lower = carnot_cop(day.sink - kelvin, day.source)
            if lower is None:
                continue
            saved += day.heat / (factor * day.cop) - day.heat / (factor * lower)
        result[kelvin] = saved
    return result


def winter_year(day: date) -> int:
    """Year of the November that opens the winter of `day`'s heating year
    (July to June): from July on this year's, before July last year's."""
    return day.year if day.month >= 7 else day.year - 1


def winter_span(year: int, first: date, last: date) -> tuple[date, date] | None:
    """November of `year` to March of the next, the field test's period,
    clipped to first … last; None if nothing of it lies within."""
    start = max(date(year, WINTER_FIRST_MONTH, 1), first)
    end = min(date(year + 1, WINTER_LAST_MONTH, 31), last)
    return None if start > end else (start, end)


def factor_spans(
    season: date, previous: date, month: date, yesterday: date
) -> dict[str, tuple[date, date, int]]:
    """Periods of the sensor: name -> (first day, last day, minimum days).
    Season and month so far, the previous season, and the winters (November
    to March, compared with the field test): the one of yesterday's heating
    year (July to June) and the one before. Independent of the season start:
    a season from January would cut every winter in two. Clipped to the
    start of the previous season, where the loaded statistics begin."""
    previous_end = season - timedelta(days=1)
    spans = {
        "season": (season, yesterday, SEASON_MIN_DAYS),
        "month": (month, yesterday, MONTH_MIN_DAYS),
        "previous_season": (previous, previous_end, SEASON_MIN_DAYS),
    }
    year = winter_year(yesterday)
    for name, winter in (("winter", year), ("previous_winter", year - 1)):
        if (span := winter_span(winter, previous, yesterday)) is not None:
            spans[name] = (*span, SEASON_MIN_DAYS)
    return spans


def factor_attributes(
    factors: Mapping[str, EfficiencyFactor], price_eur_per_kwh: float | None = None
) -> dict[str, Any]:
    """Attributes of the sensor: the season in detail, the other periods as
    value, days and reason (None for a winter not begun yet)."""
    if (season := factors.get("season")) is None:
        return {}

    def short(name: str) -> dict[str, Any] | None:
        if (figure := factors.get(name)) is None:
            return None
        return {
            "value": _round(figure.value, 2),
            "days": figure.days,
            "reason": figure.reason,
            "lower_flow_kwh": figure.lower_flow_attributes()["lower_flow_kwh"],
        }

    return {
        **season.as_attributes(),
        "month": short("month"),
        "previous_season": short("previous_season"),
        # November to March, the period of the field test.
        "winter": short("winter"),
        "previous_winter": short("previous_winter"),
        # Air/water field values: not for a brine source (none of our own).
        "field_reference": field_reference()
        if season.source_signal == SOURCE_OUTDOOR
        else None,
        # Fixed electricity price for the euro of the lower heating curve.
        "price_eur_per_kwh": price_eur_per_kwh,
    }


LOWER_FLOW_KELVIN = 2  # the sensor "Heating curve 2 K lower"


def lower_flow_figure(
    factors: Mapping[str, EfficiencyFactor], price_eur_per_kwh: float | None = None
) -> dict[str, Any] | None:
    """Saving of a heating curve LOWER_FLOW_KELVIN lower: the previous
    season when it has one (a whole season), else the current season so far;
    euro with the fixed electricity price. None without either."""
    for period in ("previous_season", "season"):
        figure = factors.get(period)
        if figure is None:
            continue
        attributes = figure.lower_flow_attributes()
        kwh = (attributes["lower_flow_kwh"] or {}).get(str(LOWER_FLOW_KELVIN))
        if not kwh:
            continue
        return {
            "kwh": kwh,
            "period": period,
            "kelvin": LOWER_FLOW_KELVIN,
            "percent": attributes["lower_flow_percent"][str(LOWER_FLOW_KELVIN)],
            "eur": None
            if price_eur_per_kwh is None
            else round(kwh * price_eur_per_kwh, 2),
            "lower_flow_kwh": attributes["lower_flow_kwh"],
            "lower_flow_percent": attributes["lower_flow_percent"],
        }
    return None


def field_reference() -> dict[str, Any]:
    """The field values to compare with (attribute)."""
    return {
        "mean": FIELD_FACTOR,
        "min": FIELD_RANGE[0],
        "max": FIELD_RANGE[1],
        "units": FIELD_UNITS,
        "source": "Fraunhofer ISE WP-QS (air/water, space heating)",
        "period": "November to March",
    }


def _dates(first: date, last: date) -> Iterable[date]:
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


# Hot water colder (health check 4.14, DHW): what a hot water temperature
# k kelvin lower would have saved, per normal charge from its Carnot COP. The
# heat pump's own efficiency factor cancels out: same heat, same factor, so
# the compressor electricity scales with the Carnot COPs. Sink: mean of the
# storage temperature at the start and the highest during the charge (the
# condenser runs a few kelvin above it: rather a little too much saving);
# source: the outdoor hourly mean at the start (the brine's with
# SOURCE_BRINE, never the outdoor one then). Own assumptions: at least
# COLDER_DHW_MIN_CHARGES charges over COLDER_DHW_MIN_DAYS days.
COLDER_DHW_KELVIN = 2  # the sensor "Hot water 2 K colder"
COLDER_DHW_MIN_CHARGES = 10
COLDER_DHW_MIN_DAYS = 7.0
TOO_FEW_CHARGES = "too_few_charges"


@dataclass(frozen=True)
class DhwCharge:
    """What one normal hot water charge adds (charges.Charge, reduced)."""

    start: datetime
    electricity_kwh: float  # compressor, without the backup heater
    sink: float  # mean storage temperature during the charge, degC
    source: float  # outdoor (or brine) hourly mean at the start, degC


@dataclass(frozen=True)
class ColderDhw:
    """Saving of a hot water temperature k kelvin lower over a window."""

    charges: int
    days: float  # length of the window the charges stand for
    electricity_kwh: float
    saved_kwh: dict[int, float] = field(default_factory=dict)
    sink: float | None = None  # electricity-weighted means
    source: float | None = None
    reason: str | None = None
    source_signal: str = SOURCE_OUTDOOR

    def per_year(self, kelvin: int) -> float | None:
        if self.reason is not None or kelvin not in self.saved_kwh:
            return None
        return self.saved_kwh[kelvin] * 365 / self.days

    def as_attributes(self, price_eur_per_kwh: float | None = None) -> dict[str, Any]:
        per_year = {k: self.per_year(k) for k in LOWER_FLOW_KELVINS}
        known = self.reason is None
        main = per_year.get(COLDER_DHW_KELVIN)
        return {
            "kelvin": COLDER_DHW_KELVIN,
            "kwh_per_year": {str(k): _round(v, 0) for k, v in per_year.items()}
            if known
            else None,
            "percent": {
                str(k): round(100 * v / self.electricity_kwh, 1)
                for k, v in self.saved_kwh.items()
            }
            if known and self.electricity_kwh > 0
            else None,
            "eur_per_year": None
            if main is None or price_eur_per_kwh is None
            else round(main * price_eur_per_kwh, 2),
            "charges": self.charges,
            "days": round(self.days, 1),
            "electricity_kwh": round(self.electricity_kwh, 2),
            "sink_temp": _round(self.sink, 1),
            "source_temp": _round(self.source, 1),
            "source_signal": self.source_signal,
            "reason": self.reason,
        }


def colder_dhw(
    charges: Iterable[DhwCharge],
    start: datetime,
    end: datetime,
    source_signal: str = SOURCE_OUTDOOR,
) -> ColderDhw:
    """Saving of a hot water temperature 1, 2, 3 K lower over the charges
    starting in [start, end), projected per year by the window they cover
    (from the first charge on, at most end - start). `source_signal`
    names the source of the charges (attribute only)."""
    chosen = [c for c in charges if start <= c.start < end]
    counted = [c for c in chosen if carnot_cop(c.sink, c.source) is not None]
    days = (end - min((c.start for c in counted), default=end)).total_seconds()
    days /= 86400
    electricity = sum(c.electricity_kwh for c in counted)
    if len(counted) < COLDER_DHW_MIN_CHARGES or days < COLDER_DHW_MIN_DAYS:
        return ColderDhw(
            len(counted),
            days,
            electricity,
            reason=TOO_FEW_CHARGES,
            source_signal=source_signal,
        )
    saved: dict[int, float] = {}
    for kelvin in LOWER_FLOW_KELVINS:
        total = 0.0
        for c in counted:
            cop = carnot_cop(c.sink, c.source)
            lower = carnot_cop(c.sink - kelvin, c.source)
            if cop is None or lower is None:
                continue
            total += c.electricity_kwh * (1 - cop / lower)
        saved[kelvin] = total
    weight = electricity or 1.0
    return ColderDhw(
        charges=len(counted),
        days=days,
        electricity_kwh=electricity,
        saved_kwh=saved,
        sink=sum(c.sink * c.electricity_kwh for c in counted) / weight,
        source=sum(c.source * c.electricity_kwh for c in counted) / weight,
        source_signal=source_signal,
    )
