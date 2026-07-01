/**
 * LLM Provider Port - core 与 LLM 服务之间的接口契约
 *
 * core 只依赖这个接口，不依赖任何具体 SDK。
 * providers/ 下的实现（StepFun/OpenAI/Vercel AI）实现这个接口。
 */

// ===== 消息类型 =====
export type MessageRole = 'system' | 'user' | 'assistant' | 'tool'

export interface ToolCallFunction {
  name: string
  arguments: string // JSON string
}

export interface ToolCall {
  id: string
  type: 'function'
  function: ToolCallFunction
}

export interface AgentMessage {
  id: string
  role: MessageRole
  content: string
  toolCalls?: ToolCall[]
  toolCallId?: string // role='tool' 时关联的 tool_call id
  timestamp: number
}

// ===== LLM 请求/响应 =====
export interface ToolDefinition {
  type: 'function'
  function: {
    name: string
    description: string
    parameters: Record<string, unknown> // JSON Schema
  }
}

export interface LLMRequest {
  messages: AgentMessage[]
  systemPrompt?: string
  tools?: ToolDefinition[]
  temperature?: number
  maxTokens?: number
  signal?: AbortSignal
}

export interface LLMUsage {
  promptTokens: number
  completionTokens: number
  totalTokens: number
}

export interface LLMResponse {
  content: string
  toolCalls?: ToolCall[]
  finishReason: 'stop' | 'length' | 'tool_calls' | 'error'
  usage?: LLMUsage
}

// ===== 流式 chunk =====
export interface LLMStreamChunk {
  delta?: string
  reasoningDelta?: string
  toolCall?: ToolCall
  finishReason?: 'stop' | 'length' | 'tool_calls'
}

// ===== LLM Provider Port =====
export interface LLMProviderPort {
  readonly modelName: string

  /** 流式生成，逐 chunk yield */
  generateStream(request: LLMRequest): AsyncIterable<LLMStreamChunk>

  /** 非流式生成（内部可由流式聚合实现） */
  generate(request: LLMRequest): Promise<LLMResponse>

  /** 是否已配置（有 API key 等） */
  isConfigured(): boolean
}
