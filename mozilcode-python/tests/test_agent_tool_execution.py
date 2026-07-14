"""工具批处理分区与实际执行测试。"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

import mozilcode.agent as agent_module
from mozilcode.agent.tool_execution import (
    StreamingExecutor,
    ToolBatch,
    _ToolExecResult,
    execute_direct_tool_call,
    execute_validated_tool,
    partition_tool_calls,
)
from mozilcode.tools import ToolRegistry
from mozilcode.tools.base import Tool, ToolCallComplete, ToolResult


class EchoParams(BaseModel):
    value: str


class EchoTool(Tool):
    name = "Echo"
    description = "Echo a value"
    params_model = EchoParams
    category = "read"
    is_concurrency_safe = True

    async def execute(self, params: EchoParams) -> ToolResult:
        return ToolResult(output=params.value)


class FailingTool(EchoTool):
    name = "FailingEcho"

    async def execute(self, params: EchoParams) -> ToolResult:
        raise RuntimeError("boom")


def test_agent_module_reexports_tool_partitioning() -> None:
    assert agent_module.partition_tool_calls is partition_tool_calls
    assert agent_module.ToolBatch is ToolBatch
    assert agent_module.StreamingExecutor is StreamingExecutor


@pytest.mark.asyncio
async def test_execute_validated_tool_runs_tool_with_validated_params() -> None:
    result = await execute_validated_tool(EchoTool(), {"value": "ok"})

    assert result == ToolResult(output="ok")


@pytest.mark.asyncio
async def test_execute_validated_tool_wraps_validation_errors() -> None:
    result = await execute_validated_tool(EchoTool(), {})

    assert result.is_error
    assert "Parameter validation error" in result.output


@pytest.mark.asyncio
async def test_execute_validated_tool_wraps_execution_errors() -> None:
    result = await execute_validated_tool(FailingTool(), {"value": "ok"})

    assert result.is_error
    assert "Tool execution error: boom" in result.output


@pytest.mark.asyncio
async def test_execute_direct_tool_call_handles_registry_states() -> None:
    registry = ToolRegistry()
    missing = await execute_direct_tool_call(
        registry,
        ToolCallComplete("missing", "MissingTool", {}),
    )
    assert missing.is_unknown is True
    assert missing.result.is_error
    assert "unknown tool" in missing.result.output

    registry.register(EchoTool())
    registry.disable("Echo")
    disabled = await execute_direct_tool_call(
        registry,
        ToolCallComplete("echo", "Echo", {"value": "ok"}),
    )
    assert disabled.is_unknown is False
    assert disabled.result.is_error
    assert "disabled" in disabled.result.output

    registry.enable("Echo")
    success = await execute_direct_tool_call(
        registry,
        ToolCallComplete("echo", "Echo", {"value": "ok"}),
    )
    assert success.tool_id == "echo"
    assert success.tool_name == "Echo"
    assert success.result == ToolResult(output="ok")
    assert success.elapsed >= 0


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
