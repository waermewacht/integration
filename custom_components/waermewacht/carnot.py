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

Days with backup heater electricity are left out: whether a heat counter
holds the heater's heat depends on the source, and Fraunhofer's SPF 2 is
the heat pump alone. Without a return temperature the sink is the flow
temperature, which makes the Carnot COP smaller and the factor too high
(flow 35 °C, spread 5 K, outdoor 0 °C: 6.8 %); the attribute says so.
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
    flow_only: bool  # no spread: the sink is the flow temperature
    day_mean_source: bool  # no outdoor mean while heating
    from_statistics: bool = False  # hourly means, not the diary


def factor_day(entry: Mapping[str, Any]) -> FactorDay | str:
    """The day's contribution, or the reason it does not count."""
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
    outdoor = Mean.from_dict(entry.get("outdoor_heating"))
    day_mean = outdoor.value is None
    source = entry.get("outdoor") if day_mean else outdoor.value
    if source is None:
        return SKIP_NO_OUTDOOR
    cop = carnot_cop(sink, float(source))
    if cop is None:
        return SKIP_SMALL_LIFT
    return FactorDay(heat, electricity, sink, float(source), cop, flow_only, day_mean)


def statistics_days(
    hours: Mapping[datetime, Totals],
    flow: Mapping[datetime, float],
    ret: Mapping[datetime, float],
    outdoor: Mapping[datetime, float],
    tz: tzinfo,
) -> dict[date, FactorDay | str]:
    """Days from the hourly statistics (look-back, see the module): the
    day's energy from all its hours, sink and source from its heating-only
    hours, weighted with their heat."""
    energy: dict[date, list[float]] = {}
    for hour, totals in hours.items():
        day = energy.setdefault(hour.astimezone(tz).date(), [0.0, 0.0, 0.0])
        day[0] += totals.get(Kind.HEAT, Mode.HEATING)
        day[1] += totals.get(Kind.ELEC, Mode.HEATING)
        day[2] += totals.get(Kind.AUX, Mode.HEATING)
    # Per day: heat, heat / Carnot COP, heat * sink, heat * source, hours,
    # hours without a return temperature.
    sums: dict[date, list[float]] = {}
    for hour, heat in heating_weights(hours).items():
        value, source = flow.get(hour), outdoor.get(hour)
        if value is None or source is None or not FLOW_MIN <= value <= FLOW_MAX:
            continue
        back = ret.get(hour)
        flow_only = back is None or back > value
        sink = value if flow_only else (value + back) / 2
        if (cop := carnot_cop(sink, source)) is None:
            continue
        row = sums.setdefault(hour.astimezone(tz).date(), [0.0] * 6)
        row[0] += heat
        row[1] += heat / cop
        row[2] += heat * sink
        row[3] += heat * source
        row[4] += 1
        row[5] += flow_only
    days: dict[date, FactorDay | str] = {}
    for day, (heat, electricity, aux) in energy.items():
        if heat <= 0 or electricity <= 0:
            days[day] = SKIP_NO_ENERGY
        elif aux > MAX_AUX_KWH:
            days[day] = SKIP_AUX
        elif (row := sums.get(day)) is None or row[4] < MIN_STATISTICS_HOURS:
            days[day] = SKIP_LITTLE_HEATING
        else:
            weight, ideal, sink, source, _, flow_only = row
            days[day] = FactorDay(
                heat=heat,
                electricity=electricity,
                sink=sink / weight,
                source=source / weight,
                cop=weight / ideal,
                flow_only=flow_only > 0,
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
    flow_only_days: int
    day_mean_days: int
    statistics_days: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    reason: str | None = None

    def as_attributes(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "days": self.days,
            "sink_temp": _round(self.sink, 1),
            "source_temp": _round(self.source, 1),
            "carnot_cop": _round(self.carnot_cop, 2),
            # "mean_flow_return" or "flow_only" (factor too high, see module).
            "sink": "flow_only" if self.flow_only_days else "mean_flow_return",
            "source": "day_mean" if self.day_mean_days else "while_heating",
            # Days from the hourly statistics (look-back) among `days`.
            "days_from_statistics": self.statistics_days,
            "skipped_days": dict(sorted(self.skipped.items())),
        }


def efficiency_factor(
    entries: Iterable[Mapping[str, Any]],
    first: date,
    last: date,
    *,
    min_days: int,
    min_electricity: float = 0.0,
    statistics: Mapping[date, FactorDay | str] | None = None,
) -> EfficiencyFactor:
    """Factor over the days first … last (both included): a diary day that
    knows the outdoor temperature while heating, else the statistics day
    (`statistics_days`), else the diary day with the day mean."""
    diary = {
        day: entry
        for entry in entries
        if first <= (day := date.fromisoformat(entry["day"])) <= last
    }
    statistics = statistics or {}
    heat = electricity = ideal = sink = source = 0.0
    days = flow_only = day_mean = from_statistics = 0
    skipped: dict[str, int] = {}
    for day in _dates(first, last):
        entry = diary.get(day)
        found: FactorDay | str | None = None if entry is None else factor_day(entry)
        if found is None or (isinstance(found, FactorDay) and found.day_mean_source):
            better = statistics.get(day)
            if isinstance(better, FactorDay) or found is None:
                found = better
        if found is None:
            continue
        if isinstance(found, str):
            skipped[found] = skipped.get(found, 0) + 1
            continue
        days += 1
        heat += found.heat
        electricity += found.electricity
        ideal += found.heat / found.cop
        sink += found.heat * found.sink
        source += found.heat * found.source
        flow_only += found.flow_only
        day_mean += found.day_mean_source
        from_statistics += found.from_statistics
    reason = None
    if days < min_days:
        reason = TOO_FEW_DAYS
    elif electricity < min_electricity:
        reason = TOO_LITTLE_ELECTRICITY
    return EfficiencyFactor(
        value=None if reason else ideal / electricity,
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
    )


def winter_span(first: date, last: date) -> tuple[date, date] | None:
    """The first November to March within first … last (clipped to it),
    the field test's period; None if it has not begun yet."""
    start = date(first.year, WINTER_FIRST_MONTH, 1)
    if start < first:
        start = date(first.year + 1, WINTER_FIRST_MONTH, 1)
    end = min(date(start.year + 1, WINTER_LAST_MONTH, 31), last)
    return None if start > end else (start, end)


def factor_spans(
    season: date, previous: date, month: date, yesterday: date
) -> dict[str, tuple[date, date, int]]:
    """Periods of the sensor: name -> (first day, last day, minimum days).
    Season and month so far, the previous season, and the winter (November
    to March, compared with the field test) of both."""
    previous_end = season - timedelta(days=1)
    spans = {
        "season": (season, yesterday, SEASON_MIN_DAYS),
        "month": (month, yesterday, MONTH_MIN_DAYS),
        "previous_season": (previous, previous_end, SEASON_MIN_DAYS),
    }
    for name, first, last in (
        ("winter", season, yesterday),
        ("previous_winter", previous, previous_end),
    ):
        if (span := winter_span(first, last)) is not None:
            spans[name] = (*span, SEASON_MIN_DAYS)
    return spans


def factor_attributes(factors: Mapping[str, EfficiencyFactor]) -> dict[str, Any]:
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
        }

    return {
        **season.as_attributes(),
        "month": short("month"),
        "previous_season": short("previous_season"),
        # November to March, the period of the field test.
        "winter": short("winter"),
        "previous_winter": short("previous_winter"),
        "field_reference": field_reference(),
    }


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
