# tests

`tests` 用来存放单元测试和集成测试。

## 测试原则

- core 测试不启动 TUI。
- core 测试使用 fake LLM 和 fake tools。
- 工具测试使用临时目录。
- Shell 工具测试必须避免危险命令。

## 推荐测试范围

- Agent Loop。
- Context Manager。
- Message Manager。
- Tool Registry。
- 文件工具路径安全。
- Shell 工具确认和危险命令拦截。
