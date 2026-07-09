from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mozilcode.agents.model_selection import select_subagent_client
from mozilcode.agents.defaults import (
    fork_agent_def,
    teammate_agent_def,
    worktree_agent_def,
)
from mozilcode.tools import rebase_file_tools
from mozilcode.tools.agent_tool_messages import (
    background_launch_message,
    empty_subagent_output,
    fork_disabled_message,
    pane_spawn_failed_message,
    pane_teammate_launch_message,
    teammate_launch_message,
    unknown_agent_type_message,
    worktree_preserved_suffix,
)
from mozilcode.tools.agent_tool_support import (
    parent_has_full_registry,
    resolve_parent_registry,
    resolve_parent_trace_id,
    unique_agent_name,
)
from mozilcode.tools.agent_tool_runtime import (
    complete_trace_from_agent,
    create_child_agent,
)
from mozilcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mozilcode.agent import Agent
    from mozilcode.agents.loader import AgentLoader
    from mozilcode.agents.task_manager import TaskManager
    from mozilcode.agents.trace import TraceManager

log = logging.getLogger(__name__)


class AgentToolParams(BaseModel):
    prompt: str
    description: str
    subagent_type: str | None = None
    model: str | None = None
    run_in_background: bool = False
    name: str | None = None
    isolation: str | None = None
    team_name: str | None = Field(
        default=None,
        description=(
            "REQUIRED when creating team members. Spawns the agent as a long-running "
            "teammate under this team (created via TeamCreate). Unlike regular sub-agents, "
            "team members run in their own terminal, persist after the lead returns, and "
            "communicate with each other via SendMessage. Without team_name the agent "
            "runs as a one-shot sub-agent that blocks and returns inline."
        ),
    )


TEAMMATE_ADDENDUM = (
    "\n\nIMPORTANT: You are running as an agent in a team.\n"
    "Just writing a response in text is not visible to others\n"
    "on your team - you MUST use the SendMessage tool.\n"
    "The user interacts primarily with the team lead.\n"
    "Your work is coordinated through the task system\n"
    "and teammate messaging.\n\n"
    "You are working in an isolated Git worktree. "
    "All file paths you use MUST be relative to your current working directory. "
    "Do NOT use absolute paths from the original project — they are outside your sandbox and will be rejected."
)


class AgentTool(Tool):
    name = "Agent"
    description = (
        "Launch a sub-agent to handle a task in an isolated context. "
        "Use subagent_type to select a predefined agent type (e.g. Explore, Plan, general-purpose), "
        "or leave it empty to fork the current conversation. "
        "Use team_name to spawn a teammate in an existing team."
    )
    params_model = AgentToolParams
    category = "command"
    is_concurrency_safe = False


    def __init__(
        self,
        agent_loader: AgentLoader,
        task_manager: TaskManager,
        trace_manager: TraceManager,
        parent_agent: Agent,
        enable_fork: bool = False,
        provider_config: Any = None,
        worktree_manager: Any = None,
        team_manager: Any = None,
    ) -> None:
        self._agent_loader = agent_loader
        self._task_manager = task_manager
        self._trace_manager = trace_manager
        self._parent_agent = parent_agent
        self._enable_fork = enable_fork
        self._provider_config = provider_config
        self._worktree_manager = worktree_manager
        self._team_manager = team_manager

    async def execute(self, params: BaseModel) -> ToolResult:
        p: AgentToolParams = params  # type: ignore[assignment]

        if p.team_name:
            return await self._execute_as_teammate(p)

        isolation = ""
        if p.subagent_type:
            defn = self._agent_loader.get(p.subagent_type)
            if defn and defn.isolation:
                isolation = defn.isolation

        if isolation == "worktree":
            return await self._execute_with_worktree(p)

        from mozilcode.agents.fork import ForkError, build_forked_messages
        from mozilcode.agents.parser import AgentDef
        from mozilcode.agents.tool_filter import resolve_agent_tools
        from mozilcode.conversation import ConversationManager

        definition: AgentDef | None = None
        conversation: ConversationManager

        if p.subagent_type:
            definition = self._agent_loader.get(p.subagent_type)
            if definition is None:
                return ToolResult(
                    output=unknown_agent_type_message(
                        p.subagent_type,
                        self._agent_loader.list_agents(),
                    ),
                    is_error=True,
                )
            conversation = ConversationManager()
        else:
            if not self._enable_fork:
                return ToolResult(
                    output=fork_disabled_message(),
                    is_error=True,
                )
            try:
                parent_conv = getattr(self._parent_agent, '_current_conversation', None)
                if parent_conv is None:
                    return ToolResult(
                        output="Cannot fork: no active conversation in parent agent.",
                        is_error=True,
                    )
                conversation = build_forked_messages(parent_conv, p.prompt)
            except ForkError as e:
                return ToolResult(output=str(e), is_error=True)

            definition = fork_agent_def(self._parent_agent.max_iterations)

        # 选择 LLM 客户端
        client = select_subagent_client(
            parent_client=self._parent_agent.client,
            provider_config=self._provider_config,
            requested_model=p.model,
            definition_model=definition.model,
        )

        # 判断是否后台运行
        is_background = p.run_in_background or definition.background
        if self._enable_fork:
            is_background = True

        # 过滤工具（coordinator 模式可能缩减了注册表，这里用完整注册表）
        _base_registry = resolve_parent_registry(self._parent_agent)
        filtered_registry = resolve_agent_tools(
            _base_registry, definition, is_background
        )
        filtered_registry = rebase_file_tools(
            filtered_registry,
            self._parent_agent.work_dir,
        )

        # 创建子 agent
        sub_agent = create_child_agent(
            parent_agent=self._parent_agent,
            client=client,
            registry=filtered_registry,
            work_dir=self._parent_agent.work_dir,
            definition=definition,
        )

        # fork 子 agent 继承父 agent 的替换状态，确保共享的 tool_use_id 做出一致的
        # 决策——这样父子共享的 prompt cache 前缀才能保持字节级一致
        if p.subagent_type is None:
            from mozilcode.context import clone_replacement_state
            sub_agent.replacement_state = clone_replacement_state(
                self._parent_agent.replacement_state
            )

        # 注册追踪节点
        trace_node = self._trace_manager.create(
            agent_type=definition.agent_type,
            parent_id=self._parent_agent.agent_id,
            trace_id=sub_agent.trace_id,
        )
        sub_agent.agent_id = trace_node.agent_id

        agent_name = p.name or p.subagent_type or f"agent-{trace_node.agent_id}"
        is_fork = p.subagent_type is None

        if is_background:
            if is_fork:
                sub_agent._fork_conversation = conversation
            task_id = self._task_manager.launch(
                agent=sub_agent,
                task="" if is_fork else p.prompt,
                name=agent_name,
                fork_conversation=conversation if is_fork else None,
            )
            return ToolResult(
                output=background_launch_message(
                    task_id=task_id,
                    agent_name=agent_name,
                    agent_type=definition.agent_type,
                ),
            )

        # 前台同步执行
        try:
            if is_fork:
                result_text = await sub_agent.run_to_completion("", conversation)
            else:
                result_text = await sub_agent.run_to_completion(p.prompt)
        except Exception as e:
            self._trace_manager.complete(trace_node.agent_id, "failed")
            return ToolResult(
                output=f"Sub-agent failed: {e}", is_error=True
            )

        complete_trace_from_agent(self._trace_manager, trace_node, sub_agent)

        return ToolResult(output=empty_subagent_output(result_text))

    async def _execute_as_teammate(self, p: AgentToolParams) -> ToolResult:
        if self._team_manager is None:
            return ToolResult(output="TeamManager not configured.", is_error=True)
        if self._worktree_manager is None:
            return ToolResult(output="WorktreeManager not configured for team spawn.", is_error=True)

        from mozilcode.agents.fork import ForkError, build_forked_messages
        from mozilcode.agents.parser import AgentDef
        from mozilcode.agents.tool_filter import build_teammate_tools
        from mozilcode.conversation import ConversationManager
        from mozilcode.teams.models import BackendType, TeammateInfo
        from mozilcode.teams.registry import AgentNameRegistry

        team = self._team_manager.get_team(p.team_name)
        if team is None:
            return ToolResult(output=f"Team '{p.team_name}' not found. Create it first with TeamCreate.", is_error=True)

        base_name = p.name or p.subagent_type or "worker"
        existing_names = {m.name for m in team.members}
        teammate_name = unique_agent_name(base_name, existing_names)

        # 1. 加载 agent 定义
        definition: AgentDef
        conversation: ConversationManager | None = None
        is_fork = False

        if p.subagent_type:
            defn = self._agent_loader.get(p.subagent_type)
            if defn is None:
                return ToolResult(
                    output=unknown_agent_type_message(
                        p.subagent_type,
                        self._agent_loader.list_agents(),
                        available_label="Available",
                    ),
                    is_error=True,
                )
            definition = defn
        else:
            if self._enable_fork:
                try:
                    parent_conv = getattr(self._parent_agent, '_current_conversation', None)
                    if parent_conv is None:
                        return ToolResult(output="Cannot fork: no active conversation.", is_error=True)
                    conversation = build_forked_messages(parent_conv, p.prompt)
                    is_fork = True
                except ForkError as e:
                    return ToolResult(output=str(e), is_error=True)

            definition = teammate_agent_def(self._parent_agent.max_iterations)

        # 2. 创建 worktree
        wt_name = f"team-{p.team_name}/{teammate_name}"
        try:
            wt = await self._worktree_manager.create(wt_name, "HEAD")
        except Exception as e:
            return ToolResult(output=f"Failed to create worktree for teammate: {e}", is_error=True)

        # 3. 选择 LLM
        client = select_subagent_client(
            parent_client=self._parent_agent.client,
            provider_config=self._provider_config,
            requested_model=p.model,
            definition_model=definition.model,
        )

        # 4. 检测后端类型
        backend = self._team_manager.detect_backend()

        # 5. 构建队友的工具集
        trace_node = self._trace_manager.create(
            agent_type=definition.agent_type,
            parent_id=self._parent_agent.agent_id,
            trace_id=resolve_parent_trace_id(self._parent_agent),
        )
        agent_id = trace_node.agent_id

        _has_full = parent_has_full_registry(self._parent_agent)
        full_registry = resolve_parent_registry(self._parent_agent)
        _full_tools = [t.name for t in full_registry.list_tools()]
        log.info(
            "[teammate] has_full_registry=%s full_tools=%d names=%s backend=%s def_tools=%s def_disallowed=%s",
            _has_full, len(_full_tools), _full_tools,
            backend.value,
            getattr(definition, 'tools', []),
            getattr(definition, 'disallowed_tools', []),
        )
        teammate_registry = build_teammate_tools(
            parent_registry=full_registry,
            team_manager=self._team_manager,
            team_name=p.team_name,
            agent_id=agent_id,
            agent_name=teammate_name,
            backend_type=backend.value,
            definition=definition,
        )
        teammate_registry = rebase_file_tools(teammate_registry, wt.path)
        _tm_tools = [t.name for t in teammate_registry.list_tools()]
        log.info("[teammate] result_tools=%d names=%s", len(_tm_tools), _tm_tools)

        # 6. 创建子 agent 并附加队友专属指令
        instructions = (definition.system_prompt or "") + TEAMMATE_ADDENDUM

        sub_agent = create_child_agent(
            parent_agent=self._parent_agent,
            client=client,
            registry=teammate_registry,
            work_dir=wt.path,
            definition=definition,
            permission_mode="dontAsk",
            instructions_content=instructions,
            agent_id=agent_id,
            team_name=p.team_name,
            team_manager=self._team_manager,
        )

        # 7. 注册名称和成员信息
        AgentNameRegistry.instance().register(teammate_name, agent_id)

        member = TeammateInfo(
            name=teammate_name,
            agent_id=agent_id,
            agent_type=definition.agent_type,
            model=p.model or definition.model,
            worktree_path=wt.path,
            backend_type=backend.value,
            is_active=True,
        )
        self._team_manager.register_member(p.team_name, member)

        # 8. 按后端类型启动队友
        if backend in (BackendType.TMUX, BackendType.ITERM2):
            return self._spawn_pane_teammate(
                p, team, member, backend, wt, agent_id, teammate_name
            )

        # 进程内模式：直接用 task_manager 执行并通知结果
        task_id = self._task_manager.launch(
            agent=sub_agent,
            task="" if is_fork else p.prompt,
            name=teammate_name,
            fork_conversation=conversation if is_fork else None,
        )

        return ToolResult(
            output=teammate_launch_message(
                teammate_name=teammate_name,
                team_name=p.team_name,
                agent_id=agent_id,
                backend=backend.value,
                worktree_path=wt.path,
                task_id=task_id,
            )
        )


    def _spawn_pane_teammate(
        self, p: Any, team: Any, member: Any, backend: Any, wt: Any,
        agent_id: str, teammate_name: str,
    ) -> ToolResult:
        from mozilcode.teams.models import BackendType

        mailbox = self._team_manager.get_mailbox(p.team_name)
        mailbox_dir = str(mailbox._base_dir) if mailbox else ""

        try:
            if backend == BackendType.TMUX:
                from mozilcode.teams.spawn_tmux import spawn_tmux_teammate
                pane_info = spawn_tmux_teammate(
                    team_name=p.team_name,
                    teammate_name=teammate_name,
                    worktree_path=wt.path,
                    prompt=p.prompt,
                    agent_type=p.subagent_type or "",
                    model=p.model or "",
                    mailbox_dir=mailbox_dir,
                )
                self._team_manager.register_pane_id(agent_id, pane_info.pane_id)
            elif backend == BackendType.ITERM2:
                from mozilcode.teams.spawn_iterm2 import spawn_iterm2_teammate
                pane_info = spawn_iterm2_teammate(
                    team_name=p.team_name,
                    teammate_name=teammate_name,
                    worktree_path=wt.path,
                    prompt=p.prompt,
                    agent_type=p.subagent_type or "",
                    model=p.model or "",
                    mailbox_dir=mailbox_dir,
                )
        except Exception as e:
            log.warning("Pane spawn failed, falling back to in-process: %s", e)
            return ToolResult(
                output=pane_spawn_failed_message(e),
                is_error=True,
            )

        return ToolResult(
            output=pane_teammate_launch_message(
                teammate_name=teammate_name,
                team_name=p.team_name,
                agent_id=agent_id,
                backend=backend.value,
                worktree_path=wt.path,
            )
        )


    async def _execute_with_worktree(self, p: AgentToolParams) -> ToolResult:
        if self._worktree_manager is None:
            return ToolResult(
                output="Worktree isolation is not available: WorktreeManager not configured.",
                is_error=True,
            )

        from mozilcode.agents.parser import AgentDef
        from mozilcode.agents.tool_filter import resolve_agent_tools
        from mozilcode.worktree.integration import (
            build_worktree_notice,
            generate_worktree_name,
        )

        definition: AgentDef | None = None
        if p.subagent_type:
            definition = self._agent_loader.get(p.subagent_type)
            if definition is None:
                return ToolResult(
                    output=unknown_agent_type_message(
                        p.subagent_type,
                        self._agent_loader.list_agents(),
                    ),
                    is_error=True,
                )
        else:
            definition = worktree_agent_def(self._parent_agent.max_iterations)

        wt_name = generate_worktree_name()
        try:
            wt = await self._worktree_manager.create(wt_name, "HEAD")
        except Exception as e:
            return ToolResult(
                output=f"Failed to create worktree: {e}",
                is_error=True,
            )

        notice = build_worktree_notice(self._parent_agent.work_dir, wt.path)
        task = notice + "\n\n" + p.prompt

        client = select_subagent_client(
            parent_client=self._parent_agent.client,
            provider_config=self._provider_config,
            requested_model=p.model,
            definition_model=definition.model,
        )

        _base_registry = resolve_parent_registry(self._parent_agent)
        filtered_registry = resolve_agent_tools(
            _base_registry, definition, False
        )
        filtered_registry = rebase_file_tools(filtered_registry, wt.path)

        sub_agent = create_child_agent(
            parent_agent=self._parent_agent,
            client=client,
            registry=filtered_registry,
            work_dir=wt.path,
            definition=definition,
        )

        trace_node = self._trace_manager.create(
            agent_type=definition.agent_type,
            parent_id=self._parent_agent.agent_id,
            trace_id=sub_agent.trace_id,
        )
        sub_agent.agent_id = trace_node.agent_id

        try:
            result_text = await sub_agent.run_to_completion(task)
        except Exception as e:
            self._trace_manager.complete(trace_node.agent_id, "failed")
            return ToolResult(
                output=f"Sub-agent in worktree failed: {e}",
                is_error=True,
            )

        complete_trace_from_agent(self._trace_manager, trace_node, sub_agent)

        cleanup = await self._worktree_manager.auto_cleanup(wt_name, wt.head_commit)
        if cleanup.kept:
            result_text = (result_text or "") + worktree_preserved_suffix(
                cleanup.path,
                cleanup.branch,
            )

        return ToolResult(output=empty_subagent_output(result_text))
