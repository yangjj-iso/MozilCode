"""Anthropic 请求构造。

cache_control、thinking 配置与 request kwargs。"""

from __future__ import annotations

from typing import Any

# Limit model metadata fetch time so slow /v1/models endpoints do not delay
# startup. Callers degrade to built-in context-window defaults on timeout.
ANTHROPIC_MODEL_FETCH_TIMEOUT = 3.0

EPHEMERAL_CACHE_CONTROL = {"type": "ephemeral"}


def mark_last_user_tail_for_cache(messages: list[dict[str, Any]]) -> None:
    """Attach cache_control to the last block of the last user message in-place."""
    if not messages:
        return
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": EPHEMERAL_CACHE_CONTROL,
                }
            ]
        elif isinstance(content, list) and content:
            last = content[-1]
            if isinstance(last, dict):
                last["cache_control"] = EPHEMERAL_CACHE_CONTROL
        return


def mark_last_tool_for_cache(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a shallow-copy tool list with cache_control on the final tool."""
    if not tools:
        return tools
    marked = list(tools)
    last = dict(marked[-1])
    last["cache_control"] = EPHEMERAL_CACHE_CONTROL
    marked[-1] = last
    return marked


def supports_adaptive_thinking(model: str) -> bool:
    for family in ("claude-opus-4-", "claude-sonnet-4-"):
        if model.startswith(family):
            rest = model[len(family):]
            if rest and rest[0].isdigit() and int(rest[0]) >= 6:
                return True
    return False


def thinking_config(model: str, max_output_tokens: int) -> dict[str, Any]:
    if supports_adaptive_thinking(model):
        return {"type": "enabled", "budget_tokens": 0}
    return {
        "type": "enabled",
        "budget_tokens": max(max_output_tokens - 1, 1024),
    }


def build_anthropic_request_kwargs(
    *,
    model: str,
    max_output_tokens: int,
    messages: list[dict[str, Any]],
    system: str = "",
    tools: list[dict[str, Any]] | None = None,
    thinking: bool = False,
) -> dict[str, Any]:
    mark_last_user_tail_for_cache(messages)
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_output_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = [
            {
                "type": "text",
                "text": system,
                "cache_control": EPHEMERAL_CACHE_CONTROL,
            }
        ]
    if tools:
        kwargs["tools"] = mark_last_tool_for_cache(tools)
    if thinking:
        kwargs["thinking"] = thinking_config(model, max_output_tokens)
    return kwargs
