"""Energy before the setup, from hourly changes of the recorder statistics.

Pure Python, no HA imports. Without compressor states for the past, an hour's
electricity of a mode counts as standby when that mode delivered no heat in
the same hour (the standby of a Bosch heat pump runs into the heating
counter). Hours with a run keep their few minutes of standby as running.
A mode without a heat counter (`heat_modes`, ViCare) cannot tell standby:
its electricity counts as running.

Counters in whole kWh (Daikin over P1P2MQTT) step rarely, and the heat and
the electricity of one run step in different hours: a step of electricity
counts as running when its mode delivered heat within COARSE_WINDOW hours.
The same holds for one electricity meter for all modes (Signal.ELEC_TOTAL)
next to a heat meter in whole kWh (a separate heat meter, e.g. SensoStar).
Standby of some 30 W makes such a counter step about once a day; hardly any
of it is lost that way.

One heat meter for heating and hot water (Signal.HEAT_TOTAL): live it goes
to the mode running, but the long-term statistics hold no activity (the
recorder keeps its states some 10 days, used for the runs only). Before the
setup an hour's heat of that meter is split by the electricity per mode of
the same hour; without electricity per mode (one meter for both) it is
heating. A pure hour (only heating or only hot water) is exact, an hour with
both gets the same ratio for both.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime, timedelta

from .energy import Kind, Totals
from .model import (
    AUX_SIGNALS,
    BOILER_HEAT_SIGNALS,
    ELEC_SIGNALS,
    FUEL_SIGNALS,
    HEAT_SIGNALS,
    TOTAL_HEAT_MODES,
    Mode,
    Signal,
)

# Hourly change per signal: {signal: {hour start (UTC): kWh}}.
type HourlyChanges = Mapping[Signal, Mapping[datetime, float]]

# Heat above electricity up to this counts as no yield (float noise of a
# calculated heat value, kWh).
YIELD_EPSILON = 0.001

# Hours before and after an hour with heat in which electricity of the same
# mode still counts as running, for counters in whole kWh (own assumption;
# one real Daikin booked 10 of 23 kWh hot water electricity of a month as
# standby with the same hour only).
COARSE_WINDOW = 2
HOUR = timedelta(hours=1)

# Counters that decide heat against electricity (and so standby) in an hour,
# heating and hot water: per mode, or the common meters. Cooling and the
# backup heater are left out: a cooling meter added later must not cut the
# look-back.
BALANCE_MODES = (Mode.HEATING, Mode.DHW)
BALANCE_HEAT = (*(HEAT_SIGNALS[m] for m in BALANCE_MODES), Signal.HEAT_TOTAL)
BALANCE_ELEC = (*(ELEC_SIGNALS[m] for m in BALANCE_MODES), Signal.ELEC_TOTAL)


def balance_groups(configured: Collection[Signal]) -> list[set[Signal]]:
    """Counters whose hours only count together: heat and electricity of one
    mode; a common electricity meter with every heat meter, a common heat
    meter with every electricity meter. Overlapping groups merge."""
    heat = {s for s in BALANCE_HEAT if s in configured}
    elec = {s for s in BALANCE_ELEC if s in configured}
    groups = [
        group
        for mode in BALANCE_MODES
        if len(
            group := {
                s for s in (HEAT_SIGNALS[mode], ELEC_SIGNALS[mode]) if s in configured
            }
        )
        > 1
    ]
    if Signal.ELEC_TOTAL in elec and heat:
        groups.append({Signal.ELEC_TOTAL, *heat})
    if Signal.HEAT_TOTAL in heat and elec:
        groups.append({Signal.HEAT_TOTAL, *elec})
    merged: list[set[Signal]] = []
    for group in groups:
        for other in [m for m in merged if m & group]:
            group |= other
            merged.remove(other)
        merged.append(group)
    return merged


def common_hours(
    hourly: HourlyChanges, configured: Collection[Signal]
) -> HourlyChanges:
    """`hourly` with each balance group (`balance_groups`) from the first
    hour in which all of its counters have statistics; a group with a
    counter without any statistics is left out. Other signals stay.

    Before, an hour with electricity but no heat row looked like standby: a
    meter for all modes with years of statistics next to heat meters added
    a week ago made all of it standby (simon42 forum, 2026-11-11: heating and
    hot water alone right, both together with standby 0.02). Per mode, a hot
    water pair with shorter statistics (EMS-ESP after a change of its id
    format) does not cut the heating.
    """
    starts: dict[Signal, datetime | None] = {}
    for group in balance_groups(configured):
        start = (
            max(min(hourly[s]) for s in group)
            if all(hourly.get(s) for s in group)
            else None
        )
        starts.update(dict.fromkeys(group, start))
    if not starts:
        return hourly
    result: dict[Signal, Mapping[datetime, float]] = {}
    for signal, values in hourly.items():
        if signal not in starts:
            result[signal] = values
        elif (start := starts[signal]) is not None and (
            kept := {h: v for h, v in values.items() if h >= start}
        ):
            result[signal] = kept
    return result


def drop_together(
    hourly: HourlyChanges,
    left_out: Mapping[Signal, Collection[datetime]],
    configured: Collection[Signal],
) -> HourlyChanges:
    """`hourly` without the hours left out of a counter (plausible_hours) in
    every counter of its balance group (`balance_groups`).

    A heat hour left out reads as no heat (`by_hour`): the electricity of the
    same hour became standby, a glitch of the heat counter (jump and fall
    back) so two running hours of standby (simon42 PN, 2026-11-12: 32 kWh of
    standby in a week before the setup at some 4 W measured live). Without
    the heat that hour, its electricity is dropped as well. Other signals
    keep their hours.
    """
    drop: dict[Signal, set[datetime]] = {}
    for group in balance_groups(configured):
        hours = {h for s in group for h in left_out.get(s, ())}
        if hours:
            for signal in group:
                drop[signal] = hours
    if not drop:
        return hourly
    result: dict[Signal, Mapping[datetime, float]] = {}
    for signal, values in hourly.items():
        hours = drop.get(signal)
        kept = (
            values if not hours else {h: v for h, v in values.items() if h not in hours}
        )
        if kept:
            result[signal] = kept
    return result


def hour_totals(
    changes: Mapping[Signal, float],
    heat_modes: Collection[Mode] = tuple(Mode),
    heat_includes_electricity: bool = False,
    near_heat: Collection[Mode] = (),
) -> Totals:
    """Book one hour of changes; `heat_modes`: modes with a heat counter.

    Electricity of a mode is standby when the mode delivered no heat; where
    the source calculates heat as electricity plus environmental yield
    (Vaillant), when the heat does not exceed the electricity (no yield).
    `near_heat`: modes with heat in a neighbouring hour (counters in whole
    kWh), their electricity is running.
    """
    totals = Totals()
    heat_by_mode: dict[Mode, float] = {}
    common = split_heat_total(changes, heat_modes)
    for mode in Mode:
        heat = changes.get(HEAT_SIGNALS[mode], 0.0) + common.get(mode, 0.0)
        elec = changes.get(ELEC_SIGNALS[mode], 0.0)
        if mode not in heat_modes:
            standby = False
        elif heat_includes_electricity:
            standby = heat - elec <= YIELD_EPSILON
            if standby:
                heat = 0.0  # only the electricity "calculated" as heat
        else:
            standby = heat <= 0 and mode not in near_heat
        heat_by_mode[mode] = heat
        totals.add(Kind.HEAT, mode, heat)
        totals.add(Kind.STANDBY if standby else Kind.ELEC, mode, elec)
    for mode, signal in AUX_SIGNALS.items():
        totals.add(Kind.AUX, mode, changes.get(signal, 0.0))
    # Boiler of a hybrid system: as it is, never part of the heat that
    # decides standby, defrosts or the split of common meters above.
    for kind, signals in (
        (Kind.BOILER, BOILER_HEAT_SIGNALS),
        (Kind.FUEL, FUEL_SIGNALS),
    ):
        for mode, signal in signals.items():
            if kwh := changes.get(signal, 0.0):
                totals.add(kind, mode, kwh)
    # Electricity of defrosts counted apart: to the mode with the most heat
    # that hour (it ran, a defrost interrupted it), else heating.
    defrost = changes.get(Signal.ELEC_DEFROST, 0.0)
    if defrost:
        mode = max(heat_by_mode, key=lambda m: heat_by_mode[m])
        if heat_by_mode[mode] <= 0:
            mode = Mode.HEATING
        totals.add(Kind.ELEC, mode, defrost)
    totals.add(Kind.STANDBY, Mode.HEATING, changes.get(Signal.ELEC_STANDBY, 0.0))
    elec_total = changes.get(Signal.ELEC_TOTAL, 0.0)
    if elec_total:
        # One meter for all modes: split by the heat of the hour; an hour
        # without heat is standby, unless a counter in whole kWh had heat in
        # a neighbouring hour (to heating first, as the common heat meter).
        heat = sum(heat_by_mode.values())
        if heat <= 0:
            near = [m for m in Mode if m in near_heat]
            mode = Mode.HEATING if not near or Mode.HEATING in near else near[0]
            totals.add(Kind.ELEC if near else Kind.STANDBY, mode, elec_total)
        else:
            for mode, part in heat_by_mode.items():
                if part > 0:
                    totals.add(Kind.ELEC, mode, elec_total * part / heat)
    aux_total = changes.get(Signal.AUX_TOTAL, 0.0)
    if aux_total:
        # One backup heater for all modes: the mode with the most heat that hour.
        mode = max(heat_by_mode, key=lambda m: heat_by_mode[m])
        if heat_by_mode[mode] <= 0:
            mode = Mode.HEATING
        totals.add(Kind.AUX, mode, aux_total)
    return totals


def split_heat_total(
    changes: Mapping[Signal, float], heat_modes: Collection[Mode] = tuple(Mode)
) -> dict[Mode, float]:
    """The hour's heat of the common heat meter per mode: by the electricity
    per mode of the hour among the modes it covers, else heating."""
    heat = changes.get(Signal.HEAT_TOTAL, 0.0)
    if not heat:
        return {}
    modes = [
        m
        for m in TOTAL_HEAT_MODES
        if m in heat_modes and HEAT_SIGNALS[m] not in changes
    ]
    weights = {m: max(changes.get(ELEC_SIGNALS[m], 0.0), 0.0) for m in modes}
    total = sum(weights.values())
    if total <= 0:
        return {Mode.HEATING: heat}
    return {m: heat * w / total for m, w in weights.items() if w > 0}


def boiler_hours(hourly: HourlyChanges) -> dict[datetime, Totals]:
    """Boiler heat and fuel of every hour (hybrid system), nothing else."""
    result: dict[datetime, Totals] = {}
    for kind, signals in (
        (Kind.BOILER, BOILER_HEAT_SIGNALS),
        (Kind.FUEL, FUEL_SIGNALS),
    ):
        for mode, signal in signals.items():
            for hour, kwh in hourly.get(signal, {}).items():
                if kwh:
                    result.setdefault(hour, Totals()).add(kind, mode, kwh)
    return result


def by_hour(
    hourly: HourlyChanges,
    heat_modes: Collection[Mode] = tuple(Mode),
    heat_includes_electricity: bool = False,
) -> dict[datetime, Totals]:
    """Booked energy of every hour."""
    hours = sorted({h for values in hourly.values() for h in values})
    near = {} if heat_includes_electricity else near_heat_hours(hourly, heat_modes)
    return {
        hour: hour_totals(
            {signal: values.get(hour, 0.0) for signal, values in hourly.items()},
            heat_modes,
            heat_includes_electricity,
            [mode for mode, around in near.items() if hour in around],
        )
        for hour in hours
    }


def compare_on_source(
    start: datetime, end: datetime, switch: datetime, previous_day: bool
) -> bool:
    """Whether periods in [start, end) are compared on the source counters
    alone (booked by `by_hour` on both sides).

    Before `switch` the energy comes from the source counters, where standby
    is only told apart in hours without heat; after it from Wärmewacht's own
    sensors, which separate it by the compressor state. A unit that cycles has
    heat in nearly every hour, so its standby would count as running in the
    earlier period only and make it look less efficient. Sources with day
    values (`previous_day`) have no source hours: their own sensors only.
    """
    return not previous_day and start < switch < end


def coarse(values: Mapping[datetime, float]) -> bool:
    """Whether a counter steps in whole kWh: every hourly change integral."""
    steps = [v for v in values.values() if v]
    return bool(steps) and all(abs(v - round(v)) < 1e-6 for v in steps)


def near_heat_hours(
    hourly: HourlyChanges, heat_modes: Collection[Mode] = tuple(Mode)
) -> dict[Mode, set[datetime]]:
    """Per mode with counters in whole kWh, the hours within COARSE_WINDOW
    of an hour with heat."""
    near: dict[Mode, set[datetime]] = {}
    for mode in heat_modes:
        heat = hourly.get(HEAT_SIGNALS[mode])
        if heat is None and mode in TOTAL_HEAT_MODES:
            heat = hourly.get(Signal.HEAT_TOTAL)
        heat = heat or {}
        elec = hourly.get(ELEC_SIGNALS[mode])
        if elec is None:
            elec = hourly.get(Signal.ELEC_TOTAL, {})
        if not (coarse(heat) or coarse(elec)):
            continue
        near[mode] = {
            hour + k * HOUR
            for hour, kwh in heat.items()
            if kwh > 0
            for k in range(-COARSE_WINDOW, COARSE_WINDOW + 1)
        }
    return near


def bookable_hours(
    hourly: HourlyChanges, start: datetime, end: datetime
) -> tuple[list[datetime], datetime]:
    """Hours in [start, end) to book now, and where to continue next time.

    `hourly` covers a look-back before `start` as well: a signal with rows
    there is expected in every hour (its rows of the newest fetch may still
    be on their way). An hour is complete when all expected signals have a
    row. Missing hours before the newest complete one are gaps the source
    never filled; they are passed over. Without a complete hour nothing
    moves.
    """
    expected = [s for s, values in hourly.items() if values]
    hours = sorted({h for s in expected for h in hourly[s] if start <= h < end})
    complete = [h for h in hours if all(h in hourly[s] for s in expected)]
    if not complete:
        return [], start
    return complete, complete[-1] + HOUR


def energy_between(
    hourly: HourlyChanges,
    start: datetime | None,
    end: datetime,
    heat_modes: Collection[Mode] = tuple(Mode),
    heat_includes_electricity: bool = False,
) -> Totals:
    """Energy of the hours in [start, end) (start None: from the first hour)."""
    total = Totals()
    for hour, totals in by_hour(hourly, heat_modes, heat_includes_electricity).items():
        if (start is None or hour >= start) and hour < end:
            total = total + totals
    return total
