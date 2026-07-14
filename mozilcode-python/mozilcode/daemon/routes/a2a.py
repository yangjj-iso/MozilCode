"""A2A JSON-RPC 与 agent card 路由。"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.a2a.bridge import A2ABridge
from mozilcode.a2a.protocol import A2AError
from mozilcode.daemon.request_body import read_json_object
from mozilcode.daemon.request_context import a2a_bridge, path_param


def public_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def json_rpc_parse_error_response() -> JSONResponse:
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": "Parse error"},
        },
        status_code=400,
    )


def a2a_error_response(error: A2AError, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"error": error.message, "code": error.code},
        status_code=status_code,
    )


async def a2a_agent_card(request: Request) -> JSONResponse:
    bridge: A2ABridge = a2a_bridge(request)
    return JSONResponse(bridge.agent_card(public_base_url(request)))


async def a2a_rpc(request: Request) -> JSONResponse:
    bridge: A2ABridge = a2a_bridge(request)
    try:
        payload = await request.json()
    except ValueError:
        return json_rpc_parse_error_response()
    return JSONResponse(await bridge.handle_json_rpc(payload))


async def a2a_message_send(request: Request) -> JSONResponse:
    bridge: A2ABridge = a2a_bridge(request)
    try:
        parsed = await read_json_object(request)
        if not parsed.ok:
            return parsed.error_response()
        body = parsed.payload
        result = await bridge.send_message(body or {})
    except A2AError as e:
        return a2a_error_response(e, 400)
    return JSONResponse(result)


async def a2a_task_get(request: Request) -> JSONResponse:
    bridge: A2ABridge = a2a_bridge(request)
    try:
        task = bridge.get_task(path_param(request, "task_id"))
    except A2AError as e:
        return a2a_error_response(e, 404)
    return JSONResponse(bridge.task_to_a2a(task))


async def a2a_task_cancel(request: Request) -> JSONResponse:
    bridge: A2ABridge = a2a_bridge(request)
    try:
        task = await bridge.cancel_task(path_param(request, "task_id"))
    except A2AError as e:
        return a2a_error_response(e, 404)
    return JSONResponse(bridge.task_to_a2a(task))
