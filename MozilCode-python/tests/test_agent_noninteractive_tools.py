from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from mozilcode.agent_helpers import build_hook_context, infer_tool_file_path
from mozilcode.agent_noninteractive_tools import execute_noninteractive_tool_call
from mozilcode.hooks import HookContext, ToolRejectedError
from mozilcode.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    PermissionMode,
    RuleEngine,
)
from mozilcode.tools import ToolRegistry
from mozilcode.tools.base import Tool, ToolCallComplete, ToolResult


class WriteParams(BaseModel):
    file_path: str
    content: str = ""


class RecordingWriteTool(Tool):
    name = "WriteFile"
    description = "Write a file"
    params_model = WriteParams
    category = "write"

    def __init__(self) -> None:
        self.calls: list[WriteParams] = []

    async def execute(self, params: WriteParams) -> ToolResult:
        self.calls.append(params)
        return ToolResult(output=f"wrote {params.file_path}")


class FakeHookEngine:
    def __init__(self, rejection: ToolRejectedError | None = None) -> None:
        self.rejection = rejection
        self.pre_contexts: list[HookContext] = []
        self.post_contexts: list[tuple[str, HookContext]] = []

    async def run_pre_tool_hooks(
        self,
        ctx: HookContext,
    ) -> ToolRejectedError | None:
        self.pre_contexts.append(ctx)
        return self.rejection

    async def run_hooks(self, event: str, ctx: HookContext) -> None:
        self.post_contexts.append((event, ctx))


def _registry(tool: RecordingWriteTool | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool or RecordingWriteTool())
    return registry


def _checker(
    tmp_path: Path,
    *,
    mode: PermissionMode = PermissionMode.DEFAULT,
    project_rules_path: Path | None = None,
) -> PermissionChecker:
    return PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(str(tmp_path)),
        rule_engine=RuleEngine(project_rules_path=project_rules_path),
        mode=mode,
    )


async def _execute(
    *,
    registry: ToolRegistry,
    tool_call: ToolCallComplete,
    checker: PermissionChecker | None = None,
    permission_mode: PermissionMode = PermissionMode.DEFAULT,
    hook_engine: FakeHookEngine | None = None,
) -> ToolResult:
    return await execute_noninteractive_tool_call(
        registry=registry,
        permission_checker=checker,
        permission_mode=permission_mode,
        hook_engine=hook_engine,
        build_hook_context=build_hook_context,
        infer_file_path=infer_tool_file_path,
        tool_call=tool_call,
    )


@pytest.mark.asyncio
async def test_execute_noninteractive_tool_call_handles_unknown_tool() -> None:
    result = await _execute(
        registry=ToolRegistry(),
        tool_call=ToolCallComplete("missing", "MissingTool", {}),
    )

    assert result.is_error
    assert "unknown tool" in result.output


@pytest.mark.asyncio
async def test_execute_noninteractive_tool_call_blocks_disabled_tool() -> None:
    registry = _registry()
    registry.disable("WriteFile")

    result = await _execute(
        registry=registry,
        tool_call=ToolCallComplete("write", "WriteFile", {"file_path": "a.txt"}),
    )

    assert result.is_error
    assert "disabled" in result.output


@pytest.mark.asyncio
async def test_execute_noninteractive_tool_call_reports_pre_hook_rejection() -> None:
    tool = RecordingWriteTool()
    hook_engine = FakeHookEngine(
        ToolRejectedError("WriteFile", "blocked by policy", "hook-1")
    )

    result = await _execute(
        registry=_registry(tool),
        tool_call=ToolCallComplete("write", "WriteFile", {"file_path": "a.txt"}),
        hook_engine=hook_engine,
    )

    assert result.is_error
    assert result.output == "Hook rejected: blocked by policy"
    assert tool.calls == []
    assert hook_engine.pre_contexts[0].file_path == "a.txt"
    assert hook_engine.post_contexts == []


@pytest.mark.asyncio
async def test_execute_noninteractive_tool_call_denies_permission_ask_by_default(
    tmp_path,
) -> None:
    tool = RecordingWriteTool()

    result = await _execute(
        registry=_registry(tool),
        tool_call=ToolCallComplete("write", "WriteFile", {"file_path": "a.txt"}),
        checker=_checker(tmp_path),
        permission_mode=PermissionMode.DEFAULT,
    )

    assert result.is_error
    assert "non-interactive agent cannot prompt user" in result.output
    assert tool.calls == []


@pytest.mark.asyncio
async def test_execute_noninteractive_tool_call_allows_ask_in_dont_ask_mode(
    tmp_path,
) -> None:
    tool = RecordingWriteTool()
    hook_engine = FakeHookEngine()

    result = await _execute(
        registry=_registry(tool),
        tool_call=ToolCallComplete("write", "WriteFile", {"file_path": "a.txt"}),
        checker=_checker(tmp_path),
        permission_mode=PermissionMode.DONT_ASK,
        hook_engine=hook_engine,
    )

    assert result == ToolResult(output="wrote a.txt")
    assert [call.file_path for call in tool.calls] == ["a.txt"]
    assert hook_engine.pre_contexts[0].event_name == "pre_tool_use"
    assert hook_engine.post_contexts[0][0] == "post_tool_use"
    assert hook_engine.post_contexts[0][1].file_path == "a.txt"


@pytest.mark.asyncio
async def test_execute_noninteractive_tool_call_reports_permission_denial(
    tmp_path,
) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        yaml.dump([{"rule": "WriteFile(secret.txt)", "effect": "deny"}]),
        encoding="utf-8",
    )

    result = await _execute(
        registry=_registry(),
        tool_call=ToolCallComplete(
            "write",
            "WriteFile",
            {"file_path": "secret.txt"},
        ),
        checker=_checker(tmp_path, project_rules_path=rules_path),
        permission_mode=PermissionMode.DONT_ASK,
    )

    assert result.is_error
    assert "Permission denied" in result.output
