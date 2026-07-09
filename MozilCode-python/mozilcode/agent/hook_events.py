from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from mozilcode.agent.events import HookEvent
from mozilcode.hooks import HookContext
from mozilcode.hooks.engine import HookNotification


BuildHookContext = Callable[..., HookContext]
DrainHookEvents = Callable[[], list[HookEvent]]


class HookNotificationSource(Protocol):
    def drain_notifications(self) -> list[HookNotification]: ...


class LifecycleHookEngine(HookNotificationSource, Protocol):
    async def run_hooks(self, event: str, ctx: HookContext) -> None: ...


def hook_notification_to_event(notification: HookNotification) -> HookEvent:
    return HookEvent(
        hook_id=notification.hook_id,
        event=notification.event,
        output=notification.output,
        success=notification.success,
    )


def hook_notifications_to_events(
    notifications: Sequence[HookNotification],
) -> list[HookEvent]:
    return [hook_notification_to_event(notification) for notification in notifications]


def drain_hook_events(
    hook_engine: HookNotificationSource | None,
) -> list[HookEvent]:
    if hook_engine is None:
        return []
    return hook_notifications_to_events(hook_engine.drain_notifications())


async def run_lifecycle_hook(
    *,
    hook_engine: LifecycleHookEngine | None,
    build_hook_context: BuildHookContext,
    drain_events: DrainHookEvents,
    event: str,
    context_kwargs: dict[str, Any] | None = None,
) -> list[HookEvent]:
    if hook_engine is None:
        return []

    hook_ctx = build_hook_context(event, **(context_kwargs or {}))
    await hook_engine.run_hooks(event, hook_ctx)
    return drain_events()
