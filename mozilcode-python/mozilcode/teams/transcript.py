"""团队对话 transcript 序列化存取。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mozilcode.conversation import (
    ConversationManager,
    Message,
    ToolResultBlock,
    ToolUseBlock,
)
from mozilcode.teams.fields import object_field, string_field
from mozilcode.teams.mailbox import validate_mailbox_id

TRANSCRIPT_ROLES = {"user", "assistant"}


def _serialize_conversation(conv: ConversationManager) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for msg in conv.history:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_uses:
            entry["tool_uses"] = [
                {
                    "tool_use_id": tu.tool_use_id,
                    "tool_name": tu.tool_name,
                    "arguments": tu.arguments,
                }
                for tu in msg.tool_uses
            ]
        if msg.tool_results:
            entry["tool_results"] = [
                {
                    "tool_use_id": tr.tool_use_id,
                    "content": tr.content,
                    "is_error": tr.is_error,
                }
                for tr in msg.tool_results
            ]
        messages.append(entry)
    return messages


def _transcript_string_field(
    data: dict[str, Any],
    name: str,
    *,
    required: bool = True,
) -> str:
    return string_field(data, name, prefix="transcript", required=required)


def _message_from_payload(entry: object) -> Message | None:
    if not isinstance(entry, dict):
        return None
    try:
        role = _transcript_string_field(entry, "role")
        if role not in TRANSCRIPT_ROLES:
            return None
        content = _transcript_string_field(entry, "content", required=False)
        raw_tool_uses = entry.get("tool_uses", [])
        if not isinstance(raw_tool_uses, list):
            return None
        raw_tool_results = entry.get("tool_results", [])
        if not isinstance(raw_tool_results, list):
            return None

        tool_uses = []
        for tu in raw_tool_uses:
            if not isinstance(tu, dict):
                return None
            tool_uses.append(
                ToolUseBlock(
                    tool_use_id=_transcript_string_field(tu, "tool_use_id"),
                    tool_name=_transcript_string_field(tu, "tool_name"),
                    arguments=object_field(tu, "arguments", prefix="transcript"),
                )
            )
        tool_results = []
        for tr in raw_tool_results:
            if not isinstance(tr, dict):
                return None
            is_error = tr.get("is_error", False)
            if not isinstance(is_error, bool):
                return None
            tool_results.append(
                ToolResultBlock(
                    tool_use_id=_transcript_string_field(tr, "tool_use_id"),
                    content=_transcript_string_field(tr, "content"),
                    is_error=is_error,
                )
            )
    except ValueError:
        return None

    return Message(
        role=role,
        content=content,
        tool_uses=tool_uses,
        tool_results=tool_results,
    )


def _deserialize_conversation(data: list[dict[str, Any]]) -> ConversationManager:
    conv = ConversationManager()
    for entry in data:
        msg = _message_from_payload(entry)
        if msg is not None:
            conv.history.append(msg)
    conv.env_injected = True
    conv.ltm_injected = True
    return conv


def save_transcript(
    team_name: str,
    agent_id: str,
    conversation: ConversationManager,
) -> Path:
    from mozilcode.teams.models import resolve_team_dir

    transcript_dir = resolve_team_dir(team_name) / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    path = transcript_dir / f"{validate_mailbox_id(agent_id, 'agent_id')}.json"
    data = _serialize_conversation(conversation)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_transcript(
    team_name: str,
    agent_id: str,
) -> ConversationManager | None:
    from mozilcode.teams.models import resolve_team_dir

    path = (
        resolve_team_dir(team_name)
        / "transcripts"
        / f"{validate_mailbox_id(agent_id, 'agent_id')}.json"
    )
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, list):
        return None
    return _deserialize_conversation(data)
