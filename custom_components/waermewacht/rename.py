"""Follow a source entity renamed in the entity registry. Pure Python.

An entry keeps its sources as entity ids: the configured signals, the older
ids of the same counters (history, backfill only) and, for a manual mapping
or a gas boiler, the unique id. Home Assistant moves the statistics along
with a renamed entity; only these references have to follow (__init__.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import CONF_ENTITIES, CONF_HISTORY, KIND_GAS


def sources(data: Mapping[str, Any]) -> set[str]:
    """Every entity id the entry refers to."""
    entities: Mapping[str, str | None] = data.get(CONF_ENTITIES) or {}
    history: Mapping[str, list[str]] = data.get(CONF_HISTORY) or {}
    return {
        *(e for e in entities.values() if e),
        *history,
        *(alias for aliases in history.values() for alias in aliases),
    }


def renamed_data(data: Mapping[str, Any], old: str, new: str) -> dict[str, Any]:
    """The entry data with `old` replaced by `new` wherever it occurs."""

    def swap(entity_id: str) -> str:
        return new if entity_id == old else entity_id

    result = dict(data)
    if CONF_ENTITIES in data:
        result[CONF_ENTITIES] = {
            signal: swap(e) if e else e for signal, e in data[CONF_ENTITIES].items()
        }
    if CONF_HISTORY in data:
        result[CONF_HISTORY] = {
            swap(e): [swap(alias) for alias in aliases]
            for e, aliases in data[CONF_HISTORY].items()
        }
    return result


def renamed_unique_id(unique_id: str | None, old: str, new: str) -> str | None:
    """The unique id after the rename; None if it does not name `old`
    (a template entry is identified by template and prefix)."""
    if unique_id == old:
        return new
    if unique_id == f"{KIND_GAS}:{old}":
        return f"{KIND_GAS}:{new}"
    return None
