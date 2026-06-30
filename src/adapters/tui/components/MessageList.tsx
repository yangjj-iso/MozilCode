import React from 'react'
import { Text, Box } from 'ink'
import { purple } from '../theme.js'
import type { ChatMessage } from '../types.js'
import { MessageRow } from './MessageRow.js'
import { ToolUseCard } from './ToolUseCard.js'

interface MessageListProps {
  messages: ChatMessage[]
  streamingText?: string
}

/**
 * 消息流列表
 * 渲染所有历史消息 + 当前流式输出
 */
export const MessageList: React.FC<MessageListProps> = ({ messages, streamingText }) => {
  return (
    <Box flexDirection="column" gap={1}>
      {messages.map(msg => (
        <MessageRow key={msg.id} message={msg} />
      ))}

      {/* 流式输出中 */}
      {streamingText !== undefined && (
        <Box flexDirection="column">
          <Text>
            <Text color={purple.primaryBright}>● </Text>
            <Text color={purple.textPrimary}>{streamingText}</Text>
            <Text color={purple.primary}>▋</Text>
          </Text>
        </Box>
      )}
    </Box>
  )
}
