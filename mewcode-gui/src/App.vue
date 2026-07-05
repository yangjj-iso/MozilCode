<template>
  <div class="app">
    <!-- Sidebar -->
    <div class="sidebar">
      <div class="sb-h">
        <h1><svg class="logo" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 8 3 12l4 4"/><path d="m17 8 4 4-4 4"/><path d="m14 4-4 16"/></svg>{{ APP_NAME }}</h1>
      </div>
      <div class="sb-btns">
        <button class="btn-new" @click="createSession()">＋ 新对话</button>
        <button class="btn-open" @click="pickWorkspace" title="选择工作区文件夹"><svg class="ficon" viewBox="0 0 24 24" fill="currentColor"><path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>打开工作区</button>
      </div>
      <div class="slist">
        <div v-for="g in sessionGroups" :key="g.workDir" class="sgroup">
          <div class="sg-h" @click="toggleGroup(g.workDir)" :title="g.workDir">
            <span class="sg-caret">{{ collapsedGroups[g.workDir] ? '▸' : '▾' }}</span>
            <span class="sg-name"><svg class="ficon" viewBox="0 0 24 24" fill="currentColor"><path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>{{ g.short }}</span>
            <span class="sg-count">{{ g.items.length }}</span>
          </div>
          <div v-show="!collapsedGroups[g.workDir]" class="sg-items">
            <div v-for="s in g.items" :key="s.id" class="sitem" :class="{ active: s.id === activeSessionId }" @click="selectSession(s.id)">
              <span class="stitle">{{ s.title || '新对话' }}</span>
              <button class="sdel" type="button" title="删除会话" @click.stop="deleteSession(s.id)">×</button>
            </div>
          </div>
        </div>
      </div>
      <div class="sb-f" @click="openSettings" title="个人中心 / 设置">
        <svg class="gear" viewBox="0 0 24 24" fill="currentColor"><path d="M19.14 12.94a7.49 7.49 0 0 0 0-1.88l2.03-1.58a.5.5 0 0 0 .12-.61l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7 7 0 0 0-1.62-.94l-.36-2.54a.5.5 0 0 0-.5-.42h-3.84a.5.5 0 0 0-.5.42l-.36 2.54a7 7 0 0 0-1.62.94l-2.39-.96a.5.5 0 0 0-.6.22L2.7 8.87a.5.5 0 0 0 .12.61l2.03 1.58a7.49 7.49 0 0 0 0 1.88L2.82 14.5a.5.5 0 0 0-.12.61l1.92 3.32a.5.5 0 0 0 .6.22l2.39-.96a7 7 0 0 0 1.62.94l.36 2.54a.5.5 0 0 0 .5.42h3.84a.5.5 0 0 0 .5-.42l.36-2.54a7 7 0 0 0 1.62-.94l2.39.96a.5.5 0 0 0 .6-.22l1.92-3.32a.5.5 0 0 0-.12-.61zM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7z"/></svg>
        <span class="sb-f-name">个人中心</span>
        <span class="dot" :class="connected ? 'ok' : 'err'" :title="connected ? 'Daemon 已连接' : 'Daemon 未连接'"></span>
      </div>
    </div>

    <!-- Main -->
    <div class="main">
      <div class="topbar">
        <div class="tb-ws" :title="currentWorkDir"><svg class="ficon" viewBox="0 0 24 24" fill="currentColor"><path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>{{ currentWorkShort || '未选择工作区' }}</div>
        <div class="tb-mid">
          <div class="mode-seg" title="同步 TUI 的 Plan / 执行模式">
            <button :class="{ active: sessionStatus.plan_mode }" @click="setMode('plan')" :disabled="!activeSessionId">计划</button>
            <button :class="{ active: !sessionStatus.plan_mode }" @click="setMode('do')" :disabled="!activeSessionId">执行</button>
          </div>
          <span class="tb-chip" :title="sessionStatus.provider.model || ''">{{ sessionStatus.provider.model || '未加载模型' }}</span>
          <span class="tb-chip">Token {{ tokenPercent }}%</span>
        </div>
        <div class="tb-actions">
          <button class="tb-icon" @click="manualCompact" :disabled="!activeSessionId" title="压缩上下文">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 7h16v2H4zm3 4h10v2H7zm3 4h4v2h-4z"/></svg>
          </button>
          <button class="tb-icon danger" @click="cancelActive" :disabled="!canStop" title="停止当前任务">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 7h10v10H7z"/></svg>
          </button>
          <button class="tb-btn" @click="openInfo">{{ showInfo ? '隐藏侧栏' : '侧栏' }}</button>
        </div>
      </div>
      <div class="chat" ref="chatEl">
        <div class="thread">
        <div v-if="messages.length === 0" class="empty">
          <div class="ic"><svg class="logo" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 8 3 12l4 4"/><path d="m17 8 4 4-4 4"/><path d="m14 4-4 16"/></svg></div>
          <div class="empty-title">{{ APP_NAME }}</div>
          <p>输入消息开始对话</p>
          <p class="empty-sub">Agent 可以读写文件、运行命令、搜索代码</p>
        </div>

        <div v-for="(msg, i) in messages" :key="msg._id || i" class="msg" :class="msg.role">
          <div class="msg-head">
            <span class="avatar" :class="msg.role">
              <template v-if="msg.role === 'user'">你</template>
              <svg v-else class="logo" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 8 3 12l4 4"/><path d="m17 8 4 4-4 4"/><path d="m14 4-4 16"/></svg>
            </span>
            <span class="who">{{ msg.role === 'user' ? '你' : APP_NAME }}</span>
            <button v-if="msg.role === 'assistant' && msg.content" class="msg-copy" type="button" @click="copyMsg(msg)">复制</button>
          </div>
          <div v-if="msg.role === 'user'" class="bubble">{{ msg.content }}</div>
          <div v-else class="msg-content">
            <div v-if="msg.thinking" class="think" :class="{ collapsed: msg.thinkCollapsed }">
              <div class="think-h" @click="msg.thinkCollapsed = !msg.thinkCollapsed">
                <span class="ti">💭 思考</span>
                <span class="tg">{{ msg.thinkCollapsed ? '展开' : '收起' }}</span>
              </div>
              <div class="think-b">{{ msg.thinking }}</div>
            </div>
            <div v-for="tool in (msg.tools || [])" :key="tool.id" class="tc">
              <div class="tc-h" @click="tool.expanded = !tool.expanded">
                <span class="ts" :class="tool.status">{{ tool.status === 'running' ? '●' : tool.status === 'error' ? '✗' : '✓' }}</span>
                <span class="tn">{{ tool.name }}</span>
                <span class="ta">{{ fmtArgs(tool) }}</span>
                <span class="te" v-if="tool.elapsed">{{ tool.elapsed.toFixed(1) }}s</span>
              </div>
              <div class="tc-b" :class="{ hide: !tool.expanded }">
                <div v-if="tool.name === 'Bash'" class="term">
                  <div class="term-cmd"><span class="term-prompt">$</span> {{ tool.args && tool.args.command }}</div>
                  <div class="term-out" :class="{ err: tool.status === 'error' }">{{ fmtRes(tool.result) }}</div>
                </div>
                <div v-else class="tbody" v-html="tool.expanded ? toolBody(tool) : ''"></div>
              </div>
            </div>
            <div v-if="msg.content" class="md" @click="onMdClick">
              <span v-html="msg.html"></span><span v-if="msg.streaming" class="cursor"></span>
            </div>
          </div>
        </div>
        </div>
      </div>

      <div class="input-area">
        <!-- Permission request — inline above the composer (Codex-style) -->
        <div v-if="perm" class="approve">
          <div class="approve-head"><span class="approve-ic">⚠</span> 权限请求 · <span class="approve-tool">{{ perm.tool_name }}</span></div>
          <div class="approve-desc">{{ perm.description }}</div>
          <div class="approve-acts">
            <button class="b-deny" @click="resolvePerm('deny')">拒绝</button>
            <button class="b-allow" @click="resolvePerm('allow')">允许</button>
            <button class="b-always" @click="resolvePerm('allow_always')">始终允许</button>
          </div>
        </div>
        <!-- AskUser prompt — inline above the composer -->
        <div v-if="ask && ask.currentQ < ask.questions.length" class="approve">
          <div class="approve-head"><span class="approve-ic">?</span> Agent 提问</div>
          <div class="approve-q">{{ ask.questions[ask.currentQ].message }}</div>
          <div v-if="ask.questions[ask.currentQ].options && ask.questions[ask.currentQ].options.length" class="approve-opts">
            <button v-for="opt in ask.questions[ask.currentQ].options" :key="opt" class="approve-opt" @click="pickOpt(ask.questions[ask.currentQ].name, opt)">{{ opt }}</button>
          </div>
          <input v-else type="text" class="approve-input" :ref="(el) => el && el.focus()" @keydown.enter="pickText(ask.questions[ask.currentQ].name, $event.target.value)" placeholder="输入回答后回车…" />
        </div>
        <div class="composer" :class="{ disabled: !activeSessionId }">
          <textarea
            ref="inputEl"
            class="composer-input"
            v-model="inputText"
            @keydown="onKey"
            @input="autoGrow"
            :placeholder="activeSessionId ? '输入消息…' : '先创建对话'"
            :disabled="!activeSessionId"
            rows="1"
          ></textarea>
          <button class="composer-send" @click="send" :disabled="!inputText.trim() || busy || !activeSessionId" :title="busy ? '生成中' : '发送'">
            <svg v-if="!busy" viewBox="0 0 24 24" fill="currentColor"><path d="M12 5l6 6-1.41 1.41L13 8.83V19h-2V8.83l-3.59 3.58L6 11z"/></svg>
            <span v-else class="spin"></span>
          </button>
        </div>
        <div class="composer-hint">Enter 发送 · Shift+Enter 换行</div>
      </div>
    </div>

    <!-- Right sidebar (toggleable): file tree + session details -->
    <div v-if="showInfo" class="rightbar">
      <div class="rb-tabs">
        <button class="rb-tab" :class="{ active: rightTab === 'files' }" @click="selectTab('files')">文件</button>
        <button class="rb-tab" :class="{ active: rightTab === 'run' }" @click="selectTab('run')">运行</button>
        <button class="rb-tab" :class="{ active: rightTab === 'worktrees' }" @click="selectTab('worktrees')">工作树</button>
        <button class="rb-tab" :class="{ active: rightTab === 'info' }" @click="selectTab('info')">详情</button>
      </div>

      <div v-show="rightTab === 'files'" class="rb-files">
        <div class="rb-files-h">
          <span class="rb-files-root" :title="currentWorkDir">{{ currentWorkShort || '工作区' }}</span>
          <button class="rb-refresh" @click="loadFiles" title="刷新">⟳</button>
        </div>
        <div v-if="filesLoading" class="rb-files-empty">加载中…</div>
        <div v-else-if="fileTree.length === 0" class="rb-files-empty">（空）</div>
        <div v-else class="ftree">
          <div v-for="node in fileTree" :key="node.rel" class="fnode" :style="{ paddingLeft: (node.depth * 14 + 6) + 'px' }" @click="toggleNode(node)">
            <span class="fcaret">{{ node.is_dir ? (node.expanded ? '▾' : '▸') : '' }}</span>
            <svg v-if="node.is_dir" class="ficon" viewBox="0 0 24 24" fill="currentColor"><path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>
            <svg v-else class="ficon fdoc" viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm-1 7V3.5L18.5 9H13z"/></svg>
            <span class="fname">{{ node.name }}</span>
          </div>
        </div>
      </div>

      <div v-show="rightTab === 'run'" class="rb-run">
        <div class="metric-grid">
          <div class="metric"><span>模式</span><strong>{{ sessionStatus.permission_mode || '—' }}</strong></div>
          <div class="metric"><span>工具</span><strong>{{ sessionStatus.tool_count || 0 }}</strong></div>
          <div class="metric"><span>输入</span><strong>{{ sessionStatus.input_tokens || 0 }}</strong></div>
          <div class="metric"><span>输出</span><strong>{{ sessionStatus.output_tokens || 0 }}</strong></div>
        </div>
        <div class="run-block">
          <div class="run-title">权限模式</div>
          <select class="rb-select" v-model="selectedMode" @change="setMode(selectedMode)">
            <option v-for="m in modeOptions" :key="m.value" :value="m.value">{{ m.label }}</option>
          </select>
        </div>
        <div class="run-actions">
          <button class="rb-btn" @click="manualCompact" :disabled="!activeSessionId">压缩上下文</button>
          <button class="rb-btn danger" @click="cancelActive" :disabled="!canStop">停止任务</button>
        </div>
        <div class="run-block">
          <div class="run-title">
            后台任务
            <button class="inline-refresh" @click="loadTasks" title="刷新">⟳</button>
          </div>
          <div v-if="tasks.length === 0" class="rb-files-empty">没有后台任务</div>
          <div v-for="t in tasks" :key="t.id" class="task-row">
            <div class="task-main">
              <span class="task-name">{{ t.name }}</span>
              <span class="task-meta">{{ t.status }} · {{ fmtElapsed(t.elapsed) }}</span>
            </div>
            <button v-if="t.status === 'running'" class="task-stop" @click="cancelTask(t.id)" title="取消">
              <svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 7h10v10H7z"/></svg>
            </button>
          </div>
        </div>
      </div>

      <div v-show="rightTab === 'worktrees'" class="rb-worktrees">
        <div class="rb-files-h">
          <span class="rb-files-root">当前: {{ worktreeState.current || '主工作区' }}</span>
          <button class="rb-refresh" @click="loadWorktrees" title="刷新">⟳</button>
        </div>
        <div class="wt-form">
          <input class="rb-input" v-model="newWorktree.name" placeholder="worktree 名称" spellcheck="false" />
          <input class="rb-input" v-model="newWorktree.base_branch" placeholder="基准分支，默认 HEAD" spellcheck="false" />
          <button class="rb-btn" @click="createWorktree" :disabled="!newWorktree.name.trim()">创建并进入</button>
        </div>
        <div v-if="worktrees.length === 0" class="rb-files-empty">没有活跃 worktree</div>
        <div v-for="wt in worktrees" :key="wt.name" class="wt-row" :class="{ current: wt.current }">
          <div class="wt-title">{{ wt.name }} <span v-if="wt.current">当前</span></div>
          <div class="wt-path mono">{{ wt.path }}</div>
          <div class="wt-branch">{{ wt.branch }}</div>
          <div class="wt-actions">
            <button @click="enterWorktree(wt.name)" :disabled="wt.current">进入</button>
          </div>
        </div>
        <div class="run-actions">
          <button class="rb-btn" @click="exitWorktree(false)" :disabled="!worktreeState.current">退出</button>
          <button class="rb-btn danger" @click="exitWorktree(true)" :disabled="!worktreeState.current">退出并删除</button>
        </div>
      </div>

      <div v-show="rightTab === 'info'" class="rb-info">
        <div class="rb-item"><span class="rb-k">工作区</span><div class="rb-v mono">{{ currentWorkDir || '—' }}</div></div>
        <div class="rb-item"><span class="rb-k">会话 ID</span><div class="rb-v mono">{{ activeSessionId || '—' }}</div></div>
        <div class="rb-item"><span class="rb-k">模型</span><div class="rb-v mono">{{ sessionStatus.provider.model || '—' }}</div></div>
        <div class="rb-item"><span class="rb-k">Tokens</span><div class="rb-v">↑{{ sessionStatus.input_tokens || tokenInfo.input }} ↓{{ sessionStatus.output_tokens || tokenInfo.output }}</div></div>
        <div class="rb-item"><span class="rb-k">Context</span><div class="rb-v">{{ sessionStatus.context_window || '—' }}</div></div>
        <div class="rb-sep"></div>
        <div class="rb-sec">在指定工作区新建会话</div>
        <div class="rb-row">
          <input class="rb-input" v-model="newWorkspace" placeholder="工作区绝对路径（留空用默认）" spellcheck="false" />
          <button class="rb-pick" @click="pickWorkspace" title="选择文件夹"><svg class="ficon" viewBox="0 0 24 24" fill="currentColor"><path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg></button>
        </div>
        <button class="rb-btn" @click="createSessionAt">＋ 在此工作区新建</button>
        <div class="rb-hint">提示：会话记录已持久化，重启 daemon 也会保留。</div>
      </div>
    </div>

  </div>

  <!-- Personal center / settings (full screen) -->
  <div v-if="showSettings" class="settings">
    <div class="set-nav">
      <button class="set-back" @click="showSettings = false">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg>
        返回应用
      </button>
      <div class="set-group">扩展</div>
      <button class="set-item" :class="{ active: setTab === 'skills' }" @click="setSettingsTab('skills')">
        <svg class="si" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.6 5.3 5.9.9-4.3 4.1 1 5.9L12 21.4 6.8 18.2l1-5.9L3.5 8.2l5.9-.9z"/></svg>
        Skills
      </button>
      <button class="set-item" :class="{ active: setTab === 'mcp' }" @click="setSettingsTab('mcp')">
        <svg class="si" viewBox="0 0 24 24" fill="currentColor"><path d="M4 5h16v5H4zm0 9h16v5H4zm3-6.5h2v2H7zm0 9h2v2H7z"/></svg>
        MCP 服务器
      </button>
    </div>
    <div class="set-main">
      <div v-if="setTab === 'skills'" class="set-pane">
        <h2>Skills</h2>
        <p class="set-desc">管理可用的技能（Agent 能力扩展）。开关会保存，新建会话时生效。</p>
        <div class="set-row-h"><span>技能</span><button class="set-add" @click="showAddSkill = !showAddSkill">＋ 创建技能</button></div>
        <div v-if="showAddSkill" class="set-form">
          <input v-model="newSkill.name" placeholder="名称（小写字母/数字/连字符，如 my-skill）" />
          <input v-model="newSkill.description" placeholder="描述（一句话说明技能用途，Agent 据此决定何时调用）" />
          <textarea v-model="newSkill.body" rows="5" placeholder="技能指令 / 提示词正文（可选）"></textarea>
          <div class="set-form-acts"><button class="set-save" @click="addSkill">创建</button><button class="set-cancel" @click="showAddSkill = false">取消</button></div>
        </div>
        <div v-if="skills.length === 0" class="set-empty">没有可用的技能</div>
        <div v-for="s in skills" :key="s.name" class="set-row">
          <div class="set-row-l">
            <div class="set-row-title">{{ s.name }} <span class="set-tag">{{ s.source }}</span></div>
            <div class="set-row-desc">{{ s.description }}</div>
          </div>
          <div class="set-row-r">
            <button v-if="s.source === 'user'" class="set-del" @click="delSkill(s.name)" title="删除">删除</button>
            <label class="switch"><input type="checkbox" :checked="s.enabled" @change="toggleSkill(s)" /><span class="track"></span></label>
          </div>
        </div>
      </div>

      <div v-else-if="setTab === 'mcp'" class="set-pane">
        <h2>MCP 服务器</h2>
        <p class="set-desc">连接外部工具和数据源。</p>
        <div class="set-row-h"><span>服务器</span><button class="set-add" @click="showAddMcp = !showAddMcp">＋ 添加服务器</button></div>
        <div v-if="showAddMcp" class="set-form">
          <input v-model="newMcp.name" placeholder="名称（必填）" />
          <input v-model="newMcp.command" placeholder="命令，如 npx / python（本地 stdio）" />
          <input v-model="newMcp.args" placeholder="参数，空格分隔（可选）" />
          <input v-model="newMcp.url" placeholder="或远程 URL（可选）" />
          <div class="set-form-acts"><button class="set-save" @click="addMcp">保存</button><button class="set-cancel" @click="showAddMcp = false">取消</button></div>
        </div>
        <div v-if="mcpServers.length === 0" class="set-empty">还没有配置 MCP 服务器</div>
        <div v-for="m in mcpServers" :key="m.name" class="set-row">
          <div class="set-row-l">
            <div class="set-row-title">{{ m.name }}</div>
            <div class="set-row-desc mono">{{ m.url || ((m.command || '') + (m.args ? ' ' + m.args : '')) || '—' }}</div>
          </div>
          <div class="set-row-r">
            <button class="set-del" @click="delMcp(m.name)" title="删除">删除</button>
            <label class="switch"><input type="checkbox" :checked="m.enabled" @change="toggleMcp(m.name)" /><span class="track"></span></label>
          </div>
        </div>
        <p class="set-note">提示：配置会保存到本地，接入将在新建会话时生效。</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue';
import { marked } from 'marked';
import { markedHighlight } from 'marked-highlight';
import hljs from 'highlight.js/lib/common';
import DOMPurify from 'dompurify';
import { open as openDialog } from '@tauri-apps/plugin-dialog';

marked.use(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      const language = hljs.getLanguage(lang) ? lang : 'plaintext';
      return hljs.highlight(code, { language }).value;
    },
  })
);
marked.setOptions({ gfm: true, breaks: true });

// Render markdown → sanitized HTML, then inject a copy button into each code
// block (added after sanitize; we fully control this markup).
function renderMarkdown(text) {
  let html = DOMPurify.sanitize(marked.parse(text || ''));
  html = html.replace(/<pre>/g, '<pre><button class="copy-btn" type="button">复制</button>');
  return html;
}

// requestAnimationFrame-coalesced live render: many token updates within a single
// frame collapse into ONE markdown parse, so streaming stays smooth even at high
// token rates (avoids the per-token O(n²) blowup).
function scheduleRender(m) {
  if (m._renderScheduled) return;
  m._renderScheduled = true;
  requestAnimationFrame(() => {
    m._renderScheduled = false;
    if (m.content) m.html = renderMarkdown(m.content);
  });
}

// Delegated click on rendered markdown: copy a code block's text.
function onMdClick(e) {
  const btn = e.target.closest('.copy-btn');
  if (!btn) return;
  const pre = btn.closest('pre');
  const code = pre && pre.querySelector('code');
  const text = code ? code.innerText : (pre ? pre.innerText : '');
  navigator.clipboard.writeText(text).then(() => {
    const prev = btn.textContent;
    btn.textContent = '已复制';
    setTimeout(() => { btn.textContent = prev; }, 1500);
  }).catch(() => {});
}

// Copy an entire assistant message (raw markdown source).
function copyMsg(m) {
  navigator.clipboard.writeText(m.content || '').then(() => toast('已复制', 'ok')).catch(() => {});
}

function escapeHtml(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Map a file extension to a highlight.js language id.
function extToLang(p) {
  const ext = (p || '').split('.').pop().toLowerCase();
  const map = {
    js: 'javascript', mjs: 'javascript', cjs: 'javascript', jsx: 'javascript',
    ts: 'typescript', tsx: 'typescript', vue: 'xml', html: 'xml', htm: 'xml', xml: 'xml', svg: 'xml',
    py: 'python', rb: 'ruby', go: 'go', rs: 'rust', java: 'java', kt: 'kotlin',
    c: 'c', h: 'c', cpp: 'cpp', cc: 'cpp', hpp: 'cpp', cs: 'csharp',
    css: 'css', scss: 'scss', less: 'less', json: 'json', md: 'markdown',
    sh: 'bash', bash: 'bash', zsh: 'bash', yml: 'yaml', yaml: 'yaml',
    sql: 'sql', toml: 'ini', ini: 'ini', php: 'php', swift: 'swift',
  };
  return map[ext] || '';
}

// Highlight raw source code (not markdown) into a <pre><code> block. Caps very
// large inputs to avoid a costly highlight pass.
function highlightCode(code, filename) {
  code = code || '';
  if (code.length > 20000) return `<pre class="code-block"><code>${escapeHtml(code)}</code></pre>`;
  const lang = extToLang(filename);
  let inner;
  try {
    inner = (lang && hljs.getLanguage(lang)) ? hljs.highlight(code, { language: lang }).value : hljs.highlightAuto(code).value;
  } catch {
    inner = escapeHtml(code);
  }
  return `<pre class="code-block"><code class="hljs">${inner}</code></pre>`;
}

// Naive line diff: show old lines as removed, new lines as added.
function renderDiff(oldStr, newStr) {
  const del = (oldStr || '').split('\n').map((l) => `<div class="d-del">- ${escapeHtml(l)}</div>`).join('');
  const add = (newStr || '').split('\n').map((l) => `<div class="d-add">+ ${escapeHtml(l)}</div>`).join('');
  return `<div class="diff">${del}${add}</div>`;
}

// Decide how a tool card body is rendered: WriteFile → the written code (the
// result is only a "Successfully wrote" note, so show args.content); EditFile →
// a +/- diff; ReadFile → highlighted content; everything else → plain output.
// Cached on the tool so it isn't recomputed on every re-render.
function toolBody(tool) {
  const a = tool.args || {};
  const sig = tool.name + '|' + tool.status + '|' + (tool.result ? tool.result.length : 0);
  if (tool._bodySig === sig && tool._bodyHtml !== undefined) return tool._bodyHtml;
  let html;
  if (tool.name === 'WriteFile') {
    html = highlightCode(a.content, a.file_path);
  } else if (tool.name === 'EditFile') {
    html = renderDiff(a.old_string, a.new_string);
  } else if (tool.name === 'ReadFile') {
    html = highlightCode(tool.result, a.file_path);
  } else {
    html = `<pre class="code-block">${escapeHtml(fmtRes(tool.result))}</pre>`;
  }
  tool._bodySig = sig;
  tool._bodyHtml = html;
  return html;
}

const APP_NAME = 'MozilCode';
const DEFAULT_DAEMON_HTTP = 'http://127.0.0.1:7800';

function stripTrailingSlash(value) {
  return (value || '').replace(/\/+$/, '');
}

function httpToWs(value) {
  return value.replace(/^http/i, (match) => (match.toLowerCase() === 'https' ? 'wss' : 'ws'));
}

const API = stripTrailingSlash(import.meta.env.VITE_MEWCODE_DAEMON_HTTP || DEFAULT_DAEMON_HTTP);
const WS_URL = stripTrailingSlash(import.meta.env.VITE_MEWCODE_DAEMON_WS || httpToWs(API));

const connected = ref(false);
const sessions = ref([]);
const activeSessionId = ref(null);
const messages = ref([]);
const inputText = ref('');
const busy = ref(false);
const chatEl = ref(null);
const inputEl = ref(null);
const perm = ref(null);
const ask = ref(null);
const tokenInfo = ref({ input: 0, output: 0 });
const sessionStatus = ref({
  permission_mode: '',
  plan_mode: false,
  input_tokens: 0,
  output_tokens: 0,
  context_window: 0,
  token_percent: 0,
  tool_count: 0,
  active_task: { id: '', running: false },
  provider: { name: '', protocol: '', model: '' },
});
const selectedMode = ref('default');
const modeOptions = [
  { value: 'default', label: 'Default' },
  { value: 'acceptEdits', label: 'Accept Edits' },
  { value: 'plan', label: 'Plan' },
  { value: 'bypassPermissions', label: 'Bypass' },
  { value: 'custom', label: 'Custom' },
  { value: 'dontAsk', label: 'Don’t Ask' },
];
const tasks = ref([]);
const worktreeState = ref({ current: '', worktrees: [] });
const newWorktree = ref({ name: '', base_branch: 'HEAD' });
const defaultWorkDir = ref('');
const newWorkspace = ref('');
const showInfo = ref(false);
const rightTab = ref('files');
const fileTree = ref([]);
const filesLoading = ref(false);
const showSettings = ref(false);
const setTab = ref('skills');
const skills = ref([]);
const mcpServers = ref([]);
const showAddMcp = ref(false);
const newMcp = ref({ name: '', command: '', args: '', url: '' });
const showAddSkill = ref(false);
const newSkill = ref({ name: '', description: '', body: '' });
const currentSession = computed(() => sessions.value.find((s) => s.id === activeSessionId.value) || null);
const currentWorkDir = computed(() => (currentSession.value && currentSession.value.work_dir) || defaultWorkDir.value);
const currentWorkShort = computed(() => {
  const w = currentWorkDir.value || '';
  const parts = w.split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : w;
});
const collapsedGroups = ref({});
const tokenPercent = computed(() => sessionStatus.value.token_percent || 0);
const canStop = computed(() => busy.value || Boolean(sessionStatus.value.active_task && sessionStatus.value.active_task.running));
const worktrees = computed(() => worktreeState.value.worktrees || []);
// Group sessions by their workspace, folder-style.
const sessionGroups = computed(() => {
  const map = new Map();
  for (const s of sessions.value) {
    const wd = s.work_dir || '(默认)';
    if (!map.has(wd)) map.set(wd, []);
    map.get(wd).push(s);
  }
  return Array.from(map.entries()).map(([workDir, items]) => ({
    workDir,
    short: workDir.split(/[\\/]/).filter(Boolean).pop() || workDir,
    items,
  }));
});
let ws = null;
let _replaying = false; // true while the daemon is replaying history on connect
let _wsGen = 0; // generation counter to ignore stale events from old connections
let _sendLock = false; // synchronous lock to prevent double-click sending

async function checkHealth() {
  try {
    const r = await fetch(`${API}/api/health`);
    const d = await r.json();
    connected.value = d.status === 'ok';
    if (d.work_dir && !defaultWorkDir.value) {
      defaultWorkDir.value = d.work_dir;
      if (!newWorkspace.value) newWorkspace.value = d.work_dir;
    }
  } catch {
    connected.value = false;
  }
}

async function refreshSessions() {
  try {
    const r = await fetch(`${API}/api/sessions`);
    const d = await r.json();
    // Sessions are now objects: { id, work_dir, title }.
    sessions.value = (d.sessions || []).map((s) => (typeof s === 'string' ? { id: s, work_dir: '', title: '' } : s));
  } catch {}
}

function applySessionStatus(data) {
  sessionStatus.value = {
    ...sessionStatus.value,
    ...data,
    active_task: data.active_task || { id: '', running: false },
    provider: data.provider || { name: '', protocol: '', model: '' },
  };
  selectedMode.value = sessionStatus.value.permission_mode || 'default';
  tokenInfo.value = {
    input: sessionStatus.value.input_tokens || 0,
    output: sessionStatus.value.output_tokens || 0,
  };
  if (activeSessionId.value && data.work_dir) {
    const s = sessions.value.find((x) => x.id === activeSessionId.value);
    if (s) {
      s.work_dir = data.work_dir;
      if (data.title !== undefined) s.title = data.title;
    }
  }
}

async function loadStatus() {
  if (!activeSessionId.value) return;
  try {
    const r = await fetch(`${API}/api/session/${activeSessionId.value}/status`);
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || '状态获取失败');
    applySessionStatus(d);
  } catch {}
}

async function setMode(mode) {
  if (!activeSessionId.value) return;
  try {
    const r = await fetch(`${API}/api/session/${activeSessionId.value}/mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
    const d = await r.json();
    if (!r.ok) {
      toast(d.error || '模式切换失败', 'err');
      return;
    }
    applySessionStatus(d);
    toast(d.plan_mode ? '已进入计划模式' : '已进入执行模式', 'ok');
  } catch (e) {
    toast('模式切换失败: ' + e.message, 'err');
  }
}

async function manualCompact() {
  if (!activeSessionId.value) return;
  try {
    const r = await fetch(`${API}/api/compact/${activeSessionId.value}`, { method: 'POST' });
    const d = await r.json();
    if (!r.ok) {
      toast(d.error || '压缩失败', 'err');
      return;
    }
    toast('上下文已压缩', 'ok');
    await loadStatus();
  } catch (e) {
    toast('压缩失败: ' + e.message, 'err');
  }
}

async function cancelActive() {
  if (!activeSessionId.value) return;
  try {
    const r = await fetch(`${API}/api/session/${activeSessionId.value}/cancel`, { method: 'POST' });
    const d = await r.json();
    if (!r.ok || !d.cancelled) {
      toast(d.error || '没有正在运行的任务', 'err');
      return;
    }
    busy.value = false;
    await loadStatus();
  } catch (e) {
    toast('停止失败: ' + e.message, 'err');
  }
}

// Create a session in the given workspace (defaults to the daemon's work_dir).
async function createSession(workDir) {
  const body = JSON.stringify(workDir ? { work_dir: workDir } : {});
  const r = await fetch(`${API}/api/session`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });
  const d = await r.json();
  if (!r.ok || !d.session_id) {
    toast(d.error || '创建会话失败', 'err');
    return;
  }
  await refreshSessions();
  await selectSession(d.session_id);
}

// Create a session in the workspace typed in the info panel.
async function createSessionAt() {
  const wd = (newWorkspace.value || '').trim();
  await createSession(wd || undefined);
}

// Open a native folder picker (Tauri) and start a session in the chosen workspace.
async function pickWorkspace() {
  try {
    const dir = await openDialog({ directory: true, multiple: false, title: '选择工作区文件夹' });
    if (dir && typeof dir === 'string') {
      newWorkspace.value = dir;
      await createSession(dir);
    }
  } catch (e) {
    // Not running under Tauri (e.g. plain browser): fall back to manual input.
    showInfo.value = true;
    toast('当前环境无原生选择框，请在右侧输入工作区路径', 'err');
  }
}

function toggleGroup(wd) {
  collapsedGroups.value = { ...collapsedGroups.value, [wd]: !collapsedGroups.value[wd] };
}

// ---- Workspace file tree (right sidebar) ----
async function fetchDir(rel) {
  if (!activeSessionId.value) return [];
  try {
    const r = await fetch(`${API}/api/fs/${activeSessionId.value}?path=${encodeURIComponent(rel)}`);
    const d = await r.json();
    return d.entries || [];
  } catch {
    return [];
  }
}
async function loadFiles() {
  fileTree.value = [];
  if (!activeSessionId.value) return;
  filesLoading.value = true;
  const entries = await fetchDir('');
  filesLoading.value = false;
  fileTree.value = entries.map((e) => ({ name: e.name, is_dir: e.is_dir, rel: e.name, depth: 0, expanded: false }));
}
async function toggleNode(node) {
  if (!node.is_dir) {
    // Insert the file path into the composer so you can reference it.
    inputText.value = (inputText.value ? inputText.value.replace(/\s*$/, ' ') : '') + node.rel + ' ';
    if (inputEl.value) inputEl.value.focus();
    return;
  }
  const arr = fileTree.value;
  const idx = arr.indexOf(node);
  if (idx < 0) return;
  if (node.expanded) {
    node.expanded = false;
    let count = 0;
    while (idx + 1 + count < arr.length && arr[idx + 1 + count].depth > node.depth) count++;
    arr.splice(idx + 1, count);
  } else {
    node.expanded = true;
    node.loading = true;
    const entries = await fetchDir(node.rel);
    node.loading = false;
    const children = entries.map((e) => ({ name: e.name, is_dir: e.is_dir, rel: node.rel + '/' + e.name, depth: node.depth + 1, expanded: false }));
    arr.splice(arr.indexOf(node) + 1, 0, ...children);
  }
}
function selectTab(t) {
  rightTab.value = t;
  if (t === 'files' && fileTree.value.length === 0) loadFiles();
  if (t === 'run') {
    loadStatus();
    loadTasks();
  }
  if (t === 'worktrees') loadWorktrees();
}

async function loadTasks() {
  if (!activeSessionId.value) return;
  try {
    const r = await fetch(`${API}/api/session/${activeSessionId.value}/tasks`);
    const d = await r.json();
    tasks.value = d.tasks || [];
  } catch {
    tasks.value = [];
  }
}

async function cancelTask(taskId) {
  if (!activeSessionId.value) return;
  try {
    await fetch(`${API}/api/session/${activeSessionId.value}/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' });
    await loadTasks();
  } catch {}
}

async function loadWorktrees() {
  if (!activeSessionId.value) return;
  try {
    const r = await fetch(`${API}/api/session/${activeSessionId.value}/worktrees`);
    const d = await r.json();
    worktreeState.value = { current: d.current || '', worktrees: d.worktrees || [] };
  } catch {
    worktreeState.value = { current: '', worktrees: [] };
  }
}

async function createWorktree() {
  if (!activeSessionId.value) return;
  const name = newWorktree.value.name.trim();
  if (!name) return;
  try {
    const r = await fetch(`${API}/api/session/${activeSessionId.value}/worktrees`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, base_branch: newWorktree.value.base_branch.trim() || 'HEAD' }),
    });
    const d = await r.json();
    if (!r.ok) {
      toast(d.error || '创建 worktree 失败', 'err');
      return;
    }
    newWorktree.value = { name: '', base_branch: 'HEAD' };
    if (d.status) applySessionStatus(d.status);
    await refreshSessions();
    await loadWorktrees();
    await loadFiles();
    toast('已创建并进入 worktree', 'ok');
  } catch (e) {
    toast('创建 worktree 失败: ' + e.message, 'err');
  }
}

async function enterWorktree(name) {
  if (!activeSessionId.value) return;
  try {
    const r = await fetch(`${API}/api/session/${activeSessionId.value}/worktrees/${encodeURIComponent(name)}/enter`, { method: 'POST' });
    const d = await r.json();
    if (!r.ok) {
      toast(d.error || '进入 worktree 失败', 'err');
      return;
    }
    if (d.status) applySessionStatus(d.status);
    await refreshSessions();
    await loadWorktrees();
    await loadFiles();
  } catch (e) {
    toast('进入 worktree 失败: ' + e.message, 'err');
  }
}

async function exitWorktree(remove) {
  if (!activeSessionId.value) return;
  if (remove && !window.confirm('退出并删除当前 worktree？有未提交改动时后端会阻止删除。')) return;
  try {
    const r = await fetch(`${API}/api/session/${activeSessionId.value}/worktrees/exit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ remove, discard: false }),
    });
    const d = await r.json();
    if (!r.ok) {
      toast(d.error || '退出 worktree 失败', 'err');
      return;
    }
    if (d.status) applySessionStatus(d.status);
    await refreshSessions();
    await loadWorktrees();
    await loadFiles();
  } catch (e) {
    toast('退出 worktree 失败: ' + e.message, 'err');
  }
}

// ---- Settings / personal center ----
function openSettings() {
  showSettings.value = true;
  setSettingsTab(setTab.value);
}
function setSettingsTab(t) {
  setTab.value = t;
  if (t === 'skills') loadSkills();
  else if (t === 'mcp') loadMcp();
}
async function loadSkills() {
  try {
    const r = await fetch(`${API}/api/skills`);
    skills.value = (await r.json()).skills || [];
  } catch { skills.value = []; }
}
async function toggleSkill(s) {
  s.enabled = !s.enabled;
  try { await fetch(`${API}/api/skills/${encodeURIComponent(s.name)}/toggle`, { method: 'POST' }); } catch {}
}
async function addSkill() {
  const n = (newSkill.value.name || '').trim();
  if (!n || !newSkill.value.description.trim()) { toast('名称和描述必填', 'err'); return; }
  try {
    const r = await fetch(`${API}/api/skills`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newSkill.value) });
    const d = await r.json();
    if (!r.ok) { toast(d.error || '创建失败', 'err'); return; }
    newSkill.value = { name: '', description: '', body: '' };
    showAddSkill.value = false;
    await loadSkills();
    toast('技能已创建', 'ok');
  } catch { toast('创建失败', 'err'); }
}
async function delSkill(name) {
  if (!window.confirm(`删除技能 “${name}”？`)) return;
  try {
    const r = await fetch(`${API}/api/skills/${encodeURIComponent(name)}`, { method: 'DELETE' });
    const d = await r.json();
    if (!r.ok) { toast(d.error || '删除失败', 'err'); return; }
  } catch {}
  await loadSkills();
}
async function loadMcp() {
  try {
    const r = await fetch(`${API}/api/settings/mcp`);
    mcpServers.value = (await r.json()).servers || [];
  } catch { mcpServers.value = []; }
}
async function toggleMcp(name) {
  const m = mcpServers.value.find((x) => x.name === name);
  if (m) m.enabled = !m.enabled;
  try { await fetch(`${API}/api/settings/mcp/${encodeURIComponent(name)}/toggle`, { method: 'POST' }); } catch {}
}
async function addMcp() {
  const n = (newMcp.value.name || '').trim();
  if (!n) { toast('请填写名称', 'err'); return; }
  try {
    await fetch(`${API}/api/settings/mcp`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newMcp.value) });
    newMcp.value = { name: '', command: '', args: '', url: '' };
    showAddMcp.value = false;
    await loadMcp();
  } catch { toast('添加失败', 'err'); }
}
async function delMcp(name) {
  if (!window.confirm(`删除 MCP 服务器 “${name}”？`)) return;
  try { await fetch(`${API}/api/settings/mcp/${encodeURIComponent(name)}`, { method: 'DELETE' }); } catch {}
  await loadMcp();
}
function openInfo() {
  showInfo.value = !showInfo.value;
  if (showInfo.value && rightTab.value === 'files' && fileTree.value.length === 0) loadFiles();
}

// Delete a session (and its persisted record) after confirmation.
async function deleteSession(sid) {
  if (!window.confirm('删除该会话？此操作不可撤销。')) return;
  try {
    await fetch(`${API}/api/session/${sid}`, { method: 'DELETE' });
  } catch {}
  const wasActive = sid === activeSessionId.value;
  await refreshSessions();
  if (wasActive) {
    if (ws) { ws._dead = true; ws.close(); }
    _wsSid = null;
    const next = sessions.value[0];
    if (next) await selectSession(next.id);
    else { activeSessionId.value = null; messages.value = []; }
  }
}

async function selectSession(sid) {
  activeSessionId.value = sid;
  messages.value = [];
  tokenInfo.value = { input: 0, output: 0 };
  sessionStatus.value = {
    ...sessionStatus.value,
    permission_mode: '',
    plan_mode: false,
    input_tokens: 0,
    output_tokens: 0,
    token_percent: 0,
    active_task: { id: '', running: false },
  };
  connectWS(sid);
  await loadStatus();
  if (rightTab.value === 'run') await loadTasks();
  if (rightTab.value === 'worktrees') await loadWorktrees();
  if (showInfo.value && rightTab.value === 'files') loadFiles();
}

let _reconnectTimer = null;
let _wsSid = null;

function connectWS(sid) {
  if (ws) {
    ws._stale = true; // mark old connection as stale
    ws.close();
  }
  if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
  _wsSid = sid;
  const gen = ++_wsGen;
  // The daemon replays the session's full event history on connect, so reset
  // to rebuild cleanly (also avoids duplicates on a transient reconnect).
  messages.value = [];
  _replaying = true; // ignore historical permission prompts until ReplayDone
  ws = new WebSocket(`${WS_URL}/api/stream/${sid}`);
  ws._gen = gen;
  ws._dead = false; // set once the daemon says this session no longer exists
  ws.onopen = () => { connected.value = true; };
  ws.onmessage = (ev) => {
    if (ws._gen !== gen) return; // ignore stale events
    const data = JSON.parse(ev.data);
    // Session vanished server-side (daemon restarted). Stop reconnecting the
    // dead id and rebuild from whatever the daemon currently has.
    if (data.type === 'SessionNotFound' || data.error === 'session not found') {
      ws._dead = true;
      recoverSession(sid);
      return;
    }
    handleEvent(data);
  };
  ws.onclose = (ev) => {
    connected.value = false;
    // Never hammer-reconnect a session the daemon has forgotten; only retry
    // genuine transient drops (daemon busy / restarting / network blips).
    if (ws._dead || (ev && ev.code === 4404)) return;
    if (_wsSid && ws._gen === gen) {
      _reconnectTimer = setTimeout(() => {
        if (_wsSid) connectWS(_wsSid);
      }, 3000);
    }
  };
  ws.onerror = () => {};
}

// The active session no longer exists on the daemon (e.g. it was restarted).
// Recover by selecting another live session, or creating a fresh one, instead
// of looping reconnects against a dead id forever.
async function recoverSession(deadSid) {
  if (_wsSid === deadSid) _wsSid = null; // block the onclose auto-reconnect
  await refreshSessions();
  const next = sessions.value.find((s) => s.id !== deadSid);
  if (next) {
    await selectSession(next.id);
  } else {
    await createSession();
  }
}

// 确保末尾是一条可写入的 assistant 消息（新建时用 push，Vue 3 对 ref 数组是响应式的）。
function ensureAssistant() {
  const last = messages.value.at(-1);
  if (last && last.role === 'assistant') return last;
  messages.value.push({
    role: 'assistant',
    content: '',
    html: '',
    thinking: '',
    thinkCollapsed: false,
    streaming: true,
    tools: [],
    _id: Date.now() + Math.random(),
  });
  return messages.value.at(-1);
}

// Finalize a streamed assistant message: parse markdown once and stop the cursor.
function finalizeAssistant() {
  const last = messages.value.at(-1);
  if (last && last.role === 'assistant') {
    last.streaming = false;
    if (last.content) last.html = renderMarkdown(last.content);
    if (last.thinking) last.thinkCollapsed = true;
  }
}

function handleEvent(data) {
  const t = data.type;
  const d = data.data || {};
  if (t === 'UserMessage') {
    // 用户消息由 daemon 记入事件日志并回放，前端据此渲染（单一数据源）。
    messages.value.push({ role: 'user', content: d.content || '', tools: [], _id: Date.now() + Math.random() });
    scrollDown();
  } else if (t === 'StreamText') {
    // 就地追加：Vue 3 对 ref 数组内的对象是深响应式，直接改属性即可触发更新，
    // 避免每个 token 都全量重建数组（长对话卡顿的元凶之一）。
    const m = ensureAssistant();
    // 正文开始时自动收起推理块（Codex 式：回答出来后思考过程折叠）。
    if (m.thinking && !m._thinkAuto) { m.thinkCollapsed = true; m._thinkAuto = true; }
    m.content += (d.text || '');
    scheduleRender(m); // 流式期间实时渲染 Markdown（rAF 合帧节流）
    scrollDown();
  } else if (t === 'ThinkingText') {
    ensureAssistant().thinking += (d.text || '');
    scrollDown();
  } else if (t === 'RetryEvent') {
    toast('重试中: ' + (d.reason || ''), 'err');
  } else if (t === 'ToolUseEvent') {
    ensureAssistant().tools.push({ id: d.tool_id, name: d.tool_name, args: d.arguments, status: 'running', expanded: false });
    scrollDown();
  } else if (t === 'ToolResultEvent') {
    const last = messages.value.at(-1);
    const tool = last && last.tools ? last.tools.find((x) => x.id === d.tool_id) : null;
    if (tool) {
      tool.status = d.is_error ? 'error' : 'done';
      tool.result = d.output;
      tool.elapsed = d.elapsed;
    }
  } else if (t === 'ReplayDone') {
    // History replay finished; live events (incl. genuinely-pending prompts) follow.
    _replaying = false;
    scrollToBottom(); // jump to the latest message when opening a session
  } else if (t === 'PermissionRequest') {
    if (_replaying) return; // historical (already-answered) prompt — don't re-open
    perm.value = { request_id: d.request_id, tool_name: d.tool_name, description: d.description };
  } else if (t === 'AskUserRequest') {
    if (_replaying) return;
    ask.value = { request_id: d.request_id, questions: d.questions || [], answers: {}, currentQ: 0 };
  } else if (t === 'PermissionResolved') {
    // Already answered (e.g. seen again during history replay) — don't re-prompt.
    if (perm.value && perm.value.request_id === d.request_id) perm.value = null;
  } else if (t === 'AskUserResolved') {
    if (ask.value && ask.value.request_id === d.request_id) ask.value = null;
  } else if (t === 'UsageEvent') {
    tokenInfo.value = { input: d.input_tokens || 0, output: d.output_tokens || 0 };
    sessionStatus.value.input_tokens = d.input_tokens || 0;
    sessionStatus.value.output_tokens = d.output_tokens || 0;
    if (sessionStatus.value.context_window) {
      sessionStatus.value.token_percent = Math.floor((sessionStatus.value.input_tokens / sessionStatus.value.context_window) * 100);
    }
  } else if (t === 'LoopComplete') {
    finalizeAssistant();
    busy.value = false;
    loadStatus();
    if (rightTab.value === 'run') loadTasks();
  } else if (t === 'TaskCancelled') {
    finalizeAssistant();
    busy.value = false;
    toast('任务已停止', 'ok');
  } else if (t === 'ErrorEvent') {
    finalizeAssistant();
    busy.value = false;
    toast(d.message || 'Error', 'err');
  } else if (t === 'CompactNotification') {
    toast('上下文已压缩', 'ok');
  } else if (t === 'ModeChanged') {
    sessionStatus.value.permission_mode = d.mode || sessionStatus.value.permission_mode;
    sessionStatus.value.plan_mode = d.mode === 'plan';
    selectedMode.value = sessionStatus.value.permission_mode;
  }
}

async function send() {
  const text = inputText.value.trim();
  if (!text || busy.value || !activeSessionId.value || _sendLock) return;
  _sendLock = true;
  // Don't optimistically add the user bubble — the daemon logs the prompt as a
  // UserMessage event and every client (including this one) renders it from the
  // replayed log, keeping a single source of truth.
  inputText.value = '';
  busy.value = true;
  await nextTick();
  if (inputEl.value) inputEl.value.style.height = 'auto';
  try {
    await fetch(`${API}/api/task`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: activeSessionId.value, prompt: text }),
    });
    await loadStatus();
  } catch (e) {
    toast('发送失败: ' + e.message, 'err');
    busy.value = false;
  } finally {
    _sendLock = false;
  }
}

async function resolvePerm(response) {
  const rid = perm.value.request_id;
  perm.value = null;
  await fetch(`${API}/api/permission/${activeSessionId.value}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: rid, response }),
  });
}

function pickOpt(qname, opt) {
  ask.value.answers[qname] = opt;
  advanceAsk();
}
function pickText(qname, text) {
  ask.value.answers[qname] = text;
  advanceAsk();
}
async function advanceAsk() {
  if (ask.value.currentQ < ask.value.questions.length - 1) {
    ask.value.currentQ++;
  } else {
    const rid = ask.value.request_id;
    const answers = ask.value.answers;
    ask.value = null;
    await fetch(`${API}/api/askuser/${activeSessionId.value}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: rid, answers }),
    });
  }
}

let _scrollPending = false;
function scrollDown() {
  // 合并同一 tick 内的多次滚动请求，避免每个 token 都触发一次布局/滚动。
  if (_scrollPending) return;
  _scrollPending = true;
  nextTick(() => {
    _scrollPending = false;
    if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight;
  });
}
// Force scroll to the very bottom after layout settles (used after switching
// sessions / finishing history replay, where content height changes late).
function scrollToBottom() {
  nextTick(() => {
    if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight;
    setTimeout(() => { if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight; }, 60);
  });
}
function toast(msg, type) {
  const t = document.createElement('div');
  t.className = 'toast ' + (type || 'ok');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

function fmtArgs(tool) {
  if (!tool.args) return '';
  if (['ReadFile', 'WriteFile', 'EditFile'].includes(tool.name)) return tool.args.file_path || '';
  if (tool.name === 'Bash') { const c = tool.args.command || ''; return c.length > 60 ? c.substring(0, 60) + '...' : c; }
  if (tool.name === 'Glob') return tool.args.pattern || '';
  if (tool.name === 'Grep') return tool.args.pattern || '';
  if (tool.name === 'Agent') return tool.args.description || '';
  if (tool.name === 'ToolSearch') return tool.args.query || '';
  return Object.entries(tool.args).slice(0, 2).map(([k, v]) => `${k}=${String(v).substring(0, 30)}`).join(', ');
}
function fmtRes(r) {
  return !r ? '' : r.length > 500 ? r.substring(0, 500) + '\n...' : r;
}
function fmtElapsed(seconds) {
  const n = Number(seconds || 0);
  if (n >= 60) return (n / 60).toFixed(1) + 'm';
  return Math.max(0, Math.round(n)) + 's';
}
function onKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}
function autoGrow() {
  if (inputEl.value) {
    inputEl.value.style.height = 'auto';
    inputEl.value.style.height = Math.min(inputEl.value.scrollHeight, 200) + 'px';
  }
}

let _statusTimer = null;

onMounted(async () => {
  await checkHealth();
  await refreshSessions();
  if (sessions.value.length > 0) await selectSession(sessions.value[0].id);
  else await createSession();
  if (inputEl.value) inputEl.value.focus();
  _statusTimer = setInterval(() => {
    checkHealth();
    if (activeSessionId.value) loadStatus();
    if (rightTab.value === 'run') loadTasks();
  }, 5000);
});

onUnmounted(() => {
  if (_statusTimer) clearInterval(_statusTimer);
  if (_reconnectTimer) clearTimeout(_reconnectTimer);
  if (ws) {
    ws._dead = true;
    ws.close();
  }
});
</script>

<style scoped>
.app { display: flex; height: 100vh; }
.sidebar { width: 260px; background: var(--bg2); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; }
.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.sb-h { padding: 16px; border-bottom: 1px solid var(--border); }
.sb-h h1 { font-size: 18px; font-weight: 600; color: var(--accent); display: flex; align-items: center; gap: 8px; }
.sb-h h1 .logo { width: 20px; height: 20px; }
.avatar .logo { width: 15px; height: 15px; color: #fff; }
.sb-h .sub { font-size: 12px; color: var(--muted); margin-top: 2px; }
.sb-btns { display: flex; gap: 6px; margin: 12px 16px; }
.btn-new { flex: 1; padding: 10px; background: var(--accent-dim); border: none; border-radius: var(--r); color: var(--text); font-size: 13px; cursor: pointer; }
.btn-new:hover { background: var(--accent); color: #fff; }
.btn-open { padding: 10px; background: var(--bg3); border: 1px solid var(--border); border-radius: var(--r); color: var(--text); font-size: 12px; cursor: pointer; white-space: nowrap; }
.btn-open:hover { border-color: var(--accent); }
.slist { flex: 1; overflow-y: auto; padding: 8px; }
.sgroup { margin-bottom: 4px; }
.sg-h { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border-radius: var(--r); cursor: pointer; color: var(--muted); font-size: 12px; }
.sg-h:hover { background: var(--bg3); }
.sg-caret { width: 10px; color: var(--dim); }
.sg-name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text); }
.sg-count { color: var(--dim); font-size: 11px; }
.sg-items { padding-left: 12px; }
.ficon { width: 14px; height: 14px; flex-shrink: 0; margin-right: 6px; vertical-align: -2px; color: var(--muted); }
.sg-name .ficon { color: var(--accent); opacity: 0.85; }
.rb-pick .ficon { margin-right: 0; }
.sitem { position: relative; display: flex; align-items: center; gap: 6px; padding: 7px 8px 7px 12px; border-radius: 6px; cursor: pointer; margin-bottom: 1px; }
.sitem:hover { background: var(--bg3); }
.sitem.active { background: var(--bg3); }
.sitem.active::before { content: ''; position: absolute; left: 3px; top: 7px; bottom: 7px; width: 2px; border-radius: 2px; background: var(--accent); }
.stitle { flex: 1; font-size: 13px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sitem:hover .stitle { color: var(--text); }
.sitem.active .stitle { color: var(--text); font-weight: 500; }
.sdel { opacity: 0; flex-shrink: 0; width: 18px; height: 18px; line-height: 1; text-align: center; border: none; background: transparent; color: var(--dim); font-size: 16px; cursor: pointer; border-radius: 4px; }
.sitem:hover .sdel { opacity: 1; }
.sdel:hover { background: var(--bg2); color: var(--red); }
.topbar { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 16px; border-bottom: 1px solid var(--border); background: var(--bg2); flex-shrink: 0; }
.topbar .tb-ws { min-width: 120px; max-width: 32%; font-size: 12px; color: var(--muted); font-family: var(--mono); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tb-mid { flex: 1; min-width: 0; display: flex; align-items: center; justify-content: center; gap: 8px; }
.tb-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.topbar .tb-btn { padding: 4px 10px; font-size: 12px; background: var(--bg3); color: var(--text); border: 1px solid var(--border); border-radius: var(--r); cursor: pointer; white-space: nowrap; }
.topbar .tb-btn:hover { border-color: var(--accent); }
.mode-seg { display: inline-flex; align-items: center; padding: 2px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); flex-shrink: 0; }
.mode-seg button { min-width: 48px; height: 26px; border: none; border-radius: 6px; background: transparent; color: var(--muted); font-size: 12px; cursor: pointer; }
.mode-seg button.active { background: var(--accent); color: #fff; }
.mode-seg button:disabled { opacity: 0.45; cursor: not-allowed; }
.tb-chip { max-width: 220px; padding: 4px 8px; border: 1px solid var(--border); border-radius: 999px; color: var(--muted); font-size: 11px; font-family: var(--mono); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; background: var(--bg); }
.tb-icon { width: 30px; height: 30px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg3); color: var(--muted); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.tb-icon svg { width: 15px; height: 15px; }
.tb-icon:hover:not(:disabled) { border-color: var(--accent); color: var(--text); }
.tb-icon.danger:hover:not(:disabled) { border-color: var(--red); color: var(--red); }
.tb-icon:disabled { opacity: 0.45; cursor: not-allowed; }
.rightbar { width: 300px; background: var(--bg2); border-left: 1px solid var(--border); flex-shrink: 0; display: flex; flex-direction: column; overflow: hidden; }
.rb-tabs { display: flex; border-bottom: 1px solid var(--border); flex-shrink: 0; }
.rb-tab { flex: 1; min-width: 0; padding: 10px 4px; background: transparent; border: none; color: var(--muted); font-size: 12px; cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.rb-tab:hover { color: var(--text); }
.rb-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.rb-files { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.rb-files-h { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
.rb-files-root { font-size: 12px; color: var(--muted); font-family: var(--mono); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rb-refresh { background: transparent; border: none; color: var(--muted); cursor: pointer; font-size: 15px; padding: 0 4px; line-height: 1; }
.rb-refresh:hover { color: var(--accent); }
.rb-files-empty { padding: 16px 12px; color: var(--dim); font-size: 12px; }
.ftree { flex: 1; overflow-y: auto; padding: 4px 0; }
.fnode { display: flex; align-items: center; gap: 4px; padding: 3px 8px; cursor: pointer; font-size: 13px; color: var(--muted); white-space: nowrap; }
.fnode:hover { background: var(--bg3); color: var(--text); }
.fcaret { width: 12px; flex-shrink: 0; color: var(--dim); font-size: 10px; text-align: center; }
.fnode .ficon { margin-right: 2px; color: var(--accent); opacity: 0.85; }
.fnode .ficon.fdoc { color: var(--muted); opacity: 0.7; }
.fname { overflow: hidden; text-overflow: ellipsis; }
.rb-info { padding: 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.rb-sec { font-size: 12px; color: var(--accent); font-weight: 600; margin-top: 4px; }
.rb-item { display: flex; flex-direction: column; gap: 2px; }
.rb-k { font-size: 11px; color: var(--muted); }
.rb-v { font-size: 13px; color: var(--text); word-break: break-all; }
.rb-v.mono { font-family: var(--mono); font-size: 12px; }
.rb-sep { height: 1px; background: var(--border); margin: 8px 0; }
.rb-row { display: flex; gap: 6px; }
.rb-input { flex: 1; background: var(--bg3); border: 1px solid var(--border); border-radius: var(--r); color: var(--text); padding: 8px 10px; font-size: 12px; font-family: var(--mono); outline: none; min-width: 0; }
.rb-input:focus { border-color: var(--accent); }
.rb-pick { padding: 8px 10px; background: var(--bg3); border: 1px solid var(--border); border-radius: var(--r); cursor: pointer; }
.rb-pick:hover { border-color: var(--accent); }
.rb-btn { padding: 8px 10px; background: var(--accent-dim); border: none; border-radius: var(--r); color: var(--text); font-size: 13px; cursor: pointer; }
.rb-btn:hover { background: var(--accent); color: #fff; }
.rb-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.rb-btn.danger { background: rgba(194, 65, 59, 0.12); color: var(--red); }
.rb-btn.danger:hover:not(:disabled) { background: var(--red); color: #fff; }
.rb-hint { font-size: 11px; color: var(--dim); line-height: 1.5; margin-top: 4px; }
.rb-run, .rb-worktrees { padding: 12px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
.metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.metric { border: 1px solid var(--border); border-radius: 8px; background: var(--bg); padding: 10px; min-width: 0; }
.metric span { display: block; color: var(--muted); font-size: 11px; margin-bottom: 4px; }
.metric strong { display: block; color: var(--text); font-size: 17px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-block { display: flex; flex-direction: column; gap: 8px; }
.run-title { display: flex; align-items: center; justify-content: space-between; color: var(--muted); font-size: 12px; font-weight: 600; }
.rb-select { width: 100%; background: var(--bg3); border: 1px solid var(--border); border-radius: var(--r); color: var(--text); padding: 8px 10px; font-size: 12px; outline: none; }
.run-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.inline-refresh { border: none; background: transparent; color: var(--muted); cursor: pointer; font-size: 14px; }
.task-row, .wt-row { border: 1px solid var(--border); border-radius: 8px; background: var(--bg); padding: 9px 10px; display: flex; gap: 8px; align-items: center; }
.task-main { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
.task-name { color: var(--text); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-meta { color: var(--muted); font-size: 11px; }
.task-stop { width: 26px; height: 26px; border: 1px solid var(--border); border-radius: 7px; background: var(--bg3); color: var(--red); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
.task-stop svg { width: 13px; height: 13px; }
.wt-form { display: flex; flex-direction: column; gap: 8px; }
.wt-row { align-items: stretch; flex-direction: column; }
.wt-row.current { border-color: var(--accent); }
.wt-title { font-size: 13px; font-weight: 600; color: var(--text); display: flex; gap: 6px; align-items: center; }
.wt-title span { padding: 1px 6px; border-radius: 999px; background: var(--accent-dim); color: var(--accent); font-size: 10px; font-weight: 600; }
.wt-path { color: var(--muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wt-branch { color: var(--dim); font-size: 11px; font-family: var(--mono); }
.wt-actions { display: flex; justify-content: flex-end; }
.wt-actions button { padding: 5px 10px; border: 1px solid var(--border); border-radius: 7px; background: var(--bg3); color: var(--text); cursor: pointer; }
.wt-actions button:disabled { opacity: 0.45; cursor: not-allowed; }
.sb-f { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-top: 1px solid var(--border); font-size: 13px; color: var(--muted); cursor: pointer; }
.sb-f:hover { background: var(--bg3); color: var(--text); }
.sb-f .gear { width: 16px; height: 16px; flex-shrink: 0; }
.sb-f-name { flex: 1; }
/* Settings / personal center */
.settings { position: fixed; inset: 0; z-index: 300; display: flex; background: var(--bg); }
.set-nav { width: 240px; background: var(--bg2); border-right: 1px solid var(--border); flex-shrink: 0; padding: 12px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
.set-back { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: transparent; border: none; color: var(--muted); font-size: 13px; cursor: pointer; border-radius: 6px; margin-bottom: 10px; }
.set-back svg { width: 18px; height: 18px; }
.set-back:hover { background: var(--bg3); color: var(--text); }
.set-group { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: 0.5px; padding: 8px 10px 4px; }
.set-item { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: transparent; border: none; color: var(--muted); font-size: 13px; cursor: pointer; border-radius: 6px; text-align: left; }
.set-item .si { width: 16px; height: 16px; flex-shrink: 0; }
.set-item:hover { background: var(--bg3); color: var(--text); }
.set-item.active { background: var(--accent-dim); color: var(--text); }
.set-main { flex: 1; overflow-y: auto; padding: 40px 48px; }
.set-pane { max-width: 720px; }
.set-pane h2 { font-size: 20px; font-weight: 600; margin-bottom: 4px; }
.set-desc { color: var(--muted); font-size: 13px; margin-bottom: 24px; }
.set-empty { color: var(--dim); font-size: 13px; padding: 20px 0; }
.set-row-h { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; color: var(--muted); font-size: 13px; }
.set-add { padding: 6px 12px; background: var(--bg3); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: 13px; cursor: pointer; }
.set-add:hover { border-color: var(--accent); }
.set-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 16px; background: var(--bg2); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 8px; }
.set-row-l { min-width: 0; }
.set-row-title { font-size: 14px; color: var(--text); font-weight: 500; }
.set-tag { font-size: 11px; color: var(--dim); background: var(--bg3); padding: 1px 6px; border-radius: 4px; margin-left: 6px; font-weight: 400; }
.set-row-desc { font-size: 12px; color: var(--muted); margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 520px; }
.set-row-desc.mono { font-family: var(--mono); }
.set-row-r { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
.set-del { background: transparent; border: none; color: var(--dim); font-size: 12px; cursor: pointer; }
.set-del:hover { color: var(--red); }
.set-form { background: var(--bg2); border: 1px solid var(--border); border-radius: 10px; padding: 14px; margin-bottom: 12px; display: flex; flex-direction: column; gap: 8px; }
.set-form input, .set-form textarea { background: var(--bg3); border: 1px solid var(--border); border-radius: 8px; color: var(--text); padding: 8px 10px; font-size: 13px; outline: none; font-family: var(--sans); resize: vertical; }
.set-form input:focus, .set-form textarea:focus { border-color: var(--accent); }
.set-form-acts { display: flex; gap: 8px; justify-content: flex-end; }
.set-save { padding: 6px 16px; background: var(--accent); color: var(--bg); border: none; border-radius: 8px; font-size: 13px; cursor: pointer; font-weight: 500; }
.set-cancel { padding: 6px 16px; background: var(--bg3); color: var(--text); border: 1px solid var(--border); border-radius: 8px; font-size: 13px; cursor: pointer; }
.set-note { color: var(--dim); font-size: 12px; margin-top: 14px; }
.switch { position: relative; display: inline-block; width: 38px; height: 22px; flex-shrink: 0; }
.switch input { opacity: 0; width: 0; height: 0; }
.switch .track { position: absolute; inset: 0; background: var(--bg3); border: 1px solid var(--border); border-radius: 22px; transition: 0.2s; }
.switch .track::before { content: ''; position: absolute; height: 16px; width: 16px; left: 3px; top: 2px; background: var(--muted); border-radius: 50%; transition: 0.2s; }
.switch input:checked + .track { background: var(--accent); border-color: var(--accent); }
.switch input:checked + .track::before { transform: translateX(16px); background: #fff; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.dot.ok { background: var(--green); }
.dot.err { background: var(--red); }
.chat { flex: 1; overflow-y: auto; padding: 24px 24px 48px; }
.thread { max-width: 780px; margin: 0 auto; }
.msg { margin-bottom: 24px; animation: msgin 0.24s ease; }
@keyframes msgin { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }
.msg-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.avatar { width: 24px; height: 24px; border-radius: 7px; display: inline-flex; align-items: center; justify-content: center; font-size: 13px; flex-shrink: 0; }
.avatar.assistant { background: linear-gradient(135deg, var(--accent), #7a3d18); }
.avatar.user { background: var(--bg3); color: var(--muted); font-size: 11px; font-weight: 600; }
.who { font-size: 12.5px; color: var(--text); font-weight: 600; }
.msg-content { line-height: 1.7; padding-left: 32px; }
.think { border-left: 2px solid var(--dim); margin: 2px 0 10px; }
.think-h { display: flex; gap: 8px; align-items: center; cursor: pointer; font-size: 12px; color: var(--muted); padding: 2px 0 2px 10px; }
.think-h .tg { color: var(--dim); }
.think-b { padding: 4px 0 4px 10px; color: var(--dim); font-size: 13px; white-space: pre-wrap; font-style: italic; }
.think.collapsed .think-b { display: none; }
.md :deep(p) { margin: 6px 0; }
.md :deep(p:first-child) { margin-top: 0; }
.md :deep(p:last-child) { margin-bottom: 0; }
.md :deep(pre) { background: var(--bg2); border: 1px solid var(--border); border-radius: var(--r); padding: 12px; overflow-x: auto; margin: 8px 0; }
.md :deep(code) { font-family: var(--mono); font-size: 13px; }
.md :deep(:not(pre) > code) { background: var(--bg3); padding: 1px 5px; border-radius: 4px; font-size: 12px; color: var(--cyan); }
.md :deep(pre code) { background: none; padding: 0; }
.md :deep(ul), .md :deep(ol) { padding-left: 22px; margin: 6px 0; }
.md :deep(li) { margin: 2px 0; }
.md :deep(a) { color: var(--accent); }
.md :deep(h1), .md :deep(h2), .md :deep(h3), .md :deep(h4) { margin: 14px 0 6px; font-weight: 600; line-height: 1.3; }
.md :deep(h1) { font-size: 20px; }
.md :deep(h2) { font-size: 17px; }
.md :deep(h3) { font-size: 15px; }
.md :deep(blockquote) { border-left: 3px solid var(--border); padding-left: 12px; color: var(--muted); margin: 8px 0; }
.md :deep(table) { border-collapse: collapse; margin: 8px 0; font-size: 13px; }
.md :deep(th), .md :deep(td) { border: 1px solid var(--border); padding: 4px 10px; text-align: left; }
.md :deep(th) { background: var(--bg2); }
.md :deep(hr) { border: none; border-top: 1px solid var(--border); margin: 12px 0; }
.md :deep(pre) { position: relative; }
.md :deep(.copy-btn) { position: absolute; top: 6px; right: 6px; padding: 2px 8px; font-size: 11px; background: var(--bg3); color: var(--muted); border: 1px solid var(--border); border-radius: 4px; cursor: pointer; opacity: 0; transition: opacity 0.15s; }
.md :deep(pre:hover .copy-btn) { opacity: 1; }
.md :deep(.copy-btn:hover) { color: var(--text); border-color: var(--accent); }
.msg-copy { margin-left: 8px; padding: 0 6px; font-size: 11px; background: transparent; color: var(--dim); border: 1px solid var(--border); border-radius: 4px; cursor: pointer; }
.msg-copy:hover { color: var(--text); border-color: var(--accent); }
.term { font-family: var(--mono); font-size: 12px; }
.term-cmd { color: var(--green); margin-bottom: 6px; white-space: pre-wrap; word-break: break-all; }
.term-prompt { color: var(--accent); font-weight: 600; margin-right: 6px; }
.term-out { color: var(--muted); white-space: pre-wrap; word-break: break-all; }
.term-out.err { color: var(--red); }
.tc-b :deep(.code-block) { margin: 0; padding: 0; background: none; font-family: var(--mono); font-size: 12px; white-space: pre; overflow-x: auto; color: var(--text); }
.tc-b :deep(.code-block code) { font-family: var(--mono); background: none; padding: 0; }
.tc-b :deep(.diff) { margin: 0; font-family: var(--mono); font-size: 12px; white-space: pre-wrap; word-break: break-all; }
.tc-b :deep(.d-del) { color: var(--red); background: rgba(247, 118, 142, 0.08); }
.tc-b :deep(.d-add) { color: var(--green); background: rgba(158, 206, 106, 0.08); }
.bubble { display: inline-block; padding: 10px 14px; border-radius: 12px; max-width: 100%; margin-left: 32px; background: var(--bg2); border: 1px solid var(--border); white-space: pre-wrap; word-break: break-word; line-height: 1.6; }
.tc { background: transparent; border: 1px solid var(--border); border-radius: 8px; margin: 6px 0; overflow: hidden; }
.tc-h { padding: 6px 10px; display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 12.5px; }
.tc-h:hover { background: var(--bg2); }
.tc-h .tn { color: var(--cyan); font-weight: 600; font-family: var(--mono); }
.tc-h .ta { color: var(--muted); font-size: 12px; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: var(--mono); }
.tc-h .ts { font-size: 11px; width: 14px; text-align: center; flex-shrink: 0; }
.tc-h .ts.running { color: var(--yellow); }
.tc-h .ts.done { color: var(--green); }
.tc-h .ts.error { color: var(--red); }
.tc-h .te { color: var(--dim); font-size: 11px; flex-shrink: 0; }
.tc-b { padding: 8px 10px; border-top: 1px solid var(--border); background: var(--bg); font-family: var(--mono); font-size: 12px; white-space: pre-wrap; word-break: break-all; max-height: 320px; overflow-y: auto; color: var(--muted); }
.tc-b.hide { display: none; }
.cursor { display: inline-block; width: 8px; height: 16px; background: var(--accent); animation: bk 1s infinite; vertical-align: text-bottom; margin-left: 2px; }
@keyframes bk { 0%, 50% { opacity: 1; } 51%, 100% { opacity: 0; } }
.input-area { padding: 12px 24px 18px; border-top: 1px solid var(--border); background: var(--bg); }
.composer { display: flex; align-items: flex-end; gap: 8px; max-width: 780px; margin: 0 auto; background: var(--bg3); border: 1px solid var(--border); border-radius: 16px; padding: 8px 8px 8px 16px; transition: border-color 0.15s, box-shadow 0.15s; }
.composer:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(162, 84, 42, 0.14); }
.composer.disabled { opacity: 0.6; }
.composer-input { flex: 1; background: transparent; border: none; outline: none; resize: none; color: var(--text); font-size: 14px; font-family: var(--sans); line-height: 1.5; padding: 6px 0; min-height: 24px; max-height: 200px; }
.composer-input::placeholder { color: var(--dim); }
.composer-send { flex-shrink: 0; width: 34px; height: 34px; border-radius: 10px; border: none; background: var(--accent); color: var(--bg); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; transition: transform 0.1s, background 0.15s; }
.composer-send svg { width: 18px; height: 18px; }
.composer-send:hover:not(:disabled) { transform: translateY(-1px); }
.composer-send:disabled { background: var(--bg2); color: var(--dim); cursor: not-allowed; }
.composer-hint { max-width: 780px; margin: 6px auto 0; font-size: 11px; color: var(--dim); text-align: center; }
.spin { width: 14px; height: 14px; border: 2px solid rgba(0, 0, 0, 0.25); border-top-color: currentColor; border-radius: 50%; animation: sp 0.7s linear infinite; }
@keyframes sp { to { transform: rotate(360deg); } }
.approve { max-width: 780px; margin: 0 auto 10px; background: var(--bg2); border: 1px solid var(--accent-dim); border-radius: 12px; padding: 12px 14px; }
.approve-head { font-size: 13px; font-weight: 600; color: var(--yellow); margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }
.approve-tool { color: var(--cyan); font-family: var(--mono); }
.approve-desc { font-size: 12px; color: var(--muted); font-family: var(--mono); background: var(--bg); border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; max-height: 140px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
.approve-q { font-size: 13px; color: var(--text); margin-bottom: 10px; line-height: 1.5; }
.approve-acts { display: flex; gap: 8px; justify-content: flex-end; }
.approve-acts button { padding: 6px 16px; border: none; border-radius: 8px; font-size: 13px; cursor: pointer; font-weight: 500; }
.approve-opts { display: flex; flex-direction: column; gap: 6px; }
.approve-opt { text-align: left; padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg3); color: var(--text); font-size: 13px; cursor: pointer; }
.approve-opt:hover { border-color: var(--accent); }
.approve-input { width: 100%; background: var(--bg3); border: 1px solid var(--border); border-radius: 8px; color: var(--text); padding: 8px 10px; font-size: 13px; outline: none; }
.approve-input:focus { border-color: var(--accent); }
.overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px; padding: 24px; max-width: 480px; width: 90%; }
.modal h3 { font-size: 16px; margin-bottom: 12px; color: var(--accent); }
.modal p { margin-bottom: 16px; line-height: 1.6; }
.modal .desc { background: var(--bg3); border-radius: var(--r); padding: 10px; font-family: var(--mono); font-size: 12px; margin-bottom: 16px; }
.modal .acts { display: flex; gap: 8px; justify-content: flex-end; }
.modal .acts button { padding: 8px 16px; border: none; border-radius: var(--r); cursor: pointer; font-size: 13px; font-weight: 500; }
.b-allow { background: var(--green); color: var(--bg); }
.b-deny { background: var(--bg3); color: var(--text); border: 1px solid var(--border) !important; }
.b-always { background: var(--accent); color: var(--bg); }
.modal .opts { margin-bottom: 16px; }
.modal .opt { padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--r); cursor: pointer; margin-bottom: 6px; }
.modal .opt:hover { border-color: var(--accent); background: var(--bg3); }
.modal .ti { width: 100%; background: var(--bg3); border: 1px solid var(--border); border-radius: var(--r); color: var(--text); padding: 10px; font-size: 14px; outline: none; }
.toast { position: fixed; top: 16px; right: 16px; padding: 10px 16px; border-radius: var(--r); font-size: 13px; z-index: 200; animation: si 0.3s; }
.toast.ok { background: var(--green); color: var(--bg); }
.toast.err { background: var(--red); color: var(--bg); }
@keyframes si { from { transform: translateX(100px); opacity: 0; } }
.tok { font-size: 11px; color: var(--dim); padding: 0 24px 4px; }
.hide { display: none !important; }
.empty { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 62vh; color: var(--muted); }
.empty .ic { margin-bottom: 16px; }
.empty .ic .logo { width: 44px; height: 44px; color: var(--accent); opacity: 0.9; }
.empty-title { font-size: 20px; font-weight: 600; color: var(--text); margin-bottom: 6px; }
.empty-sub { font-size: 12px; margin-top: 6px; color: var(--dim); }
@media (max-width: 900px) {
  .sidebar { width: 220px; }
  .tb-chip { display: none; }
  .topbar .tb-ws { max-width: 42%; }
  .rightbar { width: 270px; }
}
</style>
