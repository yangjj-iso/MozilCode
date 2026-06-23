# adapters

`adapters` 是外部交互适配层。它负责把核心事件展示给用户，并把用户输入传给 Agent Core。

## 子模块

- `tui`: 终端 UI，第一期 MVP 使用。
- `gui`: 图形界面，未来阶段预留。
- `mobile-web`: 手机 H5/PWA 控制端，未来阶段可以独立成 app。
- `relay`: 本地 Runtime 和云端通信的适配器，未来阶段预留。

## 职责

- 读取用户输入。
- 渲染 Agent 输出。
- 展示工具调用状态。
- 展示确认提示。
- 将用户确认结果返回给 core。
- 远程控制场景下，展示任务线程、审批队列和事件流。

## 边界

Adapter 可以依赖 core 的接口和事件类型，但 core 不能依赖 adapter。

正确方向：

```text
TUI -> AgentLoop
AgentLoop -> EventBus
TUI 订阅 EventBus
```

错误方向：

```text
core -> TUI component
```

## 手机控制任务

手机端 Adapter 只能做控制面展示和输入：

- 查看任务状态。
- 继续输入 prompt。
- 审批或拒绝写文件、执行命令。
- 停止任务。

它不能直接读写本地文件，也不能直接执行 Shell。
