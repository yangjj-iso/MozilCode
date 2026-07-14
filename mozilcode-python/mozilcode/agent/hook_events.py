"""生命周期 Hook 适配层。

将 HookEngine 的通知机制适配为 Agent 事件流中的 HookEvent。
核心函数 run_lifecycle_hook() 在 Agent 循环的固定位置被调用，
触发 session_start / turn_start / pre_send / post_receive 等生命周期 Hook。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from mozilcode.agent.events import HookEvent
from mozilcode.hooks import HookContext
from mozilcode.hooks.engine import HookNotification

# 构建 HookContext 的回调类型（由 Agent 提供，封装当前会话状态）
BuildHookContext = Callable[..., HookContext]
# 取出已积攒的 Hook 事件的回调类型
DrainHookEvents = Callable[[], list[HookEvent]]


class HookNotificationSource(Protocol):
    """能取出 Hook 通知的对象（如 HookEngine）。"""
    def drain_notifications(self) -> list[HookNotification]: ...


class LifecycleHookEngine(HookNotificationSource, Protocol):
    """能执行生命周期 Hook 的对象（如 HookEngine）。"""
    async def run_hooks(self, event: str, ctx: HookContext) -> None: ...


def hook_notification_to_event(notification: HookNotification) -> HookEvent:
    """将 HookEngine 的通知对象转换为 Agent 事件流中的 HookEvent。"""
    return HookEvent(
        hook_id=notification.hook_id,
        event=notification.event,
        output=notification.output,
        success=notification.success,
    )


def hook_notifications_to_events(
    notifications: Sequence[HookNotification],
) -> list[HookEvent]:
    """批量转换通知列表为事件列表。"""
    return [hook_notification_to_event(notification) for notification in notifications]


def drain_hook_events(
    hook_engine: HookNotificationSource | None,
) -> list[HookEvent]:
    """从 HookEngine 取出并清空所有积攒的通知，转换为事件列表。
    如果没有 hook_engine（未配置 Hook），返回空列表。"""
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
    """触发一个生命周期 Hook（如 session_start / turn_start / pre_send 等）。

    流程：构造上下文 → 执行 Hook → 取出通知事件。
    如果没有 hook_engine（未配置 Hook），直接返回空列表。
    返回的 HookEvent 列表会被 Agent yield 到事件流中。
    """
    if hook_engine is None:
        return []

    hook_ctx = build_hook_context(event, **(context_kwargs or {}))
    await hook_engine.run_hooks(event, hook_ctx)
    return drain_events()
