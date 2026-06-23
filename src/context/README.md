# context

`context` 是项目感知模块，用来帮助 Agent 理解当前代码库。

## 职责

- 代码搜索。
- AST 分析。
- 文档分块。
- RAG 索引。
- 提取项目结构摘要。

## MVP 范围

第一期先不做完整 RAG 和 AST 重构，只保留最小能力：

- 基于 grep 的关键词搜索。
- 直接读取相关文件。
- 由 `context-manager` 组装近期上下文。

## 未来文件规划

- `grep-engine.ts`: 封装 ripgrep。
- `ast-parser.ts`: 定位函数、类、导入导出。
- `rag-indexer.ts`: 文档分块和索引。

## 边界

`context` 负责发现和整理信息，不负责直接修改文件。
