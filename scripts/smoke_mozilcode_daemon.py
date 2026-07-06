from __future__ import annotations

import argparse
import asyncio
import json
from urllib.parse import urlparse, urlunparse

import httpx
import websockets


REMOVED_MANAGEMENT_ENDPOINTS = (
    ("GET", "/api/config"),
    ("POST", "/api/config"),
    ("GET", "/api/settings/mcp"),
    ("POST", "/api/settings/mcp"),
    ("GET", "/api/settings/memory"),
    ("POST", "/api/settings/memory"),
    ("GET", "/api/skills"),
    ("POST", "/api/skills"),
)


class SmokeFailure(RuntimeError):
    pass


def websocket_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "", "", "", ""))


async def request_json(
    http: httpx.AsyncClient,
    method: str,
    base_url: str,
    path: str,
    *,
    expected_status: int,
    payload: dict | None = None,
) -> dict:
    response = await http.request(method, f"{base_url}{path}", json=payload)
    if response.status_code != expected_status:
        raise SmokeFailure(
            f"{method} {path} returned {response.status_code}, "
            f"expected {expected_status}: {response.text[:300]}"
        )
    if not response.content:
        return {}
    try:
        data = response.json()
    except json.JSONDecodeError as e:
        raise SmokeFailure(f"{method} {path} did not return JSON") from e
    if not isinstance(data, dict):
        raise SmokeFailure(f"{method} {path} returned non-object JSON")
    return data


async def request_status(
    http: httpx.AsyncClient,
    method: str,
    base_url: str,
    path: str,
    *,
    expected_status: int,
    payload: dict | None = None,
) -> None:
    response = await http.request(method, f"{base_url}{path}", json=payload)
    if response.status_code != expected_status:
        raise SmokeFailure(
            f"{method} {path} returned {response.status_code}, "
            f"expected {expected_status}: {response.text[:300]}"
        )


async def verify_removed_management_routes(
    http: httpx.AsyncClient,
    base_url: str,
) -> None:
    for method, path in REMOVED_MANAGEMENT_ENDPOINTS:
        await request_status(
            http,
            method,
            base_url,
            path,
            expected_status=404,
            payload={} if method == "POST" else None,
        )


async def verify_stream_replay(ws_base_url: str, session_id: str, timeout: float) -> None:
    async with websockets.connect(
        f"{ws_base_url}/api/stream/{session_id}",
        open_timeout=timeout,
        close_timeout=timeout,
    ) as websocket:
        raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SmokeFailure("stream returned non-JSON event") from e
    if event != {"type": "ReplayDone", "data": {}}:
        raise SmokeFailure(f"unexpected first stream event: {event}")


async def run_smoke(base_url: str, timeout: float) -> dict:
    base_url = base_url.rstrip("/")
    ws_base = websocket_base_url(base_url)
    async with httpx.AsyncClient(timeout=timeout) as http:
        health = await request_json(
            http, "GET", base_url, "/api/health", expected_status=200
        )
        if not health.get("configured"):
            raise SmokeFailure(
                "daemon is running but no model provider is configured; "
                "create .mozilcode/config.yaml before running the full smoke"
            )

        session = await request_json(
            http, "POST", base_url, "/api/session", expected_status=200, payload={}
        )
        session_id = str(session.get("session_id") or "")
        if not session_id:
            raise SmokeFailure("session response did not include session_id")

        status = await request_json(
            http,
            "GET",
            base_url,
            f"/api/session/{session_id}/status",
            expected_status=200,
        )
        if status.get("id") != session_id:
            raise SmokeFailure("session status id did not match created session")

        agent_card = await request_json(
            http,
            "GET",
            base_url,
            "/.well-known/agent-card.json",
            expected_status=200,
        )
        if agent_card.get("name") != "MozilCode":
            raise SmokeFailure("A2A agent card did not identify MozilCode")

        await verify_removed_management_routes(http, base_url)
        await verify_stream_replay(ws_base, session_id, timeout)
        await request_json(
            http,
            "DELETE",
            base_url,
            f"/api/session/{session_id}",
            expected_status=200,
        )

    return {
        "base_url": base_url,
        "session_id": session_id,
        "provider_model": status.get("provider", {}).get("model", ""),
        "checks": [
            "health",
            "session",
            "session_status",
            "a2a_agent_card",
            "removed_management_routes",
            "websocket_replay",
            "session_delete",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke-test a running MozilCode daemon without calling a model."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:7800")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    result = asyncio.run(run_smoke(args.base_url, args.timeout))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
