"""A2A / JSON-RPC 协议解析。

解析请求体、元数据与配置字段，抽取 message/task 相关参数。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class A2AError(Exception):
    def __init__(self, message: str, code: int = -32000, data: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data


@dataclass(frozen=True)
class A2AMessageRequest:
    prompt: str
    context_id: str
    task_id_hint: str
    metadata: dict[str, Any]
    work_dir: str | None


@dataclass(frozen=True)
class JsonRpcRequest:
    id: Any
    method: str
    params: Any


def parse_json_rpc_request(payload: Any) -> JsonRpcRequest:
    if not isinstance(payload, dict):
        raise A2AError("Invalid JSON-RPC request", -32600)
    if payload.get("jsonrpc") != "2.0":
        raise A2AError("Invalid JSON-RPC request", -32600)

    method = payload.get("method")
    if not isinstance(method, str) or not method.strip():
        raise A2AError("Invalid JSON-RPC request", -32600)

    params = payload.get("params")
    if params is None:
        params = {}
    return JsonRpcRequest(
        id=payload.get("id"),
        method=method,
        params=params,
    )


def parse_message_request(params: dict[str, Any]) -> A2AMessageRequest:
    message = _message_from_params(params)
    prompt = _extract_text(message)
    if not prompt:
        raise A2AError("message must contain a text part", -32602)

    metadata = metadata_from_params(params)
    work_dir = _work_dir_from_metadata(metadata)
    return A2AMessageRequest(
        prompt=prompt,
        context_id=_context_id_from_message(params, message),
        task_id_hint=_task_id_hint_from_message(params, message),
        metadata=metadata,
        work_dir=work_dir,
    )


def task_id_from_params(params: Any) -> str:
    if isinstance(params, str):
        task_id = params.strip()
        if not task_id:
            raise A2AError("task id is required", -32602)
        return task_id
    if not isinstance(params, dict):
        raise A2AError("task params must be an object", -32602)
    task_id = _string_from_aliases(
        params,
        ("id", "taskId", "task_id"),
        field_label="task id",
    )
    if not task_id:
        raise A2AError("task id is required", -32602)
    return task_id


def metadata_from_params(params: dict[str, Any]) -> dict[str, Any]:
    metadata = params.get("metadata")
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise A2AError("metadata must be an object", -32602)
    return dict(metadata)


def configuration_from_params(params: dict[str, Any]) -> dict[str, Any]:
    config = params.get("configuration")
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise A2AError("configuration must be an object", -32602)
    return config


def should_wait(config: dict[str, Any]) -> bool:
    if "returnImmediately" in config:
        return not _bool_from_config(config, "returnImmediately")
    if "blocking" in config:
        return _bool_from_config(config, "blocking")
    if "waitUntilCompleted" in config:
        return _bool_from_config(config, "waitUntilCompleted")
    return False


def float_from_config(config: dict[str, Any], key: str, default: float) -> float:
    if key not in config:
        return default
    value = config[key]
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value <= 0
    ):
        raise A2AError(f"configuration.{key} must be a positive number", -32602)
    return float(value)


def _message_from_params(params: dict[str, Any]) -> dict[str, Any]:
    message = params["message"] if "message" in params else params
    if not isinstance(message, dict):
        raise A2AError("message must be an object", -32602)
    return message


def _extract_text(message: dict[str, Any]) -> str:
    direct = message.get("content")
    if isinstance(direct, str):
        return direct.strip()

    parts = message.get("parts") or []
    if not isinstance(parts, list):
        return ""

    chunks: list[str] = []
    for part in parts:
        if isinstance(part, str):
            chunks.append(part)
            continue
        if not isinstance(part, dict):
            continue
        if isinstance(part.get("text"), str):
            chunks.append(part["text"])
            continue
        nested = part.get("text")
        if isinstance(nested, dict) and isinstance(nested.get("text"), str):
            chunks.append(nested["text"])
            continue
        if isinstance(part.get("data"), str):
            chunks.append(part["data"])
    return "\n".join(c.strip() for c in chunks if c and c.strip()).strip()


def _work_dir_from_metadata(metadata: dict[str, Any]) -> str | None:
    work_dir = _string_from_aliases(
        metadata,
        ("work_dir", "workDir"),
        field_label="metadata.work_dir",
    )
    return work_dir or None


def _context_id_from_message(
    params: dict[str, Any],
    message: dict[str, Any],
) -> str:
    context_id = _string_from_aliases(
        message,
        ("contextId", "context_id"),
        field_label="message.contextId",
    )
    if context_id:
        return context_id
    return _string_from_aliases(
        params,
        ("contextId", "context_id"),
        field_label="contextId",
    )


def _task_id_hint_from_message(
    params: dict[str, Any],
    message: dict[str, Any],
) -> str:
    task_id = _string_from_aliases(
        message,
        ("taskId", "task_id"),
        field_label="message.taskId",
    )
    if task_id:
        return task_id
    return _string_from_aliases(
        params,
        ("taskId", "task_id"),
        field_label="taskId",
    )


def _string_from_aliases(
    data: dict[str, Any],
    aliases: tuple[str, ...],
    *,
    field_label: str,
) -> str:
    for alias in aliases:
        if alias not in data:
            continue
        value = data[alias]
        if value is None:
            return ""
        if not isinstance(value, str):
            raise A2AError(f"{field_label} must be a string", -32602)
        return value.strip()
    return ""


def _bool_from_config(config: dict[str, Any], key: str) -> bool:
    value = config.get(key)
    if not isinstance(value, bool):
        raise A2AError(f"configuration.{key} must be a boolean", -32602)
    return value
