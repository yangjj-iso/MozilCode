from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse


@dataclass(frozen=True)
class JsonObjectBody:
    payload: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    status_code: int = 200

    @property
    def ok(self) -> bool:
        return not self.error

    def error_response(self) -> JSONResponse:
        return JSONResponse({"error": self.error}, status_code=self.status_code)


async def read_json_object(request: Request) -> JsonObjectBody:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JsonObjectBody(error="Invalid JSON body", status_code=400)

    if payload is None:
        return JsonObjectBody()
    if not isinstance(payload, dict):
        return JsonObjectBody(error="JSON object is required", status_code=400)
    return JsonObjectBody(payload=payload)
