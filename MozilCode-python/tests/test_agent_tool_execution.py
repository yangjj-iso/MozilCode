from __future__ import annotations

import asyncio

import pytest

import mozilcode.agent as agent_module
from mozilcode.agent_tool_execution import (
    StreamingExecutor,
    ToolBatch,
    _ToolExecResult,
    partition_tool_calls,
)
from mozilcode.tools.base import ToolResult


def test_agent_module_reexports_tool_partitioning() -> None:
    assert agent_module.partition_tool_calls is partition_tool_calls
    assert agent_module.ToolBatch is ToolBatch
    assert agent_module.StreamingExecutor is StreamingExecutor


@pytest.mark.asyncio
async def test_streaming_executor_preserves_order_and_wraps_errors() -> None:
    async def ok(label: str, delay: float) -> _ToolExecResult:
        await asyncio.sleep(delay)
        return _ToolExecResult(
            tool_id=label,
            tool_name="ReadFile",
            result=ToolResult(output=label),
            elapsed=delay,
            is_unknown=False,
        )

    async def fail() -> _ToolExecResult:
        await asyncio.sleep(0)
        raise RuntimeError("boom")

    executor = StreamingExecutor()
    executor.submit(ok("first", 0.01))
    executor.submit(fail())
    executor.submit(ok("third", 0))

    results = await executor.collect_results()

    assert [result.tool_id for result in results] == ["first", "", "third"]
    assert [result.result.is_error for result in results] == [False, True, False]
    assert "boom" in results[1].result.output
