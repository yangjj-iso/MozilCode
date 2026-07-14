"""Daemon Origin 防护中间件测试。"""

from __future__ import annotations

from starlette.testclient import TestClient

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.server import _is_loopback_host, create_app
from mozilcode.daemon.session.store import SessionStore


ALLOWED_ORIGIN = "http://localhost:1420"


def _app(tmp_path, *, auth_token: str | None = None):
    provider = ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="test-model",
        api_key="test-key",
    )
    return create_app(
        AppConfig(providers=[provider]),
        str(tmp_path),
        session_store=SessionStore(tmp_path / "sessions"),
        cors_origins=[ALLOWED_ORIGIN],
        auth_token=auth_token,
    )


def test_origin_guard_allows_configured_browser_origin(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/health", headers={"origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_origin_guard_rejects_unknown_browser_origin(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get(
            "/api/health",
            headers={"origin": "https://untrusted.example"},
        )

    assert response.status_code == 403
    assert response.json() == {"error": "origin is not allowed"}


def test_origin_guard_keeps_non_browser_local_clients_working(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200


def test_daemon_token_protects_api_but_keeps_health_public(tmp_path) -> None:
    with TestClient(_app(tmp_path, auth_token="local-secret")) as client:
        health = client.get("/api/health")
        denied = client.get("/api/sessions")
        allowed = client.get(
            "/api/sessions",
            headers={"authorization": "Bearer local-secret"},
        )

    assert health.status_code == 200
    assert denied.status_code == 401
    assert denied.json() == {"error": "daemon authentication required"}
    assert allowed.status_code == 200


def test_loopback_host_detection() -> None:
    assert _is_loopback_host("127.0.0.1")
    assert _is_loopback_host("127.20.30.40")
    assert _is_loopback_host("localhost")
    assert _is_loopback_host("::1")
    assert not _is_loopback_host("0.0.0.0")
    assert not _is_loopback_host("192.168.1.20")
