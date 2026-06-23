# mcp

`mcp` 负责接入 Model Context Protocol。它不是 Agent Core 的一部分，而是外部工具协议适配层。

## 定位

MCP Server 是外部工具来源。MozilCode 不应该让 `core` 直接理解 MCP 协议，而应该把 MCP 工具转换成统一的 `AgentTool` 后注册到 `ToolRegistry`。

推荐链路：

```text
MCP Server
-> MCP Client
-> MCP Tool Adapter
-> AgentTool
-> ToolRegistry
-> LLMProvider function schema
-> AgentLoop 执行工具调用
```

模型最终看到的是普通工具，例如：

```text
search_docs
create_ticket
query_database
```

而不是 MCP 协议本身。

## 职责

- 管理 MCP Server 配置。
- 连接 MCP Server。
- 拉取 MCP 工具定义。
- 调用 MCP 工具。
- 将 MCP 工具 schema 转换成 MozilCode 的 `AgentTool`。
- 为 MCP 工具补充风险等级、命名空间和安全策略。

## 未来文件规划

- `mcp-client.ts`: 负责和 MCP Server 通信。
- `mcp-server-registry.ts`: 管理启用的 MCP Server。
- `mcp-tool-adapter.ts`: 将 MCP tool 转成 `AgentTool`。
- `mcp-policy.ts`: MCP 工具白名单、黑名单和风险判断。

## 注册方式

启动时由应用组装层加载 MCP 工具：

```text
内置工具
+ 记忆工具
+ MCP 工具
-> ToolRegistry
```

示例：

```ts
const builtinTools = [readFileTool, codeGrepTool, runShellTool];
const memoryTools = createMemoryTools(memory);
const mcpTools = await mcpRegistry.loadTools();

const toolRegistry = new ToolRegistry([
  ...builtinTools,
  ...memoryTools,
  ...mcpTools,
]);
```

## 安全边界

- 不要把所有 MCP 工具无条件暴露给模型。
- 每个 MCP Server 需要启用/禁用开关。
- 每个 MCP Tool 需要白名单或黑名单。
- 写入、发布、部署、删除等高风险 MCP 工具必须触发确认。
- 工具描述可以重写，避免模型误用。
- MCP 工具输出需要截断和摘要，避免污染上下文。

## 不负责什么

`mcp` 不负责：

- Agent Loop。
- Prompt 组装。
- UI 渲染。
- 用户登录和配额。
- 本地文件和 Shell 的内置工具实现。

这些职责分别属于 `core`、`context`、`adapters`、`auth/server` 和 `tools`。
