# Tc Chat Autopilot 协议

> 仅在用户明确要求"开启 autopilot/自动驾驶"，或即将调用 autopilot_* 工具，或收到
> [AUTOPILOT_TICK] / [AUTOPILOT_PAUSED] / [AUTOPILOT_BUDGET_EXHAUSTED] 系统消息时读本技能。
> 与 tc-chat.mdc 基础规则配合使用（参考版 Flow 见 tc-chat.mdc §3，本技能不重复）。

## 1. 模式概述

- **Leader**：调度中心——建/收 TaskCard，经 autopilot_progress 推进 round/mode，收集结果，派发下一轮。
- **Worker**：执行 scan/fix/review 任务，在自己的 TaskCard 上回报，等待下一轮。
- Leader **绝不**写 status/config（面板/Watchdog 权威）；Leader 只经 autopilot_progress 推进 round/mode/summary（server 端强制单调不减），tasks/findings/completed 全部走 TaskCard（task_create/task_report）。

## 2. 启动

三种方式：用户在面板右键启动（面板直接写控制态+投首轮提示词）；用户对 Leader 说"开启 autopilot"；LLM 直接调用：
```
autopilot_start({ groupId, sessionId, autoFix:false, focus:"full", maxFilesPerRound:5 })
// 5s 内返回 OK/FAILED；可周期性 autopilot_status({ groupId }) 核对；暂停/停止用 autopilot_pause/autopilot_stop
```
Leader 收到首轮提示词后：① 派发首轮任务（每个任务 task_create 后经 group_broadcast/send_to_session 派给 Worker，必带 groupId）② autopilot_progress({ round:1, mode:'scanning', summary:'第一轮已派发' }) ③ 进入第 3 节主循环。

## 2.1 自治契约（autonomyLevel/budget）

```
autopilot_start({
  groupId, sessionId, autoFix:false, focus:'full', maxFilesPerRound:5,
  goal:'找出并修复所有 P0 安全漏洞',
  successCriteria:['P0 漏洞数=0', '覆盖率≥80%'],
  budget:{ maxRounds:10, maxWallClockMs:3600000, maxAutoFixesNoConfirm:3, maxFilesPerSession:50 },
  autonomyLevel:'auto-bounded',   // 'ask'(默认，每次删除文件/超限/核心配置改动都要确认user) / 'auto-bounded'(推荐，预算内自主决策，仅预算耗尽时暂停) / 'auto'(高风险，仅崩溃/MCP 错误才问)
  degradedPolicy:'pause',         // 'pause'(默认) / 'stop' / 'notify'
})
```

**Leader 每轮自检（auto-bounded/auto 强制，ask 建议）**：调 autopilot_progress 前，依次检查：
1. successCriteria 全部达成 → autopilot_stop（reason:'goal-achieved'）+ 简报用户；
2. 预算（读 autopilot_status）：round>maxRounds 或 (now-startedAt)>maxWallClockMs → autopilot_pause + 通知用户（summary 注明 budget-exhausted:原因）；autoFix 次数超 maxAutoFixesNoConfirm → 切 autonomyLevel='ask'；
3. 收敛检查：连续 2 轮无新 finding（带 severity 的 TaskCard）→ autopilot_stop（reason:'converged'）；
4. 均未触发 → 派发下一轮。

**Watchdog 兜底**：即使 Leader 忘记自检，扩展侧 AutopilotTickScheduler 每 30s 扫一次，按 degradedPolicy 兜底处理（pause：置 paused+degraded，推送消息；stop：置 stopped，推送消息；notify：仅推送消息，不改状态）。

**铁律**：auto-bounded/auto 模式下 Leader **绝不能**每轮 wait_message 等用户批准；仅在预算耗尽/目标达成/降级时 reply_message + wait_message。

## 2.2 自主决策协议（不空等缺席的人类）

autopilot 期间用户通常不在电脑前，用 wait_message"等人类拍板"= 死等，卡死全流程，**禁止**。
1. **一般不确定性 → 自主决策**：基于 goal/successCriteria/soul_read/role_memory_read 挑最合理方案，记录决策+理由（task_report(kind:'note') 或 flow_step_create(kind:'auto')，可选 kg_upsert_entity 沉淀），然后继续。
2. **禁止空等请示**：不得用 reply_message+wait_message 问用户"我该怎么办"。autopilot 中 wait_message 只用于：收 Worker 结果、收 [AUTOPILOT_TICK]、收用户主动打断——不用于征询决策。
3. **单个卡点不拖垮全局**：真需要人类拍板或不可逆的破坏性操作（删文件/改密钥/动外部资源）→ 不自动执行，改为 task_create(kind:'fix', severity:'high', title:'[needs-human] …') 记入待办，跳过继续做别的。
4. **决策留痕**：每个自主决策都留痕（TaskCard/Flow/KG），供事后用户回顾。

> 只有 3 种情况允许收尾（经 autopilot_pause/autopilot_stop + reply_message，而非死等）：达成 successCriteria、触发预算上限、或全流程确实无法推进。

## 3. Leader 主循环（核心，禁止自行停止）

```
LOOP:
  1. 派发本轮任务：逐个 task_create({..., kind:'scan'|'fix'|'review', assignee, severity?})，
     再派给对应 Worker（group_broadcast 广而告之 + send_to_session 精准派活，均带 groupId）
  2. 等结果：wait_message({ sessionId: leaderId })，Worker 经 send_to_session(messageType:'result') 回传，
     重复直到预期成员都回应或超时
  3. 分析结果：task_read({ groupId }) 看当前 TaskCard；新问题 → task_create(severity:'<level>')
     （finding = 带 severity 的 TaskCard）
  4. 决策：新 bug→建 fix 卡或记待办；修复完成→指派 reviewer；复核完成→task_report(status:'done') 收尾卡；
     无新发现→换扫描方向或深挖
  5. 推进循环元状态：autopilot_progress({ round:<n+1>, mode:'scanning|fixing|reviewing|converging', summary:'≤200字' })
  6. 检查中断：autopilot_status → 若 status 为 paused/stopped/blocked 则退出循环；用户消息优先，暂停主循环处理
  GOTO LOOP
```

## 4. Worker 行为规则

1. 收到任务立即执行，用 share_context 共享进度；关联的 Flow 子步骤翻 in_progress；
2. 发现问题 → task_report(kind:'finding') 记在自己的 TaskCard 上（summary 含严重度）；
3. 完成 → Flow 子步骤收尾 → flow_step_update_status(done) → send_to_session(messageType:'result', groupId) 回报；
4. 等下一轮 → wait_message 保持在线；
5. 判断：崩溃/安全类严重问题→报告并建议立即修；一般问题→报告等 Leader 决策；优化建议→task_report(kind:'finding') 标低严重度，不阻塞。

## 5. 运行态与 TaskCard 模型

| 数据 | 落在哪 | 谁写 | 谁读 |
|---|---|---|---|
| status（active/paused/stopped/blocked）+ config | runtime-state autopilot **control** | 面板/Watchdog | autopilot_status |
| round/mode/本轮 summary | runtime-state autopilot **progress** | **Leader** 经 autopilot_progress | autopilot_status |
| tasks/findings/completed | **TaskCard**（task_create/task_report） | Leader 建、Worker 报 | task_read / autopilot_status（聚合） |

`autopilot_status({ groupId })` 返回：
```json
{ "status":"active", "round":5, "mode":"fixing", "cycleSummary":"...",
  "tasks":12, "inProgress":3, "findings":7, "pendingFindings":2, "highSeverityFindings":1,
  "completed":6, "timedOutWorkers":0, "autoFix":false, "maxFilesPerRound":5, "focus":"full", "updatedAt":"..." }
```

## 6. 停止/暂停 + 用户打断

- 用户说"停止/暂停 autopilot" → 调 autopilot_stop/autopilot_pause；Leader 通知全体 Worker 暂停，生成总结（扫描文件数、发现/高危、已修复、待处理）。
- 用户在 autopilot 期间发消息 → Leader 暂停主循环、处理请求、完成后询问是否恢复，是则续跑、否则 autopilot_stop。

## 7. 安全约束

- autoFix 默认关闭，需用户显式授权；文件删除永不自动执行；核心配置文件改动需 Leader 确认；每轮最多改 5 个文件，超出即暂停。

## 8. [AUTOPILOT_TICK] 强制动作规则

扩展侧 AutopilotTickScheduler（每 30s 扫一次）检测到 Leader/Worker 卡死时，向 Leader 会话注入 [AUTOPILOT_TICK]：
1. **idle-timeout**：Leader status.json 超 90s 未更新；
2. **round-stale**：progress.updatedAt 超 120s 未推进；
3. **worker-timeout**：Worker 超 120s 未回应。

格式：`[AUTOPILOT_TICK][REASON:<idle-timeout|round-stale|worker-timeout>][TICK:<n>/<max>] <动作提示>`

**[AUTOPILOT_TICK] 与 [POLL_TICK] 完全不同**：POLL_TICK 静默重call wait_message即可；**AUTOPILOT_TICK 必须立即行动，不能忽略**。

按 REASON 的必做动作：idle-timeout→autopilot_status 核对后派下一轮或收尾当前轮；round-stale→收 Worker 回复、收尾/推进其 TaskCard、autopilot_progress 推进；worker-timeout→重试/改派/跳过超时 Worker 后 autopilot_progress 推进。

**降级机制**：Leader 对连续 2 个 tick 均无动作 → TickScheduler 置 status=blocked，面板红色告警；用户可一键"恢复"或"停止"；恢复后 Leader 必须主动重启本轮派发。

**Leader 铁律**：收到 [AUTOPILOT_TICK] 等同用户拍桌子喊"动起来"。禁止：忽略继续 wait_message；只回复"收到"不行动；反问"我该做什么"（tick 里已经说了）。正确做法：立即执行 tick 里指定的动作，reply_message 简报进度，再 wait_message 回到循环。

## 9. 验收标准与证据链（防"自称完成"）

Autopilot 最大风险是"自己说完成就算完成"。完成必须**可验证、有证据**：
1. 先定验收标准：每个任务的 description 必须写清楚可衡量的完成/验收标准，没有就先补上再开始；
2. 只有证据链才算完成：Worker 标 task_report(status:'done') 前必须真的跑过验证并附真实证据——代码改动跑 build/tsc/lint/相关测试并贴真实输出；修 bug 给复现步骤+修复后不再复现的证明；行为变更给命令输出/日志等可验证物料；证据写进 task_report({status:'done', finalSummary, finalDetails:'<命令+输出+结论>'}) 和 flow_step_update_status(done, result.summary)；
3. Leader 复核证据：复核关必须核对证据链完整且真的达标，证据不足/没有 → 打回（task_report(kind:'block') 或重开该修复项），不得据此推进 successCriteria；
4. 收尾也要证据：autopilot_stop(reason:'goal-achieved') 前，在最终 reply_message 报告里给每条 successCriteria 的达成证据。

> 一句话：没有真实、可验证的证据链，就不算完成。
