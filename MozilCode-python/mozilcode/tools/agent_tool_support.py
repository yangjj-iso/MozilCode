from __future__ import annotations

from collections.abc import Iterable

from mozilcode.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    PermissionMode,
    RuleEngine,
)


PERMISSION_MODE_MAP = {
    "default": PermissionMode.DEFAULT,
    "acceptEdits": PermissionMode.ACCEPT_EDITS,
    "dontAsk": PermissionMode.DONT_ASK,
}


def resolve_permission_mode(value: str | None) -> PermissionMode:
    if value is None:
        return PermissionMode.DEFAULT
    return PERMISSION_MODE_MAP.get(value, PermissionMode.DEFAULT)


def create_subagent_permission_checker(
    work_dir: str,
    permission_mode: str | PermissionMode | None,
) -> PermissionChecker:
    mode = (
        permission_mode
        if isinstance(permission_mode, PermissionMode)
        else resolve_permission_mode(permission_mode)
    )
    return PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(work_dir),
        rule_engine=RuleEngine(),
        mode=mode,
    )


def unique_agent_name(base_name: str, existing_names: Iterable[str]) -> str:
    existing = set(existing_names)
    if base_name not in existing:
        return base_name
    counter = 2
    while f"{base_name}-{counter}" in existing:
        counter += 1
    return f"{base_name}-{counter}"
