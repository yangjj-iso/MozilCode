# 03 - LLM 客户端与 Provider 适配层

## 1. 概述

本模块负责与不同的 LLM API 通信。核心挑战是：Anthropic 和 OpenAI 的 API 格式完全不同，但 Agent 核心循环需要统一的接口。解决方案是**适配器模式**——定义一个抽象基类 `LLMClient`，然后为每种协议实现具体客户端。

对应代码：`mozilcode/client/` 和 `mozilcode/providers/`

## 2. 基础概念

### 2.1 适配器模式（Adapter Pattern）

适配器模式是一种结构型设计模式，它让不兼容的接口能够协同工作。

```
Agent 核心循环  ──→  LLMClient（抽象接口）
                        ↑           ↑           ↑
                  AnthropicClient  OpenAIClient  OpenAICompatClient
                        │           │           │
                  Anthropic API   OpenAI API   第三方兼容 API
```

### 2.2 流式响应（Streaming Response）

LLM API 通常支持流式响应——不是等整个回复生成完再返回，而是逐字返回。这带来更好的用户体验（打字机效果）。

```
非流式:  [等待 10 秒] → "这是完整的回复"
流式:    "这" → "是" → "完" → "整" → "的" → "回" → "复"（每个间隔 ~0.1 秒）
```

在 Python 中，流式响应用**异步迭代器**实现：

```python
async def stream(self, conversation, system, tools) -> AsyncIterator[StreamEvent]:
    async for chunk in api_client.stream(...):
        if chunk.text:
            yield TextDelta(text=chunk.text)  # 逐块产出
    yield StreamEnd(input_tokens=..., output_tokens=...)
```

### 2.3 Pydantic 模型校验

项目使用 Pydantic 库做数据校验。Pydantic 模型可以自动校验数据类型、生成 JSON Schema，这在工具参数校验中非常有用。

```python
from pydantic import BaseModel

class ReadFileParams(BaseModel):
    path: str           # 必须是字符串
    offset: int = 0     # 可选，默认 0
    limit: int = 0      # 可选，默认 0

# 自动校验
params = ReadFileParams.model_validate({"path": "main.py", "offset": 10})
# params.path == "main.py", params.offset == 10

# 自动生成 JSON Schema（发给 LLM 告诉它工具的参数格式）
schema = ReadFileParams.model_json_schema()
```

## 3. LLMClient 抽象基类

```python
class LLMClient(ABC):
    """所有 LLM 客户端的抽象基类。"""

    @abstractmethod
    async def stream(
        self,
        conversation: ConversationManager,
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """流式调用 LLM。

        参数:
            conversation: 对话历史
            system: 系统提示词
            tools: 可用工具的 JSON Schema 列表

        返回:
            StreamEvent 异步迭代器（TextDelta / ToolCallComplete / StreamEnd 等）
        """
        yield TextDelta("")
```

## 4. 流式事件类型

`tools/base.py` 中定义了 LLM 流式输出的所有事件类型：

```python
@dataclass
class TextDelta:
    """LLM 输出的文本片段。"""
    text: str

@dataclass
class ThinkingDelta:
    """LLM 思考过程片段（仅支持 thinking 的模型）。"""
    text: str

@dataclass
class ThinkingComplete:
    """一段思考完成。"""
    thinking: str
    signature: str  # 用于上下文缓存

@dataclass
class ToolCallStart:
    """工具调用开始（LLM 开始输出工具调用参数）。"""
    tool_name: str
    tool_id: str

@dataclass
class ToolCallDelta:
    """工具调用参数的增量片段。"""
    text: str

@dataclass
class ToolCallComplete:
    """工具调用完成，包含完整参数。"""
    tool_id: str
    tool_name: str
    arguments: dict[str, Any]

@dataclass
class StreamEnd:
    """流结束，包含 token 用量。"""
    stop_reason: str
    input_tokens: int
    output_tokens: int
    cache_read: int       # 缓存命中的 token 数
    cache_creation: int   # 新建缓存的 token 数
```

## 5. StreamCollector

`StreamCollector` 是一个消费者，它吃掉所有流式事件，同时实时转发给上层，最终组装出一个完整的 `LLMResponse`：

```python
class StreamCollector:
    def __init__(self) -> None:
        self.response = LLMResponse()

    async def consume(self, stream: AsyncIterator[StreamEvent]) -> AsyncIterator[AgentEvent]:
        async for event in stream:
            if isinstance(event, TextDelta):
                self.response.text += event.text       # 累积文本
                yield StreamText(text=event.text)      # 实时转发

            elif isinstance(event, ThinkingComplete):
                self.response.thinking_blocks.append(  # 保存思考块
                    ThinkingBlock(thinking=event.thinking, signature=event.signature)
                )

            elif isinstance(event, ToolCallComplete):
                self.response.tool_calls.append(event) # 收集工具调用
                yield ToolUseEvent(...)                # 实时转发

            elif isinstance(event, StreamEnd):
                self.response.stop_reason = event.stop_reason
                self.response.input_tokens = event.input_tokens
                self.response.output_tokens = event.output_tokens
```

```
LLM API → TextDelta("Hello") → StreamCollector → StreamText("Hello") → Agent → yield
          TextDelta(" world")                    StreamText(" world")
          ToolCallComplete(...)                   ToolUseEvent(...)
          StreamEnd(usage)                        UsageEvent(...)
```

## 6. AnthropicClient 实现

```python
class AnthropicClient(LLMClient):
    def __init__(self, config: ProviderConfig) -> None:
        self.model = config.model
        self.thinking = config.thinking
        self.max_output_tokens = config.get_max_output_tokens()
        api_key = config.resolve_api_key()
        self._client = AsyncAnthropic(api_key=api_key, base_url=config.base_url)

    async def stream(self, conversation, system, tools):
        # 1. 将内部对话格式转换为 Anthropic API 格式
        messages = build_anthropic_messages(conversation)

        # 2. 构建请求参数
        kwargs = build_anthropic_request_kwargs(
            model=self.model,
            messages=messages,
            system=system,
            tools=tools,
            thinking=self.thinking,
            max_output_tokens=self.max_output_tokens,
        )

        # 3. 调用 Anthropic API，流式接收响应
        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                # 将 Anthropic SDK 事件转换为我们自己的 StreamEvent
                yield from anthropic_stream_adapter(event)

        yield StreamEnd(input_tokens=..., output_tokens=...)
```

## 7. OpenAIClient 实现

OpenAI 有两种 API 格式：Chat Completions 和 Responses API。

```python
class OpenAIClient(LLMClient):
    def __init__(self, config: ProviderConfig) -> None:
        self.model = config.model
        self._client = AsyncOpenAI(
            api_key=resolve_openai_api_key(config),
            base_url=config.base_url,
        )

    async def stream(self, conversation, system, tools):
        # 转换为 OpenAI Chat Completions 格式
        messages = build_chat_completion_messages(conversation, system)

        kwargs = build_chat_completion_request_kwargs(
            model=self.model,
            messages=messages,
            tools=tools,
        )

        stream = await self._client.chat.completions.create(**kwargs, stream=True)
        async for chunk in stream:
            # 将 OpenAI SDK 事件转换为我们自己的 StreamEvent
            yield from openai_stream_adapter(chunk)

        yield StreamEnd(...)
```

## 8. Provider 适配层

`providers/` 目录包含各协议的具体适配逻辑：

| 文件 | 作用 |
|------|------|
| `anthropic_request.py` | 构建 Anthropic API 请求参数 |
| `anthropic_streaming.py` | 解析 Anthropic 流式响应 |
| `openai_compat_request.py` | 构建 OpenAI 兼容 API 请求 |
| `openai_responses_request.py` | 构建 OpenAI Responses API 请求 |
| `openai_streaming.py` | 解析 OpenAI 流式响应 |

### 协议适配的核心挑战

不同 API 的差异主要体现在：

1. **消息格式**：Anthropic 用 `content blocks`，OpenAI 用 `content string`
2. **工具定义**：Anthropic 用 `input_schema`，OpenAI 用 `parameters` + `type: "function"`
3. **流式事件**：两家的 SSE 事件格式完全不同
4. **Thinking 支持**：Anthropic 原生支持 extended thinking，OpenAI 有 reasoning

```python
# 工具 Schema 适配示例
def schema_for_protocol(tool: Tool, protocol: str) -> dict[str, Any]:
    base = tool.get_schema()
    if protocol in ("openai", "openai-compat"):
        # OpenAI 格式
        return {
            "type": "function",
            "name": base["name"],
            "description": base["description"],
            "parameters": base["input_schema"],
        }
    # Anthropic 格式
    return base  # {name, description, input_schema}
```

## 9. Context Window 解析

模型的上下文窗口大小决定了能处理多少对话。项目用**四层 fallback** 解析：

```python
def get_context_window(self) -> int:
    # Layer 1: 配置文件显式指定（最高优先级）
    if self.context_window > 0:
        return self.context_window

    # Layer 2: 从 provider 的 /v1/models 端点自动拉取
    if self._fetched_context_window > 0:
        return self._fetched_context_window

    # Layer 3: 内置的模型名 → window 映射表（子串匹配）
    window = lookup_model_context_window(self.model)
    if window > 0:
        return window

    # Layer 4: 保守默认值
    if "claude" in self.model.lower():
        return 200_000  # Claude 默认 200K
    return 128_000      # 其他默认 128K
```

## 10. 错误处理

### 错误类型层级

```python
class LLMError(Exception):          # 所有 LLM 错误的基类
    pass

class AuthenticationError(LLMError):  # API Key 无效
    pass

class RateLimitError(LLMError):       # 触发速率限制
    pass

class NetworkError(LLMError):         # 网络故障
    pass
```

### ProviderErrorMapper

`error_mapping.py` 将不同 Provider 的原始错误统一映射为标准错误类型：

```python
class ProviderErrorMapper:
    def map_error(self, error: Exception) -> LLMError:
        if "rate_limit" in str(error).lower():
            return RateLimitError("Rate limit exceeded")
        if "authentication" in str(error).lower():
            return AuthenticationError("Invalid API key")
        if isinstance(error, httpx.ConnectError):
            return NetworkError("Cannot connect to API")
        return LLMError(str(error))

# 全局实例
provider_error_mapper = ProviderErrorMapper()
```

## 11. 序列化层

`serialization.py` 负责将内部的 `ConversationManager` 转换为各 API 格式的消息列表：

```python
# Anthropic 格式
def build_anthropic_messages(conversation) -> list[dict]:
    return [
        {
            "role": msg.role,
            "content": [
                {"type": "text", "text": msg.content},
                *[{"type": "tool_use", ...} for tu in msg.tool_uses],
                *[{"type": "tool_result", ...} for tr in msg.tool_results],
            ]
        }
        for msg in conversation.history
    ]

# OpenAI Chat Completions 格式
def build_chat_completion_messages(conversation, system) -> list[dict]:
    messages = [{"role": "system", "content": system}]
    for msg in conversation.history:
        messages.append({"role": msg.role, "content": msg.content})
        for tu in msg.tool_uses:
            messages.append({"role": "assistant", "tool_calls": [...]})
        for tr in msg.tool_results:
            messages.append({"role": "tool", "content": tr.content})
    return messages
```
