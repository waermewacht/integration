"""Heating curve check from the rooms: could the curve be lower? Pure Python.

docs/GESUNDHEITSCHECK.md 4.18. Wärmewacht sees what the heat pump delivers,
not whether the rooms are warm enough. With room temperatures (and where
known the valve openings) the question becomes answerable (simon42 95035
#220 ff.):

- A room whose valve throttles holds its setpoint whatever the curve: it
  only shows that the curve is high enough. What counts is the room with the
  valve open the widest.
- Thermostats regulate proportionally: a room a little below its setpoint
  with a half open valve is the controller at work, not a curve too low.

Per local day and room (rooms are HA areas; several thermometers of one
area are averaged, of several valves the widest counts, room_sources.py):
the mean of temperature minus target and the mean valve opening (%), sampled once a minute all day (RoomLog), written to
the diary. Per outdoor band (the day's mean outdoor temperature) over the
heating days of the last CHECK_DAYS days:

- "too_low": a room at least TOO_LOW_K below its target while its valve is
  near the highest opening seen for it (a valve may be limited below 100 %
  in its settings), or no valve is known;
- "lower_possible": every room at most HOLD_K below its target and either
  the widest valve stays at most THROTTLED_PERCENT open on average, or (no
  valve known: the rooms are lead rooms with open valves) every room at
  least WARM_K above its target;
- "fits" otherwise.

Without valves the warmest margin also gives an estimate in kelvin of flow:
a room dT too warm means the water may be dT * (1 + (flow - room) /
(room - outdoor)) cooler (heat balance of house and emitters, linear; a
radiator's exponent is left out). With valves no kelvin figure is given:
lower in steps of 1-2 K and watch the widest valve.

The thresholds are own assumptions (to be checked on users' data).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .averages import Mean

# A heating day: the compressor heated at least this long.
MIN_HEATING_SECONDS = 3600.0
# Days of the diary looked at, and heating days a band needs.
CHECK_DAYS = 21
MIN_BAND_DAYS = 3
# Bands of the day's mean outdoor temperature (°C): lower bound, label.
BANDS: tuple[tuple[float, float, str], ...] = (
    (-50.0, 0.0, "below_0"),
    (0.0, 5.0, "0_5"),
    (5.0, 10.0, "5_10"),
    (10.0, 20.0, "10_20"),
)
HOLD_K = 0.2  # at most this much below the target still holds it
TOO_LOW_K = 0.5  # clearly below the target
WARM_K = 0.5  # clearly above the target (rooms without valve data)
THROTTLED_PERCENT = 50.0  # widest valve at most half open on average
OPEN_SHARE = 0.9  # valve near the highest opening seen for the room

LOWER_POSSIBLE = "lower_possible"
FITS = "fits"
TOO_LOW = "too_low"
# Reasons without a verdict.
NO_ROOMS = "no_rooms"
TOO_FEW_DAYS = "too_few_days"


@dataclass
class RoomDay:
    """Today's means of one room."""

    delta: Mean = field(default_factory=Mean)  # temperature - target (K)
    valve: Mean = field(default_factory=Mean)  # opening (%)
    valve_max: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "delta": self.delta.as_dict(),
            "valve": self.valve.as_dict(),
            "valve_max": self.valve_max,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RoomDay:
        return cls(
            Mean.from_dict(data.get("delta")),
            Mean.from_dict(data.get("valve")),
            data.get("valve_max"),
        )


@dataclass
class RoomLog:
    """Today's room means, keyed by area id."""

    rooms: dict[str, RoomDay] = field(default_factory=dict)

    def add(
        self, room: str, delta: float | None, valve: float | None, seconds: float
    ) -> None:
        day = self.rooms.setdefault(room, RoomDay())
        if delta is not None:
            day.delta.add(delta, seconds)
        if valve is not None:
            day.valve.add(valve, seconds)
            day.valve_max = (
                valve if day.valve_max is None else max(day.valve_max, valve)
            )

    def as_dict(self) -> dict[str, Any]:
        return {room: day.as_dict() for room, day in self.rooms.items()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> RoomLog:
        return cls({k: RoomDay.from_dict(v) for k, v in (data or {}).items()})

    def diary_entry(self) -> dict[str, dict[str, Any]] | None:
        """The day's means for the diary (rounded), None without rooms."""
        result: dict[str, dict[str, Any]] = {}
        for room, day in self.rooms.items():
            if (delta := day.delta.value) is None:
                continue
            valve = day.valve.value
            result[room] = {
                "delta": round(delta, 2),
                "valve": None if valve is None else round(valve, 1),
                "valve_max": None if day.valve_max is None else round(day.valve_max, 1),
                "hours": round(day.delta.seconds / 3600, 1),
            }
        return result or None


@dataclass(frozen=True)
class RoomBand:
    """One room in one outdoor band."""

    room: str
    days: int
    delta: float  # mean over the days (K)
    valve: float | None  # mean opening (%)
    valve_ref: float | None  # highest daily opening seen for the room (%)


@dataclass(frozen=True)
class BandVerdict:
    band: str
    verdict: str
    days: int
    outdoor: float
    flow: float | None
    rooms: tuple[RoomBand, ...]
    # The room with the valve open the widest, and its mean opening (%).
    lead_room: str | None = None
    lead_valve: float | None = None
    estimate_k: float | None = None


@dataclass(frozen=True)
class CurveCheck:
    verdict: str | None  # LOWER_POSSIBLE / FITS / TOO_LOW, None: no verdict
    reason: str | None
    bands: tuple[BandVerdict, ...] = ()

    @property
    def problem(self) -> bool | None:
        if self.verdict is None:
            return None
        return self.verdict == LOWER_POSSIBLE

    def as_attributes(self, names: Mapping[str, str] | None = None) -> dict[str, Any]:
        names = names or {}
        return {
            "verdict": self.verdict,
            "bands": [
                {
                    "band": b.band,
                    "verdict": b.verdict,
                    "days": b.days,
                    "outdoor": round(b.outdoor, 1),
                    "lead_room": names.get(b.lead_room, b.lead_room)
                    if b.lead_room
                    else None,
                    "lead_valve": None
                    if b.lead_valve is None
                    else round(b.lead_valve, 1),
                    "estimate_kelvin": b.estimate_k,
                    "rooms": [
                        {
                            "room": names.get(r.room, r.room),
                            "days": r.days,
                            "delta": round(r.delta, 2),
                            "valve": None if r.valve is None else round(r.valve, 1),
                            "valve_max": r.valve_ref,
                        }
                        for r in b.rooms
                    ],
                }
                for b in self.bands
            ],
        }


def _heating_day(entry: Mapping[str, Any]) -> bool:
    seconds = (entry.get("activity_seconds") or {}).get("heating")
    if seconds is None:
        seconds = (entry.get("flow") or {}).get("seconds", 0.0)
    return float(seconds or 0.0) >= MIN_HEATING_SECONDS


def _band(outdoor: float) -> str | None:
    for low, high, label in BANDS:
        if low <= outdoor < high:
            return label
    return None


def _flow_mean(entry: Mapping[str, Any]) -> float | None:
    return Mean.from_dict(entry.get("flow")).value


def check(diary: Sequence[Mapping[str, Any]], rooms: Iterable[str]) -> CurveCheck:
    """The verdict from the diary's last CHECK_DAYS entries (newest last)."""
    wanted = set(rooms)
    if not wanted:
        return CurveCheck(None, NO_ROOMS)
    # Highest daily opening per room over the whole diary: the reference.
    ref: dict[str, float] = {}
    for entry in diary:
        for room, day in (entry.get("rooms") or {}).items():
            if room in wanted and day.get("valve_max") is not None:
                ref[room] = max(ref.get(room, 0.0), float(day["valve_max"]))
    per_band: dict[str, list[Mapping[str, Any]]] = {}
    for entry in diary[-CHECK_DAYS:]:
        if not entry.get("rooms") or entry.get("outdoor") is None:
            continue
        if not _heating_day(entry):
            continue
        if (label := _band(float(entry["outdoor"]))) is not None:
            per_band.setdefault(label, []).append(entry)
    bands = [
        _judge_band(label, per_band[label], wanted, ref)
        for _low, _high, label in BANDS
        if len(per_band.get(label, [])) >= MIN_BAND_DAYS
    ]
    if not bands:
        return CurveCheck(None, TOO_FEW_DAYS)
    verdicts = {b.verdict for b in bands}
    if TOO_LOW in verdicts:
        verdict = TOO_LOW
    elif LOWER_POSSIBLE in verdicts:
        verdict = LOWER_POSSIBLE
    else:
        verdict = FITS
    return CurveCheck(verdict, None, tuple(bands))


def _judge_band(
    label: str,
    days: Sequence[Mapping[str, Any]],
    wanted: set[str],
    ref: Mapping[str, float],
) -> BandVerdict:
    outdoor = sum(float(d["outdoor"]) for d in days) / len(days)
    flows = [f for d in days if (f := _flow_mean(d)) is not None]
    flow = sum(flows) / len(flows) if flows else None
    room_bands: list[RoomBand] = []
    for room in sorted(wanted):
        entries = [d["rooms"][room] for d in days if room in d["rooms"]]
        if not entries:
            continue
        hours = [max(float(e.get("hours") or 0.0), 0.1) for e in entries]
        delta = sum(e["delta"] * h for e, h in zip(entries, hours, strict=True))
        delta /= sum(hours)
        valves = [
            (e["valve"], h)
            for e, h in zip(entries, hours, strict=True)
            if e.get("valve") is not None
        ]
        valve = (
            sum(v * h for v, h in valves) / sum(h for _, h in valves)
            if valves
            else None
        )
        room_ref = ref.get(room)
        room_bands.append(
            RoomBand(
                room,
                len(entries),
                delta,
                valve,
                None if room_ref is None else round(room_ref, 1),
            )
        )
    with_valve = [r for r in room_bands if r.valve is not None]
    lead = max(with_valve, key=lambda r: r.valve or 0.0) if with_valve else None
    verdict = FITS
    estimate = None

    def wide_open(r: RoomBand) -> bool:
        if r.valve is None:
            return True  # no valve known: the user names lead rooms
        return bool(r.valve_ref) and r.valve >= OPEN_SHARE * r.valve_ref  # type: ignore[operator]

    too_low = [r for r in room_bands if r.delta <= -TOO_LOW_K and wide_open(r)]
    holds = bool(room_bands) and all(r.delta >= -HOLD_K for r in room_bands)
    if too_low:
        verdict = TOO_LOW
    elif holds and lead is not None:
        if (lead.valve or 0.0) <= THROTTLED_PERCENT:
            verdict = LOWER_POSSIBLE
    elif holds:
        margin = min(r.delta for r in room_bands)
        if margin >= WARM_K:
            verdict = LOWER_POSSIBLE
            estimate = _estimate(margin, flow, outdoor)
    return BandVerdict(
        label,
        verdict,
        len(days),
        outdoor,
        flow,
        tuple(room_bands),
        None if lead is None else lead.room,
        None if lead is None else lead.valve,
        estimate,
    )


def _estimate(margin: float, flow: float | None, outdoor: float) -> float | None:
    """Kelvin of flow the curve may come down at this outdoor temperature."""
    room = 21.0  # rooms' level for the ratio; the result hardly depends on it
    if flow is None or room - outdoor < 3:
        return None
    factor = 1 + max(flow - room, 0.0) / (room - outdoor)
    return round(margin * factor, 1)
