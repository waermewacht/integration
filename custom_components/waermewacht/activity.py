"""The activity from several entities. Pure Python, no Home Assistant imports.

Most sources have one activity entity (EMS-ESP `hpactivity`). Others spread
it over flags (Stiebel ISG: defrost, hot water, cooling, heating as binary
sensors) or need a second entity (HeishaMon: the 3-way valve says room or
tank; whether the room is heated or cooled is the set operating mode, and
the defrost is a switch).

Rule: an "on" flag wins, in the order defrost, hot water, cooling, heating
(a defrost runs while heating is requested; hot water has priority over
heating). Then the activity entity, where "heating" becomes "cooling" while
the set mode cools. With flags only, all flags off is OFF. A flag that could
still decide but is unknown makes the result unknown (None) unless an
activity entity is there to fall back on.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from .model import Activity, Signal

FLAGS: tuple[tuple[Signal, Activity], ...] = (
    (Signal.DEFROST_FLAG, Activity.DEFROST),
    (Signal.DHW_FLAG, Activity.DHW),
    (Signal.COOLING_FLAG, Activity.COOLING),
    (Signal.HEATING_FLAG, Activity.HEATING),
)
ON = ("on", "true", "1")
OFF = ("off", "false", "0")
# Words of a set operating mode that cools (HeishaMon "Cool", "Auto(Cool)").
COOLING_WORDS = ("cool", "kühl")


def cooling_mode(state: str | None) -> bool:
    """Whether a set operating mode means cooling."""
    text = (state or "").casefold()
    return any(word in text for word in COOLING_WORDS)


def combine(
    activity: Activity | None,
    states: Mapping[Signal, str | None],
    configured: Collection[Signal],
) -> Activity | None:
    """Activity from the activity entity (already parsed) and the parts.

    `states` holds the raw states of the configured parts; `configured` the
    signals with an entity (ACTIVITY among them if there is one).
    """
    fallback = Signal.ACTIVITY in configured
    flags = [(s, a) for s, a in FLAGS if s in configured]
    for signal, flag_activity in flags:
        state = (states.get(signal) or "").strip().casefold()
        if state in ON:
            return flag_activity
        if state not in OFF and not fallback:
            return None
    if fallback:
        if (
            activity is Activity.HEATING
            and Signal.COOLING_MODE in configured
            and cooling_mode(states.get(Signal.COOLING_MODE))
        ):
            return Activity.COOLING
        return activity
    return Activity.OFF if flags else None
