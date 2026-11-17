"""Short summary of an entry at the top of its settings form (Markdown).

Pure Python, no Home Assistant imports. What the entry reads and how it
calculates, and what is missing with its consequence, only where it
matters. The settings form shows it through a description placeholder: the
text is not translated by Home Assistant, so it comes in German or English
here (`de` for a German Home Assistant, English otherwise).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from .allocation import PROPORTIONAL, rule_for
from .const import (
    CONF_ANALYSIS_FROM,
    CONF_BATTERY_CHARGED_ENTITY,
    CONF_BOILER_EFFICIENCY,
    CONF_BOILER_TYPE,
    CONF_CRITICAL_RUN,
    CONF_DESIGN_TEMP,
    CONF_ELECTRICITY_BASE_PRICE,
    CONF_ELECTRICITY_PRICE,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_FEED_IN_ENTITY,
    CONF_FLOW_IN_CIRCUIT,
    CONF_GAS_BASE_PRICE,
    CONF_GAS_PRICE,
    CONF_GRID_IMPORT_ENTITY,
    CONF_MANUAL_UNIT,
    CONF_OIL_PRICE,
    CONF_PRICE_CHANGES,
    CONF_PV_ENTITY,
    CONF_SEASON_START,
    CONF_SHORT_RUN,
    CONF_STARTS_PER_DAY,
    CONF_STARTS_PER_HOUR,
    DEFAULT_CRITICAL_RUN_MINUTES,
    DEFAULT_SEASON_START_MONTH,
    DEFAULT_SHORT_RUN_MINUTES,
    DEFAULT_STARTS_PER_HOUR,
    GAS_DHW,
    GAS_HEATING,
    GAS_TOTAL,
    TANK,
)
from .costs import BOILER_EFFICIENCY_HS
from .dated import CHANGE_FROM, analysis_day, sorted_changes
from .model import (
    AUX_SIGNALS,
    ELEC_SIGNALS,
    Mode,
    Signal,
    has_activity,
    has_boiler,
    has_elec,
    has_heat,
    total_heat_modes,
)
from .oil import efficiency as boiler_type_efficiency

# (English, German).
T = {
    "rooms": ("Heating curve check", "Heizkurve prüfen"),
    "thermostat": ("thermostat", "Thermostat"),
    "thermometer": ("thermometer", "Thermometer"),
    "valves": ("valves", "Ventile"),
    "valve_reported": ("valve reported", "Ventil mitgemeldet"),
    "target_entity": ("setpoint entity", "Soll-Entität"),
    "heating_share": ("heating share", "Heizanteil"),
    "check_share_on": (
        "heating share instead of a valve: heating now",
        "Heizanteil statt Ventil: heizt gerade",
    ),
    "check_share_off": (
        "heating share instead of a valve: not heating now",
        "Heizanteil statt Ventil: heizt gerade nicht",
    ),
    "no_area": ("without an area, not counted", "ohne Bereich, zählt nicht"),
    "no_room": (
        "valve without a room in its area",
        "Ventil ohne Raum in seinem Bereich",
    ),
    "check_from": ("from", "aus"),
    "check_target": ("target", "Soll"),
    "check_valve": ("valve", "Ventil"),
    "check_wish": ("wish temperature", "Wunschtemperatur"),
    "check_no_valve": (
        "no valve known: counts as fully open (lead room)",
        "kein Ventil bekannt: zählt als ganz offen (Leitraum)",
    ),
    "check_no_temp": ("no temperature yet", "noch keine Temperatur"),
    "check_found": (
        "found in the area, not chosen",
        "im Bereich gefunden, nicht eingetragen",
    ),
    "check_disabled": ("disabled", "deaktiviert"),
    "check_enable": (
        "To use a disabled entity, enable it in its settings first, then add it under valve openings.",
        "Eine deaktivierte Entität zuerst in ihren Einstellungen aktivieren, dann unter Ventilöffnungen eintragen.",
    ),
    "check_no_target": (
        "no target: enter a wish temperature",
        "kein Soll: Wunschtemperatur eintragen",
    ),
    "check_off": (
        "thermostat off: the room does not count meanwhile",
        "Thermostat aus: der Raum zählt solange nicht",
    ),
    "check_no_area": (
        "Without an area, not counted",
        "Ohne Bereich, zählt nicht",
    ),
    "check_no_area_hint": (
        "give the entity or its device an area",
        "der Entität oder ihrem Gerät einen Bereich geben",
    ),
    "check_no_room": ("Valve without a room", "Ventil ohne Raum"),
    "check_no_room_hint": (
        "area {area}, where no room is chosen: give the sensor itself the area of its room",
        "Bereich {area}, dort ist kein Raum gewählt: dem Sensor selbst den Bereich seines Raums geben",
    ),
    "template": ("Template", "Vorlage"),
    "own": ("own mapping", "eigene Zuordnung"),
    "source": ("Source", "Quelle"),
    "heating": ("Heating", "Heizen"),
    "dhw": ("Hot water", "Warmwasser"),
    "cooling": ("Cooling", "Kühlen"),
    "heat": ("heat", "Wärme"),
    "elec": ("electricity", "Strom"),
    "total": ("total", "gesamt"),
    "no_heat": ("no heat", "keine Wärme"),
    "no_elec": ("no electricity", "kein Strom"),
    "aux": ("backup heater", "Heizstab"),
    "per_mode": ("per mode", "je Betriebsart"),
    "operation": ("Operation", "Betrieb"),
    "compressor": ("compressor", "Kompressor"),
    "activity": ("activity", "Betriebsart"),
    "starts": ("start counter", "Startzähler"),
    "heating_counters": (
        "run time/start counter heating",
        "Laufzeit-/Startzähler Heizen",
    ),
    "heating_runtime": ("run time counter heating", "Laufzeitzähler Heizen"),
    "measurements": ("Measurements", "Messwerte"),
    "outdoor": ("outdoor", "außen"),
    "flow": ("flow", "Vorlauf"),
    "return": ("return", "Rücklauf"),
    "pressure": ("system pressure", "Anlagendruck"),
    "source_brine": ("source (brine)", "Quelle (Sole)"),
    "boiler": ("boiler", "Kessel"),
    "price": ("Electricity price", "Strompreis"),
    "price_changes": ("Price changes", "Preisänderungen"),
    "analysis_from": ("Evaluation from", "Auswertung ab"),
    "from": ("from", "ab"),
    "ch_electricity": ("electricity", "Strom"),
    "ch_electricity_base": ("electricity base", "Strom-Grundpreis"),
    "ch_gas": ("gas", "Gas"),
    "ch_gas_base": ("gas base", "Gas-Grundpreis"),
    "fixed": ("fixed", "fest"),
    "sensor": ("sensor", "Sensor"),
    "fallback": ("else", "sonst"),
    "none": ("none", "keiner"),
    "pv": ("PV split", "PV-Aufteilung"),
    "off": ("off", "aus"),
    "proportional": ("proportional", "anteilig"),
    "hp_first": ("heat pump first", "Wärmepumpe zuerst"),
    "battery": ("with battery", "mit Batterie"),
    "limits": ("Limits", "Grenzen"),
    "per_hour": ("starts/h", "Starts/h"),
    "per_day": ("starts/day", "Starts/Tag"),
    "short": ("short run", "Kurzlauf"),
    "critical": ("critical", "kritisch"),
    "season_from": ("season from", "Saison ab"),
    "configured": ("Set up", "Eingerichtet"),
    "missing": ("Missing", "Was fehlt"),
    "kind_gas": ("Gas boiler", "Gasheizung"),
    "kind_oil": ("Oil boiler", "Ölheizung"),
    "kind": ("Kind", "Art"),
    "meters": ("Meters", "Zähler"),
    "gas_total": ("total (heating and hot water)", "gesamt (Heizen und Warmwasser)"),
    "gas_heating": ("heating", "Heizen"),
    "gas_dhw": ("hot water", "Warmwasser"),
    "by_hand": ("readings by hand", "Ablesung von Hand"),
    "tank": ("tank level", "Tankstand"),
    "in_circuit": ("in the heating circuit", "im Heizkreis"),
    "efficiency": ("efficiency", "Nutzungsgrad"),
    "gas_price": ("Gas price", "Gaspreis"),
    "oil_price": ("Oil price", "Ölpreis"),
    "design": ("design temperature", "Normaußentemperatur"),
}
HINTS = {
    "heating": (
        "No heat or electricity meter for heating: no heating performance factor.",
        "Kein Wärme- oder Stromzähler fürs Heizen: keine Arbeitszahl Heizen.",
    ),
    "dhw_heat": (
        "No hot water heat meter: no hot water performance factor.",
        "Kein Warmwasser-Wärmezähler: keine Arbeitszahl Warmwasser.",
    ),
    "heat_total_activity": (
        "Heat produced total without an activity: all heat counts as heating.",
        "Erzeugte Wärme gesamt ohne Betriebsart: alle Wärme zählt zum Heizen.",
    ),
    "activity": (
        "No activity: no defrosts, no spread, no mean flow temperature.",
        "Keine Betriebsart: keine Abtauungen, keine Spreizung, kein mittlerer Vorlauf.",
    ),
    "compressor": (
        "No compressor state: no runs and starts, standby only from the heat.",
        "Kein Kompressor-Zustand: keine Läufe und Starts, Stillstand nur über die Wärme.",
    ),
    "coarse_heat": (
        "Without a compressor, part of the running electricity counts as standby "
        "with a heat meter in whole kWh – map the compressor if there is one.",
        "Ohne Kompressor zählt bei einem Wärmezähler in ganzen kWh ein Teil des "
        "Laufstroms als Stillstand – Kompressor eintragen, wenn vorhanden.",
    ),
    "outdoor": (
        "No outdoor temperature: no performance curve, heat load or degree days.",
        "Keine Außentemperatur: keine AZ-Kennlinie, Heizlast und Gradtage.",
    ),
    "outdoor_statistics": (
        "Outdoor temperature without long-term statistics (no state class): no performance curve, heat load or degree days.",
        "Außentemperatur ohne Langzeitstatistik (keine state_class): keine AZ-Kennlinie, Heizlast und Gradtage.",
    ),
    "flow_statistics": (
        "Flow temperature without long-term statistics (no state class): no flow temperature at 0 °C, the efficiency factor only from the setup.",
        "Vorlauf ohne Langzeitstatistik (keine state_class): kein Vorlauf bei 0 °C, Gütegrad erst ab der Einrichtung.",
    ),
    "return_statistics": (
        "Return temperature without long-term statistics (no state class): before the setup the efficiency factor counts the flow alone (rather too high).",
        "Rücklauf ohne Langzeitstatistik (keine state_class): Gütegrad vor der Einrichtung nur mit dem Vorlauf (eher zu hoch).",
    ),
    "pressure_statistics": (
        "System pressure without long-term statistics (no state class): no check of the system pressure.",
        "Anlagendruck ohne Langzeitstatistik (keine state_class): kein Befund Anlagendruck.",
    ),
    "source_statistics": (
        "Source temperature without long-term statistics (no state class): the efficiency factor only from the setup, no “Hot water 2 K colder”.",
        "Quelltemperatur ohne Langzeitstatistik (keine state_class): Gütegrad erst ab der Einrichtung, kein „Warmwasser 2 K kälter“.",
    ),
    "design": (
        "No design outdoor temperature: heat load per kelvin only.",
        "Keine Normaußentemperatur: Heizlast nur je Kelvin.",
    ),
    "price": (
        "No electricity price: no costs and no gas comparison.",
        "Kein Strompreis: keine Kosten und kein Gasvergleich.",
    ),
    "feed_in": (
        "No feed-in and PV meter: own PV is split “heat pump first from the grid” only.",
        "Kein Einspeise- und PV-Zähler: die PV-Aufteilung rechnet nur „Wärmepumpe zuerst aus dem Netz“.",
    ),
    "gas_flow": (
        "Total meter without a hot water meter and without “Flow sensor sits in the heating circuit”: no flow temperature at 0 °C.",
        "Gesamtzähler ohne Warmwasserzähler und ohne Haken „Vorlauffühler sitzt im Heizkreis“: kein Vorlauf bei 0 °C.",
    ),
    "gas_price": (
        "No gas price: no costs.",
        "Kein Gaspreis: keine Kosten.",
    ),
    "oil_price": (
        "No oil price: no costs.",
        "Kein Ölpreis: keine Kosten.",
    ),
}


# Month names for the season start ([en, de]), as the form's select.
MONTHS = (
    ("January", "Januar"),
    ("February", "Februar"),
    ("March", "März"),
    ("April", "April"),
    ("May", "Mai"),
    ("June", "Juni"),
    ("July", "Juli"),
    ("August", "August"),
    ("September", "September"),
    ("October", "Oktober"),
    ("November", "November"),
    ("December", "Dezember"),
)


def _lang(language: str | None) -> int:
    return 1 if (language or "").lower().startswith("de") else 0


CHANGE_UNITS = (
    (CONF_ELECTRICITY_PRICE, "ch_electricity", "ct/kWh"),
    (CONF_ELECTRICITY_BASE_PRICE, "ch_electricity_base", "€/a"),
    (CONF_GAS_PRICE, "ch_gas", "ct/kWh"),
    (CONF_GAS_BASE_PRICE, "ch_gas_base", "€/a"),
)


def price_change_text(options: Mapping[str, Any], lang: int) -> str | None:
    """The price changes in one line ("from 01.01.2027: gas 13.98 ct/kWh;
    …"), None without any."""
    changes = sorted_changes(options, CONF_PRICE_CHANGES)
    if not changes:
        return None
    parts = []
    for change in changes:
        day = date.fromisoformat(str(change[CHANGE_FROM]))
        when = day.strftime("%d.%m.%Y") if lang else day.isoformat()
        values = ", ".join(
            f"{T[label][lang]} {_num(float(change[field]), lang)} {unit}"
            for field, label, unit in CHANGE_UNITS
            if change.get(field) is not None
        )
        parts.append(f"{T['from'][lang]} {when}: {values}")
    return "; ".join(parts)


def _num(value: float, lang: int, digits: int = 2) -> str:
    text = f"{value:.{digits}f}"
    # Only decimals lose their trailing zeros: 90 with no decimals stays 90.
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",") if lang else text


def _flag(present: bool) -> str:
    return "✓" if present else "–"


def _lines(lines: list[str], hints: list[str], lang: int) -> str:
    """Headings as in the sister integrations: "Set up", then "Missing"
    only when something is missing."""
    text = f"**{T['configured'][lang]}**\n" + "\n".join(f"- {line}" for line in lines)
    if hints:
        text += f"\n\n**{T['missing'][lang]}**\n" + "\n".join(f"- {h}" for h in hints)
    return text


def _mode(entities: set[Signal], mode: Mode, lang: int) -> str | None:
    """`Heizen: Wärme gesamt, Strom`, or None for a mode without any meter."""
    t = lambda key: T[key][lang]  # noqa: E731
    heat = has_heat(entities, mode)
    elec = has_elec(entities, mode)
    if not heat and not elec:
        return None
    parts = []
    if not heat:
        parts.append(t("no_heat"))
    elif mode in total_heat_modes(entities):
        parts.append(f"{t('heat')} {t('total')}")
    else:
        parts.append(t("heat"))
    if not elec:
        parts.append(t("no_elec"))
    elif ELEC_SIGNALS[mode] in entities:
        parts.append(t("elec"))
    else:
        parts.append(f"{t('elec')} {t('total')}")
    return f"{t(mode.value)}: {', '.join(parts)}"


@dataclass(frozen=True)
class RoomLine:
    """One room of the heating curve check: what its area holds."""

    name: str
    thermostats: int = 0
    thermometers: int = 0
    valves: int = 0  # valve sensors
    targets: int = 0  # setpoint entities
    valve_reported: bool = False  # a thermostat reports its opening
    heating_share: bool = False  # only whether it heats: its share of time


@dataclass(frozen=True)
class RoomSummary:
    rooms: tuple[RoomLine, ...] = ()
    no_area: tuple[str, ...] = ()
    no_room: tuple[str, ...] = ()


def rooms_text(rooms: RoomSummary, lang: int) -> str:
    """ "Living room (thermostat, valve reported), Stairs (thermometer, 2
    valves) · without an area, not counted: sensor.x"."""
    t = lambda key: T[key][lang]  # noqa: E731
    parts = []
    for room in rooms.rooms:
        what = []
        if room.thermostats:
            what.append(t("thermostat"))
        if room.thermometers:
            what.append(t("thermometer"))
        if room.targets:
            what.append(t("target_entity"))
        if room.valves:
            what.append(f"{room.valves} {t('valves')}")
        elif room.valve_reported:
            what.append(t("valve_reported"))
        elif room.heating_share:
            what.append(t("heating_share"))
        parts.append(f"{room.name} ({', '.join(what)})")
    text = ", ".join(parts) or "–"
    if rooms.no_area:
        text += f" · {t('no_area')}: {', '.join(rooms.no_area)}"
    if rooms.no_room:
        text += f" · {t('no_room')}: {', '.join(rooms.no_room)}"
    return text


@dataclass(frozen=True)
class RoomCheckLine:
    """One room as the check after saving shows it: values now and where
    they come from."""

    name: str
    temp: float | None = None
    temp_from: tuple[str, ...] = ()
    target: float | None = None
    target_from: tuple[str, ...] = ()  # empty with a value: the wish
    valve: float | None = None
    valve_from: tuple[str, ...] = ()
    off: bool = False
    share: bool = False  # the valve is the heating share (100 or 0 now)
    # Without a valve: entities of the area that look like one (id, disabled).
    found: tuple[tuple[str, bool], ...] = ()


@dataclass(frozen=True)
class RoomCheck:
    rooms: tuple[RoomCheckLine, ...] = ()
    no_area: tuple[str, ...] = ()
    no_room: tuple[tuple[str, str], ...] = ()  # (entity, name of its area)


def rooms_check_text(check: RoomCheck, lang: int) -> str:
    """The check after saving the rooms, one line per room:
    "**Stairs:** 21.1 °C, target 21.5 °C, valve 40 % · from climate.stairs"."""
    t = lambda key: T[key][lang]  # noqa: E731
    lines = []
    for room in check.rooms:
        if room.off:
            lines.append(f"- **{room.name}:** {t('check_off')}")
            continue
        parts: list[tuple[str, tuple[str, ...]]] = []
        if room.temp is None:
            parts.append((t("check_no_temp"), ()))
        else:
            parts.append((f"{_num(room.temp, lang, 1)} °C", room.temp_from))
        if room.target is None:
            parts.append((t("check_no_target"), ()))
        elif room.target_from:
            target = f"{t('check_target')} {_num(room.target, lang, 1)} °C"
            parts.append((target, room.target_from))
        else:
            target = f"{t('check_target')} {_num(room.target, lang, 1)} °C"
            parts.append((f"{target} ({t('check_wish')})", ()))
        if room.valve is None:
            no_valve = t("check_no_valve")
            if room.found:
                found = ", ".join(
                    f"{e} ({t('check_disabled')})" if disabled else e
                    for e, disabled in room.found
                )
                no_valve += f" · {t('check_found')}: {found}"
            parts.append((no_valve, ()))
        else:
            valve = (
                t("check_share_on" if room.valve > 0 else "check_share_off")
                if room.share
                else f"{t('check_valve')} {_num(room.valve, lang, 0)} %"
            )
            parts.append((valve, room.valve_from))
        sources = {src for _, src in parts if src}
        if len(sources) == 1 and all(src for _, src in parts):
            # One source for all: named once at the end.
            text = ", ".join(value for value, _ in parts)
            text += f" · {t('check_from')} {', '.join(sources.pop())}"
        else:
            text = ", ".join(
                f"{value} ({t('check_from')} {', '.join(src)})" if src else value
                for value, src in parts
            )
        lines.append(f"- **{room.name}:** {text}")
    if check.no_area:
        lines.append(
            f"- **{t('check_no_area')}:** {', '.join(check.no_area)}"
            f" – {t('check_no_area_hint')}"
        )
    for entity_id, area in check.no_room:
        hint = t("check_no_room_hint").format(area=area)
        lines.append(f"- **{t('check_no_room')}:** {entity_id} – {hint}")
    if any(disabled for room in check.rooms for _, disabled in room.found):
        lines.append(f"- {t('check_enable')}")
    return "\n".join(lines)


def heat_pump_summary(
    entities: Mapping[str, Any],
    options: Mapping[str, Any],
    template_label: str | None,
    language: str | None,
    coarse_heat: bool = False,
    no_statistics: Collection[Signal] = (),
    rooms: RoomSummary | None = None,
) -> str:
    """The summary of a heat pump entry (entities: signal -> entity id).

    `coarse_heat`: a heat meter of a mode steps in whole kWh (known only
    from the loaded entry, `HeatPumpRuntime.coarse_heat_modes`).
    `no_statistics`: temperatures without a state class, so without
    long-term statistics (known from the states).
    """
    lang = _lang(language)
    t = lambda key: T[key][lang]  # noqa: E731
    mapped = {Signal(k) for k in entities if k in Signal._value2member_map_}
    source = f"{t('template')} {template_label}" if template_label else t("own")
    lines = [f"**{t('source')}:** {source}"]
    modes = [m for mode in Mode if (m := _mode(mapped, mode, lang))]
    if any(s in mapped for s in AUX_SIGNALS.values()):
        modes.append(f"{t('aux')} {t('per_mode')}")
    elif Signal.AUX_TOTAL in mapped:
        modes.append(f"{t('aux')} {t('total')}")
    if modes:
        lines.append(f"**{t('meters')}:** " + " · ".join(modes))
    lines.append(
        f"**{t('operation')}:** {t('compressor')} {_flag(Signal.COMPRESSOR in mapped)}, "
        f"{t('activity')} {_flag(has_activity(mapped))}, "
        f"{t('starts')} {_flag(Signal.STARTS_TOTAL in mapped)}"
        # Rare: only named when mapped (look-back of run time per class).
        + (
            f", {t('heating_counters')} ✓"
            if Signal.RUNTIME_HEATING in mapped and Signal.STARTS_HEATING in mapped
            else f", {t('heating_runtime')} ✓"
            if Signal.RUNTIME_HEATING in mapped
            else ""
        )
    )
    measured = [
        f"{t('outdoor')} {_flag(Signal.OUTDOOR_TEMP in mapped)}",
        f"{t('flow')} {_flag(Signal.FLOW_TEMP in mapped)}",
        f"{t('return')} {_flag(Signal.RETURN_TEMP in mapped)}",
    ]
    # Rare: only named when mapped (check "system pressure dropped").
    if Signal.SYSTEM_PRESSURE in mapped:
        measured.append(f"{t('pressure')} ✓")
    # Rare: brine/water and water/water only (Carnot source).
    if Signal.SOURCE_TEMP in mapped:
        measured.append(f"{t('source_brine')} ✓")
    if has_boiler(mapped):
        measured.append(f"{t('boiler')} ✓")
    lines.append(f"**{t('measurements')}:** {', '.join(measured)}")
    fixed = options.get(CONF_ELECTRICITY_PRICE)
    fixed_text = f"{_num(fixed, lang)} ct/kWh" if fixed is not None else None
    if options.get(CONF_ELECTRICITY_PRICE_ENTITY):
        price = t("sensor")
        if fixed_text:
            price += f" ({t('fallback')} {fixed_text})"
    elif fixed_text:
        price = f"{t('fixed')} {fixed_text}"
    else:
        price = t("none")
    lines.append(f"**{t('price')}:** {price}")
    if changes := price_change_text(options, lang):
        lines.append(f"**{t('price_changes')}:** {changes}")
    if options.get(CONF_GRID_IMPORT_ENTITY):
        rule = rule_for(
            pv=bool(options.get(CONF_PV_ENTITY)),
            feed_in=bool(options.get(CONF_FEED_IN_ENTITY)),
        )
        pv = t("proportional") if rule == PROPORTIONAL else t("hp_first")
        if options.get(CONF_BATTERY_CHARGED_ENTITY):
            pv += f", {t('battery')}"
    else:
        pv = t("off")
    lines.append(f"**{t('pv')}:** {pv}")
    # Only when rooms are set (the section is optional and rare).
    if rooms is not None:
        lines.append(f"**{t('rooms')}:** {rooms_text(rooms, lang)}")
    # Starts per day only when set: empty means no such limit.
    per_day = options.get(CONF_STARTS_PER_DAY)
    limits = [
        f"{_num(options.get(CONF_STARTS_PER_HOUR, DEFAULT_STARTS_PER_HOUR), lang)} {t('per_hour')}",
        *([f"{_num(per_day, lang)} {t('per_day')}"] if per_day else []),
        f"{t('short')} {_num(options.get(CONF_SHORT_RUN, DEFAULT_SHORT_RUN_MINUTES), lang)} min",
        f"{t('critical')} {_num(options.get(CONF_CRITICAL_RUN, DEFAULT_CRITICAL_RUN_MINUTES), lang)} min",
    ]
    # Season start only when moved from July: every season value hangs on it.
    month = int(options.get(CONF_SEASON_START) or DEFAULT_SEASON_START_MONTH)
    if month != DEFAULT_SEASON_START_MONTH:
        limits.append(f"{t('season_from')} {MONTHS[month - 1][lang]}")
    lines.append(f"**{t('limits')}:** {', '.join(limits)}")
    # A fresh start of the analyses (issue #10): easy to forget, so shown.
    if (start := analysis_day(options.get(CONF_ANALYSIS_FROM))) is not None:
        when = start.strftime("%d.%m.%Y") if lang else start.isoformat()
        lines.append(f"**{t('analysis_from')}:** {when}")

    hints = []
    h = lambda key: HINTS[key][lang]  # noqa: E731
    if not (has_heat(mapped, Mode.HEATING) and has_elec(mapped, Mode.HEATING)):
        hints.append(h("heating"))
    if Signal.HEAT_TOTAL in mapped and not has_activity(mapped):
        hints.append(h("heat_total_activity"))
    elif has_elec(mapped, Mode.DHW) and not has_heat(mapped, Mode.DHW):
        hints.append(h("dhw_heat"))
    if Signal.COMPRESSOR not in mapped:
        hints.append(h("compressor"))
        if coarse_heat:
            hints.append(h("coarse_heat"))
    if not has_activity(mapped):
        hints.append(h("activity"))
    if Signal.OUTDOOR_TEMP not in mapped:
        hints.append(h("outdoor"))
    elif Signal.OUTDOOR_TEMP in no_statistics:
        hints.append(h("outdoor_statistics"))
    elif options.get(CONF_DESIGN_TEMP) is None:
        hints.append(h("design"))
    # Name the sensor: without the flow's statistics there is no look-back
    # at all, without the return's the look-back counts the flow alone.
    missing = set(no_statistics) & mapped
    if Signal.FLOW_TEMP in missing:
        hints.append(h("flow_statistics"))
    elif Signal.RETURN_TEMP in missing:
        hints.append(h("return_statistics"))
    if Signal.SYSTEM_PRESSURE in missing:
        hints.append(h("pressure_statistics"))
    if Signal.SOURCE_TEMP in missing:
        hints.append(h("source_statistics"))
    if fixed is None and not options.get(CONF_ELECTRICITY_PRICE_ENTITY):
        hints.append(h("price"))
    if options.get(CONF_GRID_IMPORT_ENTITY) and not (
        options.get(CONF_FEED_IN_ENTITY) and options.get(CONF_PV_ENTITY)
    ):
        hints.append(h("feed_in"))
    return _lines(lines, hints, lang)


def boiler_summary(
    data: Mapping[str, Any],
    entities: Mapping[str, Any],
    options: Mapping[str, Any],
    *,
    oil: bool,
    language: str | None,
) -> str:
    """The summary of a gas or oil entry."""
    lang = _lang(language)
    t = lambda key: T[key][lang]  # noqa: E731
    lines = [f"**{t('kind')}:** {t('kind_oil' if oil else 'kind_gas')}"]
    manual = data.get(CONF_MANUAL_UNIT)
    if manual:
        meters = t("tank") if manual == TANK else t("by_hand")
    else:
        meters = ", ".join(
            t(key) for key in (GAS_TOTAL, GAS_HEATING, GAS_DHW) if entities.get(key)
        )
    lines.append(f"**{t('meters')}:** {meters or t('none')}")
    flow = Signal.FLOW_TEMP.value in entities
    flow_text = f"{t('flow')} {_flag(flow)}"
    if flow and data.get(CONF_FLOW_IN_CIRCUIT):
        flow_text += f" ({t('in_circuit')})"
    lines.append(
        f"**{t('measurements')}:** "
        f"{t('outdoor')} {_flag(Signal.OUTDOOR_TEMP.value in entities)}, {flow_text}"
    )
    if oil:
        eff = boiler_type_efficiency(
            options.get(CONF_BOILER_TYPE), options.get(CONF_BOILER_EFFICIENCY)
        )
        price_value = options.get(CONF_OIL_PRICE)
        price = f"{_num(price_value, lang)} €/100 l" if price_value else t("none")
        price_key = "oil_price"
    else:
        eff = options.get(CONF_BOILER_EFFICIENCY, BOILER_EFFICIENCY_HS)
        price_value = options.get(CONF_GAS_PRICE)
        price = f"{_num(price_value, lang)} ct/kWh" if price_value else t("none")
        price_key = "gas_price"
    design = options.get(CONF_DESIGN_TEMP)
    lines.append(
        f"**{t(price_key)}:** {price} · {t('efficiency')} "
        f"{_num(eff, lang) if eff is not None else '–'} · {t('design')} "
        f"{_num(design, lang, 1) + ' °C' if design is not None else '–'}"
    )
    hints = []
    h = lambda key: HINTS[key][lang]  # noqa: E731
    if (
        entities.get(GAS_TOTAL)
        and not entities.get(GAS_DHW)
        and flow
        and not data.get(CONF_FLOW_IN_CIRCUIT)
    ):
        hints.append(h("gas_flow"))
    if design is None:
        hints.append(h("design"))
    if not price_value:
        hints.append(h(price_key))
    return _lines(lines, hints, lang)


def lang_index(language: str | None) -> int:
    """0 English, 1 German (the texts' index)."""
    return _lang(language)
