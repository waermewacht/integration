"""Tasks of the runtime end with it: analysis and checks are cancelled,
writes finish before the final save, nothing runs after the stop."""

from __future__ import annotations

import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.waermewacht.const import DOMAIN

from .conftest import HEAT_HEATING
from .test_init import setup


async def test_unload_cancels_checks_and_awaits_writes(hass: HomeAssistant) -> None:
    entry = await setup(hass)
    runtime = entry.runtime_data
    started, release = asyncio.Event(), asyncio.Event()
    finished: list[str] = []

    async def analysis() -> None:
        started.set()
        await asyncio.Event().wait()  # never ends by itself
        finished.append("analysis")

    async def write() -> None:
        await release.wait()
        finished.append("write")

    runtime.spawn(analysis(), "test_analysis")
    runtime.spawn(write(), "test_write", cancel=False)
    await started.wait()
    hass.loop.call_later(0.05, release.set)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert finished == ["write"]  # the write ended before the stop returned
    assert not runtime._tasks


async def test_nothing_runs_or_raises_issues_after_the_stop(
    hass: HomeAssistant,
) -> None:
    entry = await setup(hass)
    runtime = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    ran: list[bool] = []

    async def late() -> None:
        ran.append(True)

    runtime.spawn(late(), "test_late")
    await hass.async_block_till_done()
    assert ran == []
    runtime._set_issue("day_counter", [HEAT_HEATING])
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"{entry.entry_id}_day_counter")
        is None
    )
