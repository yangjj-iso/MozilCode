from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from mozilcode.agent.helpers import infer_tool_file_path
from mozilcode.agent.tool_execution import execute_validated_tool
from mozilcode.hooks import HookContext, ToolRejectedError
from mozilcode.permissions import PermissionChecker, PermissionMode
from mozilcode.tools import ToolRegistry
from mozilcode.tools.base import Tool, ToolCallComplete, ToolResult


BuildHookContext = Callable[..., HookContext]
InferFilePath = Callable[[dict[str, Any]], str]


class NoninteractiveHookEngine(Protocol):
    async def run_pre_tool_hooks(
        self,
        ctx: HookContext,
    ) -> ToolRejectedError | None: ...

    async def run_hooks(self, event: str, ctx: HookContext) -> None: ...


def _tool_hook_context(
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


async def _run_pre_tool_hook(
    *,
    hook_engine: NoninteractiveHookEngine | None,
    build_hook_context: BuildHookContext,
    infer_file_path: InferFilePath,
    tool_call: ToolCallComplete,
) -> ToolResult | None:
    if hook_engine is None:
        return None

    hook_ctx = _tool_hook_context(
        build_hook_context=build_hook_context,
        infer_file_path=infer_file_path,
        event="pre_tool_use",
        tool_call=tool_call,
    )
    rejection = await hook_engine.run_pre_tool_hooks(hook_ctx)
    if rejection is None:
        return None
    return ToolResult(
        output=f"Hook rejected: {rejection.reason}",
        is_error=True,
    )


async def _run_post_tool_hook(
    *,
    hook_engine: NoninteractiveHookEngine | None,
    build_hook_context: BuildHookContext,
    infer_file_path: InferFilePath,
    tool_call: ToolCallComplete,
) -> None:
    if hook_engine is None:
        return

    hook_ctx = _tool_hook_context(
        build_hook_context=build_hook_context,
        infer_file_path=infer_file_path,
        event="post_tool_use",
        tool_call=tool_call,
    )
    await hook_engine.run_hooks("post_tool_use", hook_ctx)


def _check_noninteractive_permission(
    *,
    tool: Tool,
    permission_checker: PermissionChecker | None,
    permission_mode: PermissionMode,
    tool_call: ToolCallComplete,
) -> ToolResult | None:
    if permission_checker is None:
        return None

    decision = permission_checker.check(tool, tool_call.arguments)
    if decision.effect == "deny":
        return ToolResult(
            output=f"Permission denied: {decision.reason}",
            is_error=True,
        )
    if decision.effect == "ask" and permission_mode != PermissionMode.DONT_ASK:
        return ToolResult(
            output="Permission denied: non-interactive agent cannot prompt user",
            is_error=True,
        )
    return None


async def execute_noninteractive_tool_call(
    *,
    registry: ToolRegistry,
    permission_checker: PermissionChecker | None,
    permission_mode: PermissionMode,
    hook_engine: NoninteractiveHookEngine | None,
    build_hook_context: BuildHookContext,
    infer_file_path: InferFilePath = infer_tool_file_path,
    tool_call: ToolCallComplete,
) -> ToolResult:
    tool = registry.get(tool_call.tool_name)

    if tool is None:
        return ToolResult(
            output=f"Error: unknown tool '{tool_call.tool_name}'",
            is_error=True,
        )

    if not registry.is_enabled(tool_call.tool_name):
        return ToolResult(
            output=f"Error: tool '{tool_call.tool_name}' is disabled",
            is_error=True,
        )

    rejection = await _run_pre_tool_hook(
        hook_engine=hook_engine,
        build_hook_context=build_hook_context,
        infer_file_path=infer_file_path,
        tool_call=tool_call,
    )
    if rejection is not None:
        return rejection

    permission_error = _check_noninteractive_permission(
        tool=tool,
        permission_checker=permission_checker,
        permission_mode=permission_mode,
        tool_call=tool_call,
    )
    if permission_error is not None:
        return permission_error

    result = await execute_validated_tool(tool, tool_call.arguments)
    await _run_post_tool_hook(
        hook_engine=hook_engine,
        build_hook_context=build_hook_context,
        infer_file_path=infer_file_path,
        tool_call=tool_call,
    )
    return result
