import React from 'react'
import { Text, Box } from 'ink'
import { purple, planMode, status } from '../theme.js'
import type { PlanInfo } from '../types.js'

interface PlanProgressProps {
  plan: PlanInfo
}

const STEP_INDICATOR = {
  pending: '○',
  'in-progress': '◐',
  completed: '●',
  failed: '✗',
}

const STEP_COLOR = {
  pending: planMode.stepPending,
  'in-progress': planMode.stepCurrent,
  completed: planMode.stepDone,
  failed: status.error,
}

/**
 * Plan 进度条
 * 显示当前 plan 的步骤执行进度（改进 cc-haha 没有显式进度的缺点）
 */
export const PlanProgress: React.FC<PlanProgressProps> = ({ plan }) => {
  const total = plan.steps.length
  const done = plan.steps.filter(s => s.status === 'completed').length
  const failed = plan.steps.filter(s => s.status === 'failed').length
  const percent = total > 0 ? Math.round((done / total) * 100) : 0

  // 进度条（10 格）
  const barLen = 10
  const filled = Math.round((percent / 100) * barLen)
  const bar = '█'.repeat(filled) + '░'.repeat(barLen - filled)

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={purple.border}
      paddingX={1}
      paddingY={0}
      marginY={1}
    >
      <Box>
        <Text color={planMode.accent} bold>
          ⏸ Plan
        </Text>
        <Text color={purple.textMuted}> · </Text>
        <Text color={purple.textPrimary} bold>
          {plan.title}
        </Text>
      </Box>

      <Box>
        <Text color={planMode.stepCurrent}>{bar}</Text>
        <Text color={purple.textMuted}> </Text>
        <Text color={purple.textSecondary}>
          {done}/{total} · {percent}%
        </Text>
        {failed > 0 && (
          <Text color={status.error}> ({failed} failed)</Text>
        )}
      </Box>

      {/* 步骤列表 */}
      <Box flexDirection="column" marginTop={0}>
        {plan.steps.map((step, i) => (
          <Box key={step.id}>
            <Text color={STEP_COLOR[step.status]}>{STEP_INDICATOR[step.status]}</Text>
            <Text color={purple.textMuted}> {i + 1}. </Text>
            <Text
              color={
                step.status === 'completed'
                  ? planMode.stepDone
                  : step.status === 'in-progress'
                    ? planMode.stepCurrent
                    : step.status === 'failed'
                      ? status.error
                      : purple.textMuted
              }
              bold={step.status === 'in-progress'}
            >
              {step.title}
            </Text>
            {step.status === 'in-progress' && (
              <Text color={status.info}> (进行中…)</Text>
            )}
          </Box>
        ))}
      </Box>
    </Box>
  )
}
