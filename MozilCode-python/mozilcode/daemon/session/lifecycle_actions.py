from __future__ import annotations

import uuid
from collections.abc import MutableMapping
from dataclasses import replace
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
from mozilcode.daemon.session.store import validate_session_id
from mozilcode.hooks import HookEngine
from mozilcode.permissions import PermissionMode


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
) -> DaemonSessionRuntime:
    if config is None:
        raise ValueError("model provider is not configured")
    selected_config = _select_provider(config, provider_name)
    runtime = await create_daemon_session_runtime(
        sid=sid,
        config=selected_config,
        work_dir=work_dir,
        permission_mode=PermissionMode(config.permission_mode),
        hook_engine=hook_engine,
        session_mgr=session_mgr,
        agent_factory=agent_factory,
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

    await create_session_runtime(
        sid=sid,
        config=config,
        work_dir=work_dir,
        hook_engine=hook_engine,
        session_mgr=session_mgr,
        runtimes=runtimes,
        agent_factory=agent_factory,
        provider_name=provider_name,
    )
    records.ensure_event_log(sid)
    return True


def _select_provider(config: AppConfig, provider_name: str) -> AppConfig:
    """Reorder providers for a session without mutating shared configuration."""
    if not provider_name:
        return config
    selected = next((p for p in config.providers if p.name == provider_name), None)
    if selected is None or config.providers[0] is selected:
        return config
    return replace(config, providers=[selected, *[p for p in config.providers if p is not selected]])
