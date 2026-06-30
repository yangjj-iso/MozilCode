/**
 * 最小 Agent Loop - 连接 LLM Provider 和 TUI
 * 后续逐步演进为完整的状态机版本
 */

import type { LLMProviderPort, AgentMessage } from '../../core/ports/llm.port.js'
import type { ChatMessage } from './types.js'

export interface AgentLoopDeps {
  provider: LLMProviderPort
}

export interface AgentLoopOptions {
  signal?: AbortSignal
}

export interface AgentLoopEvent {
  type: 'stream_delta' | 'stream_end' | 'error'
  delta?: string
  fullText?: string
  error?: string
}

export class MiniAgentLoop {
  private messages: AgentMessage[] = []

  constructor(private deps: AgentLoopDeps) {}

  /** 发送用户消息，流式返回响应 */
  async *sendMessage(
    userText: string,
    options?: AgentLoopOptions
  ): AsyncGenerator<AgentLoopEvent> {
    // 添加用户消息
    const userMsg: AgentMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: userText,
      timestamp: Date.now(),
    }
    this.messages.push(userMsg)

    const systemPrompt = `你是 MozilCode，一个运行在用户本地终端的 AI 编程助手。
你帮助用户理解代码、修改文件、执行命令、调试问题。
请用简洁的中文回答。`

    let fullText = ''

    try {
      for await (const chunk of this.deps.provider.generateStream({
        messages: this.messages,
        systemPrompt,
        signal: options?.signal,
      })) {
        if (options?.signal?.aborted) break

        if (chunk.delta) {
          fullText += chunk.delta
          yield { type: 'stream_delta', delta: chunk.delta }
        }
      }

      // 添加 assistant 消息到历史
      this.messages.push({
        id: `msg-${Date.now()}`,
        role: 'assistant',
        content: fullText,
        timestamp: Date.now(),
      })

      yield { type: 'stream_end', fullText }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : String(err)
      yield { type: 'error', error: errorMsg }
    }
  }

  /** 清空对话历史 */
  clearHistory(): void {
    this.messages = []
  }

  /** 获取历史消息数 */
  get historyLength(): number {
    return this.messages.length
  }
}
