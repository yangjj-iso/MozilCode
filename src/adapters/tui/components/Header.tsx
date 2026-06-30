import React from 'react'
import { Text, Box } from 'ink'
import { purple, LOGO_MINI } from '../theme.js'

interface HeaderProps {
  cwd: string
  mode: 'default' | 'plan' | 'auto'
}

/**
 * 顶部标题栏
 * 显示 MozilCode Logo + 当前工作目录 + 模式标志
 */
export const Header: React.FC<HeaderProps> = ({ cwd, mode }) => {
  const modeLabel =
    mode === 'plan' ? '⏸ plan mode' : mode === 'auto' ? '⚡ auto mode' : '◆ default'

  return (
    <Box flexDirection="column" paddingBottom={1}>
      <Box>
        <Text color={purple.primaryBright} bold>
          {LOGO_MINI}
        </Text>
        <Text color={purple.textMuted}> · </Text>
        <Text color={purple.textSecondary}>本地 Agent 平台</Text>
      </Box>
      <Box>
        <Text color={purple.textMuted}>📁 </Text>
        <Text color={purple.textSecondary}>{cwd}</Text>
        <Text color={purple.textMuted}> · </Text>
        <Text color={mode === 'plan' ? purple.primaryBright : purple.textMuted}>{modeLabel}</Text>
      </Box>
    </Box>
  )
}
