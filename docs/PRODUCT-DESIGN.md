# MozilCode 产品设计说明

> **版本**：v1.1
> **修订日期**：2026-06-29
> **修订要点**：Agent Core 与 TUI 改为 TypeScript 实现；GUI 维持 Tauri + React；架构理念、云端、移动端、协议、演进路线不变。

---

## 1. 产品定位与设计哲学

本产品是一个类 Claude Code 的本地智能体平台，核心理念是 **"Agent 在本地运行，云端只做中继"**。这与"一切上云"的路线有本质区别：

- **计算在本地**：Agent 循环、工具执行、文件操作都发生在用户机器上。云端不跑 Agent 逻辑，不碰用户文件。
- **云端是路由层**：负责 LLM 请求代理、移动端到本地的消息中继、设备/会话管理。相当于一个"反向代理 + 计费网关"。
- **多端协同**：TUI 面向极客/编码者，GUI 面向日常用户，移动端是远程控制面——三者共享同一个本地 Agent 核心。

这样设计的三条理由：

1. **隐私与数据主权**：文件不离开本地，符合开发者对代码资产的安全预期。云端被攻破不等于用户数据泄露。
2. **延迟与离线能力**：本地工具执行是即时响应；TUI/GUI 可以在云端不可用时直连 LLM API 降级运行。
3. **成本结构**：云端只做轻量转发，不需要为每个用户常驻 Agent 计算实例，服务器成本与用户量近似线性而非指数。

需要诚实面对的代价：本地 Agent 意味着用户机器需要安装运行时、占用本地资源；移动端远程控制依赖本地机器在线；多设备场景下"哪台机器干活"需要用户自己管理。这些是路线选择带来的固有约束，不是 bug。

---

## 2. 整体架构

### 2.1 架构总览

```
┌─────────────┐      WebSocket       ┌───────────────┐     反向 WebSocket     ┌──────────────────┐
│  移动端      │ ←─────────────────→ │   云端 Relay   │ ←──────────────────→ │   本地客户端      │
│  (Android)  │   JSON-RPC over WS   │   (Go)        │   (本地主动连出)       │   TUI  /  GUI    │
└─────────────┘                      └───────────────┘                       └──────────────────┘
                                            │                                          │
                                            │ LLM API 代理                             │ Agent Core (TS)
                                            │ (密钥管理/计费/限流)                      │ + MCP Tool Registry
                                            ▼                                          ▼
                                     ┌───────────────┐                      ┌────────────────────┐
                                     │  LLM Provider │                      │  本地工具集         │
                                     │  (OpenAI 等)  │                      │  文件/Shell/浏览器  │
                                     └───────────────┘                      └────────────────────┘
```

### 2.2 组件清单

| 组件 | 位置 | 语言 / 技术栈 | 职责 |
|------|------|--------------|------|
| Agent Core | 本地 | TypeScript (Node.js runtime，Bun 编译为单二进制) | Agent 循环、工具调度、流式输出、上下文管理 |
| TUI 客户端 | 本地 | TypeScript + Ink (React for CLI) | 终端交互层，直接 import Agent Core |
| GUI 客户端 | 本地 | Tauri 2.x + React 18 + TypeScript | 桌面图形界面，通过 sidecar 调用 Agent Core |
| 云端 Relay | 云端 | Go | LLM 代理、移动↔本地中继、设备/会话管理 |
| 移动端 | Android | Kotlin + Jetpack Compose | 远程会话发起、消息展示、推送接收 |

### 2.3 关键设计决策：Agent Core 作为共享库

TUI 和 GUI 共享同一份 Agent Core（TypeScript 编写的库/二进制），而非各自实现一遍 Agent 逻辑。这是整个架构的基石：

- **TUI**：TypeScript 项目，直接 `import` Agent Core 包，Ink 渲染界面，Agent 循环跑在同一进程（Node.js）。开发期用 `tsx`/`bun` 直跑，分发时用 Bun `build --compile` 打成单二进制，用户无需装 Node。
- **GUI**：Tauri 应用，前端 React/TS 负责渲染，后端通过 sidecar 模式拉起一个 Agent Core 进程（Bun 编译的单二进制），经 stdio 或本地 socket 用 JSON-RPC 通信。这和 VS Code 跑 language server 是同一个模式。

这样做的代价是 GUI 多了一层进程间通信，但换来了"一套 Agent 逻辑、两种界面"的核心收益。如果用别的语言再重写一份 Agent Core 给 GUI 用，两份逻辑会持续漂移，维护成本远高于 IPC 开销。

---

## 3. 各端职责边界

### 3.1 本地客户端（TUI + GUI）

**owns**：Agent 循环、MCP 工具注册与执行、本地文件系统访问、会话历史持久化、流式渲染。

TUI 和 GUI 的差异只在"交互层"：

- **TUI**：键盘驱动、流式文本渲染、命令式操作、面向会写代码的人。适合在 SSH/终端里跑，资源占用低。
- **GUI**：鼠标驱动、富文本/卡片/图表渲染、可视化工具调用确认、面向不碰终端的人。适合日常任务、文件管理、内容生成。

两者共享：工作目录选择、权限审批弹窗/确认、配置（LLM 模型、工具开关）、会话存储格式。

### 3.2 云端 Relay

**不 owns**：Agent 循环逻辑、用户文件内容、工具执行。

**owns**：

1. **LLM 请求代理**：本地 Agent 把 LLM 请求发到云端，云端持有 API Key、做计费/限流/模型路由后转发给真正的 LLM 提供商。用户本地不存 API Key（降低泄露面），但保留"自带 Key 直连"的降级模式。
2. **移动↔本地中继**：这是云端最核心的功能。本地客户端主动向云端建立出站 WebSocket（解决 NAT 穿透），移动端请求经云端路由到对应的本地连接。
3. **设备与配对管理**：用户账号下的设备列表、配对码、在线状态。
4. **会话路由**：移动端发起的会话要路由到"用户指定的某台本地机器"。
5. **云端 MCP 工具**：少量适合云端执行的工具（如联网搜索、天气、第三方 API），通过远程 MCP（SSE transport）暴露给本地 Agent。

### 3.3 移动端（Android）

**owns**：远程会话发起、消息输入与流式展示、推送通知、设备切换。

移动端**不执行 Agent 逻辑**，它是"远程键盘+屏幕"。用户在手机上输入指令 → 云端 → 本地 Agent 执行 → 结果流式回传到手机。这意味着：本地机器必须在线，否则移动端只能看到"目标设备离线"。

典型场景：通勤时让家里的机器跑个构建、查个文件、生成一段文档，回家直接看结果。

---

## 4. 技术栈选型

### 4.1 选型总表

| 层 | 技术 | 选型理由 |
|----|------|----------|
| Agent Core | **TypeScript + Node.js**（Bun `build --compile` 打包为单二进制） | 与项目骨架、Port 接口定义、LLM/MCP SDK 生态同语言；TUI/GUI/Web 共享类型与协议定义 |
| TUI 框架 | **Ink**（React for CLI，Vercel 出品） | 与 GUI 侧 React 心智一致，组件/Hooks/状态模型可迁移；流式渲染天然支持 |
| GUI 框架 | **Tauri 2.x + React 18 + TypeScript** | 比 Electron 轻 10 倍以上，Rust runtime 安全，sidecar 机制官方支持 |
| GUI 样式 | **Tailwind CSS + shadcn/ui** | 组件即代码、可定制性强，避免重 UI 框架锁定 |
| 云端 | **Go + 标准库 net/http + gorilla/websocket**（或 nhooyr/websocket） | 高并发 WebSocket 连接是 Go 的舒适区；避免引入框架直到需要 |
| 移动端 | **Kotlin + Jetpack Compose + Material 3** | 官方推荐路线，Compose 声明式 UI 与 React 心智模型一致 |
| 本地存储 | **SQLite**（via `better-sqlite3` 或 `node:sqlite`） | 会话历史、配置、设备配对信息；单文件、零运维 |
| 序列化 | **JSON-RPC 2.0 over WebSocket / stdio** | 语义清晰、调试友好、生态广；不引入 gRPC 复杂度 |
| 鉴权 | **JWT（用户级）+ 设备配对码（设备级）** | 云端发 JWT，设备配对用一次性码 + 长期 refresh token |
| 构建分发 | **Bun `build --compile`** | 把 TS Agent Core + Node runtime 编译成单 exe，用户无需装 Node；跨平台交叉编译 |

### 4.2 关键选型理由展开

#### 为什么 Agent Core 选 TypeScript 而不是 Go/Rust？

1. **与项目骨架一致**：项目从一开始就用 TS 规划了 `core/ports/*.ts` 的六边形架构，Port 接口（`LLMProviderPort`、`AgentToolPort`、`ConfirmationPort`）用 TS 定义最自然；改 Go 等于推倒重来。
2. **跨端共享**：TUI、GUI 前端、未来 Web 端共享同一份 TS Agent Core 源码与类型定义，无需跨语言胶水。协议类型（`AgentMessage`、`ToolCall`、`LLMResponse`）在前后端直接复用。
3. **SDK 生态成熟**：Vercel AI SDK、OpenAI SDK、Anthropic SDK、`@modelcontextprotocol/sdk` 官方 TS 实现完善且持续更新；Go/Rust 的等价库往往是社区维护、滞后版本。
4. **流式与异步契合**：Node.js 事件循环 + `async/await` + `ReadableStream` 天然契合 LLM 流式接收、工具并行执行、UI 事件响应。`Promise.all` / `AbortController` / `AsyncIterator` 表达力足够。
5. **单二进制分发不再是短板**：Bun `build --compile` 把 TS + Node runtime 一起编译成单 exe，跨平台交叉编译（`--target=bun-windows-x64` 等），分发体验接近 Go。
6. **代价**：CPU 密集型任务（如本地向量计算、AST 大规模分析）不如 Go/Rust，但 Agent Core 是 IO 密集（LLM 流式、WebSocket、文件 IO），Node 足够；启动比纯 Go 二进制略慢（Bun 编译后可控在 50ms 级）。

#### 为什么 TUI 选 Ink 而不是 Go Charm / Blessed？

1. **与 GUI 同心智**：Ink 是"React for CLI"，组件、Hooks、状态、副作用的概念与 GUI 侧 React 完全一致，工程师在两端切换零认知成本。
2. **共享 Agent Core**：TUI 直接 `import` 同一份 TS Agent Core，无 IPC 开销，调试链路最短。
3. **流式渲染天然支持**：Ink 的 `useApp`、`useInput`、`useState` 配合 React 重渲染，流式 token 输出、工具调用进度、确认弹窗都很自然。
4. **生态质量**：Vercel 出品，GitHub CLI、Cloudflare Wrangler、Gatsby CLI 都在用，长期维护有保障。
5. **代价**：终端重渲染性能不如 Go Charm 的 diff 算法极端场景下强，但终端 IO 不是 Agent 的瓶颈；首次启动比单 Go 二进制慢一点（Bun 编译后可接受）。

#### 为什么 GUI 选 Tauri 而不是 Electron？

1. **体积**：Electron 打包后 150MB+，Tauri ~10MB，对"本地常驻"的工具更友好。
2. **sidecar 机制原生支持**：Tauri 官方支持"拉起一个外部进程并通信"，正好匹配 Agent Core 作为独立进程（Bun 编译的单二进制）的架构。
3. **安全模型更强**：默认禁用 Node 集成，文件系统访问走白名单。
4. **代价**：Tauri 社区比 Electron 小，遇到冷门问题资料少；前端仍是 React/TS，学习曲线不变。如果团队完全不会 Rust，Tauri 的 build 配置偶尔会卡，但日常开发不碰 Rust。

#### 为什么移动端选 Kotlin 原生而不是 Flutter/RN？

1. 用户明确要求安卓原生开发。
2. Compose 的声明式 UI 与 GUI 侧 React 心智一致，状态管理、副作用、重组/重渲染的概念可以迁移。
3. 原生能更好地处理后台长连接、前台服务、推送通道（FCM / 国内厂商推送）。
4. **代价**：只覆盖 Android，iOS 暂不考虑（若日后需要，Compose Multiplatform 是备选迁移路径，但不是现在的决策依据）。

#### 为什么云端不选 Java/Spring？

1. 用户提到"Go/Java"，这里选 Go。云端核心是 WebSocket 长连接管理和请求路由，Go 的 goroutine-per-connection 模型比 Spring 的线程池/反应式更简单直接。
2. **协议定义跨语言**：Agent Core 是 TS，云端是 Go，二者通过 JSON-RPC 文本协议通信，不需要 proto 文件，类型在两端各自定义即可（TS 用类型，Go 用 struct）。
3. Spring Boot 适合"有大量业务实体、CRUD、事务"的后台系统，但这个云端是"瘦中继"，引入 Spring 是过度工程。
4. 如果未来云端长出复杂业务（计费系统、团队管理、审计日志），可以在云端内部拆出 Java 服务做这些，Go 继续做中继——但不预设这个复杂度。

---

## 5. Agent Core 运行时设计

### 5.1 Agent 循环

核心是一个"消息进、动作出、结果回喂"的循环：

```
用户输入
   │
   ▼
构造 LLM 请求（system prompt + 历史 + 可用工具 schema）
   │
   ▼
调用 LLM（流式） ──→ 边收边渲染到 UI
   │
   ▼
LLM 返回 tool_calls？
   ├─ 是 → 逐个执行工具（可并行）→ 把 tool_result 塞回历史 → 回到"构造请求"
   └─ 否 → 输出最终回复 → 循环结束，等待下一轮输入
```

关键点：

- **流式**：LLM 的 SSE 流逐 token 往 UI 推，工具调用的 `tool_calls` 字段在流结束时才完整解析。
- **并行工具调用**：LLM 一次可能返回多个 `tool_call`，用 `Promise.all` + `AbortController` 并发执行，全部完成后再回喂。
- **中断**：用户可以随时 ESC/Ctrl+C 中断当前循环（`AbortController.abort()` 取消 LLM 请求 + 不执行后续工具）。
- **上下文窗口**：历史消息超长时需要摘要/截断策略，这是后续优化的重点，v1 先做简单的 token 计数 + 滑动窗口。

### 5.2 工具调度器

工具调度器是 Agent Core 和 MCP 之间的桥梁：

```
ToolDispatcher
   │
   ├── 本地 MCP 客户端（stdio transport）
   │     ├── filesystem server  → 文件读写
   │     ├── shell server       → 命令执行
   │     ├── browser server     → 浏览器自动化
   │     └── git server         → 版本控制
   │
   └── 远程 MCP 客户端（SSE transport，经云端）
         ├── web-search         → 联网搜索
         └── third-party-api    → 第三方服务
```

工具注册时声明：名称、JSON Schema（参数）、是否需要确认、执行位置（本地/云端）。Agent 把这些 schema 合并进 LLM 的 `tools` 参数。LLM 决定调用哪个工具后，`ToolDispatcher` 根据执行位置分发。

### 5.3 进程模型

**GUI 模式（多进程）**：

```
┌─────────────────────────────────────────────┐
│  GUI 进程 (Tauri)                            │
│  ┌─────────────────────────────────────────┐ │
│  │  WebView (React + TS)                   │ │
│  └───────────────┬─────────────────────────┘ │
│                  │ Tauri IPC (invoke)         │
│  ┌───────────────▼─────────────────────────┐ │
│  │  Rust backend (Tauri core)              │ │
│  └───────────────┬─────────────────────────┘ │
│                  │ sidecar stdio (JSON-RPC)   │
│  ┌───────────────▼─────────────────────────┐ │
│  │  agent-core.exe (Bun 编译的 TS 二进制)   │ │
│  │  ├── Agent 循环                          │ │
│  │  ├── ToolDispatcher                      │ │
│  │  └── MCP 客户端                          │ │
│  └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

**TUI 模式（单进程）**：

```
┌─────────────────────────────────────────────┐
│  mozil-tui.exe (Bun 编译的单二进制)           │
│  ┌─────────────────────────────────────────┐ │
│  │  Ink (React for CLI)                    │ │
│  └───────────────┬─────────────────────────┘ │
│                  │ 直接 import（同进程）       │
│  ┌───────────────▼─────────────────────────┐ │
│  │  Agent Core (TS)                        │ │
│  │  ├── Agent 循环                          │ │
│  │  ├── ToolDispatcher                      │ │
│  │  └── MCP 客户端                          │ │
│  └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

TUI 进程更简单：单个 Bun 编译二进制，Ink 直接调用 Agent Core 包，无 IPC。

---

## 6. 通信与协议

### 6.1 三条通信链路

| 链路 | 传输 | 方向 | 用途 |
|------|------|------|------|
| 本地 ↔ 云端 | WebSocket（本地主动出站） | 双向 | LLM 代理 + 移动端远程指令透传 |
| 移动 ↔ 云端 | WebSocket（或 HTTP/2 + SSE） | 双向 | 远程会话发起、流式结果接收 |
| GUI ↔ Agent Core | stdio JSON-RPC（本地进程间） | 双向 | UI ↔ Agent 循环通信 |

### 6.2 反向 WebSocket 连接模式（NAT 穿透）

本地机器通常在 NAT 后面，云端无法主动连入。采用"本地主动出站"模式：

1. 本地客户端启动后，用设备 token 向 `wss://relay.example.com/connect` 建立出站 WebSocket。
2. 连接保持长开，定期心跳（ping/pong，30s 间隔）。
3. 云端记录 `device_id → websocket_conn` 映射。
4. 移动端发请求时指定 `target_device_id`，云端找到对应连接，把消息帧透传过去。
5. 本地执行结果原路返回。

这是 frp / ngrok / tailscale 的核心思路，成熟可靠。云端只需维护连接池，不维护计算实例。

### 6.3 消息协议（JSON-RPC 2.0）

所有 WebSocket 链路统一用 JSON-RPC 2.0：

```json
// 请求（移动端 → 云端 → 本地）
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "method": "agent.sendMessage",
  "params": {
    "session_id": "sess-abc",
    "content": "帮我看看 Desktop 下的文件",
    "stream": true
  }
}

// 流式通知（本地 → 云端 → 移动端，多条）
{ "jsonrpc": "2.0", "method": "agent.streamDelta", "params": { "session_id": "sess-abc", "delta": "Desktop 下有" } }
{ "jsonrpc": "2.0", "method": "agent.streamDelta", "params": { "session_id": "sess-abc", "delta": " 3 个文件" } }

// 工具调用通知（让移动端看到 Agent 在干什么）
{ "jsonrpc": "2.0", "method": "agent.toolCall", "params": { "tool": "filesystem.list", "args": {} } }

// 流结束
{ "jsonrpc": "2.0", "method": "agent.streamEnd", "params": { "session_id": "sess-abc" } }
```

选 JSON-RPC 而非 gRPC 的理由：WebSocket 上跑 gRPC 需要 WebSocket transport + grpc-web，复杂度高；JSON-RPC 调试时肉眼可读，移动端 Kotlin 也有现成库。等出现明确的序列化性能瓶颈再迁移。

> **类型共享说明**：TS 端定义 `AgentMessage`/`ToolCall`/`LLMResponse` 等类型，Go 云端定义等价 struct，Kotlin 端定义 data class。三方通过 JSON-RPC 文本协议解耦，不引入 proto / 代码生成工具链，直到协议稳定且有性能需求。

### 6.4 鉴权与设备配对

```
用户注册/登录（云端发 JWT）
        │
        ▼
本地客户端用 JWT 换取设备 token
        │
        ▼
移动端扫码 / 输入配对码 → 绑定到同一用户账号
        │
        ▼
移动端发起会话时带 JWT + target_device_id
        │
        ▼
云端校验：JWT 合法 + 设备属于该用户 + 设备在线
        │
        ▼
放行，路由到对应本地连接
```

设备配对码是一次性 6 位码，本地客户端展示（TUI 打印 / GUI 弹窗 / 二维码），移动端输入后绑定。绑定后移动端持有该设备的长期 refresh token，用于指定目标。

---

## 7. MCP 与工具链

### 7.1 工具执行位置矩阵

| 工具类型 | 执行位置 | 理由 |
|----------|----------|------|
| 文件系统读写 | 本地 | 操作的是本地文件，数据不出机器 |
| Shell 命令 | 本地 | 在本地环境执行，继承本地 PATH/环境变量 |
| 浏览器自动化 | 本地 | 操作本地浏览器，可见可干预 |
| Git 操作 | 本地 | 操作本地仓库 |
| 联网搜索 | 云端 | 搜索引擎 API 在云端调用更稳定，避免本地 IP 被限 |
| 第三方 SaaS API | 云端 | 云端统一管理 OAuth token |

### 7.2 MCP 集成方式

Agent Core 内置一个 MCP 客户端（基于 `@modelcontextprotocol/sdk`），支持两种 transport：

- **stdio transport（本地工具）**：Agent Core 拉起 MCP server 子进程，经 stdin/stdout 通信。这是 MCP 的标准本地模式。
- **SSE/HTTP transport（云端工具）**：Agent Core 经云端访问远程 MCP server，云端持有这些工具的实现。

工具发现流程：

1. Agent Core 启动时读取配置（`~/.mozil/config.toml`），加载 MCP server 列表。
2. 逐个连接 MCP server，调用 `tools/list` 获取工具清单和 schema。
3. 合并所有工具 schema，注入 LLM 请求的 `tools` 参数。
4. LLM 返回 `tool_call` 时，`ToolDispatcher` 找到对应 server，调用 `tools/call`。

### 7.3 权限与审批

工具调用分三档权限：

| 档位 | 行为 | 示例 |
|------|------|------|
| 自动放行 | 无需确认 | 读文件、搜索、git status |
| 首次确认 | 每个会话首次问一次 | 写文件、git commit |
| 每次确认 | 每次都问 | 删除文件、Shell 命令、安装包 |

远程会话（移动端发起）额外加码：

- 默认所有工具调用都需本地确认（移动端发起的请求，本地弹审批框）。
- 用户可在配置里给特定设备/特定工具预授权（如"手机可以读文件但不能跑 Shell"）。
- 本地客户端离线时，移动端请求直接拒绝，不排队。

这是"本地是数据主权方"原则的体现：远程请求是"请求"不是"命令"，本地有权拒绝。

### 7.4 文件系统访问策略

参照成熟实践，采用"工作目录白名单"：

- Agent 只能访问用户明确选择的目录（及其子目录）。
- TUI 启动时指定 `--workdir`，GUI 让用户选文件夹。
- 移动端远程会话继承本地客户端当前的工作目录。
- 白名单外的路径访问会被 `ToolDispatcher` 拦截，返回权限错误给 LLM。

这避免了 Agent 误操作系统级目录，也给了用户心理安全感。

---

## 8. 数据流与关键链路

### 8.1 本地 TUI 一次完整对话

```
用户在终端输入 "重构 utils.ts"
    │
    ▼
TUI (Ink) 收到输入 → 调用 AgentCore.sendMessage()
    │
    ▼
AgentCore 构造 LLM 请求 → 经云端 Relay 转发到 LLM Provider
    │
    ▼  （流式 SSE）
AgentCore 逐 token 收到响应 → 通过 AsyncIterator 推给 Ink → 终端实时渲染
    │
    ▼
LLM 返回 tool_call: filesystem.read("utils.ts")
    │
    ▼
ToolDispatcher 执行（本地，自动放行）→ 返回文件内容
    │
    ▼
AgentCore 回喂 tool_result → 再次请求 LLM → 继续流式
    │
    ▼
（可能多轮工具调用）
    │
    ▼
LLM 返回最终重构后的代码 → TUI 渲染 → 用户看到结果
```

### 8.2 移动端远程会话

```
用户在手机输入 "构建一下 MozilCode 项目"
    │
    ▼
移动端 → 云端 (agent.sendMessage, target_device_id=home-pc)
    │
    ▼
云端查连接池 → 找到 home-pc 的 WebSocket → 透传消息帧
    │
    ▼
本地 GUI/TUI 收到 → AgentCore 执行（Shell 工具，需确认）
    │
    ▼
本地弹审批框 "允许执行: npm run build?" → 用户点允许
    │
    ▼
执行 → 输出流式回传 → 云端透传 → 手机实时看到构建日志
    │
    ▼
完成 → 手机收到 streamEnd
```

### 8.3 降级模式：云端不可用

- 本地客户端检测到云端 WebSocket 断开 → 切换"直连模式"。
- 用户在配置里填入自己的 LLM API Key → AgentCore 直接请求 LLM Provider。
- 代价：无移动端远程控制、无云端计费/限流、无云端 MCP 工具。
- 本地工具不受影响，正常可用。

这让产品在云端故障时仍可用，也满足"不想走云端、自带 Key"的极客用户。

---

## 9. 安全考量

- **API Key 不落本地**：默认模式下本地只持有云端 JWT 和设备 token，LLM API Key 只在云端。降级模式才让用户填本地 Key，且明确提示风险。
- **WebSocket 鉴权**：每条 WS 连接建立时带 JWT，云端校验后才注册到连接池。心跳超时自动断开。
- **工具沙箱**：文件系统白名单 + Shell 命令黑名单（可配置，如禁止 `rm -rf /`、`format` 等）。
- **远程会话审计**：移动端发起的工具调用记录到本地日志（可查），不留云端。
- **传输加密**：所有 WebSocket 走 `wss://`（TLS）。

---

## 10. 演进路线

按"先跑通本地、再接云端、最后上移动"的顺序，避免一上来铺太大的摊子：

### 阶段一：本地 TUI MVP

- Agent Core（TS）：Agent 循环 + 流式 + 2-3 个本地工具（文件读写、Shell）。
- TUI（Ink）：基础界面、流式渲染、工具调用展示。
- LLM 直连模式（自带 Key），不依赖云端。
- **目标**：能在终端里和 Agent 对话、让它读写文件、跑命令。

### 阶段二：云端 Relay

- Go 云端：WebSocket 中继 + LLM 代理 + JWT 鉴权。
- 本地客户端改为经云端请求 LLM。
- 设备配对流程。
- **目标**：本地不再需要自带 Key，云端统一计费。

### 阶段三：GUI

- Tauri + React 前端，sidecar 拉起 Agent Core（Bun 编译二进制）。
- 基础对话界面 + 工具调用可视化 + 文件选择器。
- **目标**：不碰终端的用户也能用。

### 阶段四：移动端

- Android 客户端：设备配对、远程会话、流式展示。
- 云端路由到指定本地设备。
- 远程工具调用审批流程。
- **目标**：手机上远程驱动本地 Agent。

### 阶段五（可选方向，不预设）

- 多 Agent 协作（A2A 协议）。
- 定时任务 / 事件触发（本地 Agent 常驻 + cron）。
- 向量 RAG（本地知识库检索）。
- iOS 端（Compose Multiplatform 迁移）。

每个阶段独立可用、有验证价值，不会因为后续阶段没做而让前面白做。

---

## 11. 待决问题

以下是当前设计里尚未定死、需要随着开发推进再决策的点：

- **LLM 多模型路由策略**：云端如何决定把请求发给哪个模型？按用户配置？按任务类型？按成本？v1 先做"用户指定模型"，复杂路由后置。
- **会话历史存储位置**：纯本地 SQLite，还是云端同步？本地优先 + 可选同步是倾向方案，但同步冲突需要设计。
- **工具调用的撤销**：Agent 写了文件/跑了命令后，能否回滚？git 能管代码，但 Shell 命令不可逆。是否引入"操作日志 + 手动回放"？
- **多设备会话迁移**：在 TUI 开了个会话，能否切到 GUI 继续？需要会话状态序列化 + 重建。
- **离线工具市场**：MCP server 的发现和安装流程——是否做一个类似 VS Code 扩展商店的机制？

这些不阻塞 v1，但会随着用户量增长变成必答题。

---

## 附录 A：本次修订相对原稿的变更摘要

| 变更项 | 原稿 | 本版 | 理由 |
|--------|------|------|------|
| Agent Core 语言 | Go | **TypeScript (Node.js + Bun 编译)** | 与项目既有 TS 骨架、Port 接口定义、LLM/MCP SDK 生态对齐；TUI/GUI/Web 共享类型 |
| TUI 框架 | Charm (bubbletea + lipgloss + glamour) | **Ink (React for CLI)** | 与 GUI 侧 React 同心智；与 TS Agent Core 同语言无胶水 |
| Agent Core 分发 | `GOOS=... go build` | **Bun `build --compile`** | TS 单二进制分发方案，体验接近 Go |
| 并发原语 | goroutine + channel + errgroup | **Promise.all + AbortController + AsyncIterator** | TS 异步模型表达力足够，契合 IO 密集场景 |
| SQLite 驱动 | `mattn/go-sqlite3` / `modernc.org/sqlite` | **`better-sqlite3` / `node:sqlite`** | Node 生态对应驱动 |
| 配置路径 | `~/.agent/config.toml` | `~/.mozil/config.toml` | 用产品名命名配置目录 |
| 跨语言协议共享 | Go 包共享 struct | **TS 类型 + Go struct + Kotlin data class，由 JSON-RPC 文本协议解耦** | 跨语言无法共享包，改由协议契约对齐 |
| 不变项 | — | 云端 Go、移动端 Kotlin、Tauri+React GUI、JSON-RPC 协议、NAT 穿透、权限三档、演进路线 | 用户要求"其他不变" |

> **不变的核心理念**：Agent 在本地运行、云端只做中继、多端共享同一本地 Agent 核心、本地是数据主权方。语言从 Go 换成 TS 是实现层的选择，不改变架构哲学。
