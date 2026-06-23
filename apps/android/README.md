# Android App

`apps/android` 是 MozilCode 安卓客户端预留目录。

## 定位

安卓端是远程控制入口，不是 Agent 执行端。

它负责：

- 登录。
- 查看任务列表。
- 查看任务事件流。
- 继续输入 prompt。
- 审批或拒绝高风险工具调用。
- 停止任务。
- 查看测试结果和修改摘要。

它不负责：

- 直接读取本地代码文件。
- 直接写文件。
- 直接执行 Shell。
- 直接调用本地工具。
- 保存完整代码上下文。

## 推荐链路

```text
Android App
-> Java Server
-> Secure Relay
-> Local Runtime
-> AgentLoop
-> Tools
```

## 后续技术选型

可选方案：

- 原生 Android：Kotlin + Jetpack Compose。
- 跨端方案：React Native。
- MVP 方案：先用 Mobile Web / PWA 验证，再迁移原生 Android。

第一期建议先不初始化完整 Android 工程，避免过早引入 Gradle、SDK 和 CI 复杂度。
