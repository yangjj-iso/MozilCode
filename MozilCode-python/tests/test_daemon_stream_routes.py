from __future__ import annotations

from starlette.testclient import TestClient

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.server import create_app


def _app(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    return create_app(AppConfig(providers=[provider]), str(tmp_path))


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
    app.state.server._event_logs[sid] = [
        {"type": "UserMessage", "data": {"content": "hello"}},
    ]
    app.state.server._session_meta[sid] = {"work_dir": str(tmp_path), "title": ""}

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/stream/{sid}") as websocket:
            replayed = websocket.receive_json()
            replay_done = websocket.receive_json()

    assert replayed == {"type": "UserMessage", "data": {"content": "hello"}}
    assert replay_done == {"type": "ReplayDone", "data": {}}
