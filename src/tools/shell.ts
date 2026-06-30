/**
 * shell 工具 - 执行终端命令
 *
 * 带危险命令拦截，高风险操作需要确认（MVP 暂不实现确认，先拦截明显危险的命令）
 */

import { exec } from 'node:child_process'
import { promisify } from 'node:util'
import * as path from 'node:path'
import type {
  AgentToolPort,
  ToolExecutionContext,
  ToolExecutionResult,
} from '../core/ports/tool.port.js'

const execAsync = promisify(exec)

const MAX_OUTPUT = 10000 // 10KB
const MAX_TIMEOUT = 30000 // 30s

// 危险命令模式（自动拒绝）
const DANGEROUS_PATTERNS = [
  /rm\s+-rf?\s+[/~]/i,        // rm -rf / 或 rm -rf ~
  /mkfs/i,                      // 格式化
  /dd\s+if=/i,                  // dd 写入
  /\:\(\)\s*\{\s*:\|:&\s*\}\s*;:/, // fork bomb
  />\s*\/dev\/sd[a-z]/i,       // 写入磁盘设备
  /shutdown|reboot|halt/i,     // 关机重启
]

export class ShellTool implements AgentToolPort {
  readonly name = 'exec_command'
  readonly description =
    'Execute a shell command and return stdout/stderr. ' +
    'Use this to run commands like ls, git, npm, grep, find, etc. ' +
    'The command runs in the workspace root directory. ' +
    'Output is limited to 10KB and timeout is 30 seconds.'
  readonly parameters = {
    type: 'object',
    properties: {
      command: {
        type: 'string',
        description: 'The shell command to execute.',
      },
      cwd: {
        type: 'string',
        description: 'Working directory for the command. Defaults to workspace root.',
      },
    },
    required: ['command'],
  }
  readonly readonly = false
  readonly riskLevel = 'medium' as const

  async execute(
    args: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<ToolExecutionResult> {
    const start = Date.now()
    const command = String(args.command || '')

    if (!command) {
      return {
        success: false,
        content: '',
        error: 'Missing required argument: command',
        executionTimeMs: Date.now() - start,
      }
    }

    // 危险命令拦截
    for (const pattern of DANGEROUS_PATTERNS) {
      if (pattern.test(command)) {
        return {
          success: false,
          content: '',
          error: `Blocked: command matches dangerous pattern. If this is a mistake, please modify the command.`,
          executionTimeMs: Date.now() - start,
        }
      }
    }

    const cwd = args.cwd
      ? (path.isAbsolute(String(args.cwd))
          ? String(args.cwd)
          : path.resolve(context.cwd, String(args.cwd)))
      : context.cwd

    try {
      const { stdout, stderr } = await execAsync(command, {
        cwd,
        maxBuffer: MAX_OUTPUT,
        timeout: MAX_TIMEOUT,
        signal: context.signal,
      })

      let output = ''
      if (stdout) output += stdout
      if (stderr) output += (output ? '\n[stderr]\n' : '[stderr]\n') + stderr

      // 截断超长输出
      if (output.length > MAX_OUTPUT) {
        output = output.slice(0, MAX_OUTPUT) + '\n... (output truncated)'
      }

      return {
        success: true,
        content: output || '(no output)',
        executionTimeMs: Date.now() - start,
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)

      // 命令执行失败但可能有 stderr 输出
      const errorOutput = (err as { stderr?: string }).stderr || msg

      return {
        success: false,
        content: errorOutput.slice(0, MAX_OUTPUT) || msg,
        error: `Command failed: ${command}`,
        executionTimeMs: Date.now() - start,
      }
    }
  }
}
