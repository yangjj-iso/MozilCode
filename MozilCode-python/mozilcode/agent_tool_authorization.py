from __future__ import annotations

import asyncio
from typing import AsyncIterator

from mozilcode.agent_events import PermissionRequest, PermissionResponse
from mozilcode.agent_tool_execution import _AuthResult
from mozilcode.permissions import PermissionChecker
from mozilcode.permissions.rules import Rule, extract_content
from mozilcode.tools import ToolRegistry
from mozilcode.tools.base import ToolCallComplete, ToolResult


async def authorize_tool_call(
    *,
    registry: ToolRegistry,
    permission_checker: PermissionChecker | None,
    tool_call: ToolCallComplete,
    permission_description: str,
) -> AsyncIterator[PermissionRequest | _AuthResult]:
    tool = registry.get(tool_call.tool_name)
    if tool is None:
        yield _AuthResult(
            False,
            ToolResult(
                output=f"Error: unknown tool '{tool_call.tool_name}'",
                is_error=True,
            ),
            is_unknown=True,
        )
        return

    if not registry.is_enabled(tool_call.tool_name):
        yield _AuthResult(
            False,
            ToolResult(
                output=(
                    f"Error: tool '{tool_call.tool_name}' is disabled in current mode"
                ),
                is_error=True,
            ),
        )
        return

    if permission_checker:
        decision = permission_checker.check(tool, tool_call.arguments)

        if decision.effect == "deny":
            yield _AuthResult(
                False,
                ToolResult(
                    output=f"Permission denied: {decision.reason}",
                    is_error=True,
                ),
            )
            return

        if decision.effect == "ask":
            loop = asyncio.get_running_loop()
            future: asyncio.Future[PermissionResponse] = loop.create_future()
            yield PermissionRequest(
                tool_name=tool_call.tool_name,
                description=permission_description,
                future=future,
            )
            response = await future

            if response == PermissionResponse.DENY:
                yield _AuthResult(
                    False,
                    ToolResult(
                        output="Permission denied: 用户拒绝了此操作",
                        is_error=True,
                    ),
                )
                return

            if response == PermissionResponse.ALLOW_ALWAYS:
                content = extract_content(tool_call.tool_name, tool_call.arguments)
                pattern = f"{content[:60]}*" if len(content) > 60 else f"{content}*"
                rule = Rule(
                    tool_name=tool_call.tool_name,
                    pattern=pattern,
                    effect="allow",
                )
                permission_checker.rule_engine.append_local_rule(rule)

    yield _AuthResult(True, None)
