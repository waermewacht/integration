"""Prices that change from a date on. Pure Python, no HA imports.

Rules (docs/ENTWICKLUNG.md, "Preise mit Datum"):

- The prices of the options are the prices from the start. A price change
  (option "price_changes") sets new values from local midnight of its date
  on; a field it leaves out keeps the value before. Changes are applied in
  the order of their dates.
- Electricity is priced per hour with the price of that hour, gas per local
  day with the price of that day (the heat of a day, prices.PricedDay).
- An annual base price is prorated per local day with the annual price of
  that day (costs.base_price_share per segment).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, tzinfo
from itertools import pairwise
from typing import Any

CHANGE_FROM = "from"  # date of a price change, ISO (YYYY-MM-DD)


@dataclass(frozen=True)
class Dated:
    """A value from the start (`first`), changing at UTC instants."""

    first: float | None
    changes: tuple[tuple[datetime, float | None], ...] = ()

    def at(self, moment: datetime) -> float | None:
        """The value valid at `moment`."""
        value = self.first
        for start, changed in self.changes:
            if start > moment:
                break
            value = changed
        return value

    def segments(
        self, start: datetime, end: datetime
    ) -> Iterator[tuple[datetime, datetime, float | None]]:
        """[start, end) cut at the changes: (from, to, value) each."""
        if end <= start:
            return
        bounds = [start, *(s for s, _ in self.changes if start < s < end), end]
        for lower, upper in pairwise(bounds):
            yield lower, upper, self.at(lower)

    @property
    def known(self) -> bool:
        """Whether any state has a value."""
        return self.first is not None or any(v is not None for _, v in self.changes)


Price = float | Dated | None


def value_at(price: Price, moment: datetime) -> float | None:
    """A plain or dated price at `moment`."""
    if isinstance(price, Dated):
        return price.at(moment)
    return price


def change_start(day: str | date, tz: tzinfo) -> datetime:
    """A change applies from local midnight of its date (UTC instant)."""
    if isinstance(day, str):
        day = date.fromisoformat(day)
    return datetime.combine(day, time(), tz).astimezone(UTC)


def sorted_changes(options: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    """The price changes of the options, by date."""
    changes = options.get(key) or []
    return sorted((dict(c) for c in changes), key=lambda c: str(c[CHANGE_FROM]))


def dated(
    options: Mapping[str, Any],
    field: str,
    changes_key: str,
    tz: tzinfo,
    scale: float = 1.0,
) -> Price:
    """The option `field` with its price changes; a plain float (or None)
    without any change of that field. `scale` converts the stored unit
    (0.01: ct/kWh to €/kWh)."""

    def scaled(value: Any) -> float | None:
        return None if value is None else float(value) * scale

    first = scaled(options.get(field))
    steps: list[tuple[datetime, float | None]] = []
    for change in sorted_changes(options, changes_key):
        if field in change:
            steps.append((change_start(change[CHANGE_FROM], tz), scaled(change[field])))
    if not steps:
        return first
    return Dated(first, tuple(steps))


def states(
    options: Mapping[str, Any], fields: Sequence[str], changes_key: str
) -> list[tuple[date | None, dict[str, Any]]]:
    """Every price state for the overview: (None, values from the start),
    then (date, values from then on) per change."""
    values = {f: options.get(f) for f in fields}
    result: list[tuple[date | None, dict[str, Any]]] = [(None, dict(values))]
    for change in sorted_changes(options, changes_key):
        values = {**values, **{f: change[f] for f in fields if f in change}}
        result.append((date.fromisoformat(str(change[CHANGE_FROM])), dict(values)))
    return result
