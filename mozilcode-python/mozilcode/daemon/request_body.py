"""HTTP JSON 请求体解析与字段校验。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.daemon.responses import bad_request_response, error_response


class BodyFieldError(ValueError):
    pass


T = TypeVar("T")


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


@dataclass(frozen=True)
class ParsedJsonObject(Generic[T]):
    value: T | None = None
    error: JSONResponse | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def unwrap(self) -> T:
        if self.error is not None or self.value is None:
            raise RuntimeError("parsed JSON object has no value")
        return self.value


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


async def parse_json_object(
    request: Request,
    parser: Callable[[dict[str, Any]], T],
) -> ParsedJsonObject[T]:
    parsed = await read_json_object(request)
    if not parsed.ok:
        return ParsedJsonObject(error=parsed.error_response())
    try:
        return ParsedJsonObject(value=parser(parsed.payload))
    except BodyFieldError as e:
        return ParsedJsonObject(error=bad_request_response(str(e)))


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


def required_string_field(
    payload: dict[str, Any],
    name: str,
    *,
    strip: bool = True,
) -> str:
    value = string_field(payload, name)
    if strip:
        value = value.strip()
    if not value:
        raise BodyFieldError(f"'{name}' is required")
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


def required_choice_field(
    payload: dict[str, Any],
    name: str,
    choices: set[str],
) -> str:
    value = required_string_field(payload, name)
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


def string_mapping_field(
    payload: dict[str, Any],
    name: str,
) -> dict[str, str]:
    value = object_field(payload, name)
    if not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    ):
        raise BodyFieldError(f"'{name}' must be an object of strings")
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
