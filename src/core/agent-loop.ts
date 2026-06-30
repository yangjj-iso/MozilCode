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

        // 检查最大轮次
        if (this.turn >= (this.config.maxTurns ?? 20) && currentState !== 'ABORTING' && currentState !== 'DONE') {
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
    // MVP：不做主动压缩，直接进入 STREAMING
    // 未来：在这里做 autocompact（预测 token 超限就先压）
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
    // MVP：简单截断——保留 system + 最近 N 条消息
    const keepRecent = 10
    if (this.messages.length > keepRecent + 1) {
      const system = this.messages.filter(m => m.role === 'system')
      const recent = this.messages.slice(-keepRecent)
      this.messages = [...system, ...recent]
    }

    // 压缩后重试
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

    // 策略：压缩后重试
    yield {
      type: 'error',
      error: `recovering (attempt ${this.retryCount}/${maxRetries}): compressing context and retrying`,
      recoverable: true,
    }

    // 简单压缩
    const keepRecent = 6
    if (this.messages.length > keepRecent + 1) {
      const system = this.messages.filter(m => m.role === 'system')
      const recent = this.messages.slice(-keepRecent)
      this.messages = [...system, ...recent]
    }

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

    // tool 结果回喂
    this.messages.push({
      id: `msg-${Date.now()}-tool-${tc.id}`,
      role: 'tool',
      content: result,
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

    // tool 结果回喂
    this.messages.push({
      id: `msg-${Date.now()}-tool-${tc.id}`,
      role: 'tool',
      content: result,
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
