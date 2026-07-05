from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from mozilcode.a2a.bridge import A2ABridge, TASK_COMPLETED

log = logging.getLogger(__name__)


@dataclass
class TelegramBotConfig:
    bot_token: str = ""
    api_base: str = "https://api.telegram.org"
    command_prefix: str = "/mew"
    timeout: float = 120.0
    poll_timeout: int = 30
    reconnect_delay: float = 5.0
    max_chunk_chars: int = 3900
    allowed_users: set[str] | None = None
    allowed_chats: set[str] | None = None

    @classmethod
    def from_env(cls) -> TelegramBotConfig:
        return cls(
            bot_token=os.environ.get("MOZILCODE_TELEGRAM_BOT_TOKEN", "").strip(),
            api_base=os.environ.get("MOZILCODE_TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
            command_prefix=os.environ.get("MOZILCODE_TELEGRAM_COMMAND_PREFIX", "/mew"),
            timeout=_env_float("MOZILCODE_TELEGRAM_TIMEOUT", 120.0),
            poll_timeout=max(1, int(_env_float("MOZILCODE_TELEGRAM_POLL_TIMEOUT", 30))),
            reconnect_delay=max(1.0, _env_float("MOZILCODE_TELEGRAM_RECONNECT_DELAY", 5.0)),
            max_chunk_chars=int(_env_float("MOZILCODE_TELEGRAM_MAX_CHUNK_CHARS", 3900)),
            allowed_users=_csv_env("MOZILCODE_TELEGRAM_ALLOWED_USERS"),
            allowed_chats=_csv_env("MOZILCODE_TELEGRAM_ALLOWED_CHATS"),
        )

    @classmethod
    def enabled_from_env(cls) -> bool:
        return _env_bool("MOZILCODE_TELEGRAM_ENABLED", False)

    def is_configured(self) -> bool:
        return bool(self.bot_token)


@dataclass
class TelegramMessage:
    text: str
    chat_id: str
    user_id: str
    message_id: int | None = None
    chat_type: str = ""
    username: str = ""

    @property
    def context_id(self) -> str:
        return f"telegram-chat-{self.chat_id}"


class TelegramBotApi:
    def __init__(self, config: TelegramBotConfig | None = None) -> None:
        self._config = config or TelegramBotConfig.from_env()

    async def get_me(self) -> dict[str, Any]:
        return await self._post("getMe", {})

    async def get_updates(self, *, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        data = await self._post("getUpdates", payload, timeout=timeout + 10)
        result = data.get("result")
        return result if isinstance(result, list) else []

    async def send_message(self, chat_id: str, text: str, *, reply_to_message_id: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
            payload["allow_sending_without_reply"] = True
        return await self._post("sendMessage", payload)

    async def _post(self, method: str, payload: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
        if not self._config.is_configured():
            raise RuntimeError("Telegram Bot token is not configured")
        url = f"{self._config.api_base}/bot{self._config.bot_token}/{method}"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
        except httpx.HTTPError as e:
            raise RuntimeError(f"Telegram Bot API request failed: {_redact_token(str(e), self._config.bot_token)}") from e
        if resp.status_code >= 400:
            raise RuntimeError(f"Telegram Bot API request failed: {_response_summary(resp)}")
        data = resp.json()
        if not data.get("ok", False):
            raise RuntimeError(f"Telegram Bot API returned ok=false: {_safe_json(data)}")
        return data


class TelegramBotAdapter:
    """Official Telegram Bot API adapter for MozilCode's A2A bridge."""

    def __init__(
        self,
        bridge: A2ABridge,
        *,
        api: TelegramBotApi | None = None,
        config: TelegramBotConfig | None = None,
        bot_username: str = "",
    ) -> None:
        self._bridge = bridge
        self._config = config or TelegramBotConfig.from_env()
        self._api = api or TelegramBotApi(self._config)
        self.bot_username = bot_username

    async def handle_update(self, update: dict[str, Any], *, background: bool = True) -> dict[str, Any]:
        msg = self._parse_message(update)
        if msg is None:
            return {"status": "ignored"}
        if background:
            asyncio.create_task(self._run_and_reply(msg), name=f"telegram-a2a-{msg.context_id}")
        else:
            await self._run_and_reply(msg)
        return {"status": "accepted"}

    def _parse_message(self, update: dict[str, Any]) -> TelegramMessage | None:
        message = update.get("message") or {}
        if not isinstance(message, dict):
            return None
        text = str(message.get("text") or "").strip()
        if not text:
            return None

        chat = message.get("chat") or {}
        user = message.get("from") or {}
        if not isinstance(chat, dict):
            chat = {}
        if not isinstance(user, dict):
            user = {}

        chat_id = str(chat.get("id") or "")
        user_id = str(user.get("id") or "")
        chat_type = str(chat.get("type") or "")
        if not chat_id or not self._is_allowed(user_id, chat_id):
            return None

        if chat_type == "private":
            prompt = _strip_optional_command(text, self._config.command_prefix, self.bot_username)
        else:
            prompt = _strip_required_command(text, self._config.command_prefix, self.bot_username)
        if not prompt:
            return None

        message_id = message.get("message_id")
        return TelegramMessage(
            text=prompt,
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id if isinstance(message_id, int) else None,
            chat_type=chat_type,
            username=str(user.get("username") or ""),
        )

    async def _run_and_reply(self, msg: TelegramMessage) -> None:
        output = await self._run(msg)
        try:
            await self._send_reply(msg, output)
        except Exception:
            log.exception("Failed to send Telegram response")

    async def _run(self, msg: TelegramMessage) -> str:
        try:
            task = await self._bridge.run_text(
                msg.text,
                context_id=msg.context_id,
                source="telegram-official",
                timeout=self._config.timeout,
                metadata={
                    "telegram_chat_id": msg.chat_id,
                    "telegram_user_id": msg.user_id,
                    "telegram_message_id": msg.message_id,
                    "telegram_chat_type": msg.chat_type,
                    "telegram_username": msg.username,
                },
            )
        except Exception as e:
            log.exception("Telegram A2A task failed before completion")
            return f"MozilCode 执行失败: {e}"

        if task.state != TASK_COMPLETED:
            reason = task.status_message or task.error or task.state
            return f"MozilCode 未完成: {reason}"
        return task.output or "(无输出)"

    async def _send_reply(self, msg: TelegramMessage, text: str) -> None:
        for chunk in _chunks(text, self._config.max_chunk_chars):
            await self._api.send_message(msg.chat_id, chunk, reply_to_message_id=msg.message_id)

    def _is_allowed(self, user_id: str, chat_id: str) -> bool:
        if self._config.allowed_users is not None and user_id not in self._config.allowed_users:
            return False
        if self._config.allowed_chats is not None and chat_id not in self._config.allowed_chats:
            return False
        return True


@dataclass
class TelegramBotRunner:
    adapter: TelegramBotAdapter
    api: TelegramBotApi
    config: TelegramBotConfig
    _task: asyncio.Task | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _last_update_id: int | None = None
    _bot_username: str = ""
    _running: bool = False
    _last_error: str = ""

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self.run_forever(), name="telegram-bot-polling")

    async def stop(self) -> None:
        self._stop.set()
        self._running = False
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
            "session_ready": self._running,
            "bot_username": self._bot_username,
            "last_update_id": self._last_update_id,
            "last_error": self._last_error,
        }

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                me = await self.api.get_me()
                user = me.get("result") or {}
                if isinstance(user, dict):
                    self._bot_username = str(user.get("username") or "")
                    self.adapter.bot_username = self._bot_username
                self._last_error = ""
                await self._poll_loop()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._running = False
                self._last_error = str(e)
                log.exception("Telegram Bot polling failed")
                await asyncio.sleep(self.config.reconnect_delay)

    async def _poll_loop(self) -> None:
        self._running = True
        try:
            while not self._stop.is_set():
                offset = self._last_update_id + 1 if self._last_update_id is not None else None
                updates = await self.api.get_updates(offset=offset, timeout=self.config.poll_timeout)
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        self._last_update_id = update_id
                    await self.adapter.handle_update(update, background=True)
        finally:
            self._running = False


def create_telegram_bot_runner(bridge: A2ABridge, config: TelegramBotConfig | None = None) -> TelegramBotRunner:
    cfg = config or TelegramBotConfig.from_env()
    api = TelegramBotApi(cfg)
    adapter = TelegramBotAdapter(bridge, api=api, config=cfg)
    return TelegramBotRunner(adapter=adapter, api=api, config=cfg)


def _strip_optional_command(text: str, prefix: str, bot_username: str = "") -> str:
    clean = text.strip()
    stripped = _strip_command(clean, prefix, bot_username)
    return stripped if stripped is not None else clean


def _strip_required_command(text: str, prefix: str, bot_username: str = "") -> str:
    clean = text.strip()
    if not prefix:
        return clean
    return _strip_command(clean, prefix, bot_username) or ""


def _strip_command(text: str, prefix: str, bot_username: str = "") -> str | None:
    clean = text.strip()
    if not prefix:
        return clean
    head, sep, tail = clean.partition(" ")
    if _matches_command(head, prefix, bot_username):
        return tail.strip() if sep else ""
    return None


def _matches_command(token: str, prefix: str, bot_username: str = "") -> bool:
    if token == prefix:
        return True
    if bot_username and token.lower() == f"{prefix}@{bot_username}".lower():
        return True
    return False


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
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _response_summary(resp: httpx.Response) -> str:
    body = resp.text
    if len(body) > 500:
        body = body[:500] + "..."
    return f"HTTP {resp.status_code}: {body}"


def _safe_json(data: Any) -> str:
    try:
        import json

        return json.dumps(data, ensure_ascii=False)
    except TypeError:
        return str(data)


def _redact_token(text: str, token: str) -> str:
    if not token:
        return text
    return text.replace(token, "<redacted>")
