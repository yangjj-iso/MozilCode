"""Shared LLM error types and provider-error normalization helpers."""

from __future__ import annotations


class LLMError(Exception):
    """Base error for model provider failures."""


class AuthenticationError(LLMError):
    """Raised when provider credentials are missing or rejected."""


class RateLimitError(LLMError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class NetworkError(LLMError):
    """Raised when a provider request fails due to connectivity."""


def response_header(error: BaseException, name: str) -> str:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    try:
        value = headers.get(name)
    except Exception:
        return ""
    return str(value).strip() if value is not None else ""


def parse_retry_after_seconds(value: str) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    if seconds < 0:
        return None
    return seconds


def rate_limit_error(error: BaseException) -> RateLimitError:
    retry_after = parse_retry_after_seconds(response_header(error, "retry-after"))
    if retry_after is None:
        return RateLimitError("Rate limited. Please wait.")
    return RateLimitError(
        f"Rate limited. Retry after {retry_after:g}s.",
        retry_after=retry_after,
    )
