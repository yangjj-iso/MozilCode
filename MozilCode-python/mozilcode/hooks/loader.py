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
_ACTION_STRING_FIELDS = ("command", "message", "url", "method", "body", "prompt")


class HookConfigError(Exception):
    pass


def _identify(entry: object, index: int) -> str:
    hook_id = entry.get("id", "") if isinstance(entry, dict) else ""
    return f"hook '{hook_id}'" if hook_id else f"hook #{index + 1}"


def _string_field(
    data: dict,
    field_name: str,
    label: str,
    default: str = "",
) -> str:
    value = data.get(field_name, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise HookConfigError(f"{label}: '{field_name}' must be a string")
    return value


def _bool_field(data: dict, field_name: str, label: str) -> bool:
    value = data.get(field_name, False)
    if not isinstance(value, bool):
        raise HookConfigError(f"{label}: '{field_name}' must be a boolean")
    return value


def _headers_field(data: dict, label: str) -> dict[str, str]:
    value = data.get("headers", {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HookConfigError(f"{label}: 'headers' must be a mapping")
    for key, header_value in value.items():
        if not isinstance(key, str) or not isinstance(header_value, str):
            raise HookConfigError(
                f"{label}: 'headers' must map strings to strings"
            )
    return dict(value)


def _load_action(raw_action: object, label: str) -> Action:
    if not isinstance(raw_action, dict):
        raise HookConfigError(f"{label}: missing or invalid 'action' field")

    action_type = raw_action.get("type")
    if action_type not in _VALID_ACTION_TYPES:
        raise HookConfigError(
            f"{label}: invalid action type '{action_type}', "
            f"must be one of: {', '.join(sorted(_VALID_ACTION_TYPES))}"
        )

    string_fields = {
        field_name: _string_field(
            raw_action,
            field_name,
            label,
            default="POST" if field_name == "method" else "",
        )
        for field_name in _ACTION_STRING_FIELDS
    }
    required = _REQUIRED_FIELDS[action_type]
    for field_name in required:
        if not string_fields[field_name]:
            raise HookConfigError(
                f"{label}: action type '{action_type}' requires "
                f"'{field_name}' field"
            )

    timeout = raw_action.get("timeout", 30)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise HookConfigError(f"{label}: timeout must be a positive integer")

    return Action(
        type=action_type,
        command=string_fields["command"],
        message=string_fields["message"],
        url=string_fields["url"],
        method=string_fields["method"],
        body=string_fields["body"],
        headers=_headers_field(raw_action, label),
        prompt=string_fields["prompt"],
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

        reject = _bool_field(entry, "reject", label)
        if reject and event != "pre_tool_use":
            raise HookConfigError(
                f"{label}: 'reject' can only be used with 'pre_tool_use' event"
            )

        async_exec = _bool_field(entry, "async", label)
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
                once=_bool_field(entry, "once", label),
                async_exec=async_exec,
            )
        )

    return hooks
