from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.tasks.active import ActiveTaskRegistry
from mozilcode.daemon.session.runtime import DaemonSessionRuntime
from mozilcode.daemon.session.status import (
    build_session_status,
    command_acceptance_mode,
)
from mozilcode.permissions import PermissionMode


class SessionMetaProvider(Protocol):
    def meta(self, sid: str) -> dict[str, Any]:
        ...


def configured_provider(config: AppConfig | None) -> ProviderConfig | None:
    if config is None or not config.providers:
        return None
    return config.providers[0]


def session_command_acceptance_mode(
    *,
    sid: str,
    agent: Any | None,
    config: AppConfig | None,
    pre_plan_modes: Mapping[str, PermissionMode],
) -> PermissionMode:
    configured_mode = (
        PermissionMode(config.permission_mode)
        if config is not None
        else None
    )
    return command_acceptance_mode(
        agent.permission_mode if agent is not None else None,
        pre_plan_modes.get(sid),
        configured_mode,
    )


def build_daemon_session_status(
    *,
    sid: str,
    config: AppConfig | None,
    server_work_dir: str,
    runtime: DaemonSessionRuntime | None,
    records: SessionMetaProvider,
    active_tasks: ActiveTaskRegistry,
    pre_plan_modes: Mapping[str, PermissionMode],
) -> dict[str, Any]:
    agent = runtime.agent if runtime is not None else None
    deps = runtime.deps if runtime is not None else None
    conversation = runtime.conversation if runtime is not None else None
    provider = deps.provider if deps is not None else configured_provider(config)
    return build_session_status(
        sid=sid,
        server_work_dir=server_work_dir,
        meta=records.meta(sid),
        agent=agent,
        provider=provider,
        conversation=conversation,
        configured_permission_mode=(
            config.permission_mode
            if config is not None
            else "default"
        ),
        command_mode=session_command_acceptance_mode(
            sid=sid,
            agent=agent,
            config=config,
            pre_plan_modes=pre_plan_modes,
        ),
        active_task_id=active_tasks.task_id(sid),
        active_task_running=active_tasks.is_running(sid),
    )
