from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.daemon.responses import error_response


class BodyFieldError(ValueError):
    pass


@dataclass(frozen=True)
class JsonObjectBody:
    payload: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    status_code: int = 200

    @property
    def ok(self) -> bool:
        return not self.error

    def error_response(self) -> JSONResponse:
        return error_response(self.error, self.status_code)


async def read_json_object(request: Request) -> JsonObjectBody:
    try:
        payload = await request.json()
    except ValueError:
        return JsonObjectBody(error="Invalid JSON body", status_code=400)

    if payload is None:
        return JsonObjectBody()
    if not isinstance(payload, dict):
        return JsonObjectBody(error="JSON object is required", status_code=400)
    return JsonObjectBody(payload=payload)


def string_field(
    payload: dict[str, Any],
    name: str,
    default: str = "",
) -> str:
    value = payload.get(name, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise BodyFieldError(f"'{name}' must be a string")
    return value


def choice_field(
    payload: dict[str, Any],
    name: str,
    choices: set[str],
    default: str = "",
) -> str:
    value = string_field(payload, name, default)
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise BodyFieldError(f"'{name}' must be one of: {allowed}")
    return value


def object_field(
    payload: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    value = payload.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BodyFieldError(f"'{name}' must be an object")
    return value


def bool_field(
    payload: dict[str, Any],
    name: str,
    default: bool = False,
) -> bool:
    value = payload.get(name, default)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise BodyFieldError(f"'{name}' must be a boolean")
    return value
