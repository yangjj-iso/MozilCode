from __future__ import annotations

from pathlib import Path

from mozilcode.agent.events import ToolResultEvent
from mozilcode.context import prepare_tool_result_content
from mozilcode.conversation import ToolResultBlock
from mozilcode.tools.base import ToolCallComplete, ToolResult


def tool_result_block(
    tool_call: ToolCallComplete,
    result: ToolResult,
    session_dir: Path,
) -> ToolResultBlock:
    return ToolResultBlock(
        tool_use_id=tool_call.tool_id,
        content=prepare_tool_result_content(
            tool_call.tool_id,
            result.output,
            session_dir,
        ),
        is_error=result.is_error,
    )


def tool_result_event(
    tool_call: ToolCallComplete,
    result: ToolResult,
    elapsed: float,
) -> ToolResultEvent:
    return ToolResultEvent(
        tool_id=tool_call.tool_id,
        tool_name=tool_call.tool_name,
        output=result.output,
        is_error=result.is_error,
        elapsed=elapsed,
    )


def hook_rejected_result(reason: str) -> ToolResult:
    return ToolResult(
        output=f"Hook rejected: {reason}",
        is_error=True,
    )
