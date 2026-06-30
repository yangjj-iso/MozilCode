import '../../env.js'

import React, { useState, useRef, useEffect, useMemo } from 'react'
import { Text, Box, useApp, useInput, useStdout } from 'ink'
import { purple } from './theme.js'
import { WelcomeBox } from './components/WelcomeBox.js'
import { MessageRow } from './components/MessageRow.js'
import { PromptInput } from './components/PromptInput.js'
import { StatusBar } from './components/StatusBar.js'
import { ThinkingIndicator } from './components/ThinkingIndicator.js'
import { createStepFunProviderFromEnv } from '../../providers/stepfun.provider.js'
import { MiniAgentLoop } from './mini-agent-loop.js'
import type { ChatMessage, StatusInfo } from './types.js'

/**
 * MozilCode TUI 主应用 - 接入真实 LLM
 *
 * 所有输入处理集中在此处（避免多个 useInput 冲突，这是之前 backspace 失效的根因）
 */
const App: React.FC = () => {
  const { exit } = useApp()
  const { stdout } = useStdout()
  const [rows, setRows] = useState(stdout.rows)
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

  const loopRef = useRef<MiniAgentLoop | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    const provider = createStepFunProviderFromEnv()
    if (provider.isConfigured()) {
      loopRef.current = new MiniAgentLoop({ provider })
    }
  }, [])

  useEffect(() => {
    const handleResize = () => setRows(stdout.rows)
    stdout.on('resize', handleResize)
    return () => {
      stdout.off('resize', handleResize)
    }
  }, [stdout])

  // 根据终端高度限制可见消息数量，避免内容超出终端导致边框滚动变形
  const visibleMessages = useMemo(() => {
    const welcomeHeight = 12
    const footerHeight = 4
    const avgMessageHeight = 3
    const maxMessages = Math.max(3, Math.floor((rows - welcomeHeight - footerHeight) / avgMessageHeight))
    return messages.slice(-maxMessages)
  }, [messages, rows])

  // ===== 统一输入处理（解决多个 useInput 冲突 + backspace 失效）=====
  useInput((input, key) => {
    // ESC 中断 Agent（最高优先级）
    if (key.escape && agentRunning) {
      abortRef.current?.abort()
      setThinking(null)
      setAgentRunning(false)
      setStreamingText(undefined)
      return
    }

    // Agent 执行中，只允许 ESC 和 Ctrl+C
    if (agentRunning) {
      if (key.ctrl && input === 'c') {
        abortRef.current?.abort()
        setThinking(null)
        setAgentRunning(false)
        setStreamingText(undefined)
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

    // Backspace / Delete - 删除字符（放在普通字符前，优先级更高）
    if (key.backspace || key.delete) {
      setInputText(prev => prev.slice(0, -1))
      return
    }

    // 普通字符（排除 ctrl/meta 组合键和回车）
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
    if (!loopRef.current) return

    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    }
    setMessages(prev => [...prev, userMsg])
    setAgentRunning(true)
    setThinking('Thinking')

    const controller = new AbortController()
    abortRef.current = controller

    try {
      await new Promise(r => setTimeout(r, 300))
      setThinking('Calling LLM')
      setStreamingText('')

      let fullText = ''
      for await (const event of loopRef.current.sendMessage(text, { signal: controller.signal })) {
        if (event.type === 'stream_delta' && event.delta) {
          fullText += event.delta
          setStreamingText(fullText)
        }
        if (event.type === 'error') {
          setStreamingText(undefined)
          setMessages(prev => [
            ...prev,
            {
              id: `msg-err-${Date.now()}`,
              role: 'assistant',
              content: `❌ 错误: ${event.error}`,
              timestamp: Date.now(),
            },
          ])
          break
        }
      }

      if (fullText) {
        setMessages(prev => [
          ...prev,
          {
            id: `msg-${Date.now()}`,
            role: 'assistant',
            content: fullText,
            timestamp: Date.now(),
          },
        ])
      }

      setStreamingText(undefined)
      setThinking(null)
      setAgentRunning(false)
      setTurn(prev => prev + 1)
      setCost(prev => prev + 0.01)
    } catch (err) {
      setStreamingText(undefined)
      setThinking(null)
      setAgentRunning(false)
      setMessages(prev => [
        ...prev,
        {
          id: `msg-err-${Date.now()}`,
          role: 'assistant',
          content: `❌ 异常: ${err instanceof Error ? err.message : String(err)}`,
          timestamp: Date.now(),
        },
      ])
    } finally {
      abortRef.current = null
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

  return (
    <Box flexDirection="column">
      {/* ===== 顶部：欢迎框（始终显示） ===== */}
      <WelcomeBox
        version="1.0.0"
        model={statusInfo.model}
        billing="StepFun"
        cwd={statusInfo.cwd}
      />

      {/* ===== 消息流（从上到下堆积，只显示最近若干条） ===== */}
      <Box flexDirection="column" gap={0}>
        {visibleMessages.map(msg => (
          <MessageRow key={msg.id} message={msg} />
        ))}

        {streamingText !== undefined && (
          <Box>
            <Text color={purple.primaryBright}>● </Text>
            <Text color={purple.textPrimary}>{streamingText}</Text>
            <Text color={purple.primary}>▋</Text>
          </Box>
        )}
      </Box>

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

export default App
