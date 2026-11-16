"""Rooms of the heating curve check (rooms.py) from Home Assistant areas.

The settings name thermostats (climate) and thermometers for the rooms and
optionally valve sensors; the area of each entity (its own, else its
device's) groups them into rooms, so several valves of one room (e.g. the
channels of a floor heating actuator) need no form of their own. A climate
entity gives the room temperature (`current_temperature`), the target
(`temperature`) and, where the integration reports it, the valve opening
(`valve_position`, %; a Homematic IP heating group reports the widest
channel of its floor heating controllers or radiator thermostats). Valve
sensors need an area of their own where their device sits elsewhere (the
channels of a floor heating controller in the utility room). Thermometers in an area take precedence
over the thermostats' own temperature. A fixed wish temperature replaces the
thermostats' targets (a thermostat set high on purpose to keep its valve
open, simon42 95035 #238).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

VALVE_ATTRIBUTE = "valve_position"


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
        if (value := _number(attributes.get(VALVE_ATTRIBUTE))) is not None:
            valves.append(value)
            reading.valve_from.append(entity_id)
    for entity_id in sources.thermometers:
        state = get(entity_id)
        if state is not None and (value := _number(state.state)) is not None:
            temps.append(value)
            reading.temp_from.append(entity_id)
    for entity_id in sources.valves:
        state = get(entity_id)
        if state is not None and (value := _number(state.state)) is not None:
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
