# MozilCode 架构审核报告

> 审核日期：2026-06-24
> 审核范围：PRD-MVP(1).md 与代码结构一致性检查

---

## 审核摘要

本审核基于产品需求文档定义的核心结构、依赖约束和模块职责，对项目进行了全面的架构检查。

**当前项目状态**：项目处于初始化阶段，仅包含目录结构和 README 文档规划，尚未实现任何业务代码。

**总体评价**：架构设计思路清晰，采用 Ports and Adapters（六边形）架构模式符合现代 TypeScript 项目的最佳实践。但存在结构不完整、职责边界模糊和文档缺失三类需要关注的问题。

---

## 1. 结构完整性

### 1.1 PRD 要求 vs 实际实现

| PRD 要求的文件 | 实际状态 |
|---------------|---------|
| `src/core/agent-loop.ts` | 仅 README 规划 |
| `src/core/context-manager.ts` | 仅 README 规划 |
| `src/core/message-manager.ts` | 仅 README 规划 |
| `src/core/event-bus.ts` | 仅 README 规划 |
| `src/core/tool-registry.ts` | 仅 README 规划 |
| `src/core/ports/llm.port.ts` | 仅 README 规划 |
| `src/core/ports/tool.port.ts` | 仅 README 规划 |
| `src/providers/openai.provider.ts` | 仅 README 规划 |
| `src/tools/local-file.tool.ts` | 仅 README 规划 |
| `src/tools/local-shell.tool.ts` | 仅 README 规划 |
| `src/tools/code-grep.tool.ts` | 仅 README 规划 |
| `src/adapters/tui/input.ts` | 仅 README 规划 |
| `src/adapters/tui/renderer.ts` | 仅 README 规划 |
| `src/adapters/tui/confirm.ts` | 仅 README 规划 |
| `src/index.ts` | **缺失** |

**发现问题**：
- 所有业务代码文件均未实现
- 缺少 `src/index.ts` 入口文件

### 1.2 多余/额外目录

以下目录在 PRD 中未规划，但有合理的 README 说明：

| 目录 | 状态 | 说明 |
|-----|------|-----|
| `src/context/` | 可接受 | README 明确定义为未来扩展点 |
| `src/memory/` | 可接受 | README 标注 MVP 不实现 |
| `src/auth/` | 可接受 | README 标注 MVP 不实现 |
| `src/store/` | 可接受 | UI 状态管理需求合理 |

---

## 2. 职责对应性

### 2.1 核心发现

| 问题 | 严重程度 | 描述 |
|-----|---------|-----|
| context 目录职责重叠 | HIGH | 两者都包含"上下文"相关能力，边界不清晰 |

### 2.2 context 目录与 context-manager.ts 职责混淆

**PRD Section 7.2 定义 context-manager.ts 职责**：
- 组装系统提示词
- 注入当前工作目录信息
- 注入最近对话历史
- 控制上下文长度

**src/context/README.md 定义职责**：
- 代码搜索
- AST 分析
- 文档分块
- RAG 索引
- 提取项目结构摘要

**问题分析**：
`src/context/` 目录定义的职责（grep、AST、RAG）与 PRD 中 `context-manager.ts` 的职责（上下文组装）存在概念混淆。两者都包含"上下文"相关能力，但边界不清晰。

### 2.3 ports 接口完整性

| port 接口 | 规划状态 |
|----------|---------|
| `llm.port.ts` | 仅 README，无代码 |
| `tool.port.ts` | 仅 README，无代码 |
| `confirmation.port.ts` | 仅 README 提及，PRD 未定义 |

---

## 3. 依赖边界

### 3.1 README 定义的依赖方向

```
推荐依赖方向：
adapters -> core -> ports
providers -> core/ports
tools -> core/ports

禁止依赖方向：
core -> adapters
core -> providers
core -> tools 具体实现
core -> store
```

### 3.2 检查结果

**通过**：
- 目录结构符合依赖方向约束
- core 依赖 ports，无反向依赖
- adapters、providers、tools 都有各自的 README 边界定义

**潜在风险**：
- 由于无实际代码，无法验证编译时依赖边界
- `src/index.ts` 缺失导致"组装所有模块"的职责无法落地

---

## 4. 安全性

### 4.1 安全边界规划

`tools/README.md` 规划了以下安全边界：
- 工具不能访问工作区外路径
- 写操作必须经过确认
- Shell 命令必须经过确认
- 危险命令需要拦截或二次确认
- 工具输出需要截断

### 4.2 检查结果

**规划完整性**：安全边界有规划但未文档化

| 检查项 | 状态 |
|-------|------|
| 文件操作路径限制 | 仅 README 提及 |
| Shell 危险命令拦截 | 仅 README 提及 |
| 路径越界防护 | 仅 README 提及 |
| 确认机制设计 | 仅 README 提及 |

---

## 5. 可测试性

### 5.1 测试架构设计

`tests/README.md` 和 `tests/core/README.md` 定义了良好的测试策略：
- 使用 Fake LLM、Fake Tools、Fake Confirmation
- 使用内存 EventBus
- 工具测试使用临时目录

### 5.2 检查结果

**架构支持度**：
- Ports and Adapters 架构天然支持依赖注入和 mock
- core 层不依赖具体实现，易于隔离测试
- 测试目录结构规划合理

---

## 6. 架构质量评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 模块化 | 4/5 | Ports and Adapters 模式清晰，边界明确 |
| 可扩展性 | 4/5 | Provider 和 Tool 通过 port 解耦，新增成本低 |
| 可测试性 | 4/5 | 架构支持依赖注入，但需验证 port 接口设计 |
| 安全性 | 3/5 | 有规划但文档不完整，缺少具体防护策略 |
| 文档完整性 | 2/5 | README 较完整，但安全文档缺失 |

**平均分：3.4/5**

---

## 7. 问题汇总

### HIGH（强烈建议修复）

| # | 问题 | 位置 | 说明 |
|---|-----|------|------|
| H1 | 所有业务代码文件缺失 | src/ | 包括 core/*.ts、ports/*.ts、tools/*.ts 等 15+ 个文件 |
| H2 | 缺少 index.ts 入口文件 | src/index.ts | README 定义了"组装所有模块"职责 |
| H3 | context 目录与 context-manager.ts 职责混淆 | src/context/ vs core/ | 两者都包含"上下文"相关能力，边界不清晰 |

### MEDIUM（建议优化）

| # | 问题 | 位置 | 说明 |
|---|-----|------|------|
| M1 | 安全文档缺失 | docs/ | 需要创建安全策略文档 |
| M2 | confirmation.port.ts 定义不明确 | core/ports/ | README 提及但 PRD 未规划 |
| M3 | 危险命令拦截策略未规划 | tools/ | 仅描述需要拦截，未定义实现方式 |

---

## 8. 改进建议

### 优先级 P0

**创建核心 port 接口**

```typescript
// src/core/ports/llm.port.ts
export interface AgentMessage {
  role: 'user' | 'assistant' | 'tool'
  content: string
  toolCalls?: ToolCall[]
}

export interface ToolCall {
  id: string
  name: string
  args: Record<string, unknown>
}

export interface LLMProvider {
  generate(messages: AgentMessage[]): Promise<LLMResponse>
}
```

### 优先级 P1

**解决 context 职责混淆**：建议重命名 `src/context/` 为 `src/project-context/` 以区分会话上下文和项目上下文。

### 优先级 P2

**创建安全策略文档**：明确路径边界、危险命令拦截策略、输出截断规则。

---

## 9. 总结

**优点**：
- 架构模式选择得当（六边形架构）
- 依赖边界定义清晰
- 模块职责划分合理
- 测试策略设计良好

**不足**：
- 项目处于极早期阶段，无实际代码
- 存在职责边界模糊问题
- 必要文档缺失

### 建议执行顺序

| 阶段 | 任务 | 优先级 |
|------|------|--------|
| 1 | 创建 core/ports 接口定义 | P0 |
| 2 | 创建 core 核心模块实现 | P0 |
| 3 | 创建 src/index.ts 入口 | P0 |
| 4 | 解决 context 职责混淆 | P1 |
| 5 | 创建安全策略文档 | P2 |

---

**审核完成时间**：2026-06-24
**审核范围**：项目初始化阶段架构设计
**建议 Verdict**：WARNING - 需要优先解决 H1、H2、H3 问题后再进行开发
