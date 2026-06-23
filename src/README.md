# src

`src` 是 MozilCode 的 TypeScript 源码根目录。

## 模块划分

- `core`: Agent 核心逻辑。
- `tools`: Agent 可调用的工具。
- `mcp`: MCP 协议适配层，把 MCP Server 暴露的工具转换成 `AgentTool`。
- `providers`: LLM Provider 适配。
- `adapters`: TUI/GUI 等外部交互适配器。
- `runtime`: 本地 Agent Host、任务线程和云端连接。
- `context`: 项目上下文感知。
- `memory`: 长期记忆。
- `auth`: 鉴权和配额。
- `store`: UI 状态。
- `types`: 全局类型补充。

## 依赖方向

推荐依赖方向：

```text
adapters -> core -> ports
runtime -> core -> ports
providers -> core/ports
tools -> core/ports
mcp -> core/ports
index.ts -> 组装所有模块
```

禁止依赖方向：

```text
core -> adapters
core -> providers
core -> tools 具体实现
core -> mcp
core -> store
tools -> adapters
mobile/gui -> tools
```

## 远程控制分层

手机控制任务时，`src` 内部只负责本地执行端：

- `runtime` 维护本地任务会话、工作区和云端连接。
- `core` 控制 Agent Loop 和工具调度。
- `tools` 执行本地副作用。
- `mcp` 连接外部 MCP Server，并把外部工具适配成统一工具。
- `adapters` 提供 TUI/GUI/WebSocket 等入口。

Java 云端控制面放在仓库的 `server` 层或独立服务中。
