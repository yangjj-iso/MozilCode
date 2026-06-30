import React from 'react'
import { Text, Box } from 'ink'
import wrap from 'word-wrap'
import { purple } from '../theme.js'

// 终端内容可用宽度（预留左侧圆点和边距）
const LINE_WIDTH = 72

interface MarkdownTextProps {
  text: string
  color?: string
}

type Token =
  | { type: 'text'; content: string }
  | { type: 'bold'; content: string }
  | { type: 'italic'; content: string }
  | { type: 'code'; content: string }

/**
 * 轻量 Markdown 渲染器
 *
 * 支持：
 * - 标题 # / ## / ### （加粗）
 * - 有序列表 1. 2.
 * - 无序列表 - / *
 * - 行内加粗 **text**
 * - 行内斜体 *text* / _text_
 * - 行内代码 `code`（紫色）
 * - 按单词换行，避免英文在行首只剩单个字母
 */
export const MarkdownText: React.FC<MarkdownTextProps> = ({
  text,
  color = purple.textPrimary,
}) => {
  const lines = text.split('\n')
  return (
    <Box flexDirection="column">
      {lines.map((line, i) => (
        <MarkdownLine key={i} line={line} color={color} />
      ))}
    </Box>
  )
}

const MarkdownLine: React.FC<{ line: string; color: string }> = ({ line, color }) => {
  // 空行
  if (!line.trim()) {
    return <Text color={color}> </Text>
  }

  // 标题 # / ## / ###
  const headingMatch = line.match(/^(#{1,3})\s+(.+)$/)
  if (headingMatch) {
    const level = headingMatch[1].length
    const indent = '  '.repeat(level - 1)
    const wrapped = wrapWords(headingMatch[2], LINE_WIDTH - 4)
    return (
      <Box flexDirection="column">
        {wrapped.map((row, i) => (
          <Text key={i}>
            <Text color={color}>{i === 0 ? indent : '  '}</Text>
            <InlineMarkdown text={row} color={color} bold />
          </Text>
        ))}
      </Box>
    )
  }

  // 列表项：1. / - / * 开头
  const listMatch = line.match(/^(\s*)(\d+\.\s+|[-*]\s+)(.+)$/)
  if (listMatch) {
    const indent = listMatch[1]
    const marker = listMatch[2]
    const content = listMatch[3]
    const wrapped = wrapWords(content, LINE_WIDTH - indent.length - marker.length - 2)
    return (
      <Box flexDirection="column">
        {wrapped.map((row, i) => (
          <Box key={i}>
            <Text color={purple.textMuted}>{i === 0 ? `${indent}${marker}` : `${indent}  `}</Text>
            <InlineMarkdown text={row} color={color} />
          </Box>
        ))}
      </Box>
    )
  }

  // 普通段落
  const wrapped = wrapWords(line, LINE_WIDTH)
  return (
    <Box flexDirection="column">
      {wrapped.map((row, i) => (
        <InlineMarkdown key={i} text={row} color={color} />
      ))}
    </Box>
  )
}

const InlineMarkdown: React.FC<{ text: string; color: string; bold?: boolean }> = ({
  text,
  color,
  bold = false,
}) => {
  const tokens = parseInline(text)
  return (
    <Text>
      {tokens.map((tok, i) => {
        if (tok.type === 'bold') {
          return (
            <Text key={i} bold color={color}>
              {tok.content}
            </Text>
          )
        }
        if (tok.type === 'italic') {
          return (
            <Text key={i} italic color={color}>
              {tok.content}
            </Text>
          )
        }
        if (tok.type === 'code') {
          return (
            <Text key={i} color={purple.primary}>
              {tok.content}
            </Text>
          )
        }
        return (
          <Text key={i} bold={bold} color={color}>
            {tok.content}
          </Text>
        )
      })}
    </Text>
  )
}

function parseInline(text: string): Token[] {
  const tokens: Token[] = []
  // 匹配 **bold** / *italic* / `code` / _italic_
  const regex = /(\*\*(.*?)\*\*|\*(.*?)\*|`(.*?)`|_(.*?)_)/g
  let last = 0
  let match

  while ((match = regex.exec(text)) !== null) {
    const before = text.slice(last, match.index)
    if (before) {
      tokens.push({ type: 'text', content: before })
    }

    const full = match[0]
    const bold = match[2]
    const italicA = match[3]
    const code = match[4]
    const italicB = match[5]

    if (bold !== undefined) {
      tokens.push({ type: 'bold', content: bold })
    } else if (italicA !== undefined) {
      tokens.push({ type: 'italic', content: italicA })
    } else if (code !== undefined) {
      tokens.push({ type: 'code', content: code })
    } else if (italicB !== undefined) {
      tokens.push({ type: 'italic', content: italicB })
    }

    last = match.index + full.length
  }

  const tail = text.slice(last)
  if (tail) {
    tokens.push({ type: 'text', content: tail })
  }

  return tokens
}

function wrapWords(text: string, width: number): string[] {
  if (text.length <= width) return [text]
  const result = wrap(text, {
    width,
    trim: true,
    indent: '',
    cut: false,
  })
  return result.split('\n')
}
