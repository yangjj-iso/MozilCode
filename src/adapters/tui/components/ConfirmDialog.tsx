import React, { useState } from 'react'
import { Text, Box, useInput } from 'ink'
import { purple, status } from '../theme.js'
import type { ConfirmRequest } from '../types.js'

interface ConfirmDialogProps {
  request: ConfirmRequest
  onApprove: () => void
  onDeny: () => void
}

const RISK_LABEL: Record<string, string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  critical: '极高风险',
}

const RISK_COLOR: Record<string, string> = {
  low: status.success,
  medium: status.info,
  high: status.warning,
  critical: status.error,
}

/**
 * 确认弹窗
 * 用于写文件、执行 Shell 等高风险操作前请求用户确认
 */
export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({ request, onApprove, onDeny }) => {
  const [selected, setSelected] = useState(0) // 0=approve, 1=deny

  useInput((input, key) => {
    if (key.leftArrow || key.upArrow) {
      setSelected(prev => (prev === 0 ? 1 : 0))
    }
    if (key.rightArrow || key.downArrow) {
      setSelected(prev => (prev === 1 ? 0 : 1))
    }
    if (key.return) {
      if (selected === 0) onApprove()
      else onDeny()
    }
    // y/n 快捷键
    if (input === 'y' || input === 'Y') onApprove()
    if (input === 'n' || input === 'N') onDeny()
  })

  return (
    <Box flexDirection="column" borderStyle="round" borderColor={purple.primary} paddingX={2} paddingY={1} marginY={1}>
      <Box>
        <Text color={status.warning} bold>
          ⚠ 需要确认
        </Text>
        <Text color={purple.textMuted}> · </Text>
        <Text color={RISK_COLOR[request.riskLevel]} bold>
          {RISK_LABEL[request.riskLevel]}
        </Text>
      </Box>

      <Box marginTop={1}>
        <Text color={purple.textSecondary}>{request.description}</Text>
      </Box>

      <Box flexDirection="column" marginLeft={2} marginY={1}>
        <Text color={purple.textMuted}>工具:</Text>
        <Text color={purple.primaryBright} bold>
          {request.toolName}
        </Text>
        <Text color={purple.textMuted}>目标:</Text>
        {request.targets.map((t, i) => (
          <Text key={i} color={purple.textSecondary}>
            {'  '}
            {t}
          </Text>
        ))}
      </Box>

      {/* 选项 */}
      <Box marginTop={1} gap={2}>
        <Box>
          <Text color={selected === 0 ? purple.primaryBright : purple.textMuted}>
            {selected === 0 ? '▸' : ' '} [
            <Text color={status.success} bold>
              y
            </Text>
            ] 允许
          </Text>
        </Box>
        <Box>
          <Text color={selected === 1 ? purple.primaryBright : purple.textMuted}>
            {selected === 1 ? '▸' : ' '} [
            <Text color={status.error} bold>
              n
            </Text>
            ] 拒绝
          </Text>
        </Box>
      </Box>

      <Text color={purple.textMuted} dimColor>
        ← → 切换 · Enter 确认 · y/n 快捷键
      </Text>
    </Box>
  )
}
