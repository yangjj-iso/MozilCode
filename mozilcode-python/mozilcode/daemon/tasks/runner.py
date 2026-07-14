"""前台 Agent 任务执行器。

驱动 Agent.run 事件流并处理挂起提示。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable

from mozilcode.agent import Agent
from mozilcode.conversation import ConversationManager
from mozilcode.daemon.tasks.active import ActiveTaskRegistry
from mozilcode.daemon.tasks.pending_prompts import PendingPromptRegistry
from mozilcode.daemon.session import SessionManager
from mozilcode.daemon.tasks.events import (
    loop_complete_event,
    serialize_task_event,
    task_cancelled_event,
    task_error_event,
    user_message_event,
)

log = logging.getLogger(__name__)

EmitEvent = Callable[[str, dict | None], None]
PersistEvents = Callable[[str], None]
PersistConversation = Callable[[str, ConversationManager], None]
SetTitleFromPrompt = Callable[[str, str], None]


class AgentTaskRunner:
    """Run one foreground Agent task per daemon session."""

    def __init__(
        self,
        *,
        active_tasks: ActiveTaskRegistry,
        session_mgr: SessionManager,
        pending_prompts: PendingPromptRegistry,
        emit_event: EmitEvent,
        persist_events: PersistEvents,
        persist_conversation: PersistConversation | None = None,
        set_title_from_prompt: SetTitleFromPrompt,
    ) -> None:
        self._active_tasks = active_tasks
        self._session_mgr = session_mgr
        self._pending_prompts = pending_prompts
        self._emit = emit_event
        self._persist_events = persist_events
        self._persist_conversation = persist_conversation or (lambda _sid, _conversation: None)
        self._set_title_from_prompt = set_title_from_prompt

    def start(
        self,
        sid: str,
        prompt: str,
        agent: Agent,
        conversation: ConversationManager,
    ) -> str:
        self._active_tasks.ensure_available(sid)
        self._set_title_from_prompt(sid, prompt)
        task_id = uuid.uuid4().hex[:8]
        task = asyncio.create_task(
            self._run_agent_task(
                sid,
                task_id,
                prompt,
                agent,
                conversation,
            ),
            name=f"agent-{sid}-{task_id}",
        )
        self._active_tasks.register(sid, task_id, task)
        return task_id

    async def _run_agent_task(
        self,
        sid: str,
        task_id: str,
        prompt: str,
        agent: Agent,
        conversation: ConversationManager,
    ) -> None:
        try:
            conversation.add_user_message(prompt)
            self._emit(sid, user_message_event(task_id, prompt))
            self._persist_conversation(sid, conversation)
            async for event in agent.run(conversation):
                await self._record_agent_task_event(sid, task_id, event)
                self._persist_conversation(sid, conversation)

            self._emit(sid, loop_complete_event(task_id))
        except asyncio.CancelledError:
            self._emit(sid, task_cancelled_event(task_id))
            self._emit(sid, loop_complete_event(task_id))
        except Exception as e:
            log.exception("Agent task %s failed", task_id)
            self._emit(sid, task_error_event(task_id, str(e)))
        finally:
            self._persist_conversation(sid, conversation)
            self._active_tasks.clear_if_current(sid, asyncio.current_task())
            self._persist_events(sid)

    async def _record_agent_task_event(
        self,
        sid: str,
        task_id: str,
        event: object,
    ) -> None:
        task_event = serialize_task_event(event, task_id)
        if task_event.future is not None:
            session = await self._session_mgr.get_session(sid)
            if session:
                session.register_future(
                    task_event.request_id,
                    task_event.future,
                )
        if task_event.pending_request_id:
            self._pending_prompts.record(
                sid,
                task_event.pending_request_id,
                task_event.message,
            )
        self._emit(sid, task_event.message)
