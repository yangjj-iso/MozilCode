from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from mozilcode.agent_events import PermissionRequest, PermissionResponse
from mozilcode.agent_tool_authorization import authorize_tool_call
from mozilcode.agent_tool_execution import _AuthResult
from mozilcode.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    PermissionMode,
    Rule,
    RuleEngine,
)
from mozilcode.tools import ToolRegistry
from mozilcode.tools.base import Tool, ToolCallComplete, ToolResult


class WriteParams(BaseModel):
    file_path: str
    content: str = ""


class DummyWriteTool(Tool):
    name = "WriteFile"
    description = "Write a file"
    params_model = WriteParams
    category = "write"

    async def execute(self, params: WriteParams) -> ToolResult:
        return ToolResult(output="ok")


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(DummyWriteTool())
    return registry


def _checker(
    tmp_path: Path,
    *,
    mode: PermissionMode = PermissionMode.DEFAULT,
    local_rules_path: Path | None = None,
    project_rules_path: Path | None = None,
) -> PermissionChecker:
    return PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(str(tmp_path)),
        rule_engine=RuleEngine(
            project_rules_path=project_rules_path,
            local_rules_path=local_rules_path,
        ),
        mode=mode,
    )


async def _authorize(
    registry: ToolRegistry,
    checker: PermissionChecker | None,
    tool_call: ToolCallComplete,
    *,
    response: PermissionResponse | None = None,
) -> list[PermissionRequest | _AuthResult]:
    items: list[PermissionRequest | _AuthResult] = []
    async for item in authorize_tool_call(
        registry=registry,
        permission_checker=checker,
        tool_call=tool_call,
        permission_description="target.txt",
    ):
        items.append(item)
        if isinstance(item, PermissionRequest) and response is not None:
            item.future.set_result(response)
    return items


@pytest.mark.asyncio
async def test_authorize_tool_call_marks_unknown_tool() -> None:
    items = await _authorize(
        ToolRegistry(),
        None,
        ToolCallComplete("missing", "MissingTool", {}),
    )

    assert len(items) == 1
    auth = items[0]
    assert isinstance(auth, _AuthResult)
    assert auth.approved is False
    assert auth.is_unknown is True
    assert auth.error is not None
    assert "unknown tool" in auth.error.output


@pytest.mark.asyncio
async def test_authorize_tool_call_blocks_disabled_tool(tmp_path) -> None:
    registry = _registry()
    registry.disable("WriteFile")

    items = await _authorize(
        registry,
        _checker(tmp_path),
        ToolCallComplete("write", "WriteFile", {"file_path": "target.txt"}),
    )

    assert len(items) == 1
    auth = items[0]
    assert isinstance(auth, _AuthResult)
    assert auth.approved is False
    assert auth.error is not None
    assert "disabled" in auth.error.output


@pytest.mark.asyncio
async def test_authorize_tool_call_reports_checker_denial(tmp_path) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        yaml.dump([{"rule": "WriteFile(secret.txt)", "effect": "deny"}]),
        encoding="utf-8",
    )

    items = await _authorize(
        _registry(),
        _checker(tmp_path, project_rules_path=rules_path),
        ToolCallComplete("write", "WriteFile", {"file_path": "secret.txt"}),
    )

    assert len(items) == 1
    auth = items[0]
    assert isinstance(auth, _AuthResult)
    assert auth.approved is False
    assert auth.error is not None
    assert "Permission denied" in auth.error.output


@pytest.mark.asyncio
async def test_authorize_tool_call_yields_permission_request_then_denies(tmp_path) -> None:
    items = await _authorize(
        _registry(),
        _checker(tmp_path),
        ToolCallComplete("write", "WriteFile", {"file_path": "target.txt"}),
        response=PermissionResponse.DENY,
    )

    assert len(items) == 2
    request = items[0]
    auth = items[1]
    assert isinstance(request, PermissionRequest)
    assert request.tool_name == "WriteFile"
    assert request.description == "target.txt"
    assert isinstance(auth, _AuthResult)
    assert auth.approved is False
    assert auth.error is not None
    assert "Permission denied" in auth.error.output


@pytest.mark.asyncio
async def test_authorize_tool_call_allow_always_appends_local_rule(tmp_path) -> None:
    local_rules_path = tmp_path / ".mozilcode" / "permissions.local.yaml"

    items = await _authorize(
        _registry(),
        _checker(tmp_path, local_rules_path=local_rules_path),
        ToolCallComplete("write", "WriteFile", {"file_path": "target.txt"}),
        response=PermissionResponse.ALLOW_ALWAYS,
    )

    assert len(items) == 2
    assert isinstance(items[0], PermissionRequest)
    auth = items[1]
    assert isinstance(auth, _AuthResult)
    assert auth.approved is True

    stored = yaml.safe_load(local_rules_path.read_text(encoding="utf-8"))
    assert stored == [{"rule": "WriteFile(target.txt*)", "effect": "allow"}]


@pytest.mark.asyncio
async def test_authorize_tool_call_allows_when_rule_allows(tmp_path) -> None:
    rules_path = tmp_path / "rules.yaml"
    RuleEngine(local_rules_path=rules_path).append_local_rule(
        Rule("WriteFile", "target.txt", "allow")
    )

    items = await _authorize(
        _registry(),
        _checker(tmp_path, project_rules_path=rules_path),
        ToolCallComplete("write", "WriteFile", {"file_path": "target.txt"}),
    )

    assert len(items) == 1
    auth = items[0]
    assert isinstance(auth, _AuthResult)
    assert auth.approved is True
