/**
 * MozilCode 紫色主题系统
 *
 * 色板设计：以紫罗兰为主色，配以青绿/琥珀/珊瑚作为状态色。
 * 终端友好：所有颜色都从 256 色调色板中选取，兼容性最好。
 */

// ===== 核心色板（紫罗兰系）=====
export const purple = {
  // 背景层（从深到浅）
  bgDarkest: '#1a1033', // 最深背景（header/对话框）
  bgDark: '#2d1b69', // 深背景
  bgMid: '#3d2b8c', // 中背景
  bgLight: '#4a3aa8', // 浅背景

  // 主色
  primary: '#7c3aed', // 主紫（按钮、强调）
  primaryBright: '#a78bfa', // 亮紫（高亮文字）
  primaryDim: '#5b21b6', // 暗紫（次要元素）

  // 文字层
  textOnPurple: '#f3f0ff', // 紫底上的文字
  textPrimary: '#e9d5ff', // 主文字（浅紫白）
  textSecondary: '#c4b5fd', // 次要文字
  textMuted: '#8b5cf6', // 弱化文字

  // 边框
  border: '#6d28d9', // 普通边框
  borderBright: '#a78bfa', // 高亮边框
} as const

// ===== 状态色（互补色）=====
export const status = {
  success: '#10b981', // 翠绿（完成、成功）
  error: '#ef4444', // 珊瑚红（错误、失败）
  warning: '#f59e0b', // 琥珀黄（警告、待确认）
  info: '#06b6d4', // 青蓝（信息、进行中）
  neutral: '#6b7280', // 中性灰
} as const

// ===== 工具状态色 =====
export const toolStatus = {
  pending: purple.textMuted, // 排队中（暗紫）
  running: status.info, // 执行中（青蓝）
  success: status.success, // 完成（翠绿）
  error: status.error, // 出错（珊瑚红）
  denied: status.warning, // 被拒绝（琥珀黄）
} as const

// ===== Plan 模式色 =====
export const planMode = {
  accent: '#8b5cf6', // Plan 模式标志色（亮紫）
  bgActive: '#2d1b69', // Plan 模式激活背景
  stepDone: status.success, // 已完成步骤
  stepCurrent: purple.primaryBright, // 当前步骤
  stepPending: purple.textMuted, // 未开始步骤
} as const

// ===== Logo（ASCII Art）=====
export const LOGO = `
█ ░ ░   █ █   █ █   ░ █ ░
█ ▄ ▀   █ █   █ █   ▀ █ ▀
█ █ █   █ █   █ █   █ █ █
█ █ █   █ █   █ █   █ █ █
░ ░ ░   ░ ░   ░ ░   ░ ░ ░
`

// 简短 Logo（用于状态栏）
export const LOGO_MINI = '◆ MozilCode'

// ===== 主题组合导出 =====
export const theme = {
  purple,
  status,
  toolStatus,
  planMode,
  LOGO,
  LOGO_MINI,
} as const

export type Theme = typeof theme
