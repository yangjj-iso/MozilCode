# core

`core` 是 Agent 的核心引擎层，负责“怎么思考和调度”，不负责“怎么显示、怎么调用具体 SDK、怎么操作文件系统”。

## 职责

- Agent Loop。
- 上下文组装。
- 当前会话消息管理。
- 工具调用调度。
- 事件发布。
- 推理步数限制和错误恢复。

## 边界

`core` 可以依赖：

- `core/ports` 中定义的接口。
- 纯逻辑工具函数。

`core` 不应该依赖：

- TUI/React/Ink。
- OpenAI、Vercel AI SDK、Anthropic SDK。
- Node 文件系统、Shell 具体实现。
- 全局 UI store。
- 登录、套餐、配额业务。

## MVP 文件规划

- `agent-loop.ts`: 控制 LLM 调用、工具调用和最终回答。
- `context-manager.ts`: 组装系统提示词和近期消息。
- `message-manager.ts`: 管理当前会话消息。
- `event-bus.ts`: 向外发布状态事件。
- `tool-registry.ts`: 注册和查找工具。

## 关键原则

核心层只描述流程，不执行具体副作用。所有副作用通过 port 注入。
