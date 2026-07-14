"""会话创建、初始化与运行时确保。"""

from __future__ import annotations

import uuid
from collections.abc import MutableMapping
from dataclasses import replace
import logging
from pathlib import Path
from typing import Any

from mozilcode.agent.factory import create_agent_from_config
from mozilcode.config import AppConfig
from mozilcode.daemon.session import SessionManager
from mozilcode.daemon.session.runtime import (
    AgentFactory,
    DaemonSessionRuntime,
    create_daemon_session_runtime,
)
from mozilcode.daemon.session.conversation_snapshot import (
    restore_conversation,
    restore_conversation_from_events,
)
from mozilcode.daemon.session.store import validate_session_id
from mozilcode.hooks import HookEngine
from mozilcode.permissions import PermissionMode

log = logging.getLogger(__name__)


async def create_session_runtime(
    *,
    sid: str,
    config: AppConfig | None,
    work_dir: str,
    hook_engine: HookEngine | None,
    session_mgr: SessionManager,
    runtimes: MutableMapping[str, DaemonSessionRuntime],
    agent_factory: AgentFactory = create_agent_from_config,
    provider_name: str = "",
    thinking: bool | None = None,
    conversation=None,
) -> DaemonSessionRuntime:
    if config is None:
        raise ValueError("model provider is not configured")
    selected_config = _select_provider(config, provider_name, thinking)
    runtime = await create_daemon_session_runtime(
        sid=sid,
        config=selected_config,
        work_dir=work_dir,
        permission_mode=PermissionMode(config.permission_mode),
        hook_engine=hook_engine,
        session_mgr=session_mgr,
        agent_factory=agent_factory,
        conversation=conversation,
    )
    runtimes[sid] = runtime
    return runtime


async def init_daemon_session(
    *,
    session_id: str | None,
    work_dir: str | None,
    config: AppConfig | None,
    default_work_dir: str,
    hook_engine: HookEngine | None,
    session_mgr: SessionManager,
    runtimes: MutableMapping[str, DaemonSessionRuntime],
    records: Any,
    agent_factory: AgentFactory = create_agent_from_config,
    provider_name: str = "",
) -> str:
    if config is None:
        raise ValueError("model provider is not configured")
    sid = validate_session_id(session_id or uuid.uuid4().hex[:12])
    if records.has(sid):
        raise ValueError(f"session already exists: {sid}")

    resolved_work_dir = work_dir or default_work_dir
    if not Path(resolved_work_dir).is_dir():
        raise ValueError(f"workspace not found: {resolved_work_dir}")

    await create_session_runtime(
        sid=sid,
        config=config,
        work_dir=resolved_work_dir,
        hook_engine=hook_engine,
        session_mgr=session_mgr,
        runtimes=runtimes,
        agent_factory=agent_factory,
        provider_name=provider_name,
    )
    if provider_name:
        records.create(sid, resolved_work_dir, provider_name=provider_name)
    else:
        records.create(sid, resolved_work_dir)
    return sid


async def ensure_session_runtime(
    *,
    sid: str,
    config: AppConfig | None,
    default_work_dir: str,
    hook_engine: HookEngine | None,
    session_mgr: SessionManager,
    runtimes: MutableMapping[str, DaemonSessionRuntime],
    session_meta: dict[str, dict],
    records: Any,
    agent_factory: AgentFactory = create_agent_from_config,
) -> bool:
    if sid in runtimes:
        return True
    if config is None:
        return False

    meta = session_meta.get(sid)
    if meta is None:
        return False

    work_dir = meta.get("work_dir") or default_work_dir
    if not Path(work_dir).is_dir():
        work_dir = default_work_dir

    provider_name = meta.get("provider_name", "")
    if not isinstance(provider_name, str):
        provider_name = ""
    thinking = meta.get("thinking")
    if not isinstance(thinking, bool):
        thinking = None

    snapshot = meta.get("conversation")
    conversation = restore_conversation(snapshot)
    if not snapshot:
        event_log = getattr(records, "event_log", lambda _sid: None)(sid)
        conversation = restore_conversation_from_events(event_log)
        if conversation.history:
            persist_conversation = getattr(records, "persist_conversation", None)
            if persist_conversation is not None:
                persist_conversation(sid, conversation)

    await create_session_runtime(
        sid=sid,
        config=config,
        work_dir=work_dir,
        hook_engine=hook_engine,
        session_mgr=session_mgr,
        runtimes=runtimes,
        agent_factory=agent_factory,
        provider_name=provider_name,
        thinking=thinking,
        conversation=conversation,
    )
    records.ensure_event_log(sid)
    return True


async def switch_session_provider(
    *,
    sid: str,
    provider_name: str,
    thinking: bool | None = None,
    config: AppConfig | None,
    default_work_dir: str,
    hook_engine: HookEngine | None,
    session_mgr: SessionManager,
    runtimes: MutableMapping[str, DaemonSessionRuntime],
    records: Any,
    active_tasks: Any,
    agent_factory: AgentFactory = create_agent_from_config,
) -> dict[str, Any]:
    """切换当前会话模型：更新 meta、重建 runtime，保留对话历史。"""
    name = (provider_name or "").strip()
    if not name:
        raise ValueError("provider_name is required")
    if config is None or not config.providers:
        raise ValueError("model provider is not configured")
    if not records.has(sid):
        raise ValueError("session not found")
    if not any(p.name == name for p in config.providers):
        raise ValueError(f"unknown provider: {name}")

    if hasattr(active_tasks, "is_running") and active_tasks.is_running(sid):
        raise ValueError("task already running")

    meta = records.meta(sid)
    current = str(meta.get("provider_name") or "")
    existing = runtimes.get(sid)
    if existing is not None and current == name and existing.deps.provider.name == name:
        return {
            "session_id": sid,
            "provider_name": name,
            "changed": False,
        }

    work_dir = meta.get("work_dir") or default_work_dir
    if not Path(work_dir).is_dir():
        work_dir = default_work_dir

    old_runtime = runtimes.get(sid)
    old_conversation = old_runtime.conversation if old_runtime is not None else None
    old_permission = (
        old_runtime.agent.permission_mode
        if old_runtime is not None
        else PermissionMode(config.permission_mode)
    )

    selected_config = _select_provider(config, name, thinking)
    # Build the replacement before touching the active runtime.  Provider
    # validation and MCP setup can fail; the existing conversation must remain
    # usable in that case.
    new_runtime = await create_daemon_session_runtime(
        sid=sid,
        config=selected_config,
        work_dir=work_dir,
        permission_mode=old_permission,
        hook_engine=hook_engine,
        session_mgr=session_mgr,
        agent_factory=agent_factory,
        register_session=False,
    )
    if old_conversation is not None:
        new_runtime.conversation.replace_history(old_conversation.get_messages())
        new_runtime.conversation.env_injected = old_conversation.env_injected
        new_runtime.conversation.ltm_injected = old_conversation.ltm_injected
        new_runtime.conversation.baseline_tokens = old_conversation.baseline_tokens
        new_runtime.conversation.anchor_count = old_conversation.anchor_count
        new_runtime.conversation.last_input_tokens = old_conversation.last_input_tokens

    # Promotion is deliberately last: after this point all requests for the
    # session resolve to the replacement runtime.
    await session_mgr.close_session(sid)
    await session_mgr.create_session(sid, new_runtime.agent, new_runtime.conversation)
    runtimes[sid] = new_runtime

    meta["provider_name"] = name
    if thinking is None:
        meta.pop("thinking", None)
    else:
        meta["thinking"] = thinking
    records.persist_meta(sid)

    if old_runtime is not None:
        hub = getattr(old_runtime.agent, "memory_hub", None)
        if hub is not None:
            try:
                await hub.shutdown()
            except Exception:
                log.warning("Failed to shut down old memory hub for session %s", sid, exc_info=True)
        mcp_manager = getattr(old_runtime.deps, "mcp_manager", None)
        if mcp_manager is not None:
            try:
                await mcp_manager.shutdown()
            except Exception:
                log.warning("Failed to shut down old MCP manager for session %s", sid, exc_info=True)

    return {
        "session_id": sid,
        "provider_name": name,
        "changed": True,
        "model": new_runtime.deps.provider.model,
    }


def _select_provider(
    config: AppConfig, provider_name: str, thinking: bool | None = None
) -> AppConfig:
    """Reorder providers for a session without mutating shared configuration."""
    if not provider_name:
        return config
    selected = next((p for p in config.providers if p.name == provider_name), None)
    if selected is None:
        return config
    if thinking is not None:
        selected = replace(selected, thinking=thinking)
    providers = [selected, *[p for p in config.providers if p.name != selected.name]]
    return replace(config, providers=providers)
