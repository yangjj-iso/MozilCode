from __future__ import annotations

from mozilcode.hooks.actions import load_action
from mozilcode.hooks.conditions import ConditionParseError, parse_condition
from mozilcode.hooks.errors import HookConfigError
from mozilcode.hooks.events import LifecycleEvent
from mozilcode.hooks.models import Hook

_VALID_EVENTS = {e.value for e in LifecycleEvent}


def _identify(entry: object, index: int) -> str:
    if isinstance(entry, dict):
        hook_id = entry.get("id", "")
        if isinstance(hook_id, str) and hook_id.strip():
            return f"hook '{hook_id.strip()}'"
    return f"hook #{index + 1}"


def _required_top_string(data: dict, field_name: str, label: str) -> str:
    if field_name not in data or data[field_name] is None:
        raise HookConfigError(f"{label}: missing '{field_name}' field")
    value = data[field_name]
    if not isinstance(value, str):
        raise HookConfigError(f"{label}: '{field_name}' must be a string")
    value = value.strip()
    if not value:
        raise HookConfigError(f"{label}: missing '{field_name}' field")
    return value


def _optional_top_string(
    data: dict,
    field_name: str,
    label: str,
    default: str | None = None,
    *,
    allow_empty: bool = False,
) -> str | None:
    if field_name not in data or data[field_name] is None:
        return default
    value = data[field_name]
    if not isinstance(value, str):
        raise HookConfigError(f"{label}: '{field_name}' must be a string")
    value = value.strip()
    if not value:
        if allow_empty:
            return default
        raise HookConfigError(f"{label}: '{field_name}' must not be empty")
    return value


def _bool_field(data: dict, field_name: str, label: str) -> bool:
    value = data.get(field_name, False)
    if not isinstance(value, bool):
        raise HookConfigError(f"{label}: '{field_name}' must be a boolean")
    return value


def load_hooks(raw_hooks: list[object] | None) -> list[Hook]:
    if not raw_hooks:
        return []

    hooks: list[Hook] = []
    seen_ids: set[str] = set()
    for i, entry in enumerate(raw_hooks):
        label = _identify(entry, i)

        if not isinstance(entry, dict):
            raise HookConfigError(f"{label}: must be a mapping")

        event = _required_top_string(entry, "event", label)
        if event not in _VALID_EVENTS:
            raise HookConfigError(
                f"{label}: invalid event '{event}', "
                f"must be one of: {', '.join(sorted(_VALID_EVENTS))}"
            )

        action = load_action(entry.get("action"), label)

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
        raw_if = _optional_top_string(entry, "if", label, allow_empty=True)
        if raw_if:
            try:
                condition = parse_condition(raw_if)
            except ConditionParseError as e:
                raise HookConfigError(f"{label}: condition error: {e}") from e

        hook_id = _optional_top_string(entry, "id", label, default=f"{event}_{i}")
        if hook_id in seen_ids:
            raise HookConfigError(f"{label}: duplicate hook id '{hook_id}'")
        seen_ids.add(hook_id)

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
