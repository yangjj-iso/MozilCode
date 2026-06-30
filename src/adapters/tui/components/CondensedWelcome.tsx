/**
 * 精简版欢迎 - 模仿 cc-haha 的 CondensedLogo
 * 单行显示，无边框，用于非首次启动
 */

import React from 'react'
import { Text, Box } from 'ink'
import { purple } from '../theme.js'
import { MOZIL_LOGO_MINI } from '../logo.js'

interface CondensedWelcomeProps {
  version?: string
  model?: string
  billing?: string
  cwd: string
}

export const CondensedWelcome: React.FC<CondensedWelcomeProps> = ({
  version = '1.0.0',
  model = 'claude-sonnet-4',
  billing = 'Pro',
  cwd,
}) => {
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Box>
        <Text color={purple.primary}>{MOZIL_LOGO_MINI}</Text>
        <Text color={purple.primaryBright} bold>
          {' '}
          MozilCode
        </Text>
        <Text color={purple.textMuted}> v{version}</Text>
      </Box>
      <Box>
        <Text color={purple.textMuted}>
          {model} · {billing}
        </Text>
      </Box>
      <Box>
        <Text color={purple.textMuted}>{cwd}</Text>
      </Box>
    </Box>
  )
}
