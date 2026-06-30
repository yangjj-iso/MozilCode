/**
 * list-directory 工具 - 列出目录内容
 */

import * as fs from 'node:fs/promises'
import * as path from 'node:path'
import type {
  AgentToolPort,
  ToolExecutionContext,
  ToolExecutionResult,
} from '../core/ports/tool.port.js'

export class ListDirectoryTool implements AgentToolPort {
  readonly name = 'list_directory'
  readonly description =
    'List the contents of a directory. Returns file and folder names with types. ' +
    'Use this to explore the project structure. ' +
    'Path can be absolute or relative to the workspace root.'
  readonly parameters = {
    type: 'object',
    properties: {
      path: {
        type: 'string',
        description: 'Directory path to list. Defaults to workspace root (.). Can be absolute or relative.',
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
    const dirPath = String(args.path || '.')

    try {
      const resolved = path.isAbsolute(dirPath)
        ? dirPath
        : path.resolve(context.cwd, dirPath)

      const entries = await fs.readdir(resolved, { withFileTypes: true })
      const lines = entries.map(entry => {
        const type = entry.isDirectory() ? '[DIR] ' : entry.isFile() ? '     ' : '[???]'
        return `${type} ${entry.name}`
      })

      return {
        success: true,
        content: lines.length > 0
          ? `Contents of ${dirPath}:\n${lines.join('\n')}`
          : `(empty directory: ${dirPath})`,
        executionTimeMs: Date.now() - start,
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      let friendly = msg
      if (msg.includes('ENOENT')) friendly = `Directory not found: ${dirPath}`
      if (msg.includes('EACCES')) friendly = `Permission denied: ${dirPath}`
      if (msg.includes('ENOTDIR')) friendly = `Not a directory: ${dirPath}`

      return {
        success: false,
        content: '',
        error: friendly,
        executionTimeMs: Date.now() - start,
      }
    }
  }
}
