from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from mozilcode.daemon.request_context import daemon_server, path_param
from mozilcode.daemon.task_events import pending_prompt_request_id

log = logging.getLogger(__name__)

CLIENT_ACTIONS = {"cancel"}


def parse_client_action(raw: str) -> str:
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    action = payload.get("action")
    if not isinstance(action, str):
        return ""
    return action if action in CLIENT_ACTIONS else ""


async def listen_client_actions(
    websocket: WebSocket,
    *,
    server: Any,
    sid: str,
    disconnected: asyncio.Event,
) -> None:
    try:
        while True:
            action = parse_client_action(await websocket.receive_text())
            if action == "cancel":
                server.cancel_active_task(sid)
    except WebSocketDisconnect:
        disconnected.set()
    except Exception:
        disconnected.set()


def pending_prompt_events_after_replay(
    pending_events: list[dict],
    replayed_request_ids: set[str],
) -> list[dict]:
    return [
        event
        for event in pending_events
        if pending_prompt_request_id(event) not in replayed_request_ids
    ]


async def stream_events(websocket: WebSocket) -> None:
    """Replay a session's full event history, then tail it live."""
    await websocket.accept()
    sid = path_param(websocket, "sid")
    server = daemon_server(websocket)

    log_list = server.get_event_log(sid)
    if log_list is None:
        await websocket.send_json(
            {"type": "SessionNotFound", "data": {"session_id": sid}}
        )
        await websocket.close(code=4404)
        return

    log.info("WS client connected to session %s", sid)
    disconnected = asyncio.Event()
    listener = asyncio.create_task(
        listen_client_actions(
            websocket,
            server=server,
            sid=sid,
            disconnected=disconnected,
        )
    )
    idx = 0
    replay_marked = False
    replayed_request_ids: set[str] = set()
    try:
        while not disconnected.is_set():
            if idx < len(log_list):
                batch = log_list[idx:]
                idx = len(log_list)
                stop = False
                for event in batch:
                    if event is None:
                        stop = True
                        break
                    request_id = pending_prompt_request_id(event)
                    if request_id:
                        replayed_request_ids.add(request_id)
                    await websocket.send_json(event)
                if stop:
                    break
            else:
                if not replay_marked:
                    replay_marked = True
                    try:
                        await websocket.send_json({"type": "ReplayDone", "data": {}})
                        pending_events = pending_prompt_events_after_replay(
                            server.pending_prompt_events(sid),
                            replayed_request_ids,
                        )
                        for event in pending_events:
                            await websocket.send_json(event)
                    except Exception:
                        pass
                await asyncio.sleep(0.02)
    except WebSocketDisconnect:
        log.info("WS client disconnected from session %s", sid)
    except Exception:
        log.exception("WS stream error for session %s", sid)
    finally:
        listener.cancel()
        try:
            await listener
        except (asyncio.CancelledError, Exception):
            pass
        log.info("WS stream ended for session %s", sid)
