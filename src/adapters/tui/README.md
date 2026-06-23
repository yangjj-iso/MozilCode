# adapters/tui

`tui` 是终端 UI 适配器。第一期 MVP 的主要用户界面就在这里。

## 职责

- 实现 Claude Code 风格输入框。
- 支持多行输入。
- 支持快捷键，例如 `Enter` 提交、`Ctrl+J` 换行、`Ctrl+C` 退出。
- 渲染聊天消息流。
- 渲染 Agent 状态。
- 渲染工具调用结果。
- 实现确认提示。

## MVP 文件规划

- `input.ts`: 读取用户 prompt。
- `renderer.ts`: 渲染消息、状态和工具结果。
- `confirm.ts`: 写文件或执行命令前请求用户确认。

## 约束

- TUI 只负责交互体验，不负责 Agent 推理。
- TUI 不应该直接调用 LLM SDK。
- TUI 不应该直接执行工具。
- 所有工具执行都应经过 core 的 Agent Loop。
- TUI 不保存长期任务状态；长期状态应由 runtime 或 store 承接。
- TUI 和手机端是并列入口，不能互相依赖。

## 和远程控制的关系

TUI 是本地交互入口。未来手机端接入后，TUI 仍然只是一个 Adapter：

```text
TUI 输入 -> Runtime/Core
手机输入 -> Java 云端 -> Runtime/Core
```

两种入口应复用同一套 Agent Core、ToolRegistry 和安全确认规则。
