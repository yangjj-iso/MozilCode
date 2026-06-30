import React, { useState, useEffect } from 'react'
import { Text, Box } from 'ink'
import { purple, status } from '../theme.js'
import { SPINNER_FRAMES, MIDDLE_DOT } from '../figures.js'

interface ThinkingIndicatorProps {
  phase: string
}

/**
 * 思考指示器 - 模仿 cc-haha 的 "∴ Thinking"
 * 显示旋转动画 + 当前阶段
 */
export const ThinkingIndicator: React.FC<ThinkingIndicatorProps> = ({ phase }) => {
  const [frame, setFrame] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => {
      setFrame(prev => (prev + 1) % SPINNER_FRAMES.length)
    }, 80)
    return () => clearInterval(timer)
  }, [])

  return (
    <Box>
      <Text color={purple.primary}>{SPINNER_FRAMES[frame]}</Text>
      <Text color={purple.textSecondary}> {phase}…</Text>
    </Box>
  )
}
