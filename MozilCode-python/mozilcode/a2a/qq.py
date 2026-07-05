from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from mozilcode.a2a.bridge import A2ABridge, TASK_COMPLETED

log = logging.getLogger(__name__)

_AT_RE = re.compile(r"\[CQ:at,qq=(\d+|all)\]")


@dataclass
class OneBotConfig:
    api_url: str = ""
    access_token: str = ""
    secret: str = ""
    command_prefix: str = "/mew"
    reply_mode: str = "auto"  # auto | push | quick
    timeout: float = 120.0
    max_chunk_chars: int = 1800
    allowed_users: set[str] | None = None
    allowed_groups: set[str] | None = None

    @classmethod
    def from_env(cls) -> OneBotConfig:
        return cls(
            api_url=os.environ.get("MOZILCODE_QQ_ONEBOT_API_URL", "").rstrip("/"),
            access_token=os.environ.get("MOZILCODE_QQ_ONEBOT_ACCESS_TOKEN", ""),
            secret=os.environ.get("MOZILCODE_QQ_ONEBOT_SECRET", ""),
            command_prefix=os.environ.get("MOZILCODE_QQ_COMMAND_PREFIX", "/mew"),
            reply_mode=os.environ.get("MOZILCODE_QQ_REPLY_MODE", "auto").lower(),
            timeout=_env_float("MOZILCODE_QQ_TIMEOUT", 120.0),
            max_chunk_chars=int(_env_float("MOZILCODE_QQ_MAX_CHUNK_CHARS", 1800)),
            allowed_users=_csv_env("MOZILCODE_QQ_ALLOWED_USERS"),
            allowed_groups=_csv_env("MOZILCODE_QQ_ALLOWED_GROUPS"),
        )


@dataclass
class QQIncomingMessage:
    message_type: str
    user_id: str
    group_id: str
    text: str
    context_id: str


class OneBotQQAdapter:
    """OneBot v11 webhook adapter for QQ-based agent access."""

    def __init__(self, bridge: A2ABridge, config: OneBotConfig | None = None) -> None:
        self._bridge = bridge
        self._config = config or OneBotConfig.from_env()

    async def handle_event(
        self,
        event: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        raw_body: bytes = b"",
    ) -> dict[str, Any]:
        if not self._verify_signature(headers or {}, raw_body):
            return {"status": "ignored", "reason": "invalid signature"}

        msg = self._parse_message(event)
        if msg is None:
            return {"status": "ignored"}

        reply_mode = self._resolve_reply_mode()
        if reply_mode == "quick":
            output = await self._run(msg)
            return {"reply": output, "auto_escape": True}

        asyncio.create_task(self._run_and_push(msg), name=f"qq-a2a-{msg.context_id}")
        return {"status": "accepted"}

    def _parse_message(self, event: dict[str, Any]) -> QQIncomingMessage | None:
        if event.get("post_type") != "message":
            return None
        if event.get("message_type") not in {"private", "group"}:
            return None

        message_type = str(event.get("message_type"))
        user_id = str(event.get("user_id") or "")
        group_id = str(event.get("group_id") or "")
        if not self._is_allowed(message_type, user_id, group_id):
            return None

        text = _message_text(event)
        if not text:
            return None

        if message_type == "group":
            text = _strip_at_self(text, str(event.get("self_id") or ""))
            prefix = self._config.command_prefix
            if prefix and not text.startswith(prefix):
                return None
            text = text[len(prefix):].strip() if prefix else text.strip()
        else:
            prefix = self._config.command_prefix
            if prefix and text.startswith(prefix):
                text = text[len(prefix):].strip()

        if not text:
            return None

        context_id = f"qq-group-{group_id}" if message_type == "group" else f"qq-private-{user_id}"
        return QQIncomingMessage(
            message_type=message_type,
            user_id=user_id,
            group_id=group_id,
            text=text,
            context_id=context_id,
        )

    async def _run(self, msg: QQIncomingMessage) -> str:
        try:
            task = await self._bridge.run_text(
                msg.text,
                context_id=msg.context_id,
                source="qq",
                timeout=self._config.timeout,
                metadata={
                    "qq_message_type": msg.message_type,
                    "qq_user_id": msg.user_id,
                    "qq_group_id": msg.group_id,
                },
            )
        except Exception as e:
            log.exception("QQ A2A task failed before completion")
            return f"MozilCode 执行失败：{e}"

        if task.state != TASK_COMPLETED:
            reason = task.status_message or task.error or task.state
            return f"MozilCode 未完成：{reason}"
        return task.output or "(无输出)"

    async def _run_and_push(self, msg: QQIncomingMessage) -> None:
        output = await self._run(msg)
        try:
            await self._send_message(msg, output)
        except Exception:
            log.exception("Failed to push QQ response")

    async def _send_message(self, msg: QQIncomingMessage, text: str) -> None:
        if not self._config.api_url:
            log.warning("MOZILCODE_QQ_ONEBOT_API_URL is not configured; cannot push QQ response")
            return

        endpoint = "send_group_msg" if msg.message_type == "group" else "send_private_msg"
        url = f"{self._config.api_url}/{endpoint}"
        headers = {}
        if self._config.access_token:
            headers["Authorization"] = f"Bearer {self._config.access_token}"

        async with httpx.AsyncClient(timeout=30) as client:
            for chunk in _chunks(text, self._config.max_chunk_chars):
                payload: dict[str, Any] = {
                    "message": chunk,
                    "auto_escape": True,
                }
                if msg.message_type == "group":
                    payload["group_id"] = int(msg.group_id)
                else:
                    payload["user_id"] = int(msg.user_id)
                await client.post(url, json=payload, headers=headers)

    def _verify_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        if not self._config.secret:
            return True
        supplied = headers.get("x-signature") or headers.get("X-Signature") or ""
        if not supplied.startswith("sha1="):
            return False
        digest = hmac.new(
            self._config.secret.encode("utf-8"),
            raw_body,
            hashlib.sha1,
        ).hexdigest()
        return hmac.compare_digest(supplied, f"sha1={digest}")

    def _resolve_reply_mode(self) -> str:
        if self._config.reply_mode in {"push", "quick"}:
            return self._config.reply_mode
        return "push" if self._config.api_url else "quick"

    def _is_allowed(self, message_type: str, user_id: str, group_id: str) -> bool:
        if self._config.allowed_users is not None and user_id not in self._config.allowed_users:
            return False
        if (
            message_type == "group"
            and self._config.allowed_groups is not None
            and group_id not in self._config.allowed_groups
        ):
            return False
        return True


def _message_text(event: dict[str, Any]) -> str:
    raw = event.get("raw_message")
    if isinstance(raw, str):
        return raw.strip()

    message = event.get("message")
    if isinstance(message, str):
        return message.strip()
    if not isinstance(message, list):
        return ""

    chunks: list[str] = []
    for part in message:
        if isinstance(part, str):
            chunks.append(part)
            continue
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            data = part.get("data") or {}
            if isinstance(data, dict):
                chunks.append(str(data.get("text") or ""))
        elif part.get("type") == "at":
            data = part.get("data") or {}
            if isinstance(data, dict):
                chunks.append(f"[CQ:at,qq={data.get('qq')}]")
    return "".join(chunks).strip()


def _strip_at_self(text: str, self_id: str) -> str:
    if not self_id:
        return text.strip()
    return _AT_RE.sub(lambda m: "" if m.group(1) == self_id else m.group(0), text).strip()


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


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default
