from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from starlette.responses import JSONResponse


@dataclass(frozen=True)
class DaemonActionResult:
    payload: dict[str, Any]
    status_code: int = 200


def action_result(payload: dict[str, Any], status_code: int = 200) -> DaemonActionResult:
    return DaemonActionResult(payload, status_code=status_code)


def error_result(
    message: str,
    status_code: int,
    **extra: Any,
) -> DaemonActionResult:
    return action_result({"error": message, **extra}, status_code=status_code)


def bad_request_result(message: str, **extra: Any) -> DaemonActionResult:
    return error_result(message, 400, **extra)


def not_found_result(message: str, **extra: Any) -> DaemonActionResult:
    return error_result(message, 404, **extra)


def session_not_found_result() -> DaemonActionResult:
    return not_found_result("session not found")


def action_response(result: DaemonActionResult) -> JSONResponse:
    return JSONResponse(result.payload, status_code=result.status_code)


def error_response(message: str, status_code: int, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status_code)


def bad_request_response(message: str, **extra: Any) -> JSONResponse:
    return error_response(message, 400, **extra)


def not_found_response(message: str, **extra: Any) -> JSONResponse:
    return error_response(message, 404, **extra)
