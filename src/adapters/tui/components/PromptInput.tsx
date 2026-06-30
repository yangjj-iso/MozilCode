import React, { useState, useEffect } from 'react'
import { Text, Box, useInput } from 'ink'
import { purple } from '../theme.js'
import { POINTER } from '../figures.js'
import { getRandomPlaceholder } from '../exampleCommands.js'

interface PromptInputProps {
  text: string
  setText: (updater: (prev: string) => string) => void
  onSubmit: (text: string) => void
  disabled?: boolean
  multiline?: boolean
  setMultiline?: (updater: (prev: boolean) => boolean) => void
  mode?: 'default' | 'plan' | 'accept-edits'
}

/**
 * 输入框 - 受控组件（输入处理由 App.tsx 统一管理，避免多个 useInput 冲突）
 *
 * ┌─────────────────────────────────────────┐
 * │ ❯ Try "fix lint errors"                 │
 * └─────────────────────────────────────────┘
 */
export const PromptInput: React.FC<PromptInputProps> = ({
  text,
  disabled = false,
  multiline = false,
}) => {
  const [placeholder, setPlaceholder] = useState(getRandomPlaceholder())

  useEffect(() => {
    if (text || disabled) return
    const timer = setInterval(() => {
      setPlaceholder(getRandomPlaceholder())
    }, 3000)
    return () => clearInterval(timer)
  }, [text, disabled])

  const pointer = disabled ? '' : POINTER
  const pointerColor = disabled ? purple.textMuted : purple.primaryBright

  return (
    <Box flexDirection="column" marginTop={1}>
      <Box
        borderStyle="round"
        borderColor={disabled ? purple.textMuted : purple.border}
        paddingX={1}
      >
        <Text color={pointerColor}>{pointer}</Text>
        <Text> </Text>
        {text ? (
          <Text color={purple.textPrimary}>{text}</Text>
        ) : (
          <Text color={purple.textMuted} italic>
            {disabled ? 'Agent 执行中…' : placeholder}
          </Text>
        )}
        {!disabled && <Text color={purple.primary}>▋</Text>}
      </Box>
    </Box>
  )
}
