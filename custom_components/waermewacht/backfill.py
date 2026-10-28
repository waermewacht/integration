"""Energy before the setup, from hourly changes of the recorder statistics.

Pure Python, no HA imports. Without compressor states for the past, an hour's
electricity of a mode counts as standby when that mode delivered no heat in
the same hour (the standby of a Bosch heat pump runs into the heating
counter). Hours with a run keep their few minutes of standby as running.
A mode without a heat counter (`heat_modes`, ViCare) cannot tell standby:
its electricity counts as running.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime, timedelta

from .energy import Kind, Totals
from .model import AUX_SIGNALS, ELEC_SIGNALS, HEAT_SIGNALS, Mode, Signal

# Hourly change per signal: {signal: {hour start (UTC): kWh}}.
type HourlyChanges = Mapping[Signal, Mapping[datetime, float]]

# Heat above electricity up to this counts as no yield (float noise of a
# calculated heat value, kWh).
YIELD_EPSILON = 0.001
HOUR = timedelta(hours=1)


def hour_totals(
    changes: Mapping[Signal, float],
    heat_modes: Collection[Mode] = tuple(Mode),
    heat_includes_electricity: bool = False,
) -> Totals:
    """Book one hour of changes; `heat_modes`: modes with a heat counter.

    Electricity of a mode is standby when the mode delivered no heat; where
    the source calculates heat as electricity plus environmental yield
    (Vaillant), when the heat does not exceed the electricity (no yield).
    """
    totals = Totals()
    heat_by_mode: dict[Mode, float] = {}
    for mode in Mode:
        heat = changes.get(HEAT_SIGNALS[mode], 0.0)
        elec = changes.get(ELEC_SIGNALS[mode], 0.0)
        if mode not in heat_modes:
            standby = False
        elif heat_includes_electricity:
            standby = heat - elec <= YIELD_EPSILON
            if standby:
                heat = 0.0  # only the electricity "calculated" as heat
        else:
            standby = heat <= 0
        heat_by_mode[mode] = heat
        totals.add(Kind.HEAT, mode, heat)
        totals.add(Kind.STANDBY if standby else Kind.ELEC, mode, elec)
    for mode, signal in AUX_SIGNALS.items():
        totals.add(Kind.AUX, mode, changes.get(signal, 0.0))
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
        # without heat is standby.
        heat = sum(heat_by_mode.values())
        if heat <= 0:
            totals.add(Kind.STANDBY, Mode.HEATING, elec_total)
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


def by_hour(
    hourly: HourlyChanges,
    heat_modes: Collection[Mode] = tuple(Mode),
    heat_includes_electricity: bool = False,
) -> dict[datetime, Totals]:
    """Booked energy of every hour."""
    hours = sorted({h for values in hourly.values() for h in values})
    return {
        hour: hour_totals(
            {signal: values.get(hour, 0.0) for signal, values in hourly.items()},
            heat_modes,
            heat_includes_electricity,
        )
        for hour in hours
    }


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
