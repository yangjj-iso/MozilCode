import React from 'react'
import { Text, Box } from 'ink'
import { purple } from '../theme.js'

interface WelcomeBoxProps {
  version?: string
  model?: string
  billing?: string
  cwd: string
}

/**
 * 欢迎界面 - 纯文字公告风格
 */
export const WelcomeBox: React.FC<WelcomeBoxProps> = ({
  version = '1.0.0',
  model = 'step-3.7-flash',
  billing = 'StepFun',
  cwd,
}) => {
  const truncatedCwd = truncatePath(cwd, 50)

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={purple.primary}
      paddingX={2}
      paddingY={1}
      marginY={1}
    >
      {/* 标题 */}
      <Box justifyContent="center" marginBottom={1}>
        <Text color={purple.primaryBright} bold>
          MozilCode
        </Text>
      </Box>

      {/* 分隔线 */}
      <Box justifyContent="center" marginBottom={1}>
        <Text color={purple.border}>{'─'.repeat(60)}</Text>
      </Box>

      {/* 欢迎语 */}
      <Box justifyContent="center" marginBottom={1}>
        <Text color={purple.textPrimary} bold>
          Welcome to MozilCode!
        </Text>
      </Box>

      {/* 环境信息 */}
      <Box flexDirection="column" alignItems="center" marginBottom={1}>
        <Box>
          <Text color={purple.textMuted}>模型  </Text>
          <Text color={purple.textSecondary}>{model} · {billing}</Text>
        </Box>
        <Box>
          <Text color={purple.textMuted}>目录  </Text>
          <Text color={purple.textSecondary}>{truncatedCwd}</Text>
        </Box>
      </Box>

      {/* 分隔线 */}
      <Box justifyContent="center" marginY={1}>
        <Text color={purple.border}>{'─'.repeat(60)}</Text>
      </Box>

      {/* 快捷键提示 */}
      <Box justifyContent="center" marginBottom={1}>
        <Text color={purple.textMuted}>快捷键  </Text>
        <Text color={purple.textSecondary}>Enter 发送 · Ctrl+J 多行 · Shift+Tab 切换模式 · ESC 中断</Text>
      </Box>

      {/* 版本号 */}
      <Box justifyContent="center">
        <Text color={purple.textMuted}>v{version}</Text>
      </Box>
    </Box>
  )
}

function truncatePath(path: string, maxLen: number): string {
  if (path.length <= maxLen) return path
  const head = Math.floor((maxLen - 1) / 2)
  const tail = maxLen - head - 1
  return path.slice(0, head) + '…' + path.slice(-tail)
}
