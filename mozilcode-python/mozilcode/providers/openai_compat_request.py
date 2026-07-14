"""OpenAI 兼容 Chat Completions 请求构造。"""

from __future__ import annotations

from typing import Any


def convert_tools_for_chat_completions(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert MozilCode tool schemas to Chat Completions function tools."""
    converted: list[dict[str, Any]] = []
    for tool in tools:
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", tool.get("input_schema", {})),
                },
            }
        )
    return converted


def build_chat_completion_request_kwargs(
    *,
    model: str,
    max_output_tokens: int,
    messages: list[dict[str, Any]],
    system: str = "",
    tools: list[dict[str, Any]] | None = None,
    thinking: bool = False,
) -> dict[str, Any]:
    """Build common Chat Completions streaming request arguments."""
    request_messages = messages
    if system:
        request_messages = [{"role": "system", "content": system}] + messages

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": request_messages,
        "max_tokens": max_output_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        kwargs["tools"] = convert_tools_for_chat_completions(tools)
    if thinking:
        # OpenAI's SDK merges extra_body into the JSON payload.  This is the
        # OpenAI-compatible convention used by the cloud's thinking models.
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
    return kwargs
