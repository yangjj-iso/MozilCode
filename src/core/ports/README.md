# core/ports

`ports` 存放核心层依赖的抽象接口。它是 core 和外部实现之间的边界。

## 职责

- 定义 LLM 调用接口。
- 定义工具接口。
- 定义用户确认接口。
- 定义远程运行时、任务线程和审批相关接口。
- 定义事件、消息、工具调用结果等核心数据结构。

## 为什么需要 ports

如果 `core` 直接 import OpenAI SDK、文件系统工具或 TUI 组件，核心层就会被具体实现污染。使用 ports 后：

```text
core 只知道接口
providers/tools/adapters 实现接口
index.ts 负责组装
```

## MVP 接口规划

- `llm.port.ts`: `LLMProvider`、`AgentMessage`、`LLMResponse`。
- `tool.port.ts`: `AgentTool`、`ToolRisk`、`ToolContext`。
- `confirmation.port.ts`: `ConfirmationPort`。
- `thread.port.ts`: `Thread`、`Task`、`AgentEventLog`，用于长期任务和手机端继续任务。
- `relay.port.ts`: 本地 Runtime 和 Java 云端之间的事件同步接口。

## 约束

- port 文件不应该依赖具体 SDK。
- port 文件不应该执行副作用。
- 类型命名要稳定，因为它们是模块间契约。
- 远程控制相关 port 只能描述协议，不应该包含 WebSocket 或 HTTP 框架代码。
