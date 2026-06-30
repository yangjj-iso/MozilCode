/**
 * StepFun LLM Provider
 *
 * 基于 OpenAI 兼容协议，用原生 fetch 实现，不依赖外部 SDK。
 * 端点：https://api.stepfun.com/step_plan/v1/chat/completions
 */

import type {
  LLMProviderPort,
  LLMRequest,
  LLMResponse,
  LLMStreamChunk,
  AgentMessage,
  ToolCall,
  ToolDefinition,
} from '../core/ports/llm.port.js'

export interface StepFunConfig {
  apiKey: string
  baseUrl: string // https://api.stepfun.com/step_plan/v1
  model: string // step-3.7-flash
}

interface OpenAIMessage {
  role: string
  content: string
  tool_calls?: Array<{
    id: string
    type: 'function'
    function: { name: string; arguments: string }
  }>
  tool_call_id?: string
}

interface OpenAIStreamDelta {
  content?: string
  tool_calls?: Array<{
    index: number
    id?: string
    type?: 'function'
    function?: { name?: string; arguments?: string }
  }>
}

export class StepFunProvider implements LLMProviderPort {
  readonly modelName: string
  private config: StepFunConfig

  constructor(config: StepFunConfig) {
    this.config = config
    this.modelName = config.model
  }

  isConfigured(): boolean {
    return Boolean(this.config.apiKey && this.config.baseUrl && this.config.model)
  }

  /** 流式生成 */
  async *generateStream(request: LLMRequest): AsyncIterable<LLMStreamChunk> {
    const body = this.buildRequestBody(request, true)
    const url = `${this.config.baseUrl}/chat/completions`

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.config.apiKey}`,
      },
      body: JSON.stringify(body),
      signal: request.signal,
    })

    if (!response.ok) {
      const errText = await response.text()
      // 400 错误时打印请求体到 stderr，便于调试
      if (response.status === 400) {
        console.error('[stepfun] 400 error - request body:')
        console.error(JSON.stringify(body, null, 2))
      }
      throw new Error(`StepFun API ${response.status}: ${errText}`)
    }

    if (!response.body) {
      throw new Error('StepFun API: no response body')
    }

    // 解析 SSE 流
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    const toolCallMap = new Map<number, ToolCall>() // index -> partial tool call

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed || !trimmed.startsWith('data:')) continue

          const data = trimmed.slice(5).trim()
          if (data === '[DONE]') return

          try {
            const json = JSON.parse(data)
            const choice = json.choices?.[0]
            if (!choice) continue

            const delta: OpenAIStreamDelta = choice.delta || {}

            // 文本 delta
            if (delta.content) {
              yield { delta: delta.content }
            }

            // tool_calls 增量
            if (delta.tool_calls) {
              for (const tc of delta.tool_calls) {
                const idx = tc.index
                if (!toolCallMap.has(idx)) {
                  toolCallMap.set(idx, {
                    id: tc.id || `call-${idx}`,
                    type: 'function',
                    function: {
                      name: tc.function?.name || '',
                      arguments: tc.function?.arguments || '',
                    },
                  })
                } else {
                  const existing = toolCallMap.get(idx)!
                  if (tc.function?.name) existing.function.name += tc.function.name
                  if (tc.function?.arguments) existing.function.arguments += tc.function.arguments
                  if (tc.id) existing.id = tc.id
                }
              }
            }

            // finish_reason
            if (choice.finish_reason) {
              // 流结束时 yield 完整的 tool_calls
              for (const tc of toolCallMap.values()) {
                yield { toolCall: tc }
              }
              yield { finishReason: choice.finish_reason }
            }
          } catch {
            // 忽略解析失败的行
          }
        }
      }
    } finally {
      reader.cancel()
    }
  }

  /** 非流式生成（聚合流式结果） */
  async generate(request: LLMRequest): Promise<LLMResponse> {
    let content = ''
    const toolCalls: ToolCall[] = []
    let finishReason: LLMResponse['finishReason'] = 'stop'

    for await (const chunk of this.generateStream(request)) {
      if (chunk.delta) content += chunk.delta
      if (chunk.toolCall) toolCalls.push(chunk.toolCall)
      if (chunk.finishReason) {
        finishReason = chunk.finishReason as LLMResponse['finishReason']
      }
    }

    return {
      content,
      toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
      finishReason,
    }
  }

  /** 构建请求体（OpenAI 兼容格式） */
  private buildRequestBody(
    request: LLMRequest,
    stream: boolean
  ): Record<string, unknown> {
    const messages: OpenAIMessage[] = []

    // system prompt
    if (request.systemPrompt) {
      messages.push({ role: 'system', content: request.systemPrompt })
    }

    // 历史消息
    for (const msg of request.messages) {
      const openaiMsg: OpenAIMessage = {
        role: msg.role,
        content: msg.content,
      }
      if (msg.toolCalls && msg.toolCalls.length > 0) {
        openaiMsg.tool_calls = msg.toolCalls.map(tc => ({
          id: tc.id,
          type: 'function',
          function: { name: tc.function.name, arguments: tc.function.arguments },
        }))
        // 有 tool_calls 时 content 设为 null（OpenAI 标准）
        // 但 StepFun 可能不接受 null，用空字符串
        if (!openaiMsg.content) {
          openaiMsg.content = ''
        }
      }
      if (msg.toolCallId) {
        openaiMsg.tool_call_id = msg.toolCallId
        // tool 结果消息 content 不能为空
        if (!openaiMsg.content) {
          openaiMsg.content = '(no output)'
        }
      }
      messages.push(openaiMsg)
    }

    const body: Record<string, unknown> = {
      model: this.config.model,
      messages,
      stream,
    }

    if (request.tools && request.tools.length > 0) {
      body.tools = request.tools.map((t: ToolDefinition) => ({
        type: 'function',
        function: {
          name: t.function.name,
          description: t.function.description,
          parameters: t.function.parameters,
        },
      }))
    }

    if (request.temperature !== undefined) {
      body.temperature = request.temperature
    }
    if (request.maxTokens !== undefined) {
      body.max_tokens = request.maxTokens
    }

    return body
  }
}

/** 从环境变量创建 StepFun Provider */
export function createStepFunProviderFromEnv(): StepFunProvider {
  const apiKey = process.env.STEPFUN_API_KEY || ''
  const baseUrl = process.env.STEPFUN_BASE_URL || 'https://api.stepfun.com/step_plan/v1'
  const model = process.env.STEPFUN_MODEL || 'step-3.7-flash'
  return new StepFunProvider({ apiKey, baseUrl, model })
}
