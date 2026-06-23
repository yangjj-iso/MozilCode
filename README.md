# MozilCode

MozilCode 是一个本地终端 Coding Agent 项目。目标是做出类似 Claude Code 的开发体验：用户在终端输入自然语言任务，Agent 可以理解项目、读取文件、搜索代码、修改文件、运行命令，并在高风险操作前请求用户确认。

## 当前阶段

当前仓库处于项目初始化阶段，只保留 TypeScript 配置和模块目录结构。业务代码会按 MVP 计划逐步补齐。

## MVP 模块

- `src/core`: Agent 核心循环、上下文、消息和事件。
- `src/core/ports`: 核心层依赖的抽象接口。
- `src/tools`: 本地文件、Shell、代码搜索等工具实现。
- `src/providers`: LLM SDK 适配层。
- `src/adapters`: UI 外壳适配层，第一期先做 TUI。
- `src/context`: 项目感知能力，后续承载 grep、AST、RAG。
- `src/memory`: 长期记忆，MVP 暂不实现。
- `src/auth`: 登录、套餐、配额，商业化阶段再实现。
- `src/store`: UI 状态管理，不能反向污染 core。

## 设计原则

- `core` 只依赖接口，不依赖 UI、SDK、Shell 或文件系统细节。
- 工具执行必须经过统一注册和风险判断。
- 写文件、删除文件、执行 Shell 命令必须由用户确认。
- Provider 可以替换，Agent Core 不绑定具体模型厂商。
- TUI/GUI 是外壳，不能把渲染逻辑写进核心推理循环。

## 常用命令

```bash
npm install
npm run typecheck
```
