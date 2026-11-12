"""Buttons: recompute the look-back before the setup from the statistics;
show a short report for a bug report (issue_report.py), also for gas
entries."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.button import ButtonEntity
from homeassistant.components.sensor import ATTR_STATE_CLASS
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import WaermewachtConfigEntry, is_gas
from .const import CONF_ENTITIES, CONF_MANUAL_UNIT, CONF_TEMPLATE, DOMAIN, VERSION
from .entity import HeatPumpEntity
from .gas_runtime import GasRuntime
from .issue_report import build, show, text
from .periods import Period
from .runtime import HeatPumpRuntime

NAME = "Wärmewacht"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaermewachtConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    buttons: list[HeatPumpEntity] = [IssueReport(entry)]
    if is_gas(entry):
        async_add_entities(buttons)
        return
    if not entry.runtime_data.template.previous_day:
        buttons.append(RebuildHistory(entry))
    async_add_entities(buttons)


class RebuildHistory(HeatPumpEntity, ButtonEntity):
    """The energy before the setup anew from the statistics: after meters
    were added under Reconfigure or an update corrected the rules."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: WaermewachtConfigEntry) -> None:
        super().__init__(entry, "rebuild_history")

    async def async_press(self) -> None:
        await self.runtime.async_rebuild_history()


class IssueReport(HeatPumpEntity, ButtonEntity):
    """A short report to copy into a bug report, as a notification: what an
    issue needs without the diagnostics download (issue_report.py)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: WaermewachtConfigEntry) -> None:
        super().__init__(entry, "issue_report")
        self._entry = entry

    async def async_press(self) -> None:
        entry = self._entry
        runtime = entry.runtime_data
        if isinstance(runtime, GasRuntime):
            mapping = dict(entry.data.get(CONF_ENTITIES) or {})
            extra = _gas_lines(entry, runtime)
        else:
            mapping = {s.value: e for s, e in runtime.entities.items()}
            extra = _heat_pump_lines(self.hass, entry, runtime)
        report = build(
            self.hass, DOMAIN, NAME, VERSION, entry, mapping=mapping, extra=extra
        )
        show(self.hass, DOMAIN, NAME, entry, report)


def _heat_pump_lines(
    hass: HomeAssistant, entry: WaermewachtConfigEntry, runtime: HeatPumpRuntime
) -> list[tuple[str, str]]:
    template = runtime.template
    return [
        ("kind", "heat pump"),
        ("template", str(entry.data.get(CONF_TEMPLATE) or "own mapping")),
        ("beta template", text(template.experimental)),
        ("day values", text(template.day_values)),
        ("previous day", text(template.previous_day)),
        ("since", runtime.since.date().isoformat() if runtime.since else "-"),
        (
            "counter events",
            ", ".join(f"{k} {v}" for k, v in sorted(runtime.events.items())) or "none",
        ),
        ("jumps not booked", str(len(runtime.jumps))),
        ("hours left out", _rejected_hours(runtime.rejected_hours)),
        ("price sensor", _price_sensor(hass, runtime)),
    ]


def _rejected_hours(found: dict[str, list[datetime]]) -> str:
    """The latest hours left out per counter, in UTC."""
    return (
        "; ".join(
            f"{signal} " + ", ".join(h.strftime("%Y-%m-%d %H:00Z") for h in hours)
            for signal, hours in sorted(found.items())
        )
        or "none"
    )


def _price_sensor(hass: HomeAssistant, runtime: HeatPumpRuntime) -> str:
    """Unit and state class of the price sensor (no state class: no
    long-term statistics, prices only as far back as the recorder keeps
    states) and the hours without a price per period."""
    entity_id = runtime.price_entity
    if entity_id is None:
        return "none"
    state = hass.states.get(entity_id)
    if state is None:
        return "not found"
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) or "no unit"
    state_class = state.attributes.get(ATTR_STATE_CLASS) or "no state class"
    parts = [f"{unit}, {state_class}"]
    feed = runtime.prices
    now = dt_util.utcnow()
    for period in (Period.MONTH, Period.SEASON):
        start = runtime.marks.starts.get(period)
        totals = runtime.energy(period)
        priced = (
            None
            if feed is None or start is None or totals is None
            else feed.period(start, totals, now)
        )
        if priced is None:
            parts.append(f"hours without price {period.value} -")
            continue
        missing = priced.electricity.missing_hours + priced.hours_before
        part = f"hours without price {period.value} {missing}"
        if priced.priced_from is not None:
            part += f" (priced from {priced.priced_from.astimezone(runtime.tz).date().isoformat()})"
        parts.append(part)
    return ", ".join(parts)


def _gas_lines(
    entry: WaermewachtConfigEntry, runtime: GasRuntime
) -> list[tuple[str, str]]:
    lines = [
        ("kind", "oil boiler" if runtime.oil else "gas boiler"),
        ("readings by hand", str(entry.data.get(CONF_MANUAL_UNIT) or "no")),
        ("problem", str(runtime.problem or "none")),
    ]
    if runtime.manual:
        lines.append(("readings", str(len(runtime.readings))))
    if runtime.tank:
        lines.append(("refills", str(len(runtime.refills))))
    if runtime.oil:
        lines.append(("efficiency", f"{runtime.efficiency:.2f}"))
    if (analysis := runtime.analysis) is not None:
        load = analysis.heat_load
        lines += [
            ("window", f"{analysis.start.isoformat()} - {analysis.end.isoformat()}"),
            ("days with gas", str(analysis.gas_days)),
            (
                "hot water",
                f"{analysis.split.method}, {analysis.split.summer_days} summer days",
            ),
            (
                "signature",
                f"{len(load.weeks)} points, spread {_num(load.spread)} K, "
                f"{load.frost_days} frost days, "
                + ("sufficient" if load.sufficient else ", ".join(load.reasons) or "-"),
            ),
            ("flow", analysis.flow_reason or ("-" if analysis.flow is None else "ok")),
        ]
    return lines


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"
