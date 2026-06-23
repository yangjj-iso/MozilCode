# MozilCode

MozilCode 是一个本地终端 Coding Agent 项目。用户在终端输入自然语言任务，Agent 可以理解项目、读取文件、搜索代码、修改文件、运行命令，并在高风险操作前请求用户确认。

## 当前阶段

当前仓库处于项目初始化阶段，只保留 TypeScript 配置和模块目录结构。业务代码会按 MVP 计划逐步补齐。

## MVP 模块

- `src/core`: Agent 核心循环、上下文、消息和事件。
- `src/core/ports`: 核心层依赖的抽象接口。
- `src/tools`: 本地文件、Shell、代码搜索等工具实现。
- `src/providers`: LLM SDK 适配层。
- `src/adapters`: UI 外壳适配层，第一期先做 TUI。
- `src/runtime`: 本地 Agent Host，负责承载长期任务线程和连接云端控制面。
- `src/context`: 项目感知能力，后续承载 grep、AST、RAG。
- `src/memory`: 长期记忆，MVP 暂不实现。
- `src/auth`: 登录、套餐、配额，商业化阶段再实现。
- `src/store`: UI 状态管理，不能反向污染 core。
- `apps/android`: 安卓客户端预留目录，作为手机远程控制入口。
- `server`: Java 云端控制面，负责账号、设备、任务同步、审批、审计和配额。

## 远程控制方向

MozilCode 后续可以支持手机端操控任务。这个能力不是让手机直接访问本地文件或执行 Shell，而是采用控制端和执行端分离：

```text
手机 / Web 控制端
-> Java 云端控制面
-> 本地 MozilCode Runtime
-> AgentLoop
-> 本地 Tools
```

手机端只负责查看任务、继续输入、审批高风险操作和停止任务。真实文件读写、Shell 执行和项目上下文访问只能发生在本地 Runtime。

## 设计原则

- `core` 只依赖接口，不依赖 UI、SDK、Shell 或文件系统细节。
- 工具执行必须经过统一注册和风险判断。
- 写文件、删除文件、执行 Shell 命令必须由用户确认。
- Provider 可以替换，Agent Core 不绑定具体模型厂商。
- TUI/GUI 是外壳，不能把渲染逻辑写进核心推理循环。
- 手机端、TUI、GUI 都只是控制入口，不能绕过 Runtime 和 Agent Core 直接执行工具。
- Java 云端负责控制面，不默认保存完整代码内容。

## 常用命令

```bash
npm install
npm run typecheck
```
