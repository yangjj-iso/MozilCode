from __future__ import annotations

import pytest

from mozilcode.agent_helpers import build_hook_context
from mozilcode.agent_hook_events import (
    drain_hook_events,
    hook_notification_to_event,
    hook_notifications_to_events,
    run_lifecycle_hook,
)
from mozilcode.hooks import HookContext
from mozilcode.hooks.engine import HookNotification


class FakeHookEngine:
    def __init__(self) -> None:
        self.contexts: list[tuple[str, HookContext]] = []
        self.notifications: list[HookNotification] = []

    async def run_hooks(self, event: str, ctx: HookContext) -> None:
        self.contexts.append((event, ctx))
        self.notifications.append(
            HookNotification(
                hook_id=f"{event}-hook",
                event=event,
                output=ctx.message or "ok",
                success=True,
            )
        )

    def drain_notifications(self) -> list[HookNotification]:
        notifications = list(self.notifications)
        self.notifications.clear()
        return notifications


def test_hook_notification_to_event_preserves_fields() -> None:
    event = hook_notification_to_event(
        HookNotification(
            hook_id="hook-1",
            event="pre_send",
            output="ready",
            success=True,
        )
    )

    assert event.hook_id == "hook-1"
    assert event.event == "pre_send"
    assert event.output == "ready"
    assert event.success is True


def test_hook_notifications_to_events_preserves_order() -> None:
    events = hook_notifications_to_events(
        [
            HookNotification("hook-1", "turn_start", "one", True),
            HookNotification("hook-2", "turn_end", "two", False),
        ]
    )

    assert [event.hook_id for event in events] == ["hook-1", "hook-2"]
    assert [event.success for event in events] == [True, False]


def test_drain_hook_events_skips_missing_engine() -> None:
    assert drain_hook_events(None) == []


def test_drain_hook_events_drains_engine_notifications() -> None:
    engine = FakeHookEngine()
    engine.notifications.append(HookNotification("hook-1", "turn_start", "ok", True))

    events = drain_hook_events(engine)

    assert [event.hook_id for event in events] == ["hook-1"]
    assert engine.notifications == []


@pytest.mark.asyncio
async def test_run_lifecycle_hook_runs_context_and_drains_events() -> None:
    engine = FakeHookEngine()

    events = await run_lifecycle_hook(
        hook_engine=engine,
        build_hook_context=build_hook_context,
        drain_events=lambda: drain_hook_events(engine),
        event="post_receive",
        context_kwargs={"message": "done"},
    )

    assert [event.event for event in events] == ["post_receive"]
    assert events[0].output == "done"
    assert engine.contexts[0][0] == "post_receive"
    assert engine.contexts[0][1].message == "done"


@pytest.mark.asyncio
async def test_run_lifecycle_hook_skips_missing_engine() -> None:
    events = await run_lifecycle_hook(
        hook_engine=None,
        build_hook_context=build_hook_context,
        drain_events=lambda: [],
        event="turn_start",
    )

    assert events == []
