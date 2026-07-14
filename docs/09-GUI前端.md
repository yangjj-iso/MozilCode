# 09 - GUI 前端

## 1. 概述

GUI 是一个基于 Vue 3 + Vite 的单页应用，作为 MozilCode Daemon 的 Web 前端。它通过 HTTP REST API 和 WebSocket 与 Daemon 通信，提供聊天界面、会话管理、设置面板等功能。同时支持通过 Tauri 打包为桌面应用。

对应代码：`mozilcode-gui/`

## 2. 基础概念

### 2.1 Vue 3

Vue 3 是一个渐进式 JavaScript 框架，用于构建用户界面。核心特性：

- **响应式数据**：数据变化自动更新视图
- **组件化**：UI 拆分为可复用的组件
- **模板语法**：用 HTML 模板 + 指令声明式渲染

```javascript
import { createApp, ref, computed } from 'vue';

const app = createApp({
  setup() {
    // ref: 响应式数据
    const count = ref(0);
    // computed: 计算属性
    const doubled = computed(() => count.value * 2);

    function increment() {
      count.value++;
    }

    return { count, doubled, increment };
  }
});
app.mount('#app');
```

### 2.2 Vite

Vite 是一个现代化的前端构建工具，特点是开发时极速热更新（HMR）。它用原生 ES Module 做开发服务器，不需要打包。

```javascript
// vite.config.js
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const daemonTarget = env.VITE_MOZILCODE_DAEMON_HTTP || 'http://127.0.0.1:7800';

  return {
    plugins: [vue()],
    server: {
      port: 1420,
      proxy: {
        '/api': {
          target: daemonTarget,  // 将 /api 请求代理到 daemon
          changeOrigin: true,
          ws: true,              // 支持 WebSocket 代理
        },
      },
    },
  };
});
```

### 2.3 WebSocket 浏览器 API

浏览器原生支持 WebSocket：

```javascript
// 创建连接
const ws = new WebSocket('ws://127.0.0.1:7800/api/stream/session123');

// 连接打开
ws.onopen = () => { console.log('connected'); };

// 接收消息
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('收到事件:', data);
};

// 连接关闭
ws.onclose = () => { console.log('disconnected'); };

// 发送消息
ws.send(JSON.stringify({ action: 'cancel' }));
```

### 2.4 Tauri

Tauri 是一个用 Rust 构建桌面应用的框架，类似 Electron 但更轻量。它用系统 WebView 渲染前端，不需要打包整个 Chromium。

```
mozilcode-gui/src-tauri/
├── Cargo.toml          # Rust 依赖
├── tauri.conf.json     # Tauri 配置
├── src/
│   ├── main.rs         # Rust 入口
│   └── lib.rs          # Rust 逻辑
└── capabilities/
    └── default.json    # 权限配置
```

## 3. 项目结构

```
mozilcode-gui/
├── index.html              # HTML 入口
├── package.json            # Node.js 依赖
├── vite.config.js          # Vite 配置（含代理）
├── src/
│   ├── main.js             # JS 入口（创建 Vue 应用）
│   ├── App.vue             # 主组件（4000+ 行，包含全部 UI 和逻辑）
│   └── style.css           # 全局样式
└── src-tauri/              # Tauri 桌面打包配置
    ├── tauri.conf.json
    ├── Cargo.toml
    └── src/
        ├── main.rs
        └── lib.rs
```

### 依赖说明

```json
{
  "dependencies": {
    "vue": "^3.5.0",                    // Vue 3 框架
    "marked": "^18.0.5",                 // Markdown 解析
    "marked-highlight": "^2.2.4",        // Markdown 代码高亮
    "highlight.js": "^11.11.1",          // 语法高亮
    "dompurify": "^3.4.11",             // HTML 消毒（防 XSS）
    "@tauri-apps/plugin-dialog": "^2.7.1" // Tauri 文件对话框
  },
  "devDependencies": {
    "vite": "^6.0.0",                   // 构建工具
    "@vitejs/plugin-vue": "^5.0.0",     // Vue 编译插件
    "@tauri-apps/cli": "^2.0.0"         // Tauri CLI
  }
}
```

## 4. 应用架构

`App.vue` 是唯一的组件，包含整个应用。虽然 4000+ 行很大，但结构清晰：

```
App.vue
├── <template>           # HTML 模板（~300 行）
│   ├── .sidebar         # 左侧栏：会话列表
│   ├── .main            # 主区域：聊天 + 输入框
│   │   ├── .topbar      # 顶栏：工作区名称
│   │   ├── .chat        # 聊天区域
│   │   └── .input-area  # 输入区域
│   ├── .rightbar        # 右侧栏：文件树、运行状态、工作树、详情
│   └── .settings-overlay # 设置弹窗
│
├── <script setup>       # JavaScript 逻辑（~3500 行）
│   ├── 响应式状态         # ref / reactive
│   ├── WebSocket 处理    # 连接、消息处理、重连
│   ├── API 调用          # HTTP 请求封装
│   ├── 事件处理          # handleEvent()
│   ├── Markdown 渲染    # marked + highlight.js
│   └── 生命周期          # onMounted, watch
│
└── <style scoped>       # CSS 样式（~800 行）
```

## 5. 响应式状态

```javascript
// 核心状态
const messages = ref([]);           // 聊天消息列表
const inputText = ref('');          // 输入框文本
const busy = ref(false);            // Agent 是否正在工作
const connected = ref(false);       // WebSocket 是否连接
const activeSessionId = ref(null);  // 当前会话 ID
const perm = ref(null);             // 当前权限请求
const ask = ref(null);              // 当前用户提问
const tokenInfo = ref({});          // Token 用量信息
const sessionStatus = ref({});      // 会话状态

// 设置面板
const settingsOpen = ref(false);    // 设置弹窗是否打开
const configForm = ref({});         // 模型配置表单
const skillsList = ref([]);         // 技能列表
const mcpServers = ref([]);         // MCP 服务器列表
```

## 6. WebSocket 事件流

### 6.1 连接管理

```javascript
let ws = null;
let _wsGen = 0;           // WebSocket 代次（防止旧连接事件干扰）
let _replaying = true;    // 是否正在回放历史

function connectWs(sid) {
  if (ws) { ws._dead = true; ws.close(); }

  const gen = ++_wsGen;
  messages.value = [];     // 清空消息，从事件日志重建
  _replaying = true;       // 回放模式下忽略历史权限请求

  ws = new WebSocket(`${WS_URL}/api/stream/${sid}`);
  ws._gen = gen;
  ws._dead = false;

  ws.onopen = () => {
    connected.value = true;
  };

  ws.onmessage = (ev) => {
    if (ws._gen !== gen) return;  // 忽略旧连接的事件
    const data = JSON.parse(ev.data);

    // 会话不存在（daemon 重启等）
    if (data.type === 'SessionNotFound') {
      ws._dead = true;
      handleDeadSession();
      return;
    }

    handleEvent(data);  // 分发到事件处理器
  };

  ws.onclose = () => {
    connected.value = false;
    if (!ws._dead && activeSessionId.value === sid) {
      setTimeout(() => reconnect(sid), 1000);  // 自动重连
    }
  };
}
```

### 6.2 事件处理器

`handleEvent()` 是核心事件分发函数，处理来自 Daemon 的所有事件类型：

```javascript
function handleEvent(data) {
  const t = data.type;
  const d = data.data || {};

  if (t === 'UserMessage') {
    // 用户消息（daemon 回放）
    messages.value.push({ role: 'user', content: d.content, ... });
  }
  else if (t === 'StreamText') {
    // LLM 流式文本——逐字追加到当前助手消息
    const m = ensureAssistant();
    const part = ensureTextPart(m);
    m.content += d.text;
    part.text += d.text;
    scheduleRender(part);  // 轻量渲染（流式期间）
    scrollDown();
  }
  else if (t === 'ThinkingText') {
    // LLM 思考过程
    const m = ensureAssistant();
    m.thinking += d.text;
  }
  else if (t === 'ToolUseEvent') {
    // 工具调用开始
    const m = ensureAssistant();
    m.statusText = `正在运行 ${d.tool_name}...`;
    addToolPart(m, {
      id: d.tool_id,
      name: d.tool_name,
      args: d.arguments,
      status: 'running',
    });
  }
  else if (t === 'ToolResultEvent') {
    // 工具调用完成
    const tool = findToolById(d.tool_id);
    if (tool) {
      tool.status = d.is_error ? 'error' : 'done';
      tool.result = d.output;
      tool.elapsed = d.elapsed;
    }
  }
  else if (t === 'PermissionRequest') {
    // 权限请求——弹出确认框
    if (_replaying) return;  // 忽略历史请求
    perm.value = {
      request_id: d.request_id,
      tool_name: d.tool_name,
      description: d.description,
    };
  }
  else if (t === 'UsageEvent') {
    // Token 用量更新
    tokenInfo.value = {
      input: d.context_tokens || d.input_tokens,
      output: d.output_tokens,
    };
  }
  else if (t === 'LoopComplete') {
    // 任务完成
    finalizeAssistant();
    busy.value = false;
    loadStatus();
  }
  else if (t === 'ReplayDone') {
    // 历史回放完成，后续是实时事件
    _replaying = false;
    scrollToBottom();
  }
}
```

### 6.3 事件流程图

```
Daemon (Python)                     GUI (Vue)
    │
    │  WebSocket 连接建立
    │ ←─────────────────────────────  new WebSocket('/api/stream/sid')
    │
    │  回放历史事件
    │ ─────────────────────────────→  { type: 'UserMessage', data: {...} }
    │ ─────────────────────────────→  { type: 'StreamText', data: {...} }
    │ ─────────────────────────────→  { type: 'ToolUseEvent', data: {...} }
    │ ─────────────────────────────→  { type: 'ToolResultEvent', data: {...} }
    │ ─────────────────────────────→  { type: 'ReplayDone' }  ← 回放结束标记
    │
    │  实时事件
    │ ─────────────────────────────→  { type: 'StreamText', data: { text: 'Hello' } }
    │ ─────────────────────────────→  { type: 'StreamText', data: { text: ' world' } }
    │ ─────────────────────────────→  { type: 'ToolUseEvent', data: {...} }
    │ ─────────────────────────────→  { type: 'PermissionRequest', data: {...} }
    │
    │  用户响应权限请求
    │ ←─────────────────────────────  POST /api/permission/sid
    │                                 { request_id, response: 'allow' }
    │
    │  继续实时事件
    │ ─────────────────────────────→  { type: 'ToolResultEvent', data: {...} }
    │ ─────────────────────────────→  { type: 'LoopComplete' }
```

## 7. HTTP API 调用

### 7.1 发送消息

```javascript
async function send() {
  const text = inputText.value.trim();
  if (!text || busy.value || !activeSessionId.value) return;

  // 1. 乐观更新：立即显示用户消息
  messages.value.push({
    role: 'user',
    content: text,
    _optimistic: true,  // 标记为乐观消息
  });

  // 2. 创建助手消息占位
  const pending = ensureAssistant();
  pending.statusText = '正在思考...';
  pending.streaming = true;
  busy.value = true;
  inputText.value = '';

  // 3. 发送 HTTP 请求启动任务
  const r = await fetch(`${API}/api/task`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: activeSessionId.value,
      prompt: text,
    }),
  });

  // 4. 实际的事件通过 WebSocket 接收
  //    HTTP 请求只是触发任务，不等结果
}
```

### 7.2 权限确认

```javascript
async function resolvePerm(response) {
  const rid = perm.value.request_id;
  perm.value = null;  // 立即关闭确认框

  await fetch(`${API}/api/permission/${activeSessionId.value}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      request_id: rid,
      response,  // 'allow' | 'deny' | 'allow_always'
    }),
  });
}
```

### 7.3 配置读写

```javascript
// 读取配置
async function loadConfig() {
  const r = await fetch(`${API}/api/config`);
  const d = await r.json();
  loadConfigIntoForm(d);
}

// 保存配置
async function saveConfig() {
  const r = await fetch(`${API}/api/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(buildConfigPayload()),
  });
}
```

## 8. 消息渲染

### 8.1 消息结构

GUI 中的每条助手消息有复杂的内部结构：

```javascript
{
  role: 'assistant',
  content: '完整文本',
  html: '<p>渲染后的 HTML</p>',
  thinking: '思考过程文本',
  thinkCollapsed: false,
  streaming: true,         // 是否正在流式输出
  statusText: '正在思考...',
  parts: [                 // 消息的组成部分（用于富文本展示）
    {
      id: 'text_1',
      type: 'text',
      text: '文本片段',
      html: '<p>片段 HTML</p>',
    },
    {
      id: 'tool_1',
      type: 'tool',
      tool: {
        id: 'call_abc',
        name: 'ReadFile',
        args: { path: 'main.py' },
        status: 'done',        // running | done | error
        result: '文件内容...',
        elapsed: 0.05,
        expanded: false,
      }
    },
    {
      id: 'compact_1',
      type: 'compact',
      status: 'done',
      title: '上下文已压缩',
      detail: '50K → 15K tokens',
    }
  ]
}
```

### 8.2 Markdown 渲染

使用 `marked` + `highlight.js` + `dompurify` 渲染 Markdown：

```javascript
import { marked } from 'marked';
import { markedHighlight } from 'marked-highlight';
import hljs from 'highlight.js';
import DOMPurify from 'dompurify';

marked.use(markedHighlight({
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang }).value;
    }
    return hljs.highlightAuto(code).value;
  }
}));

function renderMarkdown(text) {
  const rawHtml = marked.parse(text);
  return DOMPurify.sanitize(rawHtml);  // 消毒防 XSS
}
```

### 8.3 流式渲染优化

流式输出时每个 token 都会触发更新，如果每次都做完整的 Markdown 解析会非常卡。解决方案是**轻量渲染 + 延迟完整渲染**：

```javascript
let _renderTimer = null;

function scheduleRender(part) {
  // 流式期间：简单转义，不做 Markdown 解析
  part.html = escapeHtml(part.text);

  // 延迟完整渲染（150ms 内无新 token 则触发）
  clearTimeout(_renderTimer);
  _renderTimer = setTimeout(() => {
    part.html = renderMarkdown(part.text);
  }, 150);
}

function finalizeAssistant() {
  // 流结束：做一次完整渲染
  const m = currentAssistant();
  if (m) {
    m.parts.forEach(part => {
      if (part.type === 'text') {
        part.html = renderMarkdown(part.text);
      }
    });
    m.streaming = false;
    m.statusText = '';
  }
}
```

## 9. 设置面板

设置面板通过 HTTP API 管理 Daemon 的配置：

```
设置面板
├── 模型配置
│   ├── Provider 列表（名称、协议、模型、API Key）
│   ├── 添加/删除 Provider
│   └── 保存到 config.yaml
│
├── 技能管理
│   ├── 技能列表（名称、描述、开关状态）
│   ├── 创建新技能
│   └── 删除技能
│
├── MCP 服务器
│   ├── 服务器列表（名称、命令/URL、开关）
│   ├── 添加/删除服务器
│   └── 开关
│
└── 记忆配置
    ├── Provider 列表
    └── 启用/禁用
```

## 10. 会话管理

### 会话列表

会话按工作目录分组显示：

```javascript
const sessionGroups = computed(() => {
  const groups = {};
  for (const s of sessions.value) {
    const wd = s.work_dir || '(default)';
    if (!groups[wd]) {
      groups[wd] = {
        workDir: wd,
        short: wd.split('/').pop() || wd,
        items: [],
      };
    }
    groups[wd].items.push(s);
  }
  return Object.values(groups);
});
```

### 创建会话

```javascript
async function createSession(workDir) {
  const body = JSON.stringify(workDir ? { work_dir: workDir } : {});
  const r = await fetch(`${API}/api/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
  });
  const d = await r.json();
  activeSessionId.value = d.session_id;
  await loadSessions();
  connectWs(d.session_id);  // 连接 WebSocket
}
```

### 切换会话

```javascript
async function selectSession(sid) {
  activeSessionId.value = sid;
  connectWs(sid);  // 重新连接 WebSocket，会回放该会话的历史
}
```

## 11. 权限模式切换

GUI 底部的输入框可以切换权限模式：

```javascript
const modeOptions = [
  { value: 'default',          label: '默认' },
  { value: 'acceptEdits',      label: '接受编辑' },
  { value: 'plan',             label: '计划' },
  { value: 'bypassPermissions', label: '跳过权限' },
];

async function setCommandAcceptanceMode(mode) {
  await fetch(`${API}/api/session/${activeSessionId.value}/mode`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  });
  selectedMode.value = mode;
}
```

## 12. 前后端数据流总结

```
用户输入 "帮我读取 main.py"
    │
    ↓
GUI: send()
    │ POST /api/task { session_id, prompt }
    ↓
Daemon: start_task()
    │ 创建后台任务，运行 Agent.run()
    ↓
Agent: LLM 调用 → 决定调用 ReadFile
    │ yield ToolUseEvent
    ↓
Daemon: 序列化事件 → 追加到事件日志
    │ WebSocket 推送
    ↓
GUI: handleEvent('ToolUseEvent')
    │ 显示工具调用卡片（running 状态）
    ↓
Agent: 执行 ReadFile
    │ yield ToolResultEvent
    ↓
Daemon: WebSocket 推送
    ↓
GUI: handleEvent('ToolResultEvent')
    │ 更新工具卡片为 done 状态
    ↓
Agent: LLM 再次调用 → 生成最终回复
    │ yield StreamText (多次)
    ↓
Daemon: WebSocket 推送（逐字）
    ↓
GUI: handleEvent('StreamText')
    │ 逐字追加到消息，实时渲染
    ↓
Agent: yield LoopComplete
    ↓
Daemon: WebSocket 推送
    ↓
GUI: finalizeAssistant() → busy = false
```


---

## 13. 与 Daemon 协议的精确对接（补充）

### 13.1 前端只做两件事

1. **HTTP 发命令**（建会话、发任务、回权限、改设置）
2. **WebSocket 收事件**（渲染消息、工具卡、权限弹窗）

前端**不持有** ConversationManager，也不直接调 Agent。

### 13.2 推荐会话生命周期（实现对照）

`	ext
启动页选择/确认 work_dir
  POST /api/session { work_dir }
  保存 activeSessionId
  new WebSocket(/api/stream/{sid})
  处理回放事件 → ReplayDone → 清空“回放中”状态

用户输入
  POST /api/task { session_id, prompt }
  （可选乐观更新 UI）
  真正内容以 WS 事件为准

收到 PermissionRequest
  弹窗
  POST /api/permission/{sid} { request_id, ... }

切换会话
  断开旧 WS（注意 generation 防串线）
  连接新 sid WS（自动回放该 sid 的 events）

关闭会话
  DELETE /api/session/{sid}
`

### 13.3 事件 → UI 状态机（逻辑）

`	ext
UserMessage          → 追加用户气泡
StreamText           → 追加/创建 assistant 气泡并 append 文本
ThinkingText         → 思考区
ToolUseEvent         → 工具卡片 running
ToolResultEvent      → 工具卡片完成/失败
PermissionRequest    → 打开权限 modal（保存 request_id）
AskUserRequest       → 打开提问 modal
UsageEvent           → 状态栏 token
Compact*             → 提示条
ErrorEvent           → 错误气泡
LoopComplete         → busy=false，允许再发送
ReplayDone           → 回放结束
SessionNotFound      → 提示会话失效，回到列表
`

### 13.4 鉴权与跨域（与当前 Daemon 对齐）

若配置了 MOZILCODE_DAEMON_TOKEN：

- HTTP 需 Authorization: Bearer ...
- WS 需 ?token=...

Origin 需在 MOZILCODE_CORS_ORIGINS 白名单（默认含 Vite 1420 与 tauri://localhost）。

### 13.5 前端不能假设的三件事

1. **events 回放 = 模型仍有完整 history**（Daemon 重启后 UI 有记录，模型可能空历史）
2. **POST /api/task 的响应 body 含完整回答**（通常只有 task_id）
3. **改 /api/config 立即作用于当前会话 Agent**（多为 new_sessions）

### 13.6 调试建议

- 浏览器 Network：看 WS 帧 type 序列是否完整
- 对比 Daemon 日志：task 是否 start、permission 是否 resolve
- 确认 ctiveSessionId 与 WS URL 中 sid 一致
- 用 generation 计数丢弃旧 WS 的迟到消息

### 13.7 相关后端文档

深入协议与会话维护见 [05-Daemon服务](./05-Daemon服务.md)。
