import '../../env.js'

import React, { useState, useRef, useEffect } from 'react'
import { Text, Box, useApp, useInput, Static } from 'ink'
import { purple } from './theme.js'
import { WelcomeBox } from './components/WelcomeBox.js'
import { MessageRow } from './components/MessageRow.js'
import { PromptInput } from './components/PromptInput.js'
import { StatusBar } from './components/StatusBar.js'
import { ThinkingIndicator } from './components/ThinkingIndicator.js'
import { createStepFunProviderFromEnv } from '../../providers/stepfun.provider.js'
import { AgentLoop, type AgentEvent } from '../../core/agent-loop.js'
import { ToolRegistry } from '../../core/tool-registry.js'
import { FileReadTool } from '../../tools/file-read.js'
import { ListDirectoryTool } from '../../tools/list-directory.js'
import { ShellTool } from '../../tools/shell.js'
import type { ChatMessage, StatusInfo } from './types.js'

// Static 渲染项类型（欢迎框 + 消息统一管理）
type StaticItem =
  | { type: 'welcome'; id: 'welcome' }
  | { type: 'message'; id: string; message: ChatMessage }

/**
 * MozilCode TUI 主应用 - 接入完整 Agent Loop
 *
 * 所有输入处理集中在此处（避免多个 useInput 冲突）
 */
const App: React.FC = () => {
  const { exit } = useApp()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streamingText, setStreamingText] = useState<string | undefined>(undefined)
  const [thinking, setThinking] = useState<string | null>(null)
  const [agentRunning, setAgentRunning] = useState(false)
  const [mode, setMode] = useState<'default' | 'plan' | 'accept-edits'>('default')
  const [turn, setTurn] = useState(0)
  const [cost, setCost] = useState(0)

  // 输入状态（提升到 App，让 PromptInput 变受控组件）
  const [inputText, setInputText] = useState('')
  const [multiline, setMultiline] = useState(false)

  const loopRef = useRef<AgentLoop | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const pendingToolRef = useRef<Set<string>>(new Set())
  const streamingTextRef = useRef<string | undefined>(undefined)
  const msgIdCounter = useRef(0)

  useEffect(() => {
    const provider = createStepFunProviderFromEnv()
    if (provider.isConfigured()) {
      const tools = new ToolRegistry()
      tools.register(new FileReadTool())
      tools.register(new ListDirectoryTool())
      tools.register(new ShellTool())
      loopRef.current = new AgentLoop({
        provider,
        tools,
        cwd: process.cwd(),
        systemPrompt: `你是 MozilCode，一个运行在用户本地终端的 AI 编程助手。
你帮助用户理解代码、修改文件、执行命令、调试问题。

你有以下工具可用：
- read_file: 读取本地文件内容
- list_directory: 列出目录内容
- exec_command: 执行终端命令（如 ls, git, npm 等）

重要规则：
- 当用户需要查看文件、目录或执行命令时，请主动使用这些工具，而不是让用户自己操作。
- 使用 read_file 后，**不要在你的回复中重复输出完整文件内容**。文件内容已经在工具结果中单独展示给用户，你只需总结或引用关键片段。
- list_directory 的目录列表可以在工具结果中展示，这是允许的。
- 请用简洁的中文回答。`,
      })
    }
  }, [])

  // ===== 统一输入处理 =====
  useInput((input, key) => {
    // ESC 中断 Agent（最高优先级）
    if (key.escape && agentRunning) {
      abortRef.current?.abort()
      return
    }

    // Agent 执行中，只允许 ESC 和 Ctrl+C
    if (agentRunning) {
      if (key.ctrl && input === 'c') {
        abortRef.current?.abort()
      }
      return
    }

    // Ctrl+C 退出
    if (key.ctrl && input === 'c') {
      exit()
      return
    }

    // Ctrl+J 切换多行
    if (key.ctrl && input === 'j') {
      setMultiline(prev => !prev)
      return
    }

    // Shift+Tab 切换模式
    if (key.tab && key.shift) {
      setMode(prev => {
        if (prev === 'default') return 'plan'
        if (prev === 'plan') return 'accept-edits'
        return 'default'
      })
      return
    }

    // Enter 提交或换行
    if (key.return) {
      if (multiline) {
        setInputText(prev => prev + '\n')
      } else if (inputText.trim()) {
        const submitted = inputText.trim()
        setInputText('')
        setMultiline(false)
        handleSubmit(submitted)
      }
      return
    }

    // Backspace / Delete - 删除字符
    if (key.backspace || key.delete) {
      setInputText(prev => prev.slice(0, -1))
      return
    }

    // 普通字符
    if (
      input &&
      !key.ctrl &&
      !key.meta &&
      input !== '\r' &&
      input !== '\n' &&
      input !== '\t'
    ) {
      setInputText(prev => prev + input)
      return
    }
  })

  const handleSubmit = async (text: string) => {
    if (!loopRef.current) {
      setMessages(prev => [...prev, {
        id: `msg-err-${Date.now()}-${msgIdCounter.current++}`,
        role: 'assistant',
        content: '❌ Agent 未初始化，请检查 .env 配置',
        timestamp: Date.now(),
      }])
      return
    }

    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}-user`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    }
    setMessages(prev => [...prev, userMsg])
    setAgentRunning(true)
    setThinking('Thinking')
    setTurn(0)

    const controller = new AbortController()
    abortRef.current = controller
    pendingToolRef.current.clear()

    let finalText = ''

    try {
      for await (const event of loopRef.current.run(text, { signal: controller.signal })) {
        handleAgentEvent(event)
        if (event.type === 'done') {
          finalText = event.content
        }
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        id: `msg-err-${Date.now()}-${msgIdCounter.current++}`,
        role: 'assistant',
        content: `❌ 异常: ${err instanceof Error ? err.message : String(err)}`,
        timestamp: Date.now(),
      }])
    } finally {
      setStreamingText(undefined)
      streamingTextRef.current = undefined
      setThinking(null)
      setAgentRunning(false)
      abortRef.current = null
      pendingToolRef.current.clear()
      if (finalText) {
        setCost(prev => prev + 0.01)
      }
    }
  }

  const handleAgentEvent = (event: AgentEvent) => {
    switch (event.type) {
      case 'state_change': {
        // 根据状态更新 thinking 提示
        const stateLabels: Record<string, string> = {
          PREPARING: 'Preparing',
          STREAMING: 'Calling LLM',
          DECIDING: 'Deciding',
          EXECUTING_TOOLS: 'Executing tools',
          FEEDBACK: 'Feedback',
          COMPRESSING: 'Compressing',
          ERROR_RECOVERY: 'Recovering',
          ABORTING: 'Aborting',
        }
        if (stateLabels[event.to]) {
          setThinking(stateLabels[event.to])
        }
        break
      }

      case 'stream_delta': {
        setStreamingText(prev => {
          const next = prev === undefined ? event.delta : prev + event.delta
          streamingTextRef.current = next
          return next
        })
        break
      }

      case 'tool_call_start': {
        // 先把当前流式内容固定为 assistant 消息（不在 setStreamingText updater 内调用 setMessages）
        const currentStream = streamingTextRef.current
        if (currentStream && currentStream.trim()) {
          setMessages(prev => [...prev, {
            id: `msg-${Date.now()}-assistant-partial`,
            role: 'assistant',
            content: currentStream,
            timestamp: Date.now(),
            streaming: true,
          }])
        }
        setStreamingText(undefined)
        streamingTextRef.current = undefined

        pendingToolRef.current.add(event.toolCall.id)

        const toolMsg: ChatMessage = {
          id: `msg-${Date.now()}-tool-${event.toolCall.id}`,
          role: 'tool',
          content: '',
          timestamp: Date.now(),
          toolCalls: [{
            id: event.toolCall.id,
            name: event.toolCall.function.name,
            args: parseArgs(event.toolCall.function.arguments),
            argsDisplay: event.toolCall.function.arguments.slice(0, 80),
          }],
          toolResults: [],
        }
        setMessages(prev => [...prev, toolMsg])
        break
      }

      case 'tool_call_end': {
        pendingToolRef.current.delete(event.toolCallId)
        setMessages(prev => prev.map(msg => {
          if (msg.role === 'tool' && msg.toolCalls?.some(tc => tc.id === event.toolCallId)) {
            return {
              ...msg,
              content: event.result,
              toolResults: [
                ...(msg.toolResults || []),
                {
                  toolCallId: event.toolCallId,
                  success: !event.isError,
                  content: event.result,
                  error: event.isError ? event.result : undefined,
                },
              ],
            }
          }
          return msg
        }))
        break
      }

      case 'turn_end': {
        setTurn(event.turn)
        break
      }

      case 'stream_end': {
        // 当前流式轮次结束，如果后面还有 tool_call，内容已在 tool_call_start 中固定
        // 如果后面没有 tool_call，会在 done 中处理
        break
      }

      case 'done': {
        // 添加最终 assistant 消息
        setMessages(prev => {
          // 如果最后一条是流式占位消息，替换它
          if (prev.length > 0 && prev[prev.length - 1].streaming) {
            const updated = [...prev]
            updated[updated.length - 1] = {
              ...updated[updated.length - 1],
              content: event.content || updated[updated.length - 1].content,
              streaming: false,
            }
            return updated
          }
          // 否则添加新消息
          if (event.content.trim()) {
            return [...prev, {
              id: `msg-${Date.now()}-assistant-final`,
              role: 'assistant',
              content: event.content,
              timestamp: Date.now(),
            }]
          }
          return prev
        })
        break
      }

      case 'error': {
        setMessages(prev => [
          ...prev,
          {
            id: `msg-err-${Date.now()}-${msgIdCounter.current++}`,
            role: 'assistant',
            content: event.recoverable
              ? `⚠️ 恢复中: ${event.error}`
              : `❌ 错误: ${event.error}`,
            timestamp: Date.now(),
          },
        ])
        break
      }
    }
  }

  const statusInfo: StatusInfo = {
    model: 'step-3.7-flash',
    mode,
    cwd: process.cwd(),
    contextUsed: Math.min(turn * 5, 80),
    cost,
    turn,
  }

  // 合并欢迎框和消息，全部用 Static 渲染（写入后不重绘）
  const staticItems = React.useMemo(() => {
    const welcomeItem: StaticItem = { type: 'welcome', id: 'welcome' }
    const msgItems: StaticItem[] = messages.map(m => ({ type: 'message', id: m.id, message: m }))
    return [welcomeItem, ...msgItems]
  }, [messages])

  return (
    <Box flexDirection="column">
      {/* ===== 已完成的内容用 Static 渲染（写入终端后不再重绘，避免滚动跳动） ===== */}
      <Static items={staticItems}>
        {(item) => {
          if (item.type === 'welcome') {
            return (
              <WelcomeBox
                key="welcome"
                version="1.0.0"
                model={statusInfo.model}
                billing="StepFun"
                cwd={statusInfo.cwd}
              />
            )
          }
          return <MessageRow key={item.id} message={item.message!} />
        }}
      </Static>

      {/* ===== 动态区域：流式输出 + 思考 + 输入（行数少，重绘不影响滚动） ===== */}
      {streamingText !== undefined && (
        <Box>
          <Text color={purple.primaryBright}>● </Text>
          <Text color={purple.textPrimary}>{streamingText}</Text>
          <Text color={purple.primary}>▋</Text>
        </Box>
      )}

      {/* ===== 思考指示器 ===== */}
      {thinking && <ThinkingIndicator phase={thinking} />}

      {/* ===== 底部：输入框 + 状态栏 ===== */}
      <PromptInput
        text={inputText}
        setText={setInputText}
        onSubmit={handleSubmit}
        disabled={agentRunning}
        multiline={multiline}
        setMultiline={setMultiline}
        mode={mode}
      />
      <StatusBar info={statusInfo} agentRunning={agentRunning} />
    </Box>
  )
}

function parseArgs(jsonStr: string): Record<string, unknown> {
  try {
    return JSON.parse(jsonStr || '{}')
  } catch {
    return {}
  }
}

export default App
