from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from mozilcode.a2a.bridge import A2ABridge, TASK_COMPLETED

log = logging.getLogger(__name__)

DEFAULT_INTENTS = 1 << 25  # GROUP_AND_C2C_EVENT


@dataclass
class OfficialQQConfig:
    app_id: str = ""
    app_secret: str = ""
    api_base: str = "https://api.sgroup.qq.com"
    token_url: str = "https://bots.qq.com/app/getAppAccessToken"
    gateway_url: str = ""
    command_prefix: str = "/mew"
    timeout: float = 120.0
    max_chunk_chars: int = 1800
    intents: int = DEFAULT_INTENTS
    shard_id: int = 0
    shard_count: int = 1
    reconnect_delay: float = 5.0
    allowed_users: set[str] | None = None
    allowed_groups: set[str] | None = None

    @classmethod
    def from_env(cls) -> OfficialQQConfig:
        return cls(
            app_id=os.environ.get("MOZILCODE_QQ_OFFICIAL_APP_ID", "").strip(),
            app_secret=os.environ.get("MOZILCODE_QQ_OFFICIAL_APP_SECRET", "").strip(),
            api_base=os.environ.get("MOZILCODE_QQ_OFFICIAL_API_BASE", "https://api.sgroup.qq.com").rstrip("/"),
            token_url=os.environ.get(
                "MOZILCODE_QQ_OFFICIAL_TOKEN_URL",
                "https://bots.qq.com/app/getAppAccessToken",
            ).strip(),
            gateway_url=os.environ.get("MOZILCODE_QQ_OFFICIAL_GATEWAY_URL", "").strip(),
            command_prefix=os.environ.get("MOZILCODE_QQ_COMMAND_PREFIX", "/mew"),
            timeout=_env_float("MOZILCODE_QQ_TIMEOUT", 120.0),
            max_chunk_chars=int(_env_float("MOZILCODE_QQ_MAX_CHUNK_CHARS", 1800)),
            intents=int(_env_float("MOZILCODE_QQ_OFFICIAL_INTENTS", DEFAULT_INTENTS)),
            shard_id=int(_env_float("MOZILCODE_QQ_OFFICIAL_SHARD_ID", 0)),
            shard_count=max(1, int(_env_float("MOZILCODE_QQ_OFFICIAL_SHARD_COUNT", 1))),
            reconnect_delay=max(1.0, _env_float("MOZILCODE_QQ_OFFICIAL_RECONNECT_DELAY", 5.0)),
            allowed_users=_csv_env("MOZILCODE_QQ_ALLOWED_USERS"),
            allowed_groups=_csv_env("MOZILCODE_QQ_ALLOWED_GROUPS"),
        )

    @classmethod
    def enabled_from_env(cls) -> bool:
        return _env_bool("MOZILCODE_QQ_OFFICIAL_ENABLED", False)

    def is_configured(self) -> bool:
        return bool(self.app_id and self.app_secret)


@dataclass
class OfficialQQMessage:
    scene: str
    event_type: str
    text: str
    message_id: str
    event_id: str = ""
    user_openid: str = ""
    member_openid: str = ""
    group_openid: str = ""
    channel_id: str = ""
    guild_id: str = ""

    @property
    def context_id(self) -> str:
        if self.scene == "group":
            return f"qq-official-group-{self.group_openid}"
        if self.scene == "channel":
            return f"qq-official-channel-{self.channel_id}"
        if self.scene == "dm":
            return f"qq-official-dm-{self.guild_id}-{self.user_openid}"
        return f"qq-official-c2c-{self.user_openid}"


class OfficialQQApi:
    def __init__(self, config: OfficialQQConfig | None = None) -> None:
        self._config = config or OfficialQQConfig.from_env()
        self._access_token = ""
        self._expires_at = 0.0

    async def access_token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._expires_at - 60:
            return self._access_token
        if not self._config.is_configured():
            raise RuntimeError("Official QQ Bot AppID/AppSecret is not configured")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                self._config.token_url,
                json={
                    "appId": self._config.app_id,
                    "clientSecret": self._config.app_secret,
                },
                headers={"Content-Type": "application/json"},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"QQ access token request failed: {_response_summary(resp)}")
        data = resp.json()
        token = str(data.get("access_token") or "")
        if not token:
            raise RuntimeError(f"QQ access token response did not contain access_token: {_safe_json(data)}")
        expires_in = _float_value(data.get("expires_in"), 7200.0)
        self._access_token = token
        self._expires_at = now + max(60.0, expires_in)
        return token

    async def auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"QQBot {await self.access_token()}",
            "Content-Type": "application/json",
        }

    async def get_gateway_url(self) -> str:
        if self._config.gateway_url:
            return self._config.gateway_url
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self._config.api_base}/gateway",
                headers=await self.auth_headers(),
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"QQ gateway URL request failed: {_response_summary(resp)}")
        data = resp.json()
        gateway = str(data.get("url") or "")
        if not gateway:
            raise RuntimeError(f"QQ gateway response did not contain url: {_safe_json(data)}")
        return gateway

    async def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._config.api_base}{path}",
                headers=await self.auth_headers(),
                json=payload,
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"QQ send message request failed: {_response_summary(resp)}")
        if not resp.content:
            return {}
        return resp.json()


class OfficialQQAdapter:
    """Official QQ Bot Gateway adapter for MozilCode's A2A bridge."""

    def __init__(
        self,
        bridge: A2ABridge,
        *,
        api: OfficialQQApi | None = None,
        config: OfficialQQConfig | None = None,
    ) -> None:
        self._bridge = bridge
        self._config = config or OfficialQQConfig.from_env()
        self._api = api or OfficialQQApi(self._config)
        self._seen_message_ids: dict[str, float] = {}

    async def handle_payload(self, payload: dict[str, Any], *, background: bool = True) -> dict[str, Any]:
        if payload.get("op") != 0:
            return {"status": "ignored"}
        event_type = str(payload.get("t") or "")
        data = payload.get("d") or {}
        if not isinstance(data, dict):
            return {"status": "ignored"}
        return await self.handle_dispatch(
            event_type,
            data,
            event_id=str(payload.get("id") or ""),
            background=background,
        )

    async def handle_dispatch(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        event_id: str = "",
        background: bool = True,
    ) -> dict[str, Any]:
        msg = self._parse_message(event_type, data, event_id=event_id)
        if msg is None:
            return {"status": "ignored"}
        if self._already_seen(msg.message_id):
            return {"status": "ignored", "reason": "duplicate"}
        if background:
            asyncio.create_task(self._run_and_reply(msg), name=f"qq-official-a2a-{msg.context_id}")
        else:
            await self._run_and_reply(msg)
        return {"status": "accepted"}

    def _parse_message(self, event_type: str, data: dict[str, Any], *, event_id: str = "") -> OfficialQQMessage | None:
        content = str(data.get("content") or "").strip()
        if not content:
            return None

        author = data.get("author") or {}
        if not isinstance(author, dict):
            author = {}

        if event_type == "C2C_MESSAGE_CREATE":
            user_openid = str(author.get("user_openid") or data.get("openid") or "")
            if not self._is_allowed("c2c", user_openid, ""):
                return None
            text = _strip_optional_prefix(content, self._config.command_prefix)
            return _message_or_none(
                scene="c2c",
                event_type=event_type,
                text=text,
                message_id=str(data.get("id") or ""),
                event_id=event_id,
                user_openid=user_openid,
            )

        if event_type == "GROUP_AT_MESSAGE_CREATE":
            group_openid = str(data.get("group_openid") or "")
            member_openid = str(author.get("member_openid") or "")
            if not self._is_allowed("group", member_openid, group_openid):
                return None
            text = _strip_optional_prefix(content, self._config.command_prefix)
            return _message_or_none(
                scene="group",
                event_type=event_type,
                text=text,
                message_id=str(data.get("id") or ""),
                event_id=event_id,
                member_openid=member_openid,
                group_openid=group_openid,
            )

        if event_type == "GROUP_MESSAGE_CREATE":
            group_openid = str(data.get("group_openid") or "")
            member_openid = str(author.get("member_openid") or "")
            if not self._is_allowed("group", member_openid, group_openid):
                return None
            text = _strip_required_prefix(content, self._config.command_prefix)
            return _message_or_none(
                scene="group",
                event_type=event_type,
                text=text,
                message_id=str(data.get("id") or ""),
                event_id=event_id,
                member_openid=member_openid,
                group_openid=group_openid,
            )

        if event_type == "AT_MESSAGE_CREATE":
            text = _strip_optional_prefix(content, self._config.command_prefix)
            user_openid = str(author.get("id") or "")
            return _message_or_none(
                scene="channel",
                event_type=event_type,
                text=text,
                message_id=str(data.get("id") or ""),
                event_id=event_id,
                user_openid=user_openid,
                channel_id=str(data.get("channel_id") or ""),
                guild_id=str(data.get("guild_id") or ""),
            )

        if event_type == "MESSAGE_CREATE":
            text = _strip_required_prefix(content, self._config.command_prefix)
            user_openid = str(author.get("id") or "")
            return _message_or_none(
                scene="channel",
                event_type=event_type,
                text=text,
                message_id=str(data.get("id") or ""),
                event_id=event_id,
                user_openid=user_openid,
                channel_id=str(data.get("channel_id") or ""),
                guild_id=str(data.get("guild_id") or ""),
            )

        if event_type == "DIRECT_MESSAGE_CREATE":
            text = _strip_optional_prefix(content, self._config.command_prefix)
            user_openid = str(author.get("id") or "")
            return _message_or_none(
                scene="dm",
                event_type=event_type,
                text=text,
                message_id=str(data.get("id") or ""),
                event_id=event_id,
                user_openid=user_openid,
                channel_id=str(data.get("channel_id") or ""),
                guild_id=str(data.get("guild_id") or ""),
            )

        return None

    async def _run_and_reply(self, msg: OfficialQQMessage) -> None:
        output = await self._run(msg)
        try:
            await self._send_reply(msg, output)
        except Exception:
            log.exception("Failed to send official QQ response")

    async def _run(self, msg: OfficialQQMessage) -> str:
        try:
            task = await self._bridge.run_text(
                msg.text,
                context_id=msg.context_id,
                source="qq-official",
                timeout=self._config.timeout,
                metadata={
                    "qq_event_type": msg.event_type,
                    "qq_scene": msg.scene,
                    "qq_message_id": msg.message_id,
                    "qq_user_openid": msg.user_openid,
                    "qq_member_openid": msg.member_openid,
                    "qq_group_openid": msg.group_openid,
                    "qq_channel_id": msg.channel_id,
                    "qq_guild_id": msg.guild_id,
                },
            )
        except Exception as e:
            log.exception("Official QQ A2A task failed before completion")
            return f"MozilCode 执行失败: {e}"

        if task.state != TASK_COMPLETED:
            reason = task.status_message or task.error or task.state
            return f"MozilCode 未完成: {reason}"
        return task.output or "(无输出)"

    async def _send_reply(self, msg: OfficialQQMessage, text: str) -> None:
        path = _send_path(msg)
        for seq, chunk in enumerate(_chunks(text, self._config.max_chunk_chars), start=1):
            payload: dict[str, Any] = {
                "content": chunk,
                "msg_type": 0,
                "msg_seq": seq,
            }
            if msg.message_id:
                payload["msg_id"] = msg.message_id
            elif msg.event_id:
                payload["event_id"] = msg.event_id
            await self._api.post_json(path, payload)

    def _already_seen(self, message_id: str) -> bool:
        if not message_id:
            return False
        now = time.monotonic()
        cutoff = now - 3600
        self._seen_message_ids = {k: v for k, v in self._seen_message_ids.items() if v >= cutoff}
        if message_id in self._seen_message_ids:
            return True
        self._seen_message_ids[message_id] = now
        return False

    def _is_allowed(self, scene: str, user_id: str, group_id: str) -> bool:
        if self._config.allowed_users is not None and user_id not in self._config.allowed_users:
            return False
        if scene == "group" and self._config.allowed_groups is not None and group_id not in self._config.allowed_groups:
            return False
        return True


@dataclass
class OfficialQQGatewayRunner:
    adapter: OfficialQQAdapter
    api: OfficialQQApi
    config: OfficialQQConfig
    _task: asyncio.Task | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _last_sequence: int | None = None
    _session_id: str = ""
    _bot_username: str = ""
    _running: bool = False
    _last_error: str = ""

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self.run_forever(), name="qq-official-gateway")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.config.is_configured(),
            "running": self._running,
            "session_ready": bool(self._session_id),
            "bot_username": self._bot_username,
            "last_sequence": self._last_sequence,
            "last_error": self._last_error,
            "intents": self.config.intents,
            "shard": [self.config.shard_id, self.config.shard_count],
        }

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._running = False
                self._last_error = str(e)
                log.exception("Official QQ Gateway connection failed")
                await asyncio.sleep(self.config.reconnect_delay)

    async def _run_once(self) -> None:
        try:
            import websockets
        except ImportError as e:
            raise RuntimeError("The 'websockets' package is required for official QQ Gateway") from e

        gateway_url = await self.api.get_gateway_url()
        log.info("Connecting official QQ Gateway")
        async with websockets.connect(gateway_url, ping_interval=None, close_timeout=10) as ws:
            self._running = True
            hello = json.loads(await ws.recv())
            interval_ms = _float_value((hello.get("d") or {}).get("heartbeat_interval"), 45000.0)
            await ws.send(json.dumps(await self._identify_payload(), ensure_ascii=False))
            heartbeat = asyncio.create_task(
                self._heartbeat_loop(ws, interval_ms / 1000.0),
                name="qq-official-heartbeat",
            )
            try:
                async for raw in ws:
                    payload = json.loads(raw)
                    seq = payload.get("s")
                    if isinstance(seq, int):
                        self._last_sequence = seq
                    await self._handle_gateway_payload(ws, payload)
                    if payload.get("op") == 7:
                        break
            finally:
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass
                self._running = False

    async def _identify_payload(self) -> dict[str, Any]:
        token = await self.api.access_token()
        return {
            "op": 2,
            "d": {
                "token": f"QQBot {token}",
                "intents": self.config.intents,
                "shard": [self.config.shard_id, self.config.shard_count],
                "properties": {
                    "$os": os.name,
                    "$browser": "mozilcode",
                    "$device": "mozilcode",
                },
            },
        }

    async def _heartbeat_loop(self, ws: Any, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await ws.send(json.dumps({"op": 1, "d": self._last_sequence}))

    async def _handle_gateway_payload(self, ws: Any, payload: dict[str, Any]) -> None:
        op = payload.get("op")
        if op == 0:
            event_type = payload.get("t")
            if event_type == "READY":
                data = payload.get("d") or {}
                self._session_id = str(data.get("session_id") or "")
                user = data.get("user") or {}
                if isinstance(user, dict):
                    self._bot_username = str(user.get("username") or "")
                self._last_error = ""
                log.info("Official QQ Gateway ready as %s", self._bot_username or "(unknown)")
                return
            await self.adapter.handle_payload(payload, background=True)
        elif op == 1:
            await ws.send(json.dumps({"op": 1, "d": self._last_sequence}))
        elif op == 7:
            log.warning("Official QQ Gateway requested reconnect")
        elif op == 9:
            self._session_id = ""
            self._last_error = f"Invalid QQ Gateway session: {_safe_json(payload.get('d'))}"
            log.warning(self._last_error)


def create_official_qq_gateway(bridge: A2ABridge, config: OfficialQQConfig | None = None) -> OfficialQQGatewayRunner:
    cfg = config or OfficialQQConfig.from_env()
    api = OfficialQQApi(cfg)
    adapter = OfficialQQAdapter(bridge, api=api, config=cfg)
    return OfficialQQGatewayRunner(adapter=adapter, api=api, config=cfg)


def _send_path(msg: OfficialQQMessage) -> str:
    if msg.scene == "group":
        return f"/v2/groups/{msg.group_openid}/messages"
    if msg.scene == "channel":
        return f"/channels/{msg.channel_id}/messages"
    if msg.scene == "dm":
        return f"/dms/{msg.guild_id}/messages"
    return f"/v2/users/{msg.user_openid}/messages"


def _message_or_none(**kwargs: Any) -> OfficialQQMessage | None:
    msg = OfficialQQMessage(**kwargs)
    if not msg.text:
        return None
    if msg.scene == "group" and not msg.group_openid:
        return None
    if msg.scene == "channel" and not msg.channel_id:
        return None
    if msg.scene == "dm" and not msg.guild_id:
        return None
    if msg.scene == "c2c" and not msg.user_openid:
        return None
    return msg


def _strip_optional_prefix(text: str, prefix: str) -> str:
    clean = text.strip()
    if prefix and clean.startswith(prefix):
        return clean[len(prefix):].strip()
    return clean


def _strip_required_prefix(text: str, prefix: str) -> str:
    clean = text.strip()
    if not prefix:
        return clean
    if not clean.startswith(prefix):
        return ""
    return clean[len(prefix):].strip()


def _chunks(text: str, size: int) -> list[str]:
    clean = text or "(无输出)"
    if size <= 0:
        return [clean]
    return [clean[i:i + size] for i in range(0, len(clean), size)] or ["(无输出)"]


def _csv_env(name: str) -> set[str] | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    return _float_value(os.environ.get(name), default)


def _float_value(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _response_summary(resp: httpx.Response) -> str:
    body = resp.text
    if len(body) > 500:
        body = body[:500] + "..."
    return f"HTTP {resp.status_code}: {body}"


def _safe_json(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)
    except TypeError:
        return str(data)
