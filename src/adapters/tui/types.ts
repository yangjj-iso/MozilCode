/**
 * TUI 共享类型定义
 */

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool'

export interface ToolCall {
  id: string
  name: string
  args: Record<string, unknown>
  argsDisplay: string // 工具调用的可读参数（如文件路径、命令）
}

export type ToolStatus = 'pending' | 'running' | 'success' | 'error' | 'denied'

export interface ToolResult {
  toolCallId: string
  success: boolean
  content: string
  error?: string
  executionTime?: number
}

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  toolCalls?: ToolCall[]
  toolResults?: ToolResult[]
  timestamp: number
  streaming?: boolean
}

export type AgentState = 'idle' | 'thinking' | 'calling-llm' | 'executing-tools' | 'completed' | 'error'

export type PermissionMode = 'default' | 'plan' | 'auto' | 'accept-edits'

export interface PlanStep {
  id: string
  title: string
  status: 'pending' | 'in-progress' | 'completed' | 'failed'
  detail?: string
}

export interface PlanInfo {
  title: string
  steps: PlanStep[]
  savedAt: string
  filePath: string
}

export interface ConfirmRequest {
  id: string
  type: 'write_file' | 'delete_file' | 'run_shell' | 'multi_file'
  toolName: string
  targets: string[]
  description: string
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
}

export interface StatusInfo {
  model: string
  mode: PermissionMode
  cwd: string
  contextUsed: number // 百分比
  cost: number // 美元
  turn: number
}
