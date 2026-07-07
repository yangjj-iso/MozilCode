"""Request construction helpers for OpenAI Responses API calls."""

from __future__ import annotations

from typing import Any


def build_openai_response_request_kwargs(
    *,
    model: str,
    input_messages: list[dict[str, Any]],
    system: str = "",
    tools: list[dict[str, Any]] | None = None,
    thinking: bool = False,
) -> dict[str, Any]:
    """Build common OpenAI Responses streaming request arguments."""
    kwargs: dict[str, Any] = {
        "model": model,
        "input": input_messages,
        "stream": True,
    }
    if system:
        kwargs["instructions"] = system
    if tools:
        kwargs["tools"] = tools
    if thinking:
        kwargs["reasoning"] = {"summary": "auto"}
    return kwargs
