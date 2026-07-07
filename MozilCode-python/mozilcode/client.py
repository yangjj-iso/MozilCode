from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from mozilcode.anthropic_request import (
    ANTHROPIC_MODEL_FETCH_TIMEOUT,
    build_anthropic_request_kwargs,
    mark_last_tool_for_cache as _mark_last_tool_for_cache,
    mark_last_user_tail_for_cache as _mark_last_user_tail_for_cache,
    supports_adaptive_thinking as _supports_adaptive_thinking,
)
from mozilcode.config import ProviderConfig
from mozilcode.conversation import ConversationManager
from mozilcode.serialization import (
    build_anthropic_messages,
    build_chat_completion_messages,
    build_openai_input,
)
from mozilcode.llm_errors import (
    AuthenticationError,
    LLMError,
    NetworkError,
    RateLimitError,
    rate_limit_error as _rate_limit_error,
)
from mozilcode.openai_streaming import (
    OpenAIChatToolCallState,
    OpenAIResponseToolCallState,
    RESPONSE_REASONING_DELTA_EVENTS as _RESPONSE_REASONING_DELTA_EVENTS,
    RESPONSE_REASONING_DONE_EVENTS as _RESPONSE_REASONING_DONE_EVENTS,
    extract_chat_reasoning_delta as _extract_chat_reasoning_delta,
    extract_response_reasoning_summary as _extract_response_reasoning_summary,
    get_text as _get_text,
    stream_end_from_openai_chat_usage as _stream_end_from_openai_chat_usage,
    stream_end_from_openai_response_usage as _stream_end_from_openai_response_usage,
)
from mozilcode.openai_compat_request import build_chat_completion_request_kwargs
from mozilcode.openai_responses_request import build_openai_response_request_kwargs
from mozilcode.provider_auth import (
    is_local_base_url as _is_local_base_url,
    resolve_openai_api_key as _resolve_openai_api_key,
)
from mozilcode.tools.base import (
    StreamEnd,
    StreamEvent,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
)


class LLMClient(ABC):
    @abstractmethod
    async def stream(
        self,
        conversation: ConversationManager,
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        yield TextDelta("")

    def set_max_output_tokens(self, tokens: int) -> None:
        pass


class AnthropicClient(LLMClient):
    def __init__(self, config: ProviderConfig) -> None:
        self.model = config.model
        self.thinking = config.thinking
        self.max_output_tokens = config.get_max_output_tokens()
        api_key = config.resolve_api_key()
        if not api_key:
            raise AuthenticationError(
                "Anthropic API key not found. "
                "Set it in .mozilcode/config.yaml or via ANTHROPIC_API_KEY env var."
            )
        self._client = AsyncAnthropic(api_key=api_key, base_url=config.base_url)

    def set_max_output_tokens(self, tokens: int) -> None:
        self.max_output_tokens = tokens

    async def fetch_model_context_window(self) -> int | None:
        """向 Anthropic 兼容的 /v1/models/{model} 端点查询模型的
        max_input_tokens（context window 解析的第 2 层）。

        采用尽力而为策略：遇到任何错误——非 anthropic 端点、网络故障、
        超时、字段缺失——都返回 ``None`` 而非抛出异常，以便调用方降级到
        下一层。它的阻塞时间不会超过 ANTHROPIC_MODEL_FETCH_TIMEOUT，也不会
        向外传播异常，因此在启动时调用是安全的。
        """
        try:
            info = await self._client.models.retrieve(
                self.model, timeout=ANTHROPIC_MODEL_FETCH_TIMEOUT
            )
            window = getattr(info, "max_input_tokens", None)
            if isinstance(window, int) and window > 0:
                return window
            return None
        except Exception:
            return None

    async def stream(
        self,
        conversation: ConversationManager,
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        import anthropic as _anthropic

        kwargs = build_anthropic_request_kwargs(
            model=self.model,
            max_output_tokens=self.max_output_tokens,
            messages=build_anthropic_messages(conversation.get_messages()),
            system=system,
            tools=tools,
            thinking=self.thinking,
        )

        current_tool_name = ""
        current_tool_id = ""
        json_accum = ""
        in_thinking = False
        thinking_accum = ""
        thinking_signature = ""

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "thinking":
                            in_thinking = True
                            thinking_accum = ""
                            thinking_signature = ""
                        elif block.type == "tool_use":
                            current_tool_name = block.name
                            current_tool_id = block.id
                            json_accum = ""
                            yield ToolCallStart(
                                tool_name=current_tool_name,
                                tool_id=current_tool_id,
                            )
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield TextDelta(text=delta.text)
                        elif delta.type == "thinking_delta":
                            thinking_accum += delta.thinking
                            yield ThinkingDelta(text=delta.thinking)
                        elif delta.type == "signature_delta":
                            thinking_signature = delta.signature
                        elif delta.type == "input_json_delta":
                            json_accum += delta.partial_json
                            yield ToolCallDelta(text=delta.partial_json)
                    elif event.type == "content_block_stop":
                        if in_thinking:
                            yield ThinkingComplete(
                                thinking=thinking_accum,
                                signature=thinking_signature,
                            )
                            in_thinking = False
                        if current_tool_name:
                            try:
                                args = json.loads(json_accum) if json_accum else {}
                            except json.JSONDecodeError:
                                args = {}
                            yield ToolCallComplete(
                                tool_id=current_tool_id,
                                tool_name=current_tool_name,
                                arguments=args,
                            )
                            current_tool_name = ""
                            current_tool_id = ""
                            json_accum = ""
                    elif event.type == "message_stop":
                        pass

                final = await stream.get_final_message()
                usage = final.usage
                yield StreamEnd(
                    stop_reason=final.stop_reason or "end_turn",
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read=getattr(usage, "cache_read_input_tokens", 0) or 0,
                    cache_creation=getattr(
                        usage, "cache_creation_input_tokens", 0
                    ) or 0,
                )

        except _anthropic.AuthenticationError as e:
            raise AuthenticationError(f"Invalid API key: {e}") from e
        except _anthropic.RateLimitError as e:
            raise _rate_limit_error(e) from e
        except _anthropic.APIConnectionError as e:
            raise NetworkError(f"Network error: {e}") from e
        except _anthropic.APIStatusError as e:
            raise LLMError(f"API error ({e.status_code}): {e.message}") from e


class OpenAIClient(LLMClient):
    def __init__(self, config: ProviderConfig) -> None:
        self.model = config.model
        self.thinking = config.thinking
        self.max_output_tokens = config.get_max_output_tokens()
        api_key = _resolve_openai_api_key(config)
        if not api_key:
            raise AuthenticationError(
                "OpenAI API key not found. "
                "Set it in .mozilcode/config.yaml or via OPENAI_API_KEY env var."
            )
        self._client = AsyncOpenAI(api_key=api_key, base_url=config.base_url)

    def set_max_output_tokens(self, tokens: int) -> None:
        self.max_output_tokens = tokens

    async def stream(
        self,
        conversation: ConversationManager,
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        import openai as _openai

        kwargs = build_openai_response_request_kwargs(
            model=self.model,
            input_messages=build_openai_input(conversation.get_messages()),
            system=system,
            tools=tools,
            thinking=self.thinking,
        )

        response_tool_call = OpenAIResponseToolCallState()
        reasoning_accum = ""
        reasoning_completed = False

        try:
            response_stream = await self._client.responses.create(**kwargs)
            async for event in response_stream:
                if event.type == "response.output_text.delta":
                    yield TextDelta(text=event.delta)
                elif event.type in _RESPONSE_REASONING_DELTA_EVENTS:
                    text = _get_text(event, "delta", "text")
                    if text:
                        reasoning_accum += text
                        yield ThinkingDelta(text=text)
                elif event.type in _RESPONSE_REASONING_DONE_EVENTS:
                    text = _get_text(event, "text")
                    if text and not reasoning_accum.endswith(text):
                        reasoning_accum += text
                        yield ThinkingDelta(text=text)
                    if reasoning_accum:
                        yield ThinkingComplete(
                            thinking=reasoning_accum,
                            signature="",
                        )
                        reasoning_completed = True
                elif event.type == "response.function_call_arguments.delta":
                    for tool_event in response_tool_call.add_arguments_delta(event):
                        yield tool_event
                elif event.type == "response.function_call_arguments.done":
                    yield response_tool_call.complete(event)
                elif event.type == "response.output_item.added":
                    tool_start = response_tool_call.add_output_item(
                        getattr(event, "item", None)
                    )
                    if tool_start is not None:
                        yield tool_start
                elif event.type == "response.completed":
                    resp = getattr(event, "response", None)
                    if self.thinking and not reasoning_completed:
                        summary = _extract_response_reasoning_summary(resp)
                        if summary:
                            yield ThinkingDelta(text=summary)
                            yield ThinkingComplete(thinking=summary, signature="")
                            reasoning_completed = True
                    usage = getattr(resp, "usage", None) if resp else None
                    yield _stream_end_from_openai_response_usage(usage)

        except _openai.AuthenticationError as e:
            raise AuthenticationError(f"Invalid API key: {e}") from e
        except _openai.RateLimitError as e:
            raise _rate_limit_error(e) from e
        except _openai.APIConnectionError as e:
            raise NetworkError(f"Network error: {e}") from e
        except _openai.APIStatusError as e:
            raise LLMError(f"API error ({e.status_code}): {e.message}") from e


class OpenAICompatClient(LLMClient):
    """面向 OpenAI 兼容 provider 的客户端，使用 Chat Completions API。

    与面向较新的 Responses API（``/responses``）的 ``OpenAIClient`` 不同，
    本客户端使用受广泛支持的 Chat Completions 端点（``/chat/completions``），
    因此能兼容任何暴露 OpenAI 兼容接口的 provider（例如 vLLM、Ollama、
    Together、Azure OpenAI 等）。
    """

    def __init__(self, config: ProviderConfig) -> None:
        self.model = config.model
        self.thinking = config.thinking
        self.max_output_tokens = config.get_max_output_tokens()
        api_key = _resolve_openai_api_key(config)
        if not api_key:
            raise AuthenticationError(
                "OpenAI-compatible API key not found. "
                "Set it in .mozilcode/config.yaml or via OPENAI_API_KEY env var."
            )
        self._client = AsyncOpenAI(api_key=api_key, base_url=config.base_url)

    def set_max_output_tokens(self, tokens: int) -> None:
        self.max_output_tokens = tokens

    async def stream(
        self,
        conversation: ConversationManager,
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        import openai as _openai

        messages = build_chat_completion_messages(conversation.get_messages())
        kwargs = build_chat_completion_request_kwargs(
            model=self.model,
            max_output_tokens=self.max_output_tokens,
            messages=messages,
            system=system,
            tools=tools,
        )

        chat_tool_call = OpenAIChatToolCallState()
        reasoning_accum = ""
        reasoning_completed = False

        try:
            response = await self._client.chat.completions.create(**kwargs)
            async for chunk in response:
                if not chunk.choices:
                    # 最后一个 chunk，只包含 usage 数据。
                    if chunk.usage:
                        yield _stream_end_from_openai_chat_usage(chunk.usage)
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                if self.thinking and delta:
                    reasoning = _extract_chat_reasoning_delta(delta)
                    if reasoning:
                        reasoning_accum += reasoning
                        yield ThinkingDelta(text=reasoning)

                # --- 文本内容 ---
                if delta and delta.content:
                    yield TextDelta(text=delta.content)

                # --- tool call 增量 ---
                if delta and delta.tool_calls:
                    for tool_event in chat_tool_call.add_tool_call_deltas(
                        delta.tool_calls
                    ):
                        yield tool_event

                # --- 结束原因 ---
                if choice.finish_reason in ("tool_calls", "stop"):
                    if reasoning_accum and not reasoning_completed:
                        yield ThinkingComplete(thinking=reasoning_accum, signature="")
                        reasoning_completed = True
                    if choice.finish_reason == "tool_calls":
                        for tool_complete in chat_tool_call.complete():
                            yield tool_complete

        except _openai.AuthenticationError as e:
            raise AuthenticationError(f"Invalid API key: {e}") from e
        except _openai.RateLimitError as e:
            raise _rate_limit_error(e) from e
        except _openai.APIConnectionError as e:
            raise NetworkError(f"Network error: {e}") from e
        except _openai.APIStatusError as e:
            raise LLMError(f"API error ({e.status_code}): {e.message}") from e


def create_client(config: ProviderConfig) -> LLMClient:
    if config.protocol == "anthropic":
        return AnthropicClient(config)
    elif config.protocol == "openai":
        return OpenAIClient(config)
    elif config.protocol == "openai-compat":
        return OpenAICompatClient(config)
    raise ValueError(f"Unknown protocol: {config.protocol}")


async def resolve_context_window(config: ProviderConfig) -> None:
    """context window 解析的第 2 层：对于 anthropic 协议的 provider，
    从 {base_url}/v1/models/{model} 自动拉取一次模型的 max_input_tokens，
    并通过 set_fetched_context_window 缓存到 ``config`` 上，这样后续
    config.get_context_window() 调用就能直接使用、无需再次访问网络。

    完全尽力而为，绝不抛出异常：非 anthropic provider、客户端构造失败
    （例如缺少 API key）、拉取失败或超时，都会让缓存保持不变，从而让
    get_context_window() 降级到内置映射表 / 默认值。在启动时调用是安全的——
    阻塞时间不会超过拉取自身的超时，也不会导致崩溃。
    """
    # 配置中显式指定的 window 在 get_context_window() 中优先级最高，
    # 上次调用已缓存的值也不需要重新拉取——直接跳过网络请求。
    if config.context_window > 0 or config._fetched_context_window > 0:
        return
    if config.protocol != "anthropic":
        return

    try:
        client = create_client(config)
    except Exception:
        return
    fetch = getattr(client, "fetch_model_context_window", None)
    if fetch is None:
        return

    try:
        window = await fetch()
    except Exception:
        window = None
    if window:
        config.set_fetched_context_window(window)
