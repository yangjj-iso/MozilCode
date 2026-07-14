"""Agent 循环小工具函数测试。"""

from __future__ import annotations

from mozilcode.agent.helpers import (
    build_hook_context,
    build_permission_description,
    infer_tool_file_path,
    latest_user_query,
)
from mozilcode.conversation import ConversationManager, ToolResultBlock
from mozilcode.tools.base import ToolCallComplete


def test_build_hook_context_normalizes_optional_fields() -> None:
    ctx = build_hook_context(
        "tool_call",
        tool_name="ReadFile",
        tool_args={"file_path": "README.md"},
        file_path="README.md",
        message="ok",
    )

    assert ctx.event_name == "tool_call"
    assert ctx.tool_name == "ReadFile"
    assert ctx.tool_args == {"file_path": "README.md"}
    assert ctx.file_path == "README.md"
    assert ctx.message == "ok"
    assert ctx.error == ""


def test_infer_tool_file_path_prefers_file_path_then_path() -> None:
    assert infer_tool_file_path({"file_path": "a.txt", "path": "b.txt"}) == "a.txt"
    assert infer_tool_file_path({"path": "b.txt"}) == "b.txt"
    assert infer_tool_file_path({}) == ""


def test_latest_user_query_skips_reminders_cwd_and_tool_results() -> None:
    conversation = ConversationManager()
    conversation.add_user_message("first useful")
    conversation.add_tool_results_message(
        [ToolResultBlock("tool-1", "tool output")],
    )
    conversation.add_user_message("Current working directory: D:/repo")
    conversation.add_system_reminder("do not count me")
    conversation.add_user_message("  final useful  ")

    assert latest_user_query(conversation) == "final useful"


def test_latest_user_query_falls_back_to_older_user_message() -> None:
    conversation = ConversationManager()
    conversation.add_user_message("older")
    conversation.add_system_reminder("ignore")
    conversation.add_user_message("Current working directory: D:/repo")

    assert latest_user_query(conversation) == "older"


def test_latest_user_query_returns_empty_when_no_user_query() -> None:
    conversation = ConversationManager()
    conversation.add_system_reminder("ignore")

    assert latest_user_query(conversation) == ""


def test_build_permission_description_uses_stable_tool_fields() -> None:
    assert (
        build_permission_description(
            ToolCallComplete("1", "Bash", {"command": "pytest -q"}),
        )
        == "pytest -q"
    )
    assert (
        build_permission_description(
            ToolCallComplete("2", "ReadFile", {"file_path": "README.md"}),
        )
        == "README.md"
    )
    assert (
        build_permission_description(
            ToolCallComplete("3", "CustomTool", {"value": 1}),
        )
        == "{'value': 1}"
    )
