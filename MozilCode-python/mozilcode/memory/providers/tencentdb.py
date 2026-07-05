from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx

from mozilcode.conversation import ConversationManager, Message
from mozilcode.memory.providers.base import (
    MEMORY_EVENT_SESSION_END,
    MEMORY_EVENT_TURN_COMPLETED,
    BaseMemoryProvider,
    MemoryEvent,
    MemoryItem,
    MemoryScope,
)

log = logging.getLogger(__name__)

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8420"


class TencentDBGatewayError(RuntimeError):
    pass


class TencentDBGatewayClient:
    def __init__(
        self,
        base_url: str = DEFAULT_GATEWAY_URL,
        *,
        api_key: str = "",
        timeout: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.transport = transport

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def recall(self, query: str, session_key: str, user_id: str = "") -> dict[str, Any]:
        body: dict[str, Any] = {"query": query, "session_key": session_key}
        if user_id:
            body["user_id"] = user_id
        return await self._request("POST", "/recall", json=body)

    async def capture(
        self,
        user_content: str,
        assistant_content: str,
        session_key: str,
        *,
        session_id: str = "",
        user_id: str = "",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "user_content": user_content,
            "assistant_content": assistant_content,
            "session_key": session_key,
        }
        if session_id:
            body["session_id"] = session_id
        if user_id:
            body["user_id"] = user_id
        return await self._request("POST", "/capture", json=body)

    async def search_memories(
        self,
        query: str,
        *,
        limit: int = 5,
        type_filter: str = "",
        scene: str = "",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"query": query, "limit": limit}
        if type_filter:
            body["type"] = type_filter
        if scene:
            body["scene"] = scene
        return await self._request("POST", "/search/memories", json=body)

    async def end_session(self, session_key: str, user_id: str = "") -> dict[str, Any]:
        body: dict[str, Any] = {"session_key": session_key}
        if user_id:
            body["user_id"] = user_id
        return await self._request("POST", "/session/end", json=body)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
        ) as client:
            response = await client.request(method, path, json=json, headers=headers)
        if response.status_code >= 400:
            body = response.text[:300]
            raise TencentDBGatewayError(f"{method} {path} failed: HTTP {response.status_code}: {body}")
        try:
            data = response.json()
        except ValueError as e:
            raise TencentDBGatewayError(f"{method} {path} returned invalid JSON") from e
        if not isinstance(data, dict):
            raise TencentDBGatewayError(f"{method} {path} returned non-object JSON")
        return data


class TencentDBMemoryProvider(BaseMemoryProvider):
    name = "tencentdb"
    kind = "builtin.tencentdb"
    version = "1.0"

    def __init__(
        self,
        project_root: str,
        config: dict[str, Any] | None = None,
        *,
        client: TencentDBGatewayClient | None = None,
    ) -> None:
        self.project_root = project_root
        self.config = config or {}
        self.user_id = _config_str(
            self.config,
            "user_id",
            os.environ.get("MOZILCODE_USER_ID", ""),
        )
        self.session_prefix = _config_str(self.config, "session_prefix", "mozilcode")
        self.capture_enabled = _config_bool(self.config, "capture", True)
        self.recall_enabled = _config_bool(self.config, "recall", True)
        self.search_type = _config_str(self.config, "search_type", "")
        self.search_scene = _config_str(self.config, "search_scene", "")
        self._last_session_key = ""
        self._process: subprocess.Popen | None = None
        self.client = client or TencentDBGatewayClient(
            _gateway_url(self.config),
            api_key=_gateway_api_key(self.config),
            timeout=_config_float(self.config, "timeout", 5.0),
        )

    async def initialize(self) -> None:
        if await self._health_ok():
            return
        if not self._should_auto_start():
            raise TencentDBGatewayError(
                f"memory-tencentdb Gateway is not available at {self.client.base_url}"
            )
        await self._start_gateway()
        for _ in range(_config_int(self.config, "startup_retries", 30)):
            if await self._health_ok():
                return
            await asyncio.sleep(1)
        raise TencentDBGatewayError(
            f"memory-tencentdb Gateway did not become healthy at {self.client.base_url}"
        )

    async def load_context(self, query: str, scope: MemoryScope) -> str:
        if not self.recall_enabled or not query.strip():
            return ""
        session_key = self._session_key(scope.session_id, scope.project_root)
        self._last_session_key = session_key
        result = await self.client.recall(
            query.strip(),
            session_key,
            self._user_id(scope.user_id),
        )
        context = result.get("context", "")
        return context if isinstance(context, str) else ""

    async def observe(self, event: MemoryEvent) -> None:
        if event.type == MEMORY_EVENT_TURN_COMPLETED:
            await self._capture_turn(event)
        elif event.type == MEMORY_EVENT_SESSION_END:
            session_key = self._session_key(event.session_id)
            await self.client.end_session(session_key, self._user_id())
        else:
            return

    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        if not query.strip():
            return []
        result = await self.client.search_memories(
            query.strip(),
            limit=limit,
            type_filter=self.search_type,
            scene=self.search_scene,
        )
        text = result.get("results", "")
        if not isinstance(text, str) or not text.strip():
            return []
        return [
            MemoryItem(
                content=text.strip(),
                scope="project",
                metadata={
                    "provider": self.name,
                    "total": result.get("total"),
                    "strategy": result.get("strategy", ""),
                },
            )
        ]

    async def shutdown(self) -> None:
        if self._last_session_key:
            await self.client.end_session(self._last_session_key, self._user_id())

    async def _capture_turn(self, event: MemoryEvent) -> None:
        if not self.capture_enabled:
            return
        user_content, assistant_content = _last_user_assistant_turn(event.conversation)
        if not user_content or not assistant_content:
            return
        session_key = self._session_key(event.session_id)
        self._last_session_key = session_key
        await self.client.capture(
            user_content,
            assistant_content,
            session_key,
            session_id=event.session_id,
            user_id=self._user_id(),
        )

    async def _health_ok(self) -> bool:
        try:
            result = await self.client.health()
        except Exception:
            return False
        return result.get("status") in {"ok", "degraded"}

    def _should_auto_start(self) -> bool:
        return bool(_config_str(self.config, "gateway_cmd", os.environ.get("MEMORY_TENCENTDB_GATEWAY_CMD", ""))) and _config_bool(
            self.config,
            "auto_start",
            True,
        )

    async def _start_gateway(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        cmd = _config_str(self.config, "gateway_cmd", os.environ.get("MEMORY_TENCENTDB_GATEWAY_CMD", ""))
        if not cmd:
            return
        log_dir = Path(_config_str(self.config, "log_dir", str(Path.home() / ".mozilcode" / "logs" / "memory_tencentdb")))
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout = (log_dir / "gateway.stdout.log").open("ab")
        stderr = (log_dir / "gateway.stderr.log").open("ab")
        cwd = _config_str(self.config, "gateway_cwd", "")
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        self._process = subprocess.Popen(
            cmd,
            cwd=cwd or None,
            shell=True,
            stdout=stdout,
            stderr=stderr,
            creationflags=flags,
        )

    def _session_key(self, session_id: str = "", project_root: str = "") -> str:
        explicit = _config_str(self.config, "session_key", "")
        if explicit:
            return explicit
        sid = session_id.strip()
        root = project_root or self.project_root
        if not sid:
            sid = _project_digest(root)
        if self.session_prefix:
            return f"{self.session_prefix}:{sid}"
        return sid

    def _user_id(self, scoped_user_id: str = "") -> str:
        return scoped_user_id.strip() or self.user_id


def _gateway_url(config: dict[str, Any]) -> str:
    base_url = _config_str(config, "base_url", os.environ.get("MEMORY_TENCENTDB_GATEWAY_URL", ""))
    if base_url:
        return base_url
    host = _config_str(config, "host", os.environ.get("MEMORY_TENCENTDB_GATEWAY_HOST", "127.0.0.1"))
    port = _config_int(
        config,
        "port",
        _safe_int(os.environ.get("MEMORY_TENCENTDB_GATEWAY_PORT", "8420"), 8420),
    )
    return f"http://{host}:{port}"


def _gateway_api_key(config: dict[str, Any]) -> str:
    return _config_str(
        config,
        "api_key",
        os.environ.get("MEMORY_TENCENTDB_GATEWAY_API_KEY")
        or os.environ.get("TDAI_GATEWAY_API_KEY", ""),
    )


def _last_user_assistant_turn(conversation: Any) -> tuple[str, str]:
    if not isinstance(conversation, ConversationManager):
        return "", ""
    assistant = ""
    for message in reversed(conversation.history):
        if not assistant:
            if message.role == "assistant" and message.content.strip():
                assistant = message.content.strip()
            continue
        if _is_real_user_message(message):
            return message.content.strip(), assistant
    return "", ""


def _is_real_user_message(message: Message) -> bool:
    if message.role != "user" or message.tool_results:
        return False
    content = message.content.strip()
    if not content:
        return False
    if content.startswith("<system-reminder>"):
        return False
    if content.startswith("Current working directory:"):
        return False
    return True


def _project_digest(project_root: str) -> str:
    try:
        value = str(Path(project_root).resolve())
    except OSError:
        value = project_root or os.getcwd()
    return hashlib.sha1(value.encode("utf-8", errors="replace")).hexdigest()[:12]


def _config_str(config: dict[str, Any], key: str, default: str = "") -> str:
    value = config.get(key, default)
    return str(value or "").strip()


def _config_bool(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _config_int(config: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(config.get(key, default))
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _config_float(config: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(config.get(key, default))
    except (TypeError, ValueError):
        return default
