"""Energy before the setup, from hourly changes of the recorder statistics.

Pure Python, no HA imports. Without compressor states for the past, an hour's
electricity of a mode counts as standby when that mode delivered no heat in
the same hour (the standby of a Bosch heat pump runs into the heating
counter). Hours with a run keep their few minutes of standby as running.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from .energy import Kind, Totals
from .model import AUX_SIGNALS, ELEC_SIGNALS, HEAT_SIGNALS, Mode, Signal

# Hourly change per signal: {signal: {hour start (UTC): kWh}}.
type HourlyChanges = Mapping[Signal, Mapping[datetime, float]]


def hour_totals(changes: Mapping[Signal, float]) -> Totals:
    """Book one hour of changes."""
    totals = Totals()
    heat_by_mode: dict[Mode, float] = {}
    for mode in Mode:
        heat = changes.get(HEAT_SIGNALS[mode], 0.0)
        heat_by_mode[mode] = heat
        totals.add(Kind.HEAT, mode, heat)
        elec = changes.get(ELEC_SIGNALS[mode], 0.0)
        totals.add(Kind.STANDBY if heat <= 0 else Kind.ELEC, mode, elec)
    for mode, signal in AUX_SIGNALS.items():
        totals.add(Kind.AUX, mode, changes.get(signal, 0.0))
    aux_total = changes.get(Signal.AUX_TOTAL, 0.0)
    if aux_total:
        # One backup heater for all modes: the mode with the most heat that hour.
        mode = max(heat_by_mode, key=lambda m: heat_by_mode[m])
        if heat_by_mode[mode] <= 0:
            mode = Mode.HEATING
        totals.add(Kind.AUX, mode, aux_total)
    return totals


def by_hour(hourly: HourlyChanges) -> dict[datetime, Totals]:
    """Booked energy of every hour."""
    hours = sorted({h for values in hourly.values() for h in values})
    return {
        hour: hour_totals(
            {signal: values.get(hour, 0.0) for signal, values in hourly.items()}
        )
        for hour in hours
    }


def energy_between(
    hourly: HourlyChanges, start: datetime | None, end: datetime
) -> Totals:
    """Energy of the hours in [start, end) (start None: from the first hour)."""
    total = Totals()
    for hour, totals in by_hour(hourly).items():
        if (start is None or hour >= start) and hour < end:
            total = total + totals
    return total
