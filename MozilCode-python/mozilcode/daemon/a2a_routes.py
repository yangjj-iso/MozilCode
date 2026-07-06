from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.a2a.bridge import A2ABridge, A2AError


def public_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


async def a2a_agent_card(request: Request) -> JSONResponse:
    bridge: A2ABridge = request.app.state.a2a_bridge
    return JSONResponse(bridge.agent_card(public_base_url(request)))


async def a2a_rpc(request: Request) -> JSONResponse:
    bridge: A2ABridge = request.app.state.a2a_bridge
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
        )
    return JSONResponse(await bridge.handle_json_rpc(payload))


async def a2a_message_send(request: Request) -> JSONResponse:
    bridge: A2ABridge = request.app.state.a2a_bridge
    try:
        body = await request.json()
        result = await bridge.send_message(body or {})
    except A2AError as e:
        return JSONResponse({"error": e.message, "code": e.code}, status_code=400)
    return JSONResponse(result)


async def a2a_task_get(request: Request) -> JSONResponse:
    bridge: A2ABridge = request.app.state.a2a_bridge
    try:
        task = bridge.get_task(request.path_params["task_id"])
    except A2AError as e:
        return JSONResponse({"error": e.message, "code": e.code}, status_code=404)
    return JSONResponse(bridge.task_to_a2a(task))


async def a2a_task_cancel(request: Request) -> JSONResponse:
    bridge: A2ABridge = request.app.state.a2a_bridge
    try:
        task = await bridge.cancel_task(request.path_params["task_id"])
    except A2AError as e:
        return JSONResponse({"error": e.message, "code": e.code}, status_code=404)
    return JSONResponse(bridge.task_to_a2a(task))
