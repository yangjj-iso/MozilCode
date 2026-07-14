"""工具级 Hook 适配层。

提供 pre_tool_use 和 post_tool_use 两个 Hook 触发函数，
在 Agent 循环的工具执行前后被调用。
pre_tool_use 支持 reject 拦截（阻止工具执行），
post_tool_use 用于后置操作（如 lint / 格式化）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from mozilcode.agent.events import HookEvent
from mozilcode.agent.helpers import infer_tool_file_path
from mozilcode.agent.hook_events import BuildHookContext, DrainHookEvents
from mozilcode.hooks import HookContext, ToolRejectedError
from mozilcode.tools.base import ToolCallComplete

# 从工具参数中推断文件路径的回调类型
InferFilePath = Callable[[dict[str, Any]], str]


class ToolHookEngine(Protocol):
    """工具级 Hook 引擎协议：需要同时支持 pre/post tool use Hook。"""
    async def run_pre_tool_hooks(
        self,
        ctx: HookContext,
    ) -> ToolRejectedError | None: ...

    async def run_hooks(self, event: str, ctx: HookContext) -> None: ...


@dataclass(frozen=True)
class PreToolHookResult:
    """pre_tool_use Hook 的执行结果。

    - rejection: 非 None 表示 Hook 拒绝了工具执行，Agent 应跳过执行
    - events: Hook 执行过程中产生的事件（通知 / 提示消息等）
    """
    rejection: ToolRejectedError | None
    events: list[HookEvent]


def build_tool_hook_context(
    *,
    build_hook_context: BuildHookContext,
    infer_file_path: InferFilePath,
    event: str,
    tool_call: ToolCallComplete,
) -> HookContext:
    """为工具级 Hook 构建上下文：填充 tool_name / tool_args / file_path。"""
    return build_hook_context(
        event,
        tool_name=tool_call.tool_name,
        tool_args=tool_call.arguments,
        file_path=infer_file_path(tool_call.arguments),
    )


async def run_pre_tool_hook(
    *,
    hook_engine: ToolHookEngine | None,
    build_hook_context: BuildHookContext,
    drain_hook_events: DrainHookEvents,
    infer_file_path: InferFilePath = infer_tool_file_path,
    tool_call: ToolCallComplete,
) -> PreToolHookResult:
    """执行 pre_tool_use Hook（工具执行前）。

    如果 Hook 配置了 reject: true 且条件匹配，返回的 PreToolHookResult.rejection 不为 None，
    Agent 收到后跳过工具执行，将拒绝原因作为工具结果返回给 LLM。
    """
    if hook_engine is None:
        return PreToolHookResult(None, [])

    hook_ctx = build_tool_hook_context(
        build_hook_context=build_hook_context,
        infer_file_path=infer_file_path,
        event="pre_tool_use",
        tool_call=tool_call,
    )
    rejection = await hook_engine.run_pre_tool_hooks(hook_ctx)
    return PreToolHookResult(rejection, drain_hook_events())


async def run_post_tool_hook(
    *,
    hook_engine: ToolHookEngine | None,
    build_hook_context: BuildHookContext,
    drain_hook_events: DrainHookEvents,
    infer_file_path: InferFilePath = infer_tool_file_path,
    tool_call: ToolCallComplete,
) -> list[HookEvent]:
    """执行 post_tool_use Hook（工具执行后）。

    典型用途：执行 lint / 格式化 / 通知外部系统等后置操作。
    post_tool_use 不支持 reject（工具已经执行完了）。
    """
    if hook_engine is None:
        return []

    hook_ctx = build_tool_hook_context(
        build_hook_context=build_hook_context,
        infer_file_path=infer_file_path,
        event="post_tool_use",
        tool_call=tool_call,
    )
    await hook_engine.run_hooks("post_tool_use", hook_ctx)
    return drain_hook_events()
