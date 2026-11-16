"""Rooms of the heating curve check (rooms.py) from Home Assistant areas.

The settings name thermostats (climate) and thermometers for the rooms and
optionally valve sensors; the area of each entity (its own, else its
device's) groups them into rooms, so several valves of one room (e.g. the
channels of a floor heating actuator) need no form of their own. A climate
entity gives the room temperature (`current_temperature`), the target
(`temperature`) and, where the integration reports it, the valve opening in
% (VALVE_ATTRIBUTES: `valve_position` of a Homematic IP heating group via
hcu_integration, the widest channel of its floor heating controllers or
radiator thermostats; `heating_power_request` of a Netatmo valve room, 0-100;
`pulse_width_modulation` of an Uponor room, the actuators' PWM share in %;
research 16.11.). Valve entities are sensors or numbers in %, numbers 0-99
without a unit (Z-Wave "Valve control") or entities of the valve domain
(`current_position`, 0-100; Bosch Smart Home). They need an
area of their own where their device sits elsewhere (the channels of a floor
heating controller in the utility room). Thermometers in an area take
precedence over the thermostats' own temperature. A fixed wish temperature replaces the
thermostats' targets (a thermostat set high on purpose to keep its valve
open, simon42 95035 #238).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

# Climate attributes with the valve opening (or the heating demand) in %.
VALVE_ATTRIBUTES = ("valve_position", "heating_power_request", "pulse_width_modulation")
# The position of an entity of the valve domain (0-100).
VALVE_POSITION = "current_position"
# Without any valve opening: the climate's action (heating or not) gives the
# share of time a thermostat heats (all thermostats report hvac_action).
HVAC_ACTION = "hvac_action"
HEATING_ACTIONS = frozenset({"heating", "preheating"})
# Highest level of a Z-Wave Multilevel Switch (fully open).
ZWAVE_LEVEL_MAX = 99
# Entities in a room's area that look like a valve opening (check step).
VALVE_WORDS = ("valve", "ventil", "heating_demand", "stellantrieb")


def climate_valve(attributes: Mapping[str, Any]) -> float | None:
    """The valve opening a climate entity reports, if any."""
    for key in VALVE_ATTRIBUTES:
        if (value := _number(attributes.get(key))) is not None:
            return value
    return None


def level_number(state: State) -> bool:
    """A number without a unit from 0 to 99: the level of a Z-Wave Multilevel
    Switch ("Valve control" of a Z-Wave thermostat, 99 = fully open; Eurotronic
    Spirit Z-Wave Plus manual 6.5: the valve opening in percent)."""
    attributes = state.attributes
    return (
        state.domain == "number"
        and not attributes.get("unit_of_measurement")
        and _number(attributes.get("min")) == 0
        and _number(attributes.get("max")) == ZWAVE_LEVEL_MAX
    )


def valve_value(state: State) -> float | None:
    """Opening of a valve entity in %: the state of a sensor or number in %,
    a Z-Wave level 0-99, the position of a valve."""
    if state.domain == "valve":
        return _number(state.attributes.get(VALVE_POSITION))
    value = _number(state.state)
    if value is not None and level_number(state):
        return min(value * 100 / ZWAVE_LEVEL_MAX, 100.0)
    return value


def valve_candidates(
    hass: HomeAssistant, area: str, chosen: Iterable[str]
) -> list[tuple[str, bool]]:
    """Entities in the area (their own or their device's) that look like a
    valve opening and are not chosen: (entity_id, disabled). For the check
    step: some integrations create them disabled or as diagnostics
    (Homematic IP Local, ViCare, Zigbee `pi_heating_demand`)."""
    skip = set(chosen)
    found = []
    for entry in er.async_get(hass).entities.values():
        if entry.entity_id in skip or entry.domain not in ("sensor", "number", "valve"):
            continue
        if entry.domain == "sensor" and entry.unit_of_measurement != "%":
            continue
        if entry.domain == "number" and entry.unit_of_measurement not in ("%", None):
            continue
        words = " ".join(
            str(x or "")
            for x in (entry.entity_id, entry.translation_key, entry.original_name)
        ).lower()
        if not any(word in words for word in VALVE_WORDS):
            continue
        if area_of(hass, entry.entity_id) != area:
            continue
        found.append((entry.entity_id, entry.disabled_by is not None))
    return sorted(found)


@dataclass
class RoomSources:
    """The entities of one room (area)."""

    climates: list[str] = field(default_factory=list)
    thermometers: list[str] = field(default_factory=list)
    valves: list[str] = field(default_factory=list)


@dataclass
class RoomMap:
    """Rooms by area id, their names, and what found no room."""

    rooms: dict[str, RoomSources] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    # Entities without an area, valves in an area without a room entity.
    no_area: list[str] = field(default_factory=list)
    no_room: list[str] = field(default_factory=list)


def area_of(hass: HomeAssistant, entity_id: str) -> str | None:
    """The entity's area, else its device's."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return None
    if entry.area_id:
        return entry.area_id
    if entry.device_id and (device := dr.async_get(hass).async_get(entry.device_id)):
        return device.area_id
    return None


def resolve_rooms(
    hass: HomeAssistant, room_entities: Iterable[str], valve_entities: Iterable[str]
) -> RoomMap:
    result = RoomMap()
    areas = ar.async_get(hass)
    for entity_id in room_entities:
        if (area := area_of(hass, entity_id)) is None:
            result.no_area.append(entity_id)
            continue
        sources = result.rooms.setdefault(area, RoomSources())
        if entity_id.startswith("climate."):
            sources.climates.append(entity_id)
        else:
            sources.thermometers.append(entity_id)
    for entity_id in valve_entities:
        area = area_of(hass, entity_id)
        if area is None:
            result.no_area.append(entity_id)
        elif area not in result.rooms:
            result.no_room.append(entity_id)
        else:
            result.rooms[area].valves.append(entity_id)
    for area in result.rooms:
        entry = areas.async_get_area(area)
        result.names[area] = entry.name if entry else area
    return result


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return None
    return number


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


@dataclass
class RoomReading:
    """What one room shows now, and from which entities."""

    temp: float | None = None
    temp_from: list[str] = field(default_factory=list)
    target: float | None = None
    target_from: list[str] = field(default_factory=list)
    valve: float | None = None
    valve_from: list[str] = field(default_factory=list)
    # The valve is the heating share: 100 while a thermostat heats, else 0.
    share: bool = False
    off: bool = False  # a thermostat is switched off


def read_room(
    get: Callable[[str], State | None],
    sources: RoomSources,
    wish: float | None,
) -> RoomReading:
    """The room now. Thermometers take precedence over the thermostats'
    temperature; the wish replaces their targets. Several valves: the widest
    counts (a Homematic IP heating group reports the widest of its channels
    the same way, hcu_integration climate.py). `get`: hass.states.get."""
    reading = RoomReading()
    temps: list[float] = []
    targets: list[float] = []
    valves: list[float] = []
    climate_temps: list[float] = []
    climate_temp_from: list[str] = []
    actions: dict[str, str] = {}
    # Any valve source at all (even without a value this minute): no share.
    has_valve = bool(sources.valves)
    for entity_id in sources.climates:
        state = get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            continue
        if state.state == STATE_OFF:
            reading.off = True
            continue
        attributes = state.attributes
        if (value := _number(attributes.get("current_temperature"))) is not None:
            climate_temps.append(value)
            climate_temp_from.append(entity_id)
        if (value := _number(attributes.get("temperature"))) is not None:
            targets.append(value)
            reading.target_from.append(entity_id)
        if (value := climate_valve(attributes)) is not None:
            valves.append(value)
            reading.valve_from.append(entity_id)
        has_valve = has_valve or any(k in attributes for k in VALVE_ATTRIBUTES)
        if isinstance(action := attributes.get(HVAC_ACTION), str):
            actions[entity_id] = action
    for entity_id in sources.thermometers:
        state = get(entity_id)
        if state is not None and (value := _number(state.state)) is not None:
            temps.append(value)
            reading.temp_from.append(entity_id)
    for entity_id in sources.valves:
        state = get(entity_id)
        if state is not None and (value := valve_value(state)) is not None:
            valves.append(value)
            reading.valve_from.append(entity_id)
    if temps:
        reading.temp = _mean(temps)
    else:
        reading.temp = _mean(climate_temps)
        reading.temp_from = climate_temp_from
    if wish is not None:
        reading.target = wish
        reading.target_from = []
    else:
        reading.target = _mean(targets)
    reading.valve = max(valves) if valves else None
    if reading.valve is None and not has_valve and actions:
        # No valve opening anywhere in the room: whether a thermostat heats
        # (TP-Link Kasa KE100 and others report only that). Sampled each
        # minute, the day's mean is the share of time it heats.
        heating = [e for e, a in actions.items() if a in HEATING_ACTIONS]
        reading.valve = 100.0 if heating else 0.0
        reading.valve_from = heating or list(actions)
        reading.share = True
    return reading


def sample_room(
    get: Callable[[str], State | None],
    sources: RoomSources,
    wish: float | None,
) -> tuple[float | None, float | None]:
    """Temperature minus target (K) and valve opening (%) of a room now;
    None where unknown. A thermostat switched off takes its room out."""
    reading = read_room(get, sources, wish)
    if reading.off:
        return None, None
    if reading.temp is None or reading.target is None:
        return None, reading.valve
    return reading.temp - reading.target, reading.valve
