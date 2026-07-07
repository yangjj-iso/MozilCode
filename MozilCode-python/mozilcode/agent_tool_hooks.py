from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from mozilcode.agent_events import HookEvent
from mozilcode.agent_helpers import infer_tool_file_path
from mozilcode.hooks import HookContext, ToolRejectedError
from mozilcode.tools.base import ToolCallComplete


BuildHookContext = Callable[..., HookContext]
DrainHookEvents = Callable[[], list[HookEvent]]
InferFilePath = Callable[[dict[str, Any]], str]


class ToolHookEngine(Protocol):
    async def run_pre_tool_hooks(
        self,
        ctx: HookContext,
    ) -> ToolRejectedError | None: ...

    async def run_hooks(self, event: str, ctx: HookContext) -> None: ...


@dataclass(frozen=True)
class PreToolHookResult:
    rejection: ToolRejectedError | None
    events: list[HookEvent]


def build_tool_hook_context(
    *,
    build_hook_context: BuildHookContext,
    infer_file_path: InferFilePath,
    event: str,
    tool_call: ToolCallComplete,
) -> HookContext:
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
