# MozilCode MVP 实现建议报告

> **报告日期**：2026-06-24
> **基于**：架构审核报告 v2.0
> **审核状态**：REQUEST CHANGES - 修复 2 个 CRITICAL 问题后可通过

---

## 审核结论

| 严重程度 | 数量 | 状态 |
|----------|------|------|
| CRITICAL | 2 | 必须修复 |
| HIGH | 4 | 强烈建议修复 |
| MEDIUM | 3 | 建议优化 |
| LOW | 2 | 可选 |

---

## 一、MVP 骨架文件清单（调整后）

### P0 优先级文件

```
src/
├── index.ts                              # 项目入口/依赖组装
├── core/
│   ├── ports/
│   │   ├── llm.port.ts                   # LLM Provider 接口
│   │   ├── tool.port.ts                 # Tool 接口
│   │   ├── confirmation.port.ts          # 确认机制接口
│   │   ├── event-bus.port.ts             # 事件总线接口 ← 新增
│   │   └── index.ts
│   ├── agent-loop.ts                     # Agent 主循环
│   ├── context-manager.ts               # 会话上下文管理
│   ├── message-manager.ts               # 消息管理器
│   ├── event-bus.ts                     # 事件总线实现
│   └── tool-registry.ts                 # 工具注册表
├── providers/
│   ├── base.provider.ts                   # Provider 基类
│   ├── vercel-ai.provider.ts             # Vercel AI 实现 ← 新增
│   ├── openai.provider.ts               # OpenAI 实现
│   └── index.ts
├── tools/
│   ├── base.tool.ts                     # Tool 基类
│   ├── file-read.tool.ts                # 文件读取
│   ├── file-write.tool.ts              # 文件写入
│   ├── shell.tool.ts                   # Shell 执行
│   ├── search.tool.ts                   # 代码搜索
│   └── index.ts
├── adapters/
│   ├── tui/
│   │   ├── index.ts
│   │   └── tui.adapter.ts
│   └── gui/
│       └── index.ts
├── security/
│   ├── path-validator.ts               # 路径验证 ← 新增
│   ├── command-scanner.ts               # 命令扫描
│   ├── output-truncator.ts             # 输出截断
│   └── index.ts
└── types/
    └── index.ts
```

### 测试骨架文件

```
tests/
├── README.md                            # 测试规范 ← 新增
├── fakes/
│   ├── index.ts
│   ├── fake-llm.provider.ts
│   ├── fake-tool.ts
│   ├── fake-confirmation.ts
│   └── fake-event-bus.ts
├── unit/
│   ├── agent-loop.test.ts
│   ├── context-manager.test.ts
│   ├── message-manager.test.ts
│   └── tool-registry.test.ts
└── integration/
    └── full-loop.test.ts
```

---

## 二、接口设计建议

### 2.1 LLM Port

```typescript
// src/core/ports/llm.port.ts

export type MessageRole = 'system' | 'user' | 'assistant' | 'tool'

export interface AgentMessage {
  id: string
  role: MessageRole
  content: string
  toolCalls?: ToolCall[]
  toolCallId?: string
  timestamp: number
}

export interface ToolCall {
  id: string
  type: 'function'
  function: {
    name: string
    arguments: string // JSON string
  }
}

export interface LLMResponse {
  id: string
  content: string
  toolCalls?: ToolCall[]
  finishReason: 'stop' | 'length' | 'tool_calls' | 'error'
  usage?: { promptTokens: number; completionTokens: number; totalTokens: number }
}

export interface LLMProviderPort {
  readonly config: LLMProviderConfig
  readonly modelName: string
  generate(messages: AgentMessage[]): Promise<LLMResponse>
  getModel(): string
  isConfigured(): boolean
  getMaxTokens(): number
}
```

### 2.2 Tool Port

```typescript
// src/core/ports/tool.port.ts

export type RiskLevel = 'none' | 'low' | 'medium' | 'high' | 'critical'

export interface ToolContext {
  workspaceRoot: string
  workingDirectory: string
  env: Record<string, string>
  sessionId: string
}

export interface ToolResult {
  success: boolean
  content: string
  error?: string
  executionTime?: number
}

export interface AgentToolDefinition {
  name: string
  description: string
  parameters: {
    type: 'object'
    properties: Record<string, ToolParameterProperty>
    required?: string[]
  }
}

export interface AgentToolPort {
  readonly definition: AgentToolDefinition
  readonly riskLevel: RiskLevel
  readonly category: 'file' | 'shell' | 'search' | 'memory' | 'other'
  execute(args: Record<string, unknown>, context: ToolContext): Promise<ToolResult>
  validateArgs?(args: unknown): boolean
}
```

### 2.3 Confirmation Port

```typescript
// src/core/ports/confirmation.port.ts

export type ConfirmationType = 'write_file' | 'delete_file' | 'run_shell' | 'multi_file'
export type ConfirmationResult = 'approved' | 'denied' | 'cancelled' | 'trust_all'

export interface ConfirmationRequest {
  id: string
  type: ConfirmationType
  targets: string[]
  riskLevel: RiskLevel
  description: string
  timestamp: number
}

export interface ConfirmationPort {
  requestConfirmation(request: ConfirmationRequest): Promise<ConfirmationResult>
  requiresConfirmation(request: ConfirmationRequest): boolean
  requestBatchConfirmation(requests: ConfirmationRequest[]): Promise<ConfirmationResult[]>
}
```

### 2.4 Event Bus Port

```typescript
// src/core/ports/event-bus.port.ts ← 新增

export type EventType =
  | 'agent.thinking'
  | 'agent.tool_call'
  | 'agent.tool_result'
  | 'agent.response'
  | 'agent.error'
  | 'agent.confirm_request'
  | 'agent.confirm_result'

export interface AgentEvent<T = unknown> {
  type: EventType
  payload: T
  timestamp: number
}

export type EventHandler<T = unknown> = (event: AgentEvent<T>) => void | Promise<void>

export interface EventBusPort {
  emit<T>(event: AgentEvent<T>): void
  on<T>(type: EventType, handler: EventHandler<T>): () => void
  off<T>(type: EventType, handler: EventHandler<T>): void
}
```

---

## 三、安全边界实现

### 3.1 路径验证器

```typescript
// src/security/path-validator.ts

export class PathValidator {
  private allowedRoots: string[]
  private blockedPatterns: RegExp[]

  constructor(workspaceRoot: string) {
    this.allowedRoots = [workspaceRoot]
    this.blockedPatterns = [
      /^\/etc/i, /^\/sys/i, /^\/proc/i,
      /\.env$/i, /\.git\/config$/i,
      /node_modules/
    ]
  }

  validate(path: string): PathValidationResult {
    const absolutePath = this.resolvePath(path)
    const realPath = this.resolveSymlinks(absolutePath)

    const isInAllowedRoot = this.allowedRoots.some(
      root => realPath.startsWith(root)
    )
    const isBlocked = this.blockedPatterns.some(
      pattern => pattern.test(realPath)
    )

    return {
      valid: isInAllowedRoot && !isBlocked,
      resolvedPath: realPath,
      reason: isBlocked ? 'BLOCKED_PATTERN'
           : !isInAllowedRoot ? 'OUTSIDE_WORKSPACE'
           : 'VALID'
    }
  }

  private resolveSymlinks(path: string): string {
    // 递归解析符号链接
    return path
  }
}
```

### 3.2 命令扫描器（增强版）

```typescript
// src/security/command-scanner.ts

export type RiskLevel = 'auto_deny' | 'high' | 'medium' | 'low'

export interface ScanResult {
  riskLevel: RiskLevel
  reason: string
  matchedPattern?: string
}

export class CommandScanner {
  private readonly AUTO_DENY_PATTERNS = [
    /rm\s+-rf\s+(\/|--no-preserve-root)/,
    /dd\s+if\s*=/,
    /mkfs\s+/,
  ]

  private readonly HIGH_RISK_PATTERNS = [
    /chmod\s+-R\s+777/,
    /chown\s+/,
    /git\s+reset\s+--hard/,
    /git\s+force-push/,
  ]

  private readonly DANGEROUS_OPERATORS = ['&&', '||', '|', ';', '>', '>>']

  scan(command: string): ScanResult {
    // 1. 检查自动拒绝
    for (const pattern of this.AUTO_DENY_PATTERNS) {
      if (pattern.test(command)) {
        return { riskLevel: 'auto_deny', reason: '危险命令已被拦截', matchedPattern: pattern.source }
      }
    }

    // 2. 检查高风险
    for (const pattern of this.HIGH_RISK_PATTERNS) {
      if (pattern.test(command)) {
        return { riskLevel: 'high', reason: '高风险命令', matchedPattern: pattern.source }
      }
    }

    // 3. 检查危险操作符
    const tokens = command.split(/\s+/)
    for (const op of this.DANGEROUS_OPERATORS) {
      if (tokens.includes(op)) {
        return { riskLevel: 'medium', reason: `包含危险操作符: ${op}` }
      }
    }

    return { riskLevel: 'low', reason: '命令安全' }
  }
}
```

---

## 四、实现优先级

### 调整后的执行顺序

| 阶段 | 任务 | 优先级 | 说明 |
|------|------|--------|------|
| 0.5 | 更新 package.json（添加 vitest） | P0 | 修复 C2 |
| 0.5 | 创建 tests/ 目录结构 | P0 | 为覆盖率奠基 |
| 1 | 创建 `event-bus.port.ts` | P0 | 修复 C1 |
| 1 | 创建 `vercel-ai.provider.ts` | P0 | 匹配 README |
| 2 | 实现 core 核心模块 | P0 | Day 2-3 |
| 3 | 实现 security 模块 | P1 | Day 4 |
| 4 | 实现 tools 模块 | P1 | Day 4-5 |
| 5 | 实现 providers 模块 | P1 | Day 4-5 |
| 6 | 实现 adapters 模块 | P2 | Day 6-8 |
| 7 | 补充文档 | P2 | Day 6-8 |

### 并行任务组

**并行组 A**（Day 1）：
- 创建所有 ports 接口文件（含 event-bus.port.ts）
- 更新 package.json
- 创建 tests/ 目录结构

**并行组 B**（Day 2-3）：
- 实现 event-bus.ts
- 实现 message-manager.ts
- 实现 context-manager.ts
- 实现 tool-registry.ts
- 实现 agent-loop.ts

**并行组 C**（Day 4-5）：
- 实现 vercel-ai.provider.ts / openai.provider.ts
- 实现所有 tools/*.tool.ts
- 实现 security 模块

---

## 五、需要修复的问题

### CRITICAL 必须修复

| # | 问题 | 解决方案 |
|---|------|----------|
| C1 | `event-bus.port.ts` 在接口设计中定义但未列入文件清单 | 创建 `src/core/ports/event-bus.port.ts` |
| C2 | package.json 缺少测试依赖 | 添加 vitest 和覆盖率工具 |

### HIGH 强烈建议修复

| # | 问题 | 解决方案 |
|---|------|----------|
| H1 | CommandScanner 无法检测所有 shell 注入 | 增加操作符检测和 token 化解析 |
| H2 | shell.tool.ts 耦合方式未定义 | 通过依赖注入解耦 `CommandScanner` |
| H3 | 缺少 tests/ 目录结构定义 | 创建 `tests/README.md` 和 Fake 实现 |
| H4 | vercel-ai.provider.ts 在 README 提到但未列入清单 | 创建 `src/providers/vercel-ai.provider.ts` |

---

## 六、风险提示

| 风险点 | 影响 | 缓解措施 |
|--------|------|----------|
| CommandScanner 无法检测所有 shell 注入 | HIGH | 优先实现命令数组模式 (避免 shell 解析) |
| context 模块命名冲突 | MEDIUM | MVP 阶段可忽略，Phase 2 再重构 |

---

## 七、快速启动检查清单

### Day 1 交付物

- [ ] `src/core/ports/llm.port.ts`
- [ ] `src/core/ports/tool.port.ts`
- [ ] `src/core/ports/confirmation.port.ts`
- [ ] `src/core/ports/event-bus.port.ts` ← 新增
- [ ] `src/core/ports/index.ts`
- [ ] `src/types/index.ts`
- [ ] 更新 `package.json`（添加 vitest）← 新增
- [ ] 创建 `tests/` 目录结构 ← 新增
- [ ] TypeScript 编译验证通过

### Day 2-3 交付物

- [ ] `src/index.ts`
- [ ] `src/core/event-bus.ts`
- [ ] `src/core/message-manager.ts`
- [ ] `src/core/context-manager.ts`
- [ ] `src/core/tool-registry.ts`
- [ ] `src/core/agent-loop.ts`

### Day 4-5 交付物

- [ ] `src/providers/vercel-ai.provider.ts` ← 新增
- [ ] `src/providers/openai.provider.ts`
- [ ] `src/tools/base.tool.ts`
- [ ] `src/tools/file-read.tool.ts`
- [ ] `src/tools/file-write.tool.ts`
- [ ] `src/tools/shell.tool.ts`
- [ ] `src/security/path-validator.ts`
- [ ] `src/security/command-scanner.ts`（增强版）

### Day 6-8 交付物

- [ ] `src/adapters/tui/tui.adapter.ts`
- [ ] `docs/SECURITY.md`
- [ ] `vitest.config.ts`
- [ ] 完整测试覆盖报告（目标 80%+）

---

**审核日期**：2026-06-24
**Verdict**：REQUEST CHANGES — 修复 2 个 CRITICAL 问题后可通过
