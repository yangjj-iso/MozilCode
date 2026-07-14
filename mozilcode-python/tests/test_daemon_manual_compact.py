"""Daemon 手动 compact 端到端测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from mozilcode.agent import CompactNotification, ErrorEvent
from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.context import compute_compact_threshold
from mozilcode.daemon.server import create_app
from mozilcode.daemon.responses import DaemonActionResult
from mozilcode.daemon.session.store import SessionStore
from mozilcode.daemon.server_state import DaemonServer, DaemonSessionRuntime
from mozilcode.permissions import PermissionMode


class _Registry:
    def list_tools(self):
        return []

    def is_enabled(self, _name):
        return False


class _Conversation:
    def __init__(self, tokens: int = 42_000) -> None:
        self.tokens = tokens

    def current_tokens(self) -> int:
        return self.tokens


class _Provider:
    name = "local"
    protocol = "openai-compat"
    model = "smoke-model"

    def get_context_window(self):
        return 128_000


class _Agent:
    permission_mode = PermissionMode.DEFAULT
    plan_mode = False
    context_window = 128_000
    total_input_tokens = 11
    total_output_tokens = 7
    registry = _Registry()
    memory_hub = None

    def __init__(self, result) -> None:
        self.result = result

    async def manual_compact(self, _conversation):
        return self.result


def _server_with_agent(tmp_path, result) -> tuple[DaemonServer, str]:
    provider = ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
    )
    server = DaemonServer(AppConfig(providers=[provider]), str(tmp_path))
    sid = "session-compact"
    server._agents[sid] = DaemonSessionRuntime(
        _Agent(result),
        SimpleNamespace(provider=_Provider()),
        _Conversation(),
    )
    server._records.event_logs[sid] = []
    server._records.session_meta[sid] = {"work_dir": str(tmp_path), "title": "compact"}
    server._records.persisted_count[sid] = 0
    return server, sid


@pytest.mark.asyncio
async def test_manual_compact_success_emits_started_result_and_usage(tmp_path):
    server, sid = _server_with_agent(
        tmp_path,
        CompactNotification(
            before_tokens=42_000,
            message="done",
            after_tokens=8_000,
        ),
    )

    result = await server.manual_compact(sid)

    assert result.status_code == 200
    assert result.payload["type"] == "CompactNotification"
    assert result.payload["data"]["message"] == "done"
    assert result.payload["status"]["id"] == sid
    assert [event["type"] for event in server._records.event_logs[sid]] == [
        "CompactStarted",
        "CompactNotification",
        "UsageEvent",
    ]
    started = server._records.event_logs[sid][0]["data"]
    assert started["current_tokens"] == 42_000
    assert started["threshold"] == max(
        0,
        compute_compact_threshold(128_000, manual=True),
    )
    assert server._records.event_logs[sid][2]["data"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "context_tokens": 42_000,
    }


@pytest.mark.asyncio
async def test_manual_compact_failure_emits_error_without_usage(tmp_path):
    server, sid = _server_with_agent(tmp_path, ErrorEvent("compact failed"))

    result = await server.manual_compact(sid)

    assert result == DaemonActionResult(
        {"error": "compact failed"},
        status_code=400,
    )
    assert [event["type"] for event in server._records.event_logs[sid]] == [
        "CompactStarted",
        "ErrorEvent",
    ]


@pytest.mark.asyncio
async def test_manual_compact_missing_session_returns_404(tmp_path):
    server = DaemonServer(AppConfig(providers=[]), str(tmp_path))

    result = await server.manual_compact("missing")

    assert result == DaemonActionResult(
        {"error": "session not found"},
        status_code=404,
    )


def test_manual_compact_route_uses_server_action_result(tmp_path, monkeypatch):
    provider = ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
    )
    app = create_app(
        AppConfig(providers=[provider]),
        str(tmp_path),
        session_store=SessionStore(tmp_path / "sessions"),
    )

    async def fake_manual_compact(sid: str):
        assert sid == "sid-1"
        return DaemonActionResult({"error": "not found"}, status_code=404)

    monkeypatch.setattr(app.state.server, "manual_compact", fake_manual_compact)

    with TestClient(app) as client:
        response = client.post("/api/compact/sid-1")

    assert response.status_code == 404
    assert response.json() == {"error": "not found"}
