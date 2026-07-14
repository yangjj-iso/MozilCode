"""工具结果块与 ToolResultEvent 构造测试。"""

from __future__ import annotations

from mozilcode.agent.tool_results import (
    hook_rejected_result,
    tool_result_block,
    tool_result_event,
)
from mozilcode.context.tool_results import PERSISTED_TAG, SINGLE_RESULT_CHAR_LIMIT
from mozilcode.tools.base import ToolCallComplete, ToolResult


def _tool_call() -> ToolCallComplete:
    return ToolCallComplete(
        tool_id="tool-1",
        tool_name="ReadFile",
        arguments={"file_path": "README.md"},
    )


def test_tool_result_block_keeps_small_output_inline(tmp_path) -> None:
    block = tool_result_block(
        _tool_call(),
        ToolResult(output="ok"),
        tmp_path,
    )

    assert block.tool_use_id == "tool-1"
    assert block.content == "ok"
    assert block.is_error is False


def test_tool_result_block_persists_large_output(tmp_path) -> None:
    block = tool_result_block(
        _tool_call(),
        ToolResult(output="x" * (SINGLE_RESULT_CHAR_LIMIT + 1)),
        tmp_path,
    )

    assert block.tool_use_id == "tool-1"
    assert block.content.startswith(PERSISTED_TAG)
    assert (tmp_path / "tool-1.txt").exists()


def test_tool_result_block_preserves_error_flag(tmp_path) -> None:
    block = tool_result_block(
        _tool_call(),
        ToolResult(output="failed", is_error=True),
        tmp_path,
    )

    assert block.content == "failed"
    assert block.is_error is True


def test_tool_result_event_uses_raw_output_and_elapsed() -> None:
    event = tool_result_event(
        _tool_call(),
        ToolResult(output="raw result", is_error=True),
        elapsed=1.25,
    )

    assert event.tool_id == "tool-1"
    assert event.tool_name == "ReadFile"
    assert event.output == "raw result"
    assert event.is_error is True
    assert event.elapsed == 1.25


def test_hook_rejected_result_formats_reason() -> None:
    result = hook_rejected_result("blocked by policy")

    assert result.output == "Hook rejected: blocked by policy"
    assert result.is_error is True
