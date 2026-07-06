from __future__ import annotations

import asyncio
import json
import logging

from starlette.websockets import WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)


async def stream_events(websocket: WebSocket) -> None:
    """Replay a session's full event history, then tail it live."""
    await websocket.accept()
    sid = websocket.path_params["sid"]
    server = websocket.app.state.server

    log_list = server.get_event_log(sid)
    if log_list is None:
        await websocket.send_json(
            {"type": "SessionNotFound", "data": {"session_id": sid}}
        )
        await websocket.close(code=4404)
        return

    log.info("WS client connected to session %s", sid)
    disconnected = asyncio.Event()

    async def _listen_client() -> None:
        try:
            while True:
                raw = await websocket.receive_text()
                if not raw:
                    continue
                try:
                    if json.loads(raw).get("action") == "cancel":
                        task = server._tasks.get(sid)
                        if task and not task.done():
                            task.cancel()
                except (json.JSONDecodeError, AttributeError):
                    pass
        except WebSocketDisconnect:
            disconnected.set()
        except Exception:
            disconnected.set()

    listener = asyncio.create_task(_listen_client())
    idx = 0
    replay_marked = False
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
                    await websocket.send_json(event)
                if stop:
                    break
            else:
                if not replay_marked:
                    replay_marked = True
                    try:
                        await websocket.send_json({"type": "ReplayDone", "data": {}})
                        for event in list(server._pending_prompts.get(sid, {}).values()):
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
