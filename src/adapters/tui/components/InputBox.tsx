import React, { useState, useCallback } from 'react'
import { Text, Box, useInput } from 'ink'
import { purple } from '../theme.js'

interface InputBoxProps {
  onSubmit: (text: string) => void
  placeholder?: string
  disabled?: boolean
}

/**
 * 输入框
 * - Enter 提交
 * - Ctrl+J 换行
 * - Ctrl+C 退出
 * - 多行支持
 */
export const InputBox: React.FC<InputBoxProps> = ({
  onSubmit,
  placeholder = '输入消息，Enter 发送，Ctrl+J 换行',
  disabled = false,
}) => {
  const [text, setText] = useState('')
  const [multiline, setMultiline] = useState(false)

  useInput((input, key) => {
    if (disabled) return

    // Ctrl+C
    if (key.ctrl && input === 'c') {
      process.exit(0)
    }

    // Enter - 提交或换行
    if (key.return) {
      if (multiline) {
        setText(prev => prev + '\n')
      } else if (text.trim()) {
        onSubmit(text.trim())
        setText('')
        setMultiline(false)
      }
    }

    // Ctrl+J - 切换多行模式
    if (key.ctrl && input === 'j') {
      setMultiline(prev => !prev)
    }

    // Backspace
    if (key.backspace) {
      setText(prev => prev.slice(0, -1))
    }

    // 普通字符
    if (input && !key.ctrl && !key.meta && input !== '\r' && input !== '\n') {
      setText(prev => prev + input)
    }
  })

  return (
    <Box flexDirection="column" marginTop={1}>
      <Box>
        <Text color={purple.primaryBright} bold>
          {multiline ? '┌─' : '▸'}
        </Text>
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
      {multiline && (
        <Text color={purple.textMuted}>└─ 多行模式 (Ctrl+J 退出，Enter 换行，Ctrl+Enter 提交)</Text>
      )}
    </Box>
  )
}
