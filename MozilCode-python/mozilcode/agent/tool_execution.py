from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from mozilcode.tools import ToolRegistry
from mozilcode.tools.base import Tool, ToolCallComplete, ToolResult


@dataclass
class ToolBatch:
    concurrent: bool
    calls: list[ToolCallComplete]


def partition_tool_calls(
    tool_calls: list[ToolCallComplete],
    registry: ToolRegistry,
) -> list[ToolBatch]:
    batches: list[ToolBatch] = []
    for tc in tool_calls:
        tool = registry.get(tc.tool_name)
        safe = (
            tool is not None
            and tool.is_concurrency_safe
            and registry.is_enabled(tc.tool_name)
        )

        if safe and batches and batches[-1].concurrent:
            batches[-1].calls.append(tc)
        else:
            batches.append(ToolBatch(concurrent=safe, calls=[tc]))
    return batches


@dataclass
class _ToolExecResult:
    tool_id: str
    tool_name: str
    result: ToolResult
    elapsed: float
    is_unknown: bool


@dataclass
class _AuthResult:
    """Tool authorization result. If approved is False, error holds the result."""

    approved: bool
    error: ToolResult | None = None
    is_unknown: bool = False


async def execute_validated_tool(tool: Tool, arguments: dict[str, Any]) -> ToolResult:
    try:
        params = tool.params_model.model_validate(arguments)
        return await tool.execute(params)
    except ValidationError as e:
        return ToolResult(output=f"Parameter validation error: {e}", is_error=True)
    except Exception as e:
        return ToolResult(output=f"Tool execution error: {e}", is_error=True)


async def execute_direct_tool_call(
    registry: ToolRegistry,
    tool_call: ToolCallComplete,
) -> _ToolExecResult:
    start = time.monotonic()
    tool = registry.get(tool_call.tool_name)

    if tool is None:
        return _ToolExecResult(
            tool_id=tool_call.tool_id,
            tool_name=tool_call.tool_name,
            result=ToolResult(
                output=f"Error: unknown tool '{tool_call.tool_name}'",
                is_error=True,
            ),
            elapsed=time.monotonic() - start,
            is_unknown=True,
        )

    if not registry.is_enabled(tool_call.tool_name):
        return _ToolExecResult(
            tool_id=tool_call.tool_id,
            tool_name=tool_call.tool_name,
            result=ToolResult(
                output=f"Error: tool '{tool_call.tool_name}' is disabled",
                is_error=True,
            ),
            elapsed=time.monotonic() - start,
            is_unknown=False,
        )

    result = await execute_validated_tool(tool, tool_call.arguments)
    return _ToolExecResult(
        tool_id=tool_call.tool_id,
        tool_name=tool_call.tool_name,
        result=result,
        elapsed=time.monotonic() - start,
        is_unknown=False,
    )


class StreamingExecutor:
    def __init__(self) -> None:
        self._tasks: list[tuple[int, asyncio.Task[_ToolExecResult]]] = []
        self._order = 0

    def submit(
        self,
        coro: Any,
    ) -> None:
        task = asyncio.create_task(coro)
        self._tasks.append((self._order, task))
        self._order += 1

    async def collect_results(self) -> list[_ToolExecResult]:
        if not self._tasks:
            return []
        tasks = [t for _, t in sorted(self._tasks, key=lambda x: x[0])]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: list[_ToolExecResult] = []
        for r in results:
            if isinstance(r, Exception):
                out.append(
                    _ToolExecResult(
                        tool_id="",
                        tool_name="",
                        result=ToolResult(
                            output=f"Tool execution error: {r}",
                            is_error=True,
                        ),
                        elapsed=0.0,
                        is_unknown=False,
                    )
                )
            else:
                out.append(r)
        return out
