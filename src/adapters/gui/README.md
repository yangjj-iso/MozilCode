# adapters/gui

`gui` 是未来图形界面适配器预留目录。

## 未来方向

- Electron + React。
- WebView 聊天界面。
- 文件 diff 预览。
- 工具调用时间线。
- 项目结构浏览。
- 手机 H5/PWA 控制端。
- 远程任务监控和审批页面。

## 当前状态

第一期 MVP 不实现 GUI。当前目录只用于保留架构扩展点。

## 边界

GUI 和 TUI 一样，只是外壳。它应该复用同一个 `core`、`tools` 和 `providers`，不能复制一套 Agent 逻辑。

## 手机端方向

如果先做移动端，建议优先做 Web/PWA，而不是直接做原生 App。第一版只需要：

- 任务列表。
- 任务事件流。
- prompt 输入。
- 工具审批。
- 停止任务。

所有真实执行仍然发生在本地 Runtime。
