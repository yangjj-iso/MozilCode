"""Hook Action 配置解析。

将 config.yaml 中的 raw action 字典解析为 Action 数据对象。
校验 action type 合法性、必填字段、timeout 类型等。
"""

from __future__ import annotations

from mozilcode.hooks.errors import HookConfigError
from mozilcode.hooks.models import Action

# 有效的 action 类型集合
_VALID_ACTION_TYPES = {"command", "prompt", "http", "agent"}

# 每种 action 类型必须配置的字段
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "command": ["command"],
    "prompt": ["message"],
    "http": ["url"],
    "agent": ["prompt"],
}
# 所有字符串类型的 action 字段名
_ACTION_STRING_FIELDS = ("command", "message", "url", "method", "body", "prompt")


def _string_field(
    data: dict,
    field_name: str,
    label: str,
    default: str = "",
) -> str:
    """从原始配置字典中提取字符串字段，带类型校验。"""
    value = data.get(field_name, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise HookConfigError(f"{label}: '{field_name}' must be a string")
    return value


def _headers_field(data: dict, label: str) -> dict[str, str]:
    """解析 http action 的 headers 字段，确保 key 和 value 都是字符串。"""
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
    """从 config.yaml 的原始字典解析出 Action 对象。

    解析流程：
    1. 校验 action type 是否合法
    2. 提取所有字符串字段（统一处理，避免重复代码）
    3. 校验必填字段是否已配置
    4. 校验 timeout 为正整数
    5. 构造并返回 Action 对象

    label 参数用于错误消息定位（如 "hooks[0]"）。
    """
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
