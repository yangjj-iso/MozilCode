import React from 'react'
import { Text, Box } from 'ink'
import { purple } from '../theme.js'
import { BLACK_CIRCLE, TOOL_INDENT } from '../figures.js'
import { MarkdownText } from './MarkdownText.js'
import type { ChatMessage } from '../types.js'

interface MessageRowProps {
  message: ChatMessage
}

/**
 * 单条消息渲染 - 模仿 cc-haha
 *
 * 用户消息：浅紫背景块
 * Assistant 消息：● 圆点前缀 + 无背景
 * Tool 消息：⎿ 缩进
 */
export const MessageRow: React.FC<MessageRowProps> = ({ message }) => {
  // 用户消息 - 亮紫背景高对比
  if (message.role === 'user') {
    return (
      <Box backgroundColor={purple.primary} paddingX={1} paddingY={0} marginY={1}>
        <Text color={purple.textOnPurple} bold>
          {message.content}
        </Text>
      </Box>
    )
  }

  // Assistant 消息 - 圆点前缀 + Markdown 渲染
  if (message.role === 'assistant') {
    return (
      <Box flexDirection="column" marginY={1}>
        <Box>
          <Text color={purple.primaryBright}>{BLACK_CIRCLE}</Text>
          <Text> </Text>
          <MarkdownText text={message.content} color={purple.textPrimary} />
        </Box>

        {/* 工具调用缩进显示 */}
        {message.toolCalls && message.toolCalls.length > 0 && (
          <Box flexDirection="column" marginLeft={2}>
            {message.toolCalls.map(tc => (
              <Text key={`${message.id}-tc-${tc.id}`} color={purple.textSecondary}>
                {TOOL_INDENT} {tc.name}({tc.argsDisplay})
              </Text>
            ))}
          </Box>
        )}
      </Box>
    )
  }

  // Tool 结果消息
  if (message.role === 'tool') {
    const isError = message.content.toLowerCase().includes('error') ||
      message.content.toLowerCase().includes('not found')
    return (
      <Box marginLeft={2} marginY={1}>
        <Text color={purple.textMuted}>{TOOL_INDENT} </Text>
        <Text color={isError ? '#ef4444' : '#10b981'}>{message.content}</Text>
      </Box>
    )
  }

  // System 消息
  return (
    <Box marginY={1}>
      <Text color={purple.textMuted} italic>
        {message.content}
      </Text>
    </Box>
  )
}
