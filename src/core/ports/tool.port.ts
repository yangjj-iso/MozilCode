/**
 * Tool Port - core 与具体工具实现之间的接口契约
 *
 * core 只依赖这个接口，不依赖任何具体工具。
 * tools/ 下的实现（file-read/file-write/shell/search）实现这个接口。
 */

import type { ToolDefinition } from './llm.port.js'

// ===== 工具执行上下文 =====
export interface ToolExecutionContext {
  /** 工作区根目录（用于路径校验） */
  cwd: string
  /** 中断信号 */
  signal?: AbortSignal
  /** 请求用户确认（高风险操作） */
  requestConfirm?: (req: ToolConfirmRequest) => Promise<ToolConfirmResult>
}

export interface ToolConfirmRequest {
  toolName: string
  args: Record<string, unknown>
  description: string
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
}

export interface ToolConfirmResult {
  approved: boolean
  reason?: string
}

// ===== 工具执行结果 =====
export interface ToolExecutionResult {
  success: boolean
  content: string
  error?: string
  executionTimeMs?: number
}

// ===== Tool Port =====
export interface AgentToolPort {
  /** 工具名（唯一标识，如 "read_file"） */
  readonly name: string

  /** 工具描述（给 LLM 看，决定何时调用） */
  readonly description: string

  /** JSON Schema 参数定义（给 LLM 看，决定怎么调用） */
  readonly parameters: Record<string, unknown>

  /** 是否只读（只读工具可并行执行，写工具串行） */
  readonly readonly: boolean

  /** 风险等级（决定是否需要用户确认） */
  readonly riskLevel: 'low' | 'medium' | 'high' | 'critical'

  /** 执行工具 */
  execute(
    args: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<ToolExecutionResult>
}

// ===== 辅助：把 AgentToolPort 转成 LLM 的 ToolDefinition =====
export function toolToDefinition(tool: AgentToolPort): ToolDefinition {
  return {
    type: 'function',
    function: {
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
    },
  }
}
