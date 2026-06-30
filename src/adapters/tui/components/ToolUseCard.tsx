import React from 'react'
import { Text, Box } from 'ink'
import { purple, toolStatus, status } from '../theme.js'
import type { ToolCall, ToolStatus, ToolResult } from '../types.js'

interface ToolUseCardProps {
  toolCall: ToolCall
  status: ToolStatus
  result?: ToolResult
}

const STATUS_INDICATOR: Record<ToolStatus, string> = {
  pending: '◌',
  running: '◐',
  success: '●',
  error: '✗',
  denied: '⊘',
}

const STATUS_COLOR: Record<ToolStatus, string> = {
  pending: toolStatus.pending,
  running: toolStatus.running,
  success: toolStatus.success,
  error: toolStatus.error,
  denied: toolStatus.denied,
}

/**
 * 工具调用卡片
 * 显示：状态圆点 + 工具名 + 参数 + 结果摘要
 */
export const ToolUseCard: React.FC<ToolUseCardProps> = ({ toolCall, status: st, result }) => {
  const indicator = STATUS_INDICATOR[st]
  const color = STATUS_COLOR[st]

  return (
    <Box flexDirection="column">
      <Box>
        <Text color={color}>{indicator}</Text>
        <Text> </Text>
        <Text color={purple.primaryBright} bold>
          {toolCall.name}
        </Text>
        <Text color={purple.textSecondary}> ({toolCall.argsDisplay})</Text>
      </Box>

      {/* 状态/结果行 */}
      <Box marginLeft={2}>
        {st === 'pending' && <Text color={purple.textMuted}>⎿ Queued…</Text>}
        {st === 'running' && <Text color={status.info}>⎿ Executing…</Text>}
        {st === 'success' && result && (
          <Text color={status.success}>
            ⎿ {truncateResult(result.content)}
            {result.executionTime && ` (${result.executionTime}ms)`}
          </Text>
        )}
        {st === 'error' && result && (
          <Text color={status.error}>⎿ Error: {result.error || result.content}</Text>
        )}
        {st === 'denied' && <Text color={status.warning}>⎿ User denied</Text>}
      </Box>
    </Box>
  )
}

function truncateResult(content: string, maxLen = 80): string {
  if (content.length <= maxLen) return content
  return content.slice(0, maxLen) + '…'
}
