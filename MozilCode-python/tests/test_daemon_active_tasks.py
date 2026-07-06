from __future__ import annotations

import asyncio

import pytest

from mozilcode.daemon.active_tasks import (
    ACTIVE_TASK_RUNNING_ERROR,
    ActiveTaskRegistry,
)


async def _done() -> None:
    return None


async def _blocked(event: asyncio.Event) -> None:
    await event.wait()


@pytest.mark.asyncio
async def test_active_task_registry_rejects_running_task() -> None:
    registry = ActiveTaskRegistry()
    release = asyncio.Event()
    task = asyncio.create_task(_blocked(release))
    registry.register("sid", "task-1", task)

    try:
        with pytest.raises(ValueError, match=ACTIVE_TASK_RUNNING_ERROR):
            registry.ensure_available("sid")
        assert registry.task_id("sid") == "task-1"
        assert registry.is_running("sid") is True
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_active_task_registry_discards_completed_task_before_reuse() -> None:
    registry = ActiveTaskRegistry()
    task = asyncio.create_task(_done())
    await task
    registry.register("sid", "task-1", task)

    registry.ensure_available("sid")

    assert registry.task_id("sid") == ""
    assert registry.is_running("sid") is False
    assert "sid" not in registry.tasks


@pytest.mark.asyncio
async def test_active_task_registry_cancels_and_pops_task() -> None:
    registry = ActiveTaskRegistry()
    release = asyncio.Event()
    task = asyncio.create_task(_blocked(release))
    registry.register("sid", "task-1", task)

    assert registry.cancel("sid") is True
    with pytest.raises(asyncio.CancelledError):
        await task
    assert registry.pop_task("sid") is task
    assert registry.task_id("sid") == ""
    assert registry.cancel("sid") is False


@pytest.mark.asyncio
async def test_active_task_registry_clears_only_matching_current_task() -> None:
    registry = ActiveTaskRegistry()
    old_task = asyncio.create_task(_done())
    await old_task
    new_task = asyncio.create_task(_done())
    registry.register("sid", "new", new_task)

    registry.clear_if_current("sid", old_task)
    assert registry.task_id("sid") == "new"

    await new_task
    registry.clear_if_current("sid", new_task)
    assert registry.task_id("sid") == ""
