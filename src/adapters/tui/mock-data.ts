/**
 * Mock 数据 - 用于 TUI 演示
 * 后续接入 Agent Core 后替换为真实数据
 */
import type { ChatMessage, PlanInfo, ConfirmRequest, StatusInfo, ToolCall } from './types.js'

let idCounter = 0
const nextId = () => `msg-${++idCounter}`

export const mockMessages: ChatMessage[] = [
  {
    id: nextId(),
    role: 'user',
    content: '构建一个小说生成平台',
    timestamp: Date.now(),
  },
  {
    id: nextId(),
    role: 'assistant',
    content:
      '我来帮你构建一个小说生成平台。这是一个多模块项目，我先探索当前目录结构，然后制定计划。',
    timestamp: Date.now(),
  },
  {
    id: nextId(),
    role: 'assistant',
    content: '探索完成后，我制定了以下计划：',
    timestamp: Date.now(),
    toolCalls: [
      {
        id: 'tc-1',
        name: 'Glob',
        args: { pattern: '**/*' },
        argsDisplay: '**/*',
      },
      {
        id: 'tc-2',
        name: 'Read',
        args: { path: 'package.json' },
        argsDisplay: 'package.json',
      },
      {
        id: 'tc-3',
        name: 'Write',
        args: { path: '~/.mozil/plans/novel-platform.md' },
        argsDisplay: '~/.mozil/plans/novel-platform.md',
      },
    ],
  },
  {
    id: nextId(),
    role: 'tool',
    content: 'Glob: 0 files found',
    timestamp: Date.now(),
  },
  {
    id: nextId(),
    role: 'tool',
    content: 'Read: file not found',
    timestamp: Date.now(),
  },
  {
    id: nextId(),
    role: 'tool',
    content: 'Plan saved to ~/.mozil/plans/novel-platform.md',
    timestamp: Date.now(),
  },
]

export const mockPlan: PlanInfo = {
  title: '构建小说生成平台',
  savedAt: '2026-06-30 22:00',
  filePath: '~/.mozil/plans/novel-platform.md',
  steps: [
    {
      id: 'step-1',
      title: '初始化项目结构（前端 + 后端 + 数据库 schema）',
      status: 'completed',
    },
    {
      id: 'step-2',
      title: '实现后端核心 API（小说生成接口，调 LLM）',
      status: 'in-progress',
    },
    {
      id: 'step-3',
      title: '实现用户认证模块（注册/登录/JWT）',
      status: 'pending',
    },
    {
      id: 'step-4',
      title: '实现小说管理 CRUD（保存/查询/删除）',
      status: 'pending',
    },
    {
      id: 'step-5',
      title: '实现前端界面（生成页 + 书架页 + 登录页）',
      status: 'pending',
    },
    {
      id: 'step-6',
      title: '联调 + 基础测试',
      status: 'pending',
    },
  ],
}

export const mockConfirmRequest: ConfirmRequest = {
  id: 'confirm-1',
  type: 'run_shell',
  toolName: 'Bash',
  targets: ['mkdir -p frontend backend && cd frontend && npm init -y'],
  description: '执行 Shell 命令初始化项目结构',
  riskLevel: 'medium',
}

export const mockStatus: StatusInfo = {
  model: 'claude-sonnet-4',
  mode: 'plan',
  cwd: '~/projects/novel-platform',
  contextUsed: 12,
  cost: 0.04,
  turn: 3,
}

export const mockToolCalls: Array<{ call: ToolCall; status: 'success' | 'running' | 'pending' }> = [
  {
    call: { id: 'tc-1', name: 'Glob', args: { pattern: '**/*' }, argsDisplay: '**/*' },
    status: 'success',
  },
  {
    call: { id: 'tc-2', name: 'Read', args: { path: 'package.json' }, argsDisplay: 'package.json' },
    status: 'success',
  },
  {
    call: {
      id: 'tc-3',
      name: 'Write',
      args: { path: '~/.mozil/plans/novel-platform.md' },
      argsDisplay: '~/.mozil/plans/novel-platform.md',
    },
    status: 'success',
  },
]
