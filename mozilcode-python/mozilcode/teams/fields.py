"""Team 相关字段解析辅助。"""

from __future__ import annotations

from typing import Any


def string_field(
    data: dict[str, Any],
    name: str,
    *,
    prefix: str,
    default: str = "",
    required: bool = True,
) -> str:
    value = data.get(name, default)
    if not isinstance(value, str):
        raise ValueError(f"{prefix}.{name} must be a string")
    if required and not value:
        raise ValueError(f"{prefix}.{name} is required")
    return value


def string_list_field(
    data: dict[str, Any],
    name: str,
    *,
    prefix: str,
) -> list[str]:
    value = data.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{prefix}.{name} must be a list of strings")
    return value


def object_field(
    data: dict[str, Any],
    name: str,
    *,
    prefix: str,
) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"{prefix}.{name} must be an object")
    return value


def non_negative_number_field(
    data: dict[str, Any],
    name: str,
    *,
    prefix: str,
    default: float = 0.0,
) -> float:
    value = data.get(name, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{prefix}.{name} must be a non-negative number")
    return float(value)


def optional_bool_field(
    data: dict[str, Any],
    name: str,
    *,
    prefix: str,
) -> bool | None:
    value = data.get(name)
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{prefix}.{name} must be a boolean or null")
    return value
