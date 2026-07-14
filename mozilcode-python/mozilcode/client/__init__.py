"""LLM 客户端包。

Provider 客户端、错误处理、鉴权与 context window 解析。"""

from mozilcode.client.auth import is_local_base_url, resolve_openai_api_key
from mozilcode.client.core import (
    AnthropicClient,
    LLMClient,
    OpenAIClient,
    OpenAICompatClient,
    _mark_last_tool_for_cache,
    _mark_last_user_tail_for_cache,
    _rate_limit_error,
    _resolve_openai_api_key,
    _stream_end_from_openai_chat_usage,
    _stream_end_from_openai_response_usage,
    _supports_adaptive_thinking,
    create_client,
    resolve_context_window,
)
from mozilcode.client.error_mapping import ProviderErrorMapper, provider_error_mapper
from mozilcode.client.errors import (
    AuthenticationError,
    LLMError,
    NetworkError,
    RateLimitError,
    rate_limit_error,
)

# Aliases matching the private names used in core.py
_is_local_base_url = is_local_base_url

__all__ = [
    "AnthropicClient",
    "AuthenticationError",
    "LLMClient",
    "LLMError",
    "NetworkError",
    "OpenAIClient",
    "OpenAICompatClient",
    "ProviderErrorMapper",
    "RateLimitError",
    "create_client",
    "is_local_base_url",
    "provider_error_mapper",
    "rate_limit_error",
    "resolve_context_window",
    "resolve_openai_api_key",
]
