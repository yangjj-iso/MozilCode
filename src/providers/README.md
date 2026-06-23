# providers

`providers` 是 LLM 接口适配层，负责屏蔽不同模型 SDK 的差异。

## 职责

- 调用 Vercel AI SDK、OpenAI SDK 或其他模型 SDK。
- 把 MozilCode 内部消息格式转换成模型请求。
- 把模型响应转换成统一的 `LLMResponse`。
- 处理工具调用返回格式。
- 处理 API 错误、超时和重试策略。

## MVP 选型

第一期建议优先实现：

```text
vercel-ai.provider.ts
```

原因是 Vercel AI SDK 对 TypeScript、多 Provider、Tool Calling 和 Streaming 支持较好。

同时保留：

```text
openai.provider.ts
```

作为后续直连 OpenAI Responses API 或 Agents SDK 的扩展点。

## 边界

- Provider 不负责确认工具调用。
- Provider 不直接执行工具。
- Provider 不直接渲染 UI。
- Provider 只负责模型请求和响应转换。
