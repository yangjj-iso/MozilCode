# MozilCode 分层架构与能力边界

> **版本**：v1.0
> **更新日期**：2026-06-29
> **适用范围**：MozilCode 本地 Agent 平台（TypeScript 实现）
> **关联文档**：`PRODUCT-DESIGN.md`（产品设计）、`PROPOSAL-IMPLEMENTATION.md`（MVP 实现建议）、`REVIEW-PRD-Architecture.md`（架构审核）

---

## 0. 文档目的

本文档明确 MozilCode 源码各层的**定位、职责、能力边界、依赖方向**，作为代码评审、模块设计、新人入职的统一参考。所有 PR 涉及跨层依赖时，应以本文档为准。

---

## 1. 分层总览

```
┌─────────────────────────────────────────────────────────────────┐
│  入口层    adapters/  (TUI / GUI / Mobile-web / Relay)            │
├─────────────────────────────────────────────────────────────────┤
│  宿主层    runtime/   (本地常驻 Host、工作区、云端连接)            │
├─────────────────────────────────────────────────────────────────┤
│  核心层    core/      (Agent Loop、上下文、消息、事件、工具表)     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  契约层   core/ports/  (LLM / Tool / Confirmation / Event) │  │
│  └───────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  实现层    providers/ + tools/ + mcp/  (实现 ports，产生副作用)   │
├─────────────────────────────────────────────────────────────────┤
│  横切层    security/ + context/ + memory/ + auth/ + store/       │
├─────────────────────────────────────────────────────────────────┤
│  组装层    index.ts    (依赖注入、模块装配)                        │
└─────────────────────────────────────────────────────────────────┘
```

### 依赖方向铁律

```
允许：
  adapters  → core → ports
  runtime   → core → ports
  providers → core/ports
  tools     → core/ports
  mcp       → core/ports
  security  → core/ports（被 tools/providers 引用）
  context   → core/ports（被 core 引用，见 §9 注意事项）
  index.ts  → 所有模块（组装）

禁止：
  core      → adapters / providers / tools / mcp / store
  core      → 具体 SDK（OpenAI/Vercel/Anthropic）
  core      → Node fs / child_process
  tools     → adapters
  adapters  → tools（直接调用）
  任何层    → index.ts（组装层是最外层，不被依赖）
```

---

## 2. Core 层（`src/core/`）

### 定位

Agent 的**核心引擎**，负责"怎么思考和调度"，不负责"怎么显示、怎么调用具体 SDK、怎么操作文件系统"。Core 是纯逻辑层，所有副作用通过 ports 注入。

### 职责（5 项 MVP 必做）

| 文件 | 职责 | 说明 |
|------|------|------|
| `agent-loop.ts` | Agent 主循环 | 构造 LLM 请求 → 流式接收 → 解析 `tool_calls` → 并行执行工具 → 回喂 `tool_result` → 再请求 LLM；支持 `AbortController` 中断；多轮工具调用迭代 |
| `context-manager.ts` | 会话上下文组装 | 组装系统提示词 + 近期消息；上下文窗口管理；token 计数 + 滑动窗口截断（v1 简单策略，后续做摘要） |
| `message-manager.ts` | 会话消息管理 | 当前会话消息 CRUD；区分 role（system/user/assistant/tool）；保存 `toolCalls`/`toolCallId`；会话历史持久化 |
| `event-bus.ts` | 事件发布订阅 | 7 种 EventType（thinking/tool_call/tool_result/response/error/confirm_request/confirm_result）；供 UI 订阅渲染 |
| `tool-registry.ts` | 工具注册与查找 | 注册内置工具 + 记忆工具 + MCP 工具；按 name 查找；合并所有工具 schema 注入 LLM 的 `tools` 参数 |

### 未来扩展（2 项）

| 文件 | 职责 |
|------|------|
| `thread-manager.ts` | 长期任务线程，状态序列化 + 重建，支持手机端继续未完成任务 |
| `approval-manager.ts` | 待审批工具调用队列；远程会话审批状态机；三档权限（auto / first-confirm / each-confirm） |

### 能力边界

**Core 可以**：
- 依赖 `core/ports` 中定义的接口
- 依赖纯逻辑工具函数
- 依赖 `context/` 提供的项目感知能力（通过接口注入）

**Core 不可以**：
- ❌ 依赖 TUI / React / Ink 等 UI 框架
- ❌ 依赖 OpenAI / Vercel AI / Anthropic SDK
- ❌ 依赖 Node `fs` / `child_process` 等具体副作用模块
- ❌ 依赖全局 UI store
- ❌ 依赖登录、套餐、配额业务逻辑
- ❌ 依赖手机端、WebSocket、设备绑定等传输细节
- ❌ 直接执行任何副作用（文件读写、Shell、网络请求）

### 关键原则

> 核心层只描述流程，不执行具体副作用。所有副作用通过 port 注入。
>
> 手机端控制任务时，core 仍然不关心请求来自 TUI、GUI 还是手机。它只接收用户输入、产生事件、等待审批结果，并继续推进 Agent Loop。

---

## 3. Ports 层（`src/core/ports/`）

### 定位

Core 与外部世界之间的**接口契约层**。定义 core 能触碰什么、怎么触碰，但不关心具体实现。Ports 是六边形架构的边界，类型命名一旦确定就应保持稳定，因为它是模块间契约。

### 职责（MVP 4 个 port）

| Port 文件 | 接口 | 对应的"外部" | 说明 |
|-----------|------|-------------|------|
| `llm.port.ts` | `LLMProviderPort` | LLM 服务 | `generate` / `getModel` / `isConfigured` / `getMaxTokens`；定义 `AgentMessage` / `ToolCall` / `LLMResponse` 核心类型 |
| `tool.port.ts` | `AgentToolPort` | 工具副作用 | `definition` / `riskLevel` / `category` / `execute`；定义 `ToolContext` / `ToolResult` / `RiskLevel` |
| `confirmation.port.ts` | `ConfirmationPort` | UI 确认弹窗 | `requestConfirmation` / `requiresConfirmation` / `requestBatchConfirmation`；core 向 UI"请求人类决策"的通道 |
| `event-bus.port.ts` | `EventBusPort` | UI 订阅 | `emit` / `on` / `off`；core 向 UI"推送状态"的通道；定义 `EventType` / `AgentEvent` |

### 未来扩展（2 个 port，远程控制）

| Port 文件 | 接口 | 说明 |
|-----------|------|------|
| `thread.port.ts` | `Thread` / `Task` / `AgentEventLog` | 长期任务序列化，支持跨会话/跨设备继续 |
| `relay.port.ts` | 本地 Runtime ↔ 云端 Relay 同步协议 | 只描述协议，不含 WebSocket/HTTP 框架代码 |

### 能力边界

**Ports 可以**：
- 定义接口、类型、数据结构
- 被 core 依赖（core 只依赖接口，不依赖实现）
- 被实现层（providers/tools/mcp/adapters）实现

**Ports 不可以**：
- ❌ 依赖具体 SDK（OpenAI/Vercel 等）
- ❌ 执行任何副作用
- ❌ 包含 WebSocket / HTTP 框架代码
- ❌ 依赖 core 的其他模块（ports 是最内层，不反向依赖 core）

### 关键原则

> 如果 core 直接 import OpenAI SDK、文件系统工具或 TUI 组件，核心层就会被具体实现污染。使用 ports 后：core 只知道接口，providers/tools/adapters 实现接口，index.ts 负责组装。

---

## 4. Providers 层（`src/providers/`）

### 定位

LLM 接口适配层，负责**屏蔽不同模型 SDK 的差异**，把 MozilCode 内部消息格式转换成模型请求，把模型响应转换成统一的 `LLMResponse`。

### 职责

- 调用 Vercel AI SDK、OpenAI SDK 或其他模型 SDK
- 把内部 `AgentMessage[]` 转换成模型请求格式
- 把模型响应转换成统一的 `LLMResponse`
- 处理工具调用返回格式（`tool_calls` 解析）
- 处理 API 错误、超时和重试策略
- 流式 SSE 接收，逐 token 往外推
- 后续接入云端模型网关时，把请求转发到 Go 云端或直连模型厂商

### MVP 文件

| 文件 | 说明 |
|------|------|
| `base.provider.ts` | Provider 基类，封装通用逻辑（重试、错误处理） |
| `vercel-ai.provider.ts` | Vercel AI SDK 实现（MVP 首选，多 Provider 支持、Tool Calling、Streaming 完善） |
| `openai.provider.ts` | OpenAI 直连实现（后续扩展点） |

### 能力边界

**Providers 可以**：
- 依赖 `core/ports/llm.port`（实现 `LLMProviderPort`）
- 依赖具体 SDK（OpenAI / Vercel AI / Anthropic）
- 依赖 `security/` 做请求级安全检查（如脱敏）

**Providers 不可以**：
- ❌ 确认工具调用（那是 `confirmation.port` 的职责）
- ❌ 直接执行工具（那是 `tools/` 的职责）
- ❌ 直接渲染 UI
- ❌ 判断用户配额（配额由 Go 云端控制面或本地 guard 在进入 Agent Loop 前处理）

### 云端模型网关模式

商业化阶段可以让 Provider 调用 Go 云端模型网关，而不是直接访问模型厂商：

```
AgentLoop → Provider → Go Model Gateway → OpenAI / Claude / DeepSeek / Qwen
```

这样可以统一做模型路由、成本统计、限流、重试和团队策略。

---

## 5. Tools 层（`src/tools/`）

### 定位

Agent 的**工具执行层**，负责真正操作本地环境。工具实现 `core/ports/tool.port` 中的 `AgentToolPort` 接口，由 `ToolRegistry` 统一调度。

### 职责

- 读取文件（`file-read`）
- 写入文件（`file-write`，需确认）
- 搜索代码（`code-grep`）
- 执行本地 Shell 命令（`run-shell`，需确认）
- 后续扩展远程 SSH、语义搜索、Git 操作等能力
- 接收 MCP 适配后的外部工具，统一纳入工具注册和风险控制

### MVP 文件

| 文件 | 工具名 | riskLevel | 说明 |
|------|--------|-----------|------|
| `base.tool.ts` | — | — | Tool 基类，封装通用逻辑 |
| `file-read.tool.ts` | `read_file` | `none` | 读取工作区内文件，自动放行 |
| `file-write.tool.ts` | `write_file` | `medium` | 写入工作区内文件，首次确认 |
| `shell.tool.ts` | `run_shell` | `high` | 执行本地命令，每次确认 |
| `search.tool.ts` | `code_grep` | `none` | 搜索代码关键词，自动放行 |

### 能力边界

**Tools 可以**：
- 依赖 `core/ports/tool.port`（实现 `AgentToolPort`）
- 依赖 `security/` 做路径验证、命令扫描、输出截断
- 依赖 Node `fs` / `child_process` 等具体副作用模块
- 声明 `riskLevel` 和 `category`

**Tools 不可以**：
- ❌ 访问工作区外路径（由 `security/path-validator` 拦截）
- ❌ 绕过确认机制（写操作、Shell 必须过 `confirmation.port`）
- ❌ 直接被 `adapters` 调用（必须经 `ToolRegistry` → `AgentLoop`）
- ❌ 渲染 UI

### 安全边界

- 工具不能访问工作区外路径
- 写操作必须经过确认
- Shell 命令必须经过确认
- 危险命令需要拦截或二次确认（`rm -rf /`、`mkfs`、`dd` 自动拒绝）
- 工具输出需要截断，避免超长结果污染上下文
- 远程控制场景下，手机端只能审批工具调用，不能直接调用工具
- 本地 Runtime 必须是工具执行的唯一入口

### 与 core 的关系

```
工具实现 AgentToolPort 接口
→ ToolRegistry 注册
→ AgentLoop 通过 ToolRegistry 查找并调度
→ 工具执行
→ ToolResult 回喂给 AgentLoop
```

core 不直接依赖具体工具文件，而是通过 `ToolRegistry` 调度。手机端、Web 端或 TUI 发起的任务最终都必须汇入同一个 `ToolRegistry`，避免不同入口出现不同安全规则。

---

## 6. MCP 层（`src/mcp/`）

### 定位

Model Context Protocol 适配层。**不是 Agent Core 的一部分**，而是外部工具协议适配层。把 MCP Server 暴露的工具转换成统一的 `AgentTool` 后注册到 `ToolRegistry`。

### 职责

- 管理 MCP Server 配置（启用/禁用列表）
- 连接 MCP Server（stdio transport 本地工具 + SSE/HTTP transport 云端工具）
- 拉取 MCP 工具定义（`tools/list`）
- 调用 MCP 工具（`tools/call`）
- 将 MCP 工具 schema 转换成 MozilCode 的 `AgentTool`
- 为 MCP 工具补充风险等级、命名空间和安全策略
- MCP 工具输出截断和摘要，避免污染上下文

### 文件规划

| 文件 | 职责 |
|------|------|
| `mcp-client.ts` | 和 MCP Server 通信（stdio + SSE 两种 transport） |
| `mcp-server-registry.ts` | 管理启用的 MCP Server 列表 |
| `mcp-tool-adapter.ts` | 将 MCP tool 转成 `AgentTool` |
| `mcp-policy.ts` | MCP 工具白名单、黑名单和风险判断 |

### 适配链路

```
MCP Server
  → MCP Client
  → MCP Tool Adapter
  → AgentTool
  → ToolRegistry
  → LLMProvider function schema
  → AgentLoop 执行工具调用
```

模型最终看到的是普通工具（如 `search_docs`、`create_ticket`、`query_database`），而不是 MCP 协议本身。

### 能力边界

**MCP 可以**：
- 依赖 `core/ports/tool.port`（产出 `AgentTool`）
- 依赖 `@modelcontextprotocol/sdk`
- 依赖 `security/` 做工具策略判断

**MCP 不可以**：
- ❌ 负责 Agent Loop
- ❌ 负责 Prompt 组装
- ❌ 负责 UI 渲染
- ❌ 负责用户登录和配额
- ❌ 负责本地文件和 Shell 的内置工具实现（那是 `tools/` 的职责）
- ❌ 把所有 MCP 工具无条件暴露给模型

### 安全边界

- 每个 MCP Server 需要启用/禁用开关
- 每个 MCP Tool 需要白名单或黑名单
- 写入、发布、部署、删除等高风险 MCP 工具必须触发确认
- 工具描述可以重写，避免模型误用
- MCP 工具输出需要截断和摘要

### 注册方式

启动时由应用组装层（`index.ts`）加载 MCP 工具：

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

---

## 7. Adapters 层（`src/adapters/`）

### 定位

外部交互适配层。把核心事件展示给用户，把用户输入传给 Agent Core。Adapter 是**用户与 Agent 之间的桥梁**，但不参与 Agent 推理。

### 子模块

| 子模块 | 状态 | 说明 |
|--------|------|------|
| `tui/` | MVP | 终端 UI，第一期主要界面（Ink / React for CLI） |
| `gui/` | 未来 | 图形界面（Tauri + React），通过 sidecar 拉起 Agent Core |
| `mobile-web/` | 未来 | 手机 H5/PWA 控制端，远程控制面 |
| `relay/` | 未来 | 本地 Runtime 和云端通信的适配器 |

### 职责

- 读取用户输入
- 渲染 Agent 输出（流式）
- 展示工具调用状态
- 展示确认提示，将用户确认结果返回给 core
- 远程控制场景下，展示任务线程、审批队列和事件流

### TUI MVP 文件

| 文件 | 职责 |
|------|------|
| `input.ts` | 读取用户 prompt（多行输入、快捷键） |
| `renderer.ts` | 渲染消息、状态和工具结果 |
| `confirm.ts` | 写文件或执行命令前请求用户确认 |

### 能力边界

**Adapters 可以**：
- 依赖 `core` 的接口和事件类型
- 订阅 `EventBus` 获取 Agent 状态
- 调用 `AgentLoop` 的公共方法（如 `sendMessage`）
- 实现 `ConfirmationPort`（把确认请求转给 UI 弹窗）

**Adapters 不可以**：
- ❌ 被 `core` 依赖（依赖方向只能是 adapter → core）
- ❌ 直接调用 LLM SDK
- ❌ 直接执行工具
- ❌ 直接读写文件
- ❌ 保存长期任务状态（长期状态由 `runtime` 或 `store` 承接）
- ❌ TUI 和手机端互相依赖（两者是并列入口）

### 依赖方向

```
正确：TUI → AgentLoop，AgentLoop → EventBus，TUI 订阅 EventBus
错误：core → TUI component
```

### 手机控制任务的边界

手机端 Adapter 只能做**控制面展示和输入**：
- ✅ 查看任务状态
- ✅ 继续输入 prompt
- ✅ 审批或拒绝写文件、执行命令
- ✅ 停止任务
- ❌ 直接读写本地文件
- ❌ 直接执行 Shell

---

## 8. Runtime 层（`src/runtime/`）

### 定位

本地 Agent 运行时层，MozilCode 的**本地执行宿主**。当需要支持手机端查看和操控任务时，Runtime 是手机端和本地项目之间的**安全隔离层**。

### 为什么需要 Runtime

TUI 只能覆盖本机终端交互。如果未来要支持手机端查看和操控任务，就需要一个长期存在的本地 Runtime：

```
手机端 → Go 云端控制面 → 本地 Runtime → AgentLoop → Tools
```

手机端不能直接执行工具，必须通过 Runtime 进入 Agent Core。

### 职责

- 管理本地工作区（`workspace-registry`）
- 创建和恢复任务线程（`thread-session`）
- 启动 Agent Loop
- 维护本地事件日志
- 接收云端下发的继续任务、停止任务、审批结果
- 将 Agent 状态、工具调用、审批请求同步给云端
- 执行本地安全策略（路径限制、工具权限）

### 文件规划

| 文件 | 职责 |
|------|------|
| `local-agent-host.ts` | 本地常驻宿主 |
| `workspace-registry.ts` | 管理可被 Agent 使用的工作区 |
| `thread-session.ts` | 管理单个任务线程的生命周期 |
| `cloud-relay-client.ts` | 和 Go 云端建立安全连接（反向 WebSocket） |

### 能力边界

**Runtime 可以**：
- 依赖 `core` 和 `core/ports`
- 管理 Agent Loop 生命周期
- 连接 Go 云端 Relay
- 执行本地安全策略

**Runtime 不可以**：
- ❌ 负责用户登录页面（那是 `auth` + adapter 的职责）
- ❌ 负责套餐计费（那是 Go 云端的职责）
- ❌ 负责模型供应商选择策略（那是 `providers` 的职责）
- ❌ 直接渲染手机 UI（那是移动端的职责）

### MVP 状态

MVP 阶段不实现 Runtime，TUI 直接调用 Agent Core。Runtime 在阶段二（云端 Relay）引入。

---

## 9. Context 层（`src/context/`）

### 定位

**项目感知模块**，帮助 Agent 理解当前代码库。注意：这里的 "context" 指**项目上下文**（代码结构、AST、RAG），与 `core/context-manager` 的**会话上下文**（提示词、历史消息）是不同概念。

### 职责

- 代码搜索（MVP：基于 grep 的关键词搜索）
- AST 分析（未来：定位函数、类、导入导出）
- 文档分块（未来）
- RAG 索引（未来）
- 提取项目结构摘要（未来）

### MVP 范围

第一期先不做完整 RAG 和 AST 重构，只保留最小能力：
- 基于 grep 的关键词搜索（`grep-engine.ts`，封装 ripgrep）
- 直接读取相关文件
- 由 `core/context-manager` 组装近期上下文

### 文件规划

| 文件 | 状态 | 职责 |
|------|------|------|
| `grep-engine.ts` | MVP | 封装 ripgrep，关键词搜索 |
| `ast-parser.ts` | 未来 | 定位函数、类、导入导出 |
| `rag-indexer.ts` | 未来 | 文档分块和索引 |

### 能力边界

**Context 可以**：
- 读取项目文件（只读）
- 为 `core/context-manager` 提供项目感知数据

**Context 不可以**：
- ❌ 直接修改文件（只负责发现和整理信息）
- ❌ 被手机端直接请求完整项目上下文

### 远程控制场景

- 本地 Runtime 在本机生成项目摘要
- 云端只保存任务事件、摘要和必要元数据
- 敏感文件内容默认不上传云端
- 如果企业开启云端模型网关，需要通过策略判断哪些上下文可以离开本机

### ⚠️ 命名注意事项

`src/context/`（项目上下文）与 `core/context-manager.ts`（会话上下文）存在命名重叠。架构审核报告（v2.0）建议未来将 `src/context/` 重命名为 `src/project-context/` 以消除混淆。MVP 阶段可暂时接受。

---

## 10. Security 层（`src/security/`）

### 定位

**安全策略横切层**，为 tools、providers、mcp 提供统一的安全校验。不是独立运行的服务，而是被其他层引用的工具集。

### 职责

- **路径验证**（`path-validator.ts`）：工作区白名单，阻止访问工作区外路径；解析符号链接防绕过；拦截敏感文件（`.env`、`.git/config`）
- **命令扫描**（`command-scanner.ts`）：危险命令自动拒绝（`rm -rf /`、`mkfs`、`dd`）；高风险命令标记（`chmod -R 777`、`git reset --hard`）；危险操作符检测（`&&`、`||`、`|`、`;`、`>`）
- **输出截断**（`output-truncator.ts`）：工具输出超长截断，避免污染上下文

### 文件

| 文件 | 职责 |
|------|------|
| `path-validator.ts` | 路径验证，工作区白名单 + 符号链接解析 |
| `command-scanner.ts` | 命令扫描，危险命令拦截 + 风险分级 |
| `output-truncator.ts` | 输出截断 |

### 能力边界

**Security 可以**：
- 被 `tools/`、`providers/`、`mcp/` 引用
- 依赖 Node `fs`（只读，用于路径解析）
- 定义风险等级常量

**Security 不可以**：
- ❌ 直接执行工具
- ❌ 直接拒绝用户请求（只能返回风险等级，由 `confirmation.port` 决定是否放行）
- ❌ 渲染 UI

---

## 11. Memory 层（`src/memory/`）

### 定位

**长期记忆模块**，MVP 阶段暂不实现。管理跨会话、长期存在的信息。

### 未来职责

- 记录用户偏好
- 记录项目长期决策
- 记录跨会话知识
- 提供语义搜索
- 支持向量数据库

### 与 message-manager 的区别

| 模块 | 时间维度 | 内容 |
|------|----------|------|
| `core/message-manager` | 当前会话内 | 短期消息（system/user/assistant/tool） |
| `memory/` | 跨会话 | 长期信息（偏好、决策、知识） |

### MVP 状态

第一期不引入向量数据库，避免复杂度过高。先用短期消息和文件搜索完成闭环。

### 云端同步方向

- **本地记忆**：项目结构、代码偏好、常用命令，默认留在本机
- **云端记忆**：用户偏好、团队规范、跨设备任务摘要
- 不默认把完整代码内容写入云端长期记忆
- 云端记忆需要可查看、可删除、可关闭

---

## 12. Auth 层（`src/auth/`）

### 定位

**鉴权与商业化模块**，MVP 阶段暂不实现。

### 未来职责

- 用户登录 / 登出 / Token 刷新
- 本地安全存储
- 用户套餐查询、配额缓存
- Agent 执行前的配额校验
- 设备绑定、手机端登录态
- 本地 Runtime 和云端之间的授权

### 设计原则

> 鉴权和配额不应该写进 Agent Loop。

推荐流程：

```
用户提交任务 → quota guard 检查 → 通过后调用 AgentLoop
```

而不是：

```
AgentLoop 内部判断用户套餐
```

### MVP 状态

第一期不做登录和配额，默认本地单用户使用。

### 远程控制阶段

当支持手机端控制任务时，`auth` 需要配合 Go 云端完成：
- 用户登录
- 设备绑定和解绑
- 本地 Runtime 注册
- 手机端访问令牌
- Runtime 连接令牌
- 任务审批权限校验

> 审批权限不能只靠前端判断，必须由云端控制面校验。

---

## 13. Store 层（`src/store/`）

### 定位

**全局状态管理层**，主要服务 UI。MVP 阶段可以先不引入复杂 store，TUI 直接订阅 EventBus 渲染。

### 可能职责

- 当前聊天消息流
- Agent 当前状态
- 工具调用展示状态
- 任务线程状态
- 待审批操作队列
- 云端同步状态
- SSH 连接状态
- 用户界面偏好

### 能力边界

**Store 可以**：
- 订阅 `EventBus` 获取状态
- 被 `adapters` 引用（UI 从 store 读状态）
- 维护 UI 视角的状态快照

**Store 不可以**：
- ❌ 被 `core` 依赖（core 不应该依赖 store）
- ❌ 成为工具执行入口

### 依赖方向

```
推荐：core → event-bus → store → UI
不推荐：core → store
```

---

## 14. Types 层（`src/types/`）

### 定位

全局类型补充，存放跨模块共享的类型定义。

### 职责

- 定义全局补充类型（`global.d.ts`）
- 跨模块共享的 utility 类型

### 能力边界

- 只放类型定义，不放运行时逻辑
- 不依赖任何其他层

---

## 15. 组装层（`src/index.ts`）

### 定位

**依赖注入与模块装配层**，是整个应用的最外层。负责把所有模块实例化并注入依赖。

### 职责

- 实例化 `EventBus`、`MessageManager`、`ToolRegistry`
- 实例化 `LLMProvider`（选择 Vercel AI 或 OpenAI）
- 实例化 `AgentLoop`，注入所有依赖
- 实例化 `TUIAdapter`，注入 `AgentLoop` 和 `EventBus`
- 加载 MCP 工具、内置工具、记忆工具，注册到 `ToolRegistry`
- 导出公共 API

### 示例

```ts
// src/index.ts
const eventBus = new EventBus();
const messageManager = new MessageManager();
const toolRegistry = new ToolRegistry();

const builtinTools = [readFileTool, codeGrepTool, runShellTool];
const mcpTools = await mcpRegistry.loadTools();
toolRegistry.register([...builtinTools, ...mcpTools]);

const llmProvider = new VercelAIProvider({ /* config */ });
const agentLoop = new AgentLoop({ llmProvider, toolRegistry, messageManager, eventBus });

const tui = new TUIAdapter({ agentLoop, eventBus });
```

### 能力边界

**组装层可以**：
- 依赖所有模块
- 决定使用哪个 Provider、哪些工具

**组装层不可以**：
- ❌ 被任何其他层依赖（它是最外层）
- ❌ 包含业务逻辑（只做装配）

---

## 16. 跨层协作流程示例

### 16.1 本地 TUI 一次完整对话

```
1. 用户在 TUI 输入 "重构 utils.ts"
2. TUI (adapter) 调用 AgentLoop.sendMessage()
3. AgentLoop (core) 调用 ContextManager 组装请求
4. AgentLoop 调用 LLMProvider.generate() (providers，经云端 Relay)
5. LLMProvider 流式返回 → AgentLoop 通过 EventBus 发 thinking/response 事件
6. TUI 订阅 EventBus，实时渲染
7. LLM 返回 tool_call: read_file("utils.ts")
8. AgentLoop 通过 ToolRegistry 查找工具
9. Tool 执行（经 security/path-validator 校验路径，riskLevel=none 自动放行）
10. AgentLoop 通过 EventBus 发 tool_call/tool_result 事件
11. TUI 渲染工具调用状态
12. AgentLoop 把 tool_result 塞回 MessageManager → 回到步骤 3
13. LLM 返回最终回复 → TUI 渲染 → 用户看到结果
```

### 16.2 需要确认的写操作

```
1. LLM 返回 tool_call: write_file("utils.ts", "...")
2. AgentLoop 通过 ToolRegistry 查找工具，riskLevel=medium
3. AgentLoop 调用 ConfirmationPort.requestConfirmation()
4. TUI (实现了 ConfirmationPort) 弹出确认框
5. 用户点"允许"
6. ConfirmationPort 返回 'approved'
7. AgentLoop 执行工具（经 security 校验）
8. 结果回喂，继续循环
```

### 16.3 移动端远程会话（未来）

```
1. 手机端输入 "构建项目" → Go 云端 → 本地 Runtime
2. Runtime 调用 AgentLoop.sendMessage()
3. AgentLoop 执行，遇到 Shell 工具（riskLevel=high）
4. ConfirmationPort 请求确认 → Runtime 弹本地审批框
5. 本地用户点"允许"
6. 工具执行 → 输出流式回传 → 云端透传 → 手机实时看到构建日志
```

---

## 17. 层级速查表

| 层 | 目录 | 定位 | MVP | 可依赖 | 不可依赖 |
|----|------|------|-----|--------|----------|
| Core | `src/core/` | 核心引擎，纯逻辑 | ✅ 5 文件 | ports、context | SDK/UI/fs/store |
| Ports | `src/core/ports/` | 接口契约 | ✅ 4 port | 无 | SDK/副作用 |
| Providers | `src/providers/` | LLM 适配 | ✅ | ports、SDK | core/tools/UI |
| Tools | `src/tools/` | 工具执行 | ✅ 4 工具 | ports、security、fs | adapters |
| MCP | `src/mcp/` | MCP 协议适配 | ✅ | ports、SDK | core/UI |
| Adapters | `src/adapters/` | 用户交互 | ✅ TUI | core、ports | 被 core 依赖 |
| Security | `src/security/` | 安全策略 | ✅ | fs（只读） | 执行工具 |
| Context | `src/context/` | 项目感知 | ✅ 最小 | fs（只读） | 修改文件 |
| Runtime | `src/runtime/` | 本地宿主 | ❌ 未来 | core、ports | UI 渲染 |
| Memory | `src/memory/` | 长期记忆 | ❌ 未来 | 向量库 | 写入 core |
| Auth | `src/auth/` | 鉴权配额 | ❌ 未来 | 云端 API | 写入 AgentLoop |
| Store | `src/store/` | UI 状态 | ❌ 可选 | EventBus | 被 core 依赖 |
| Types | `src/types/` | 全局类型 | ✅ | 无 | 任何层 |
| 组装 | `src/index.ts` | 依赖注入 | ✅ | 所有模块 | 被依赖 |

---

## 18. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-29 | v1.0 | 初版，基于各模块 README + 架构审核报告 + 产品设计文档整理 |
