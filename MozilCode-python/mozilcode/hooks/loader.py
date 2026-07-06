from __future__ import annotations

from mozilcode.hooks.conditions import ConditionParseError, parse_condition
from mozilcode.hooks.events import LifecycleEvent
from mozilcode.hooks.models import Action, Hook

_VALID_EVENTS = {e.value for e in LifecycleEvent}
_VALID_ACTION_TYPES = {"command", "prompt", "http", "agent"}

_REQUIRED_FIELDS: dict[str, list[str]] = {
    "command": ["command"],
    "prompt": ["message"],
    "http": ["url"],
    "agent": ["prompt"],
}


class HookConfigError(Exception):
    pass


def _identify(entry: object, index: int) -> str:
    hook_id = entry.get("id", "") if isinstance(entry, dict) else ""
    return f"hook '{hook_id}'" if hook_id else f"hook #{index + 1}"


def _load_action(raw_action: object, label: str) -> Action:
    if not isinstance(raw_action, dict):
        raise HookConfigError(f"{label}: missing or invalid 'action' field")

    action_type = raw_action.get("type")
    if action_type not in _VALID_ACTION_TYPES:
        raise HookConfigError(
            f"{label}: invalid action type '{action_type}', "
            f"must be one of: {', '.join(sorted(_VALID_ACTION_TYPES))}"
        )

    required = _REQUIRED_FIELDS[action_type]
    for field_name in required:
        if not raw_action.get(field_name):
            raise HookConfigError(
                f"{label}: action type '{action_type}' requires "
                f"'{field_name}' field"
            )

    timeout = raw_action.get("timeout", 30)
    if not isinstance(timeout, int) or timeout <= 0:
        raise HookConfigError(f"{label}: timeout must be a positive integer")

    return Action(
        type=action_type,
        command=raw_action.get("command", ""),
        message=raw_action.get("message", ""),
        url=raw_action.get("url", ""),
        method=raw_action.get("method", "POST"),
        body=raw_action.get("body", ""),
        headers=raw_action.get("headers", {}),
        prompt=raw_action.get("prompt", ""),
        timeout=timeout,
    )


def load_hooks(raw_hooks: list[object] | None) -> list[Hook]:
    if not raw_hooks:
        return []

    hooks: list[Hook] = []
    for i, entry in enumerate(raw_hooks):
        label = _identify(entry, i)

        if not isinstance(entry, dict):
            raise HookConfigError(f"{label}: must be a mapping")

        event = entry.get("event")
        if not event:
            raise HookConfigError(f"{label}: missing 'event' field")
        if event not in _VALID_EVENTS:
            raise HookConfigError(
                f"{label}: invalid event '{event}', "
                f"must be one of: {', '.join(sorted(_VALID_EVENTS))}"
            )

        action = _load_action(entry.get("action"), label)

        reject = bool(entry.get("reject", False))
        if reject and event != "pre_tool_use":
            raise HookConfigError(
                f"{label}: 'reject' can only be used with 'pre_tool_use' event"
            )

        async_exec = bool(entry.get("async", False))
        if async_exec and event == "pre_tool_use":
            raise HookConfigError(
                f"{label}: 'async' cannot be used with 'pre_tool_use' event"
            )

        condition = None
        raw_if = entry.get("if")
        if raw_if:
            try:
                condition = parse_condition(str(raw_if))
            except ConditionParseError as e:
                raise HookConfigError(f"{label}: condition error: {e}") from e

        hook_id = entry.get("id", f"{event}_{i}")

        hooks.append(
            Hook(
                id=hook_id,
                event=event,
                action=action,
                condition=condition,
                reject=reject,
                once=bool(entry.get("once", False)),
                async_exec=async_exec,
            )
        )

    return hooks
