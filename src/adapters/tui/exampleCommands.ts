/**
 * Placeholder 示例命令 - 模仿 cc-haha 的 exampleCommands.ts
 * 输入框 placeholder 轮换显示
 */

export const EXAMPLE_COMMANDS = [
  'Try "fix lint errors"',
  'Try "how does auth work?"',
  'Try "refactor the utils module"',
  'Try "add unit tests for server.ts"',
  'Try "explain the agent loop"',
  'Try "find all TODO comments"',
  'Try "build a novel platform"',
  'Try "review my recent commits"',
] as const

/** 随机选一个 placeholder */
export function getRandomPlaceholder(): string {
  return EXAMPLE_COMMANDS[Math.floor(Math.random() * EXAMPLE_COMMANDS.length)]
}
