/**
 * Tool Registry - 工具注册表
 *
 * 职责：
 * - 注册工具（启动时一次性注册所有工具）
 * - 按 name 查找工具
 * - 导出所有工具的 ToolDefinition（给 LLM）
 *
 * core 只依赖 AgentToolPort 接口，不依赖具体工具实现。
 */

import type { AgentToolPort } from './ports/tool.port.js'
import { toolToDefinition } from './ports/tool.port.js'
import type { ToolDefinition } from './ports/llm.port.js'

export class ToolRegistry {
  private tools = new Map<string, AgentToolPort>()

  /** 注册工具 */
  register(tool: AgentToolPort): void {
    if (this.tools.has(tool.name)) {
      throw new Error(`Tool already registered: ${tool.name}`)
    }
    this.tools.set(tool.name, tool)
  }

  /** 按 name 查找工具 */
  get(name: string): AgentToolPort | undefined {
    return this.tools.get(name)
  }

  /** 是否已注册 */
  has(name: string): boolean {
    return this.tools.has(name)
  }

  /** 导出所有工具的 ToolDefinition（给 LLM） */
  toDefinitions(): ToolDefinition[] {
    return Array.from(this.tools.values()).map(toolToDefinition)
  }

  /** 获取所有已注册工具 */
  list(): AgentToolPort[] {
    return Array.from(this.tools.values())
  }

  /** 已注册工具数量 */
  get size(): number {
    return this.tools.size
  }
}
