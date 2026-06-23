# runtime

`runtime` 是本地 Agent 运行时层，也可以理解为 MozilCode 的本地执行宿主。

## 为什么需要 runtime

TUI 只能覆盖本机终端交互。如果未来要支持手机端查看和操控任务，就需要一个长期存在的本地 Runtime：

```text
手机端
-> Java 云端控制面
-> 本地 Runtime
-> AgentLoop
-> Tools
```

Runtime 是手机端和本地项目之间的安全隔离层。手机端不能直接执行工具，必须通过 Runtime 进入 Agent Core。

## 职责

- 管理本地工作区。
- 创建和恢复任务线程。
- 启动 Agent Loop。
- 维护本地事件日志。
- 接收云端下发的继续任务、停止任务、审批结果。
- 将 Agent 状态、工具调用、审批请求同步给云端。
- 执行本地安全策略，例如路径限制和工具权限。

## 未来文件规划

- `local-agent-host.ts`: 本地常驻宿主。
- `workspace-registry.ts`: 管理可被 Agent 使用的工作区。
- `thread-session.ts`: 管理单个任务线程的生命周期。
- `cloud-relay-client.ts`: 和 Java 云端建立安全连接。

## 不负责什么

- 不负责用户登录页面。
- 不负责套餐计费。
- 不负责模型供应商选择策略。
- 不直接渲染手机 UI。

这些能力应该放在 Java 云端或对应 Adapter 中。
