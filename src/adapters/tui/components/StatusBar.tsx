import React from 'react'
import { Text, Box } from 'ink'
import { purple, status } from '../theme.js'
import { MIDDLE_DOT } from '../figures.js'
import type { StatusInfo } from '../types.js'

interface StatusBarProps {
  info: StatusInfo
  agentRunning?: boolean
}

/**
 * 底部状态栏 - 模仿 cc-haha 的 PromptInputFooterLeftSide
 *
 * ◆ default on  ·  ? for shortcuts
 * 或
 * ◆ default on  ·  esc to interrupt  ·  ctrl+t to show tasks
 */
export const StatusBar: React.FC<StatusBarProps> = ({ info, agentRunning = false }) => {
  const contextColor =
    info.contextUsed > 80
      ? status.error
      : info.contextUsed > 50
        ? status.warning
        : status.success

  const modeSymbol =
    info.mode === 'plan' ? '✻' : info.mode === 'auto' ? '⚡' : '◆'

  return (
    <Box marginTop={1}>
      <Text color={purple.primaryBright} bold>
        {modeSymbol}
      </Text>
      <Text color={purple.textSecondary}> {info.mode} on</Text>
      <Text color={purple.textMuted}>
        {' '}
        {MIDDLE_DOT} {agentRunning ? 'esc to interrupt' : '? for shortcuts'}
      </Text>
      <Text color={purple.textMuted}>
        {' '}
        {MIDDLE_DOT} shift+tab to cycle
      </Text>
      <Text color={purple.textMuted}>
        {' '}
        {MIDDLE_DOT} {info.model}
      </Text>
      <Text color={purple.textMuted}>
        {' '}
        {MIDDLE_DOT}{' '}
      </Text>
      <Text color={contextColor}>ctx {info.contextUsed}%</Text>
      <Text color={purple.textMuted}>
        {' '}
        {MIDDLE_DOT} turn {info.turn}
      </Text>
      <Text color={purple.textMuted}>
        {' '}
        {MIDDLE_DOT}{' '}
      </Text>
      <Text color={status.success}>${info.cost.toFixed(2)}</Text>
    </Box>
  )
}
