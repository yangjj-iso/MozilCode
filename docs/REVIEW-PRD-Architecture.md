# MozilCode 架构审核报告

> **审核日期**：2026-06-24
> **审核版本**：v2.0（深度审核）
> **审核范围**：PRD-MVP(1).md 及全部项目文档

---

## 执行摘要

### 整体评价

MozilCode 项目采用 **Ports and Adapters（六边形）架构模式**，设计思路清晰，符合现代 TypeScript 终端 Coding Agent 的最佳实践。架构分层明确：核心逻辑（core）与外部依赖（providers、tools、adapters）通过接口（ports）解耦，支持依赖注入和测试 Mock。

**当前状态**：项目处于骨架搭建阶段（Skeleton Project），仅完成目录结构设计和 README 文档规划，尚未实现任何业务代码。

### 关键发现

| 类别 | 数量 |
|------|------|
| CRITICAL | 1 |
| HIGH | 4 |
| MEDIUM | 3 |
| LOW | 2 |

**核心风险**：context 模块命名与 context-manager.ts 存在概念混淆，可能导致未来职责边界模糊；项目无实际代码，无法验证架构决策的可执行性。

---

## 1. 架构模式评估

### 1.1 Ports and Adapters 模式应用

**评估**：设计合理，符合六边形架构原则。

```
┌─────────────────────────────────────────────────────────────────┐
│                        外部世界                                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                    │
│  │  TUI     │   │  Provider│   │  Tools   │                    │
│  │ Adapter  │   │ (LLM)    │   │          │                    │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘                    │
│       │              │              │                           │
├───────┴──────────────┴──────────────┴───────────────────────────┤
│                        ports (接口层)                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                │
│  │ LLM Port   │  │ Tool Port  │  │Confirm Port│                │
│  └────────────┘  └────────────┘  └────────────┘                │
├─────────────────────────────────────────────────────────────────┤
│                        core (核心层)                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌───────────┐ │
│  │Agent Loop  │  │ Message    │  │ Context    │  │Tool       │ │
│  │            │  │ Manager    │  │ Manager    │  │Registry   │ │
│  └────────────┘  └────────────┘  └────────────┘  └───────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**优点**：
- 核心层完全不依赖外部 SDK、UI 框架、文件系统
- ports 作为契约层，类型稳定后即可并行开发
- 依赖注入机制支持多种 Provider/Tool 实现

**不足**：
- 缺少 ports 接口的 TypeScript 代码定义
- 无实际代码验证架构可执行性

### 1.2 核心层与适配器层边界

**边界定义清晰度**：★★★★☆（4/5）

| 边界 | 定义位置 | 清晰度 |
|------|----------|--------|
| core ↔ providers | providers/README.md | 清晰 |
| core ↔ tools | tools/README.md | 清晰 |
| core ↔ adapters | adapters/README.md | 清晰 |
| core ↔ store | store/README.md | 清晰 |
| core ↔ context | **边界模糊** | 需改进 |

---

## 2. 模块边界审查

### 2.1 核心模块职责矩阵

| 模块 | README 规划职责 | PRD 定义 | 一致性 |
|------|----------------|----------|--------|
| `core/agent-loop.ts` | LLM 调用、工具调度、状态事件 | PRD 7.1 | ✓ 一致 |
| `core/context-manager.ts` | 系统提示词、对话历史、上下文长度 | PRD 7.2 | ✓ 一致 |
| `core/message-manager.ts` | 会话消息管理 | PRD 7.3 | ✓ 一致 |
| `core/event-bus.ts` | 状态事件发布 | PRD 7.4 | ✓ 一致 |
| `core/tool-registry.ts` | 工具注册与查找 | **PRD 未定义** | ⚠ 新增 |

### 2.2 问题模块详细分析

#### 问题 1：context 目录与 context-manager.ts 职责混淆

**CRITICAL - 架构缺陷**

| 实体 | 位置 | 定义的"上下文"含义 |
|------|------|-------------------|
| `context-manager.ts` | `core/` | 会话上下文：组装系统提示词、对话历史、上下文长度 |
| `src/context/` | 根目录 | 项目上下文：代码搜索、AST 分析、RAG 索引、项目结构 |

**语义冲突分析**：

```
"Context" 在系统中存在两种完全不同的含义：

1. LLM Context（会话上下文）
   - 系统提示词
   - 用户历史消息
   - 工具调用结果
   - 上下文窗口管理

2. Project Context（项目上下文）
   - 项目文件结构
   - 代码语义（AST）
   - 文档知识（RAG）
   - 语义搜索能力
```

---

## 3. 接口设计评估

### 3.1 Port 接口完整性

**当前状态**：仅在 README 中规划，无 TypeScript 代码。

| Port 接口 | README 定义 | TypeScript 状态 | 建议优先级 |
|-----------|-------------|-----------------|-----------|
| `llm.port.ts` | ✓ 规划 | ✗ 未实现 | P0 |
| `tool.port.ts` | ✓ 规划 | ✗ 未实现 | P0 |
| `confirmation.port.ts` | ⚠ README 提及 | ✗ 未实现 | P1 |

### 3.2 建议的接口设计

#### LLM Port

```typescript
// src/core/ports/llm.port.ts

export type MessageRole = 'system' | 'user' | 'assistant' | 'tool'

export interface AgentMessage {
  role: MessageRole
  content: string
  toolCalls?: ToolCall[]
  toolCallId?: string
}

export interface ToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
}

export interface LLMResponse {
  content: string
  toolCalls?: ToolCall[]
  finishReason: 'stop' | 'length' | 'content_filter' | 'tool_calls'
}

export interface LLMProviderPort {
  generate(messages: AgentMessage[]): Promise<LLMResponse>
  getModel(): string
  isConfigured(): boolean
}
```

#### Tool Port

```typescript
// src/core/ports/tool.port.ts

export type RiskLevel = 'none' | 'low' | 'medium' | 'high' | 'critical'

export interface ToolContext {
  workspaceRoot: string
  workingDirectory?: string
  env?: Record<string, string>
}

export interface ToolResult {
  success: boolean
  content: string
  error?: string
}

export interface AgentToolDefinition {
  name: string
  description: string
  parameters: {
    type: 'object'
    properties: Record<string, unknown>
    required?: string[]
  }
}

export interface AgentToolPort {
  readonly definition: AgentToolDefinition
  readonly riskLevel: RiskLevel
  execute(args: Record<string, unknown>, context: ToolContext): Promise<ToolResult>
}
```

#### Confirmation Port

```typescript
// src/core/ports/confirmation.port.ts

export interface ConfirmationRequest {
  type: 'write_file' | 'delete_file' | 'run_shell' | 'multi_file'
  targets: string[]
  riskLevel: RiskLevel
  description: string
}

export type ConfirmationResult = 'approved' | 'denied' | 'cancelled'

export interface ConfirmationPort {
  requestConfirmation(request: ConfirmationRequest): Promise<ConfirmationResult>
  requiresConfirmation(request: ConfirmationRequest): boolean
}
```

---

## 4. 依赖边界检查

### 4.1 依赖方向规则

```
允许的依赖方向：
adapters  →  core  →  ports
providers  →  core/ports
tools      →  core/ports
index.ts   →  组装所有模块

禁止的依赖方向：
core      →  adapters
core      →  providers
core      →  tools 具体实现
core      →  store
```

### 4.2 循环依赖风险评估

**风险等级**：低

**潜在风险点**：
```
如果未来 context/project-context 依赖 tools，
可能导致：core → context/project → tools → core（循环）
```

---

## 5. 安全架构设计

### 5.1 安全边界规划完整性

**评分**：★★★☆☆（3/5）

| 安全边界 | README 提及 | PRD 定义 | 实现规划 |
|----------|-------------|----------|----------|
| 工作区路径限制 | ✓ | ✓ | 仅规划 |
| 写操作确认 | ✓ | ✓ | 仅规划 |
| Shell 危险命令拦截 | ✓ | ✓ | 仅规划 |
| 输出截断 | ✓ | ✓ | 仅规划 |

### 5.2 危险命令拦截策略

```typescript
// 危险命令模式
const DANGEROUS_PATTERNS = [
  /^rm\s+-rf\s+/,
  /^git\s+reset\s+--hard/,
  /^del\s+\/s/i,
  /^format\s+/i,
  /^dd\s+/,
  /^mkfs\s+/,
]

// 二次确认阈值
const SECOND_CONFIRM_THRESHOLD = 'high'
```

---

## 6. 可测试性设计

### 6.1 Fake 实现点规划

```typescript
// tests/fakes/fake-llm.provider.ts
export class FakeLLMProvider implements LLMProviderPort {
  responses: LLMResponse[] = []
  callHistory: AgentMessage[][] = []

  async generate(messages: AgentMessage[]): Promise<LLMResponse> {
    this.callHistory.push(messages)
    return this.responses.shift() ?? { content: '', finishReason: 'stop' }
  }
}

// tests/fakes/fake-tool.ts
export class FakeTool implements AgentToolPort {
  definition = { name: 'fake', description: '', parameters: { type: 'object', properties: {} } }
  riskLevel = 'none'
  executionLog: { args: Record<string, unknown>, context: ToolContext }[] = []

  async execute(args: Record<string, unknown>, context: ToolContext): Promise<ToolResult> {
    this.executionLog.push({ args, context })
    return { success: true, content: 'fake result' }
  }
}
```

### 6.2 测试覆盖目标

| 模块 | 建议覆盖率 | 关键测试用例 |
|------|-----------|-------------|
| agent-loop | 90%+ | 工具调用、会话管理、错误恢复 |
| context-manager | 85%+ | 上下文组装、长度限制 |
| message-manager | 90%+ | 消息类型区分、历史管理 |
| tool-registry | 90%+ | 工具注册、查找、风险评估 |

---

## 7. 架构质量评分

### 评分明细表

| 维度 | 得分 | 权重 | 评价 |
|------|------|------|------|
| 模块化 | 4.0/5 | 15% | Ports and Adapters 模式清晰 |
| 可扩展性 | 4.0/5 | 15% | Provider/Tool 扩展成本低 |
| 可测试性 | 4.0/5 | 15% | 架构天然支持 Mock |
| 安全性 | 3.0/5 | 15% | 有规划但无实现和文档 |
| 可维护性 | 3.5/5 | 10% | 职责清晰但 context 混淆 |
| 文档完整性 | 2.5/5 | 10% | 基础 README 好，深度文档缺失 |
| 接口设计 | 3.0/5 | 10% | 设计合理但无代码 |
| 架构一致性 | 3.0/5 | 10% | context 命名问题 |

**总分**：**3.45 / 5**

---

## 8. 问题汇总

### CRITICAL（架构缺陷 - 必须修复）

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| C1 | 所有业务代码文件缺失 | src/ | 包括 core/*.ts、ports/*.ts、tools/*.ts 等 15+ 个文件 |
| C2 | 缺少 src/index.ts 入口文件 | src/index.ts | 依赖组装职责无法落地 |

### HIGH（设计问题 - 强烈建议修复）

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| H1 | context 目录与 context-manager.ts 职责混淆 | src/context/ vs core/ | 两者都包含"上下文"相关能力，边界不清晰 |
| H2 | confirmation.port.ts 定义不明确 | src/core/ports/ | 确认机制无统一契约 |
| H3 | 无 TypeScript 编译时依赖边界检查 | tsconfig/eslint | 无法防止错误的依赖方向 |
| H4 | 危险命令拦截策略未具体规划 | src/tools/ | Shell 安全边界不明确 |

### MEDIUM（改进建议 - 建议优化）

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| M1 | 安全文档缺失 | docs/SECURITY.md | 安全设计无法审查 |
| M2 | 架构图文档缺失 | docs/ARCHITECTURE.md | 新成员理解成本高 |
| M3 | 无 package.json 依赖 | package.json | 无法安装测试工具 |

### LOW（可选优化）

| # | 问题 | 说明 |
|---|------|------|
| L1 | memory 模块 MVP 不实现但有目录 | 轻微混淆（可接受） |
| L2 | 缺少 .gitignore 详细规则 | 可能提交不必要的文件 |

---

## 9. 改进建议

### 9.1 优先级 P0（立即执行）

#### 创建核心 Port 接口

**文件清单**：
```
src/core/ports/
├── llm.port.ts           # LLM Provider 接口
├── tool.port.ts          # Tool 接口
├── confirmation.port.ts  # 确认接口
└── index.ts             # 统一导出
```

#### 创建 index.ts 入口文件

```typescript
// src/index.ts
import { AgentLoop } from './core/agent-loop.js'
import { MessageManager } from './core/message-manager.js'
import { ContextManager } from './core/context-manager.js'
import { EventBus } from './core/event-bus.js'
import { ToolRegistry } from './core/tool-registry.js'
import { OpenAIProvider } from './providers/openai.provider.js'
import { TUIAdapter } from './adapters/tui/index.js'

const eventBus = new EventBus()
const messageManager = new MessageManager()
const toolRegistry = new ToolRegistry()
const llmProvider = new OpenAIProvider({ /* config */ })
const agentLoop = new AgentLoop({ llmProvider, toolRegistry, messageManager, eventBus })
const tui = new TUIAdapter({ agentLoop, eventBus })

export { agentLoop, tui, eventBus }
```

### 9.2 优先级 P1（下一迭代）

#### 解决 context 职责混淆

**方案**：重命名 `src/context/` 为 `src/project-context/`

```bash
mv src/context src/project-context
```

#### 创建安全策略文档

**文件**：`docs/SECURITY.md`

---

## 10. 优先级排序

### 建议执行顺序

| 阶段 | 任务 | 优先级 |
|------|------|--------|
| 1 | 创建 src/core/ports/*.ts 接口定义 | P0 |
| 2 | 创建 src/index.ts 入口文件 | P0 |
| 3 | 验证 TypeScript 编译通过 | P0 |
| 4 | 实现 core 核心模块 | P0 |
| 5 | 解决 context 职责混淆 | P1 |
| 6 | 创建 docs/SECURITY.md | P1 |
| 7 | 实现 tools 和 providers | P1 |
| 8 | 实现 TUI adapters | P1 |

### 并行化建议

**可并行执行**：
- P0 接口定义 + P0 index.ts 可以同时开始
- 核心模块和工具可并行开发，通过 Mock 隔离

---

## 11. 总结

### 架构优势

1. **模式选择得当**：Ports and Adapters 是复杂 Agent 系统的最佳架构选择
2. **依赖方向清晰**：核心层与外部依赖完全解耦
3. **扩展性优秀**：新增 Provider/Tool 成本低
4. **测试友好**：架构天然支持 Mock 和 Fake

### 需要改进

1. **context 概念混淆**：需要明确区分"会话上下文"和"项目上下文"
2. **文档深度不足**：缺少安全策略和架构图
3. **无实际代码**：无法验证架构决策的可执行性

### 最终建议

| 决策 | 建议 |
|------|------|
| 是否继续当前架构 | **是**，架构设计优秀 |
| 最优先修复 | H1（context 混淆） |
| 最优先实现 | P0 接口定义 + index.ts |
| 风险最高点 | 危险命令拦截逻辑 |

---

**审核完成**

**审核日期**：2026-06-24
**Verdict**：WARNING — 项目处于骨架阶段，建议优先完成 P0 任务后再进行大规模开发。当前架构设计优秀，但需解决 context 混淆问题以确保长期可维护性。
