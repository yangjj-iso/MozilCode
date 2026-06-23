# adapters/gui

`gui` 是未来图形界面适配器预留目录。

## 未来方向

- Electron + React。
- WebView 聊天界面。
- 文件 diff 预览。
- 工具调用时间线。
- 项目结构浏览。

## 当前状态

第一期 MVP 不实现 GUI。当前目录只用于保留架构扩展点。

## 边界

GUI 和 TUI 一样，只是外壳。它应该复用同一个 `core`、`tools` 和 `providers`，不能复制一套 Agent 逻辑。
