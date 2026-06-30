#!/usr/bin/env node
/**
 * MozilCode TUI 入口
 * 运行：npx tsx src/adapters/tui/index.tsx
 */
import React from 'react'
import { render } from 'ink'
import App from './App.js'

// 启动时清空终端之前的所有输出
process.stdout.write('\u001B[2J\u001B[3J\u001B[H')

render(React.createElement(App))
