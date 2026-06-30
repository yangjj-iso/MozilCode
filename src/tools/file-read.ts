/**
 * file-read 工具 - 读取本地文件内容
 *
 * 第一个工具实现，用于验证 Agent Loop 端到端链路。
 */

import * as fs from 'node:fs/promises'
import * as path from 'node:path'
import type {
  AgentToolPort,
  ToolExecutionContext,
  ToolExecutionResult,
} from '../core/ports/tool.port.js'

const MAX_FILE_SIZE = 1024 * 1024 // 1MB
const MAX_OUTPUT_LINES = 2000

export class FileReadTool implements AgentToolPort {
  readonly name = 'read_file'
  readonly description =
    'Read the contents of a local file. Returns the file content as text. ' +
    'Use this to inspect source code, config files, or any text file. ' +
    'Path can be absolute or relative to the workspace root.'
  readonly parameters = {
    type: 'object',
    properties: {
      path: {
        type: 'string',
        description: 'Path to the file to read. Can be absolute or relative to workspace root.',
      },
      offset: {
        type: 'number',
        description: 'Line number to start reading from (1-based, default 1).',
      },
      limit: {
        type: 'number',
        description: 'Maximum number of lines to read (default 2000).',
      },
    },
    required: ['path'],
  }
  readonly readonly = true
  readonly riskLevel = 'low' as const

  async execute(
    args: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<ToolExecutionResult> {
    const start = Date.now()
    const filePath = String(args.path || '')
    const offset = Number(args.offset || 1)
    const limit = Number(args.limit || MAX_OUTPUT_LINES)

    if (!filePath) {
      return {
        success: false,
        content: '',
        error: 'Missing required argument: path',
        executionTimeMs: Date.now() - start,
      }
    }

    try {
      // 解析路径（相对路径基于 cwd）
      const resolved = path.isAbsolute(filePath)
        ? filePath
        : path.resolve(context.cwd, filePath)

      // 安全校验：禁止读取工作区外的敏感文件（MVP 简化版，后续用 path-validator）
      // if (!isInsideWorkspace(resolved, context.cwd)) {
      //   return { success: false, content: '', error: 'Path outside workspace' }
      // }

      // 读取文件
      const stat = await fs.stat(resolved)
      if (stat.size > MAX_FILE_SIZE) {
        return {
          success: false,
          content: '',
          error: `File too large: ${stat.size} bytes (max ${MAX_FILE_SIZE})`,
          executionTimeMs: Date.now() - start,
        }
      }

      const content = await fs.readFile(resolved, 'utf-8')
      const lines = content.split('\n')

      // 应用 offset 和 limit
      const startLine = Math.max(0, offset - 1)
      const endLine = Math.min(lines.length, startLine + limit)
      const sliced = lines.slice(startLine, endLine)

      // 加行号（模仿 cat -n）
      const numbered = sliced
        .map((line, i) => `${String(startLine + i + 1).padStart(6)}\t${line}`)
        .join('\n')

      return {
        success: true,
        content: numbered || '(empty file)',
        executionTimeMs: Date.now() - start,
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      let friendly = msg
      if (msg.includes('ENOENT')) friendly = `File not found: ${filePath}`
      if (msg.includes('EACCES')) friendly = `Permission denied: ${filePath}`
      if (msg.includes('EISDIR')) friendly = `Is a directory, not a file: ${filePath}`

      return {
        success: false,
        content: '',
        error: friendly,
        executionTimeMs: Date.now() - start,
      }
    }
  }
}
