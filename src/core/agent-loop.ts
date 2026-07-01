/**
 * Agent Loop - 核心循环
 *
 * 显式状态机实现，借鉴 cc-haha 的设计但简化：
 * - 不用 while(true)+7 continue，用 switch(state) 显式状态机
 * - 每个 transition 带 reason，便于测试断言
 * - 父子 AbortController（父=整个 run，子=单轮 LLM 调用）
 * - 工具分区并行（只读并行，写串行）
 * - 中断时为未完成 tool_call 合成 tool_result（否则 API 报错）
 *
 * 状态流转：
 *   IDLE → PREPARING → STREAMING → DECIDING
 *     ├─ stop → DONE
 *     ├─ tool_calls → EXECUTING_TOOLS → FEEDBACK → PREPARING（循环）
 *     ├─ length → COMPRESSING → PREPARING（重试）
 *     └─ error → ERROR_RECOVERY → PREPARING / ABORTING
 *
 * 任何状态都可被 user_cancel → ABORTING → DONE
 */

import type {
  LLMProviderPort,
  AgentMessage,
  ToolCall,
  LLMStreamChunk,
} from './ports/llm.port.js'
import type { ToolRegistry } from './tool-registry.js'
import type { ToolExecutionContext } from './ports/tool.port.js'

// ===== 状态机 =====
export type LoopState =
  | 'IDLE'
  | 'PREPARING'
  | 'STREAMING'
  | 'DECIDING'
  | 'EXECUTING_TOOLS'
  | 'FEEDBACK'
  | 'COMPRESSING'
  | 'ERROR_RECOVERY'
  | 'ABORTING'
  | 'DONE'

// ===== transition reason（便于测试断言）=====
export type TransitionReason =
  | 'user_input'
  | 'request_ready'
  | 'stream_end'
  | 'stop'
  | 'tool_calls'
  | 'length'
  | 'error'
  | 'tools_done'
  | 'feedback_ready'
  | 'compressed'
  | 'compression_failed'
  | 'recovered'
  | 'unrecoverable'
  | 'user_cancel'
  | 'max_turns'

// ===== yield 给消费者的事件 =====
export type AgentEvent =
  | { type: 'state_change'; from: LoopState; to: LoopState; reason: TransitionReason; turn: number }
  | { type: 'stream_delta'; delta: string }
  | { type: 'reasoning_delta'; delta: string }
  | { type: 'stream_end'; content: string }
  | { type: 'tool_call_start'; toolCall: ToolCall; turn: number }
  | { type: 'tool_call_end'; toolCallId: string; result: string; isError: boolean; turn: number }
  | { type: 'error'; error: string; recoverable: boolean }
  | { type: 'turn_end'; turn: number }
  | { type: 'done'; content: string; turns: number }

// ===== 配置 =====
export interface AgentLoopConfig {
  provider: LLMProviderPort
  tools: ToolRegistry
  systemPrompt: string
  cwd: string
  maxTurns?: number
  maxRetries?: number
  /** 上下文 token 上限估算值，超过则在 PREPARING 阶段主动压缩 */
  maxContextTokens?: number
  /** 工具结果在 messages 中的最大字符数（超出则截断保留头尾） */
  maxToolResultChars?: number
  /** 是否打印状态转换日志（DEBUG 模式） */
  debug?: boolean
}

// ===== 运行选项 =====
export interface AgentRunOptions {
  signal?: AbortSignal
}

export class AgentLoop {
  private messages: AgentMessage[] = []
  private state: LoopState = 'IDLE'
  private turn = 0
  private retryCount = 0

  // 父 AbortController（整个 run）
  private parentAbort: AbortController | null = null
  // 外部 signal 监听
  private externalSignal?: AbortSignal
  private externalAbortListener: (() => void) | null = null

  // 单轮中间状态
  private currentContent = ''
  private currentToolCalls: ToolCall[] = []
  private currentFinishReason: 'stop' | 'length' | 'tool_calls' = 'stop'
  private lastErrorMessage = ''

  constructor(private config: AgentLoopConfig) {}

  /**
   * 运行 Agent Loop
   * @param userInput 用户输入
   * @param options 运行选项（signal 用于中断）
   */
  async *run(
    userInput: string,
    options?: AgentRunOptions
  ): AsyncGenerator<AgentEvent> {
    this.parentAbort = new AbortController()
    this.externalSignal = options?.signal

    // 监听外部 signal，传播到 parentAbort
    if (options?.signal) {
      if (options.signal.aborted) {
        this.parentAbort.abort()
      } else {
        this.externalAbortListener = () => this.parentAbort?.abort()
        options.signal.addEventListener('abort', this.externalAbortListener, { once: true })
      }
    }

    // 添加用户消息
    this.messages.push({
      id: `msg-${Date.now()}-user`,
      role: 'user',
      content: userInput,
      timestamp: Date.now(),
    })

    this.transition('IDLE', 'PREPARING', 'user_input')

    try {
      // 用局部变量避免 TS 控制流分析对 this.state 的过度窄化
      let running = true
      while (running) {
        const currentState: LoopState = this.getState()

        // 检查中断
        if (this.parentAbort.signal.aborted && currentState !== 'ABORTING' && currentState !== 'DONE') {
          this.transition(currentState, 'ABORTING', 'user_cancel')
          continue
        }

        // 检查最大轮次（0 = 不限制）
        const maxTurns = this.config.maxTurns ?? 0
        if (maxTurns > 0 && this.turn >= maxTurns && currentState !== 'ABORTING' && currentState !== 'DONE') {
          yield { type: 'error', error: 'max turns reached', recoverable: false }
          this.transition(currentState, 'DONE', 'max_turns')
          continue
        }

        if (currentState === 'DONE') {
          running = false
          break
        }

        try {
          switch (currentState) {
            case 'PREPARING':
              this.handlePreparing()
              break
            case 'STREAMING':
              yield* this.handleStreaming()
              break
            case 'DECIDING':
              this.handleDeciding()
              break
            case 'EXECUTING_TOOLS':
              yield* this.handleExecutingTools()
              break
            case 'FEEDBACK':
              yield* this.handleFeedback()
              break
            case 'COMPRESSING':
              this.handleCompressing()
              break
            case 'ERROR_RECOVERY':
              yield* this.handleErrorRecovery()
              break
            case 'ABORTING':
              yield* this.handleAborting()
              break
            default:
              this.transition(currentState, 'ERROR_RECOVERY', 'error')
          }
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err)
          this.lastErrorMessage = msg
          yield { type: 'error', error: msg, recoverable: true }
          const s = this.getState()
          if (s !== 'ABORTING' && s !== 'DONE') {
            this.transition(s, 'ERROR_RECOVERY', 'error')
          }
        }
      }

      // 最终输出
      const finalContent = this.getLastAssistantContent()
      yield { type: 'done', content: finalContent, turns: this.turn }
    } finally {
      // 清理 signal 监听
      if (this.externalAbortListener && this.externalSignal) {
        this.externalSignal.removeEventListener('abort', this.externalAbortListener)
        this.externalAbortListener = null
      }
    }
  }

  // ===== PREPARING：组装请求 =====
  private handlePreparing(): void {
    // 主动压缩：估算 token，超限则先压缩
    const maxTokens = this.config.maxContextTokens ?? 24000 // 保守上限
    const estimated = this.estimateTokens()

    if (this.config.debug) {
      console.error(`[agent-loop] PREPARING: estimated ${estimated} tokens, max ${maxTokens}`)
    }

    if (estimated > maxTokens) {
      this.compressContext(estimated)
    }

    this.transition('PREPARING', 'STREAMING', 'request_ready')
  }

  // ===== STREAMING：流式调 LLM =====
  private async *handleStreaming(): AsyncGenerator<AgentEvent> {
    this.currentContent = ''
    this.currentToolCalls = []
    this.currentFinishReason = 'stop'

    // 子 AbortController（单轮可中断，父 abort 传播到子）
    const childAbort = new AbortController()
    const onParentAbort = () => childAbort.abort()
    this.parentAbort!.signal.addEventListener('abort', onParentAbort, { once: true })

    try {
      const toolDefs = this.config.tools.toDefinitions()

      const request = {
        messages: this.messages,
        systemPrompt: this.config.systemPrompt,
        tools: toolDefs.length > 0 ? toolDefs : undefined,
        signal: childAbort.signal,
      }

      for await (const chunk of this.config.provider.generateStream(request)) {
        if (childAbort.signal.aborted) break

        if (chunk.delta) {
          this.currentContent += chunk.delta
          yield { type: 'stream_delta', delta: chunk.delta }
        }
        if (chunk.reasoningDelta) {
          yield { type: 'reasoning_delta', delta: chunk.reasoningDelta }
        }
        if (chunk.toolCall) {
          this.currentToolCalls = this.mergeToolCall(this.currentToolCalls, chunk.toolCall)
        }
        if (chunk.finishReason) {
          this.currentFinishReason = chunk.finishReason
        }
      }

      // assistant 消息入历史
      this.messages.push({
        id: `msg-${Date.now()}-assistant-${this.turn}`,
        role: 'assistant',
        content: this.currentContent,
        toolCalls: this.currentToolCalls.length > 0 ? this.currentToolCalls : undefined,
        timestamp: Date.now(),
      })

      yield { type: 'stream_end', content: this.currentContent }
      this.turn++
      yield { type: 'turn_end', turn: this.turn }

      this.transition('STREAMING', 'DECIDING', 'stream_end')
    } finally {
      this.parentAbort!.signal.removeEventListener('abort', onParentAbort)
    }
  }

  // ===== DECIDING：判断 finishReason =====
  private handleDeciding(): void {
    if (this.currentFinishReason === 'stop' || this.currentToolCalls.length === 0) {
      this.transition('DECIDING', 'DONE', 'stop')
    } else if (this.currentFinishReason === 'tool_calls') {
      this.transition('DECIDING', 'EXECUTING_TOOLS', 'tool_calls')
    } else if (this.currentFinishReason === 'length') {
      this.transition('DECIDING', 'COMPRESSING', 'length')
    } else {
      this.transition('DECIDING', 'ERROR_RECOVERY', 'error')
    }
  }

  // ===== EXECUTING_TOOLS：执行工具 =====
  private async *handleExecutingTools(): AsyncGenerator<AgentEvent> {
    // 分组：只读工具并行，写工具串行
    const { readonly: readonlyCalls, write: writeCalls } = this.partitionToolCalls(this.currentToolCalls)

    // 只读工具并行（限并发 10）
    if (readonlyCalls.length > 0) {
      yield* this.executeToolsConcurrent(readonlyCalls, 10)
    }

    // 写工具串行
    for (const tc of writeCalls) {
      yield* this.executeTool(tc)
    }

    this.transition('EXECUTING_TOOLS', 'FEEDBACK', 'tools_done')
  }

  // ===== FEEDBACK：回喂结果，进入下一轮 =====
  private async *handleFeedback(): AsyncGenerator<AgentEvent> {
    // tool 结果已在 executeTool 中 push 进 messages
    this.retryCount = 0 // 成功执行完工具，重置重试计数
    this.transition('FEEDBACK', 'PREPARING', 'feedback_ready')
  }

  // ===== COMPRESSING：上下文压缩 =====
  private handleCompressing(): void {
    this.compressContext(this.estimateTokens())
    this.transition('COMPRESSING', 'PREPARING', 'compressed')
  }

  // ===== ERROR_RECOVERY：错误恢复 =====
  private async *handleErrorRecovery(): AsyncGenerator<AgentEvent> {
    const maxRetries = this.config.maxRetries ?? 3

    if (this.retryCount >= maxRetries) {
      yield { type: 'error', error: `max retries (${maxRetries}) exceeded`, recoverable: false }
      this.transition('ERROR_RECOVERY', 'ABORTING', 'unrecoverable')
      return
    }

    this.retryCount++

    // 检测是否为上下文过长错误
    const lastError = this.lastErrorMessage || ''
    const isContextTooLong = lastError.includes('input length too long') ||
                             lastError.includes('context length') ||
                             lastError.includes('maximum context')

    if (isContextTooLong) {
      yield {
        type: 'error',
        error: `context too long, compressing aggressively (attempt ${this.retryCount}/${maxRetries})`,
        recoverable: true,
      }
      // 激进压缩：只保留最近 4 条 + 截断所有工具结果
      this.compressContext(this.estimateTokens(), 4)
    } else {
      yield {
        type: 'error',
        error: `recovering (attempt ${this.retryCount}/${maxRetries}): compressing context and retrying`,
        recoverable: true,
      }
      // 普通压缩
      this.compressContext(this.estimateTokens())
    }

    this.lastErrorMessage = ''
    this.transition('ERROR_RECOVERY', 'PREPARING', 'recovered')
  }

  // ===== ABORTING：中断清理 =====
  private async *handleAborting(): AsyncGenerator<AgentEvent> {
    // 为每个未完成的 tool_call 合成 tool_result（否则 API 报错）
    for (const tc of this.currentToolCalls) {
      const hasResult = this.messages.some(m => m.toolCallId === tc.id)
      if (!hasResult) {
        this.messages.push({
          id: `msg-abort-${Date.now()}-${tc.id}`,
          role: 'tool',
          content: 'Error: user_interrupted',
          toolCallId: tc.id,
          timestamp: Date.now(),
        })
      }
    }

    this.transition('ABORTING', 'DONE', 'user_cancel')
  }

  // ===== 执行单个工具 =====
  private async *executeTool(tc: ToolCall): AsyncGenerator<AgentEvent> {
    yield { type: 'tool_call_start', toolCall: tc, turn: this.turn }

    const tool = this.config.tools.get(tc.function.name)
    let result: string
    let isError = false

    if (!tool) {
      result = `Error: unknown tool "${tc.function.name}"`
      isError = true
    } else {
      try {
        // 解析参数
        let args: Record<string, unknown>
        try {
          args = JSON.parse(tc.function.arguments || '{}')
        } catch {
          args = {}
        }

        const context: ToolExecutionContext = {
          cwd: this.config.cwd,
          signal: this.parentAbort?.signal,
        }

        const execResult = await tool.execute(args, context)
        result = execResult.content || execResult.error || '(no output)'
        isError = !execResult.success
      } catch (err) {
        result = `Error: ${err instanceof Error ? err.message : String(err)}`
        isError = true
      }
    }

    yield { type: 'tool_call_end', toolCallId: tc.id, result, isError, turn: this.turn }

    // tool 结果回喂（截断超长结果，避免上下文爆炸）
    this.messages.push({
      id: `msg-${Date.now()}-tool-${tc.id}`,
      role: 'tool',
      content: this.truncateToolResult(result),
      toolCallId: tc.id,
      timestamp: Date.now(),
    })
  }

  // ===== 并发执行工具（带限流）=====
  private async *executeToolsConcurrent(
    tcs: ToolCall[],
    limit: number
  ): AsyncGenerator<AgentEvent> {
    if (tcs.length === 0) return

    // 简化版：全部并行（MVP 工具少，暂不做严格限流）
    // 未来：用带并发限制的 generator 合流
    const generators = tcs.map(tc => this.collectToolEvents(tc))

    // 并行执行，收集所有事件
    const results = await Promise.all(generators)

    // 按原始顺序 yield 事件
    for (const events of results) {
      for (const ev of events) {
        yield ev
      }
    }
  }

  /** 收集单个工具的所有事件（用于并行执行） */
  private async collectToolEvents(tc: ToolCall): Promise<AgentEvent[]> {
    const events: AgentEvent[] = []
    events.push({ type: 'tool_call_start', toolCall: tc, turn: this.turn })

    const tool = this.config.tools.get(tc.function.name)
    let result: string
    let isError = false

    if (!tool) {
      result = `Error: unknown tool "${tc.function.name}"`
      isError = true
    } else {
      try {
        let args: Record<string, unknown>
        try {
          args = JSON.parse(tc.function.arguments || '{}')
        } catch {
          args = {}
        }

        const context: ToolExecutionContext = {
          cwd: this.config.cwd,
          signal: this.parentAbort?.signal,
        }

        const execResult = await tool.execute(args, context)
        result = execResult.content || execResult.error || '(no output)'
        isError = !execResult.success
      } catch (err) {
        result = `Error: ${err instanceof Error ? err.message : String(err)}`
        isError = true
      }
    }

    events.push({ type: 'tool_call_end', toolCallId: tc.id, result, isError, turn: this.turn })

    // tool 结果回喂（截断超长结果）
    this.messages.push({
      id: `msg-${Date.now()}-tool-${tc.id}`,
      role: 'tool',
      content: this.truncateToolResult(result),
      toolCallId: tc.id,
      timestamp: Date.now(),
    })

    return events
  }

  // ===== 工具方法 =====

  /** 状态转换（通过方法避免 TS 控制流分析窄化） */
  private transition(from: LoopState, to: LoopState, reason: TransitionReason): void {
    if (this.config.debug) {
      console.error(`[agent-loop] ${from} → ${to} (${reason}) turn=${this.turn}`)
    }
    this.state = to
  }

  /** 读取当前状态（避免 TS 窄化 this.state） */
  private getState(): LoopState {
    return this.state
  }

  /** 粗略估算当前上下文 token 数（~4 chars/token） */
  private estimateTokens(): number {
    let totalChars = this.config.systemPrompt.length
    for (const msg of this.messages) {
      totalChars += msg.content.length
      if (msg.toolCalls) {
        for (const tc of msg.toolCalls) {
          totalChars += tc.function.name.length + tc.function.arguments.length
        }
      }
    }
    return Math.ceil(totalChars / 4)
  }

  /** 截断工具结果文本（保留头尾，中间用省略号替代） */
  private truncateToolResult(text: string): string {
    const maxChars = this.config.maxToolResultChars ?? 3000
    if (text.length <= maxChars) return text
    const headLen = Math.floor(maxChars * 0.6)
    const tailLen = Math.floor(maxChars * 0.3)
    return (
      text.slice(0, headLen) +
      `\n\n... (truncated ${text.length - headLen - tailLen} chars)\n\n` +
      text.slice(-tailLen)
    )
  }

  /**
   * 压缩上下文
   *
   * 策略：
   * 1. 截断所有 tool 消息中的超长内容
   * 2. 如果仍超限，保留最近 keepRecent 条消息（默认 6）
   * 3. 确保不破坏 tool_call → tool_result 的配对关系
   */
  private compressContext(_currentTokens: number, keepRecent = 6): void {
    const maxTokens = this.config.maxContextTokens ?? 24000

    // Step 1: 截断所有 tool 结果
    for (const msg of this.messages) {
      if (msg.role === 'tool' && msg.content.length > 1000) {
        msg.content = this.truncateToolResult(msg.content)
      }
    }

    // Step 2: 如果截断后仍超限，删除旧消息
    let estimated = this.estimateTokens()
    if (estimated <= maxTokens) {
      if (this.config.debug) {
        console.error(`[agent-loop] compress: truncated tool results, now ${estimated} tokens`)
      }
      return
    }

    // 保留最近 keepRecent 条，但需要保证 tool_call 和 tool_result 配对
    // 从尾部往前找，保证不截断配对的中间
    while (this.messages.length > keepRecent + 2 && estimated > maxTokens) {
      // 找到第一条可以安全删除的消息
      const removed = this.messages.shift()
      if (!removed) break

      // 如果删除了带 toolCalls 的 assistant 消息，其对应的 tool 结果也必须删除
      if (removed.toolCalls && removed.toolCalls.length > 0) {
        const tcIds = new Set(removed.toolCalls.map(tc => tc.id))
        // 删除紧接着的 tool 消息
        while (this.messages.length > 0 && this.messages[0].role === 'tool' && tcIds.has(this.messages[0].toolCallId || '')) {
          this.messages.shift()
        }
      }

      // 如果删除了 tool 消息，检查它对应的 assistant toolCall 消息是否还在
      // 如果 assistant 还在但没有对应的 tool 结果，也要删除 assistant
      if (removed.role === 'tool' && removed.toolCallId) {
        // 找到对应的 assistant 消息
        const assistantIdx = this.messages.findIndex(
          m => m.role === 'assistant' && m.toolCalls?.some(tc => tc.id === removed.toolCallId)
        )
        if (assistantIdx !== -1) {
          const assistant = this.messages[assistantIdx]
          // 检查这个 assistant 的所有 toolCalls 是否都有对应的 tool 结果
          const allHaveResults = assistant.toolCalls!.every(tc =>
            this.messages.some(m => m.role === 'tool' && m.toolCallId === tc.id)
          )
          if (!allHaveResults) {
            // 删除孤立的 assistant 消息
            this.messages.splice(assistantIdx, 1)
          }
        }
      }

      estimated = this.estimateTokens()
    }

    if (this.config.debug) {
      console.error(`[agent-loop] compress: reduced to ${this.messages.length} messages, ~${estimated} tokens`)
    }
  }

  /** 合并流式 tool_call 分片
   *
   * Provider 已经按 index 聚合了完整的 tool_call，这里只需按 id 去重。
   * 绝不能按 function.name 匹配——LLM 可能同时调两个同名工具，
   * 按 name 匹配会把第二个的 arguments 拼到第一个上，产生非法 JSON。
   */
  private mergeToolCall(existing: ToolCall[], delta: ToolCall): ToolCall[] {
    // 只按 id 匹配（provider 已保证每个 tool_call 有唯一 id）
    const idx = existing.findIndex(tc => tc.id === delta.id)

    if (idx === -1) {
      // 新的 tool_call，直接追加
      return [...existing, { ...delta }]
    }

    // 同 id 的分片合并（流式 delta 场景，provider 理论上已聚合完毕）
    const merged = [...existing]
    merged[idx] = {
      id: merged[idx].id,
      type: 'function',
      function: {
        name: merged[idx].function.name || delta.function.name,
        arguments: (merged[idx].function.arguments || '') + (delta.function.arguments || ''),
      },
    }
    return merged
  }

  /** 按 readonly 分组工具调用 */
  private partitionToolCalls(tcs: ToolCall[]): { readonly: ToolCall[]; write: ToolCall[] } {
    const readonly: ToolCall[] = []
    const write: ToolCall[] = []
    for (const tc of tcs) {
      const tool = this.config.tools.get(tc.function.name)
      if (tool?.readonly) readonly.push(tc)
      else write.push(tc)
    }
    return { readonly, write }
  }

  /** 获取最后一条 assistant 消息内容 */
  private getLastAssistantContent(): string {
    for (let i = this.messages.length - 1; i >= 0; i--) {
      if (this.messages[i].role === 'assistant') return this.messages[i].content
    }
    return ''
  }

  /** 外部调用：中断 */
  abort(): void {
    this.parentAbort?.abort()
  }

  /** 清空对话历史 */
  clearHistory(): void {
    this.messages = []
    this.turn = 0
    this.retryCount = 0
    this.lastErrorMessage = ''
    this.state = 'IDLE'
  }

  /** 获取历史消息数 */
  get historyLength(): number {
    return this.messages.length
  }

  /** 获取当前状态 */
  get currentState(): LoopState {
    return this.state
  }
}
