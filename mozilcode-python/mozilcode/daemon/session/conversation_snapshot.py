"""Durable, provider-neutral ConversationManager snapshots for daemon sessions."""

from __future__ import annotations

from typing import Any

from mozilcode.conversation import (
    ConversationManager,
    Message,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def serialize_conversation(conversation: ConversationManager) -> list[dict[str, Any]]:
    """Return a JSON-safe copy of the model-visible conversation history."""
    return [
        {
            "role": message.role,
            "content": message.content,
            "tool_uses": [
                {"id": tool.tool_use_id, "name": tool.tool_name, "arguments": tool.arguments}
                for tool in message.tool_uses
            ],
            "tool_results": [
                {"id": result.tool_use_id, "content": result.content, "is_error": result.is_error}
                for result in message.tool_results
            ],
            "thinking_blocks": [
                {"thinking": block.thinking, "signature": block.signature}
                for block in message.thinking_blocks
            ],
        }
        for message in conversation.history
    ]


def restore_conversation(raw: object) -> ConversationManager:
    """Restore a validated snapshot; malformed entries are ignored safely."""
    history: list[Message] = []
    if not isinstance(raw, list):
        return ConversationManager()
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        tool_uses = [
            ToolUseBlock(tool_use_id=entry["id"], tool_name=entry["name"], arguments=entry.get("arguments", {}))
            for entry in item.get("tool_uses", [])
            if isinstance(entry, dict)
            and isinstance(entry.get("id"), str)
            and isinstance(entry.get("name"), str)
            and isinstance(entry.get("arguments", {}), dict)
        ]
        tool_results = [
            ToolResultBlock(
                tool_use_id=entry["id"],
                content=entry["content"],
                is_error=entry.get("is_error", False),
            )
            for entry in item.get("tool_results", [])
            if isinstance(entry, dict)
            and isinstance(entry.get("id"), str)
            and isinstance(entry.get("content"), str)
            and isinstance(entry.get("is_error", False), bool)
        ]
        thinking_blocks = [
            ThinkingBlock(thinking=entry["thinking"], signature=entry["signature"])
            for entry in item.get("thinking_blocks", [])
            if isinstance(entry, dict)
            and isinstance(entry.get("thinking"), str)
            and isinstance(entry.get("signature"), str)
        ]
        history.append(Message(role, content, tool_uses, tool_results, thinking_blocks))
    return ConversationManager(history=history)


def restore_conversation_from_events(events: object) -> ConversationManager:
    """Best-effort migration path for sessions written before snapshots existed."""
    if not isinstance(events, list):
        return ConversationManager()
    conversation = ConversationManager()
    text = ""
    tools: list[ToolUseBlock] = []
    results: list[ToolResultBlock] = []

    def flush_assistant() -> None:
        nonlocal text, tools, results
        if text or tools:
            conversation.add_assistant_message(text, tool_uses=tools)
        if results:
            conversation.add_tool_results_message(results)
        text, tools, results = "", [], []

    for event in events:
        if not isinstance(event, dict):
            continue
        data = event.get("data")
        data = data if isinstance(data, dict) else {}
        kind = event.get("type")
        if kind == "UserMessage":
            flush_assistant()
            content = data.get("content")
            if isinstance(content, str):
                conversation.add_user_message(content)
        elif kind == "StreamText" and isinstance(data.get("text"), str):
            text += data["text"]
        elif kind == "ToolUseEvent":
            tool_id = data.get("tool_id")
            name = data.get("tool_name")
            arguments = data.get("arguments", {})
            if isinstance(tool_id, str) and isinstance(name, str) and isinstance(arguments, dict):
                tools.append(ToolUseBlock(tool_id, name, arguments))
        elif kind == "ToolResultEvent":
            tool_id = data.get("tool_id")
            output = data.get("output")
            if isinstance(tool_id, str) and isinstance(output, str):
                results.append(ToolResultBlock(tool_id, output, bool(data.get("is_error"))))
        elif kind in {"TurnComplete", "LoopComplete", "TaskCancelled", "ErrorEvent"}:
            flush_assistant()
    flush_assistant()
    return conversation
