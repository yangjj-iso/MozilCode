from __future__ import annotations

from mozilcode.hooks.errors import HookConfigError
from mozilcode.hooks.models import Action

_VALID_ACTION_TYPES = {"command", "prompt", "http", "agent"}

_REQUIRED_FIELDS: dict[str, list[str]] = {
    "command": ["command"],
    "prompt": ["message"],
    "http": ["url"],
    "agent": ["prompt"],
}
_ACTION_STRING_FIELDS = ("command", "message", "url", "method", "body", "prompt")


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


def load_action(raw_action: object, label: str) -> Action:
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
