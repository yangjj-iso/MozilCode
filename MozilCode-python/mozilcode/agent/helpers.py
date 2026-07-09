from __future__ import annotations

from typing import Any

from mozilcode.conversation import ConversationManager
from mozilcode.hooks import HookContext
from mozilcode.tools.base import ToolCallComplete


def build_hook_context(event: str, **kwargs: str | dict) -> HookContext:
    return HookContext(
        event_name=event,
        tool_name=str(kwargs.get("tool_name", "")),
        tool_args=kwargs.get("tool_args", {}),
        file_path=str(kwargs.get("file_path", "")),
        message=str(kwargs.get("message", "")),
        error=str(kwargs.get("error", "")),
    )


def infer_tool_file_path(args: dict[str, Any]) -> str:
    return str(args.get("file_path", args.get("path", "")))


def latest_user_query(conversation: ConversationManager) -> str:
    for message in reversed(conversation.history):
        if message.role != "user" or message.tool_results:
            continue
        content = message.content.strip()
        if not content:
            continue
        if content.startswith("<system-reminder>"):
            continue
        if content.startswith("Current working directory:"):
            continue
        return content
    return ""


def build_permission_description(tc: ToolCallComplete) -> str:
    if tc.tool_name == "Bash":
        return tc.arguments.get("command", tc.tool_name)
    if tc.tool_name in ("ReadFile", "WriteFile", "EditFile"):
        return tc.arguments.get("file_path", tc.tool_name)
    return str(tc.arguments)
