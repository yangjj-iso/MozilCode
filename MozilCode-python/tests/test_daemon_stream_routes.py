from __future__ import annotations

from starlette.testclient import TestClient

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.server import create_app
from mozilcode.daemon.session.store import SessionStore
from mozilcode.daemon.stream_routes import (
    parse_client_action,
    pending_prompt_events_after_replay,
)


def _app(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    return create_app(
        AppConfig(providers=[provider]),
        str(tmp_path),
        session_store=SessionStore(tmp_path / "sessions"),
    )


class _CancellableTask:
    def __init__(self) -> None:
        self.cancelled = False

    def done(self) -> bool:
        return False

    def cancel(self) -> None:
        self.cancelled = True


def test_stream_unknown_session_reports_session_not_found(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/api/stream/missing") as websocket:
            event = websocket.receive_json()

    assert event == {
        "type": "SessionNotFound",
        "data": {"session_id": "missing"},
    }


def test_stream_replays_existing_events_then_marks_replay_done(tmp_path):
    app = _app(tmp_path)
    sid = "existing-session"
    app.state.server._records.event_logs[sid] = [
        {"type": "UserMessage", "data": {"content": "hello"}},
    ]
    app.state.server._records.session_meta[sid] = {"work_dir": str(tmp_path), "title": ""}

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/stream/{sid}") as websocket:
            replayed = websocket.receive_json()
            replay_done = websocket.receive_json()

    assert replayed == {"type": "UserMessage", "data": {"content": "hello"}}
    assert replay_done == {"type": "ReplayDone", "data": {}}


def test_parse_client_action_accepts_cancel_action() -> None:
    assert parse_client_action('{"action": "cancel"}') == "cancel"


def test_parse_client_action_rejects_invalid_messages() -> None:
    assert parse_client_action("") == ""
    assert parse_client_action("{bad") == ""
    assert parse_client_action("[]") == ""
    assert parse_client_action('{"action": 7}') == ""
    assert parse_client_action('{"action": "unknown"}') == ""


def test_stream_cancel_action_cancels_active_session_task(tmp_path):
    app = _app(tmp_path)
    sid = "busy-session"
    task = _CancellableTask()
    app.state.server._records.event_logs[sid] = []
    app.state.server._records.session_meta[sid] = {"work_dir": str(tmp_path), "title": ""}
    app.state.server._active_tasks.tasks[sid] = task

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/stream/{sid}") as websocket:
            assert websocket.receive_json() == {"type": "ReplayDone", "data": {}}
            websocket.send_json({"action": "cancel"})

    assert task.cancelled


def test_pending_prompt_events_after_replay_skips_replayed_requests() -> None:
    replayed = {"req-1"}
    pending_events = [
        {
            "type": "PermissionRequest",
            "data": {"request_id": "req-1"},
        },
        {
            "type": "AskUserRequest",
            "data": {"request_id": "req-2"},
        },
    ]

    assert pending_prompt_events_after_replay(pending_events, replayed) == [
        {
            "type": "AskUserRequest",
            "data": {"request_id": "req-2"},
        }
    ]


def test_pending_prompt_events_after_replay_keeps_events_without_request_id() -> None:
    pending_events = [
        {
            "type": "PermissionRequest",
            "data": {},
        }
    ]

    assert (
        pending_prompt_events_after_replay(pending_events, {"req-1"})
        == pending_events
    )
