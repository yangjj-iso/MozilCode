"""本地账号会话持久化。

只存 JWT / 邮箱 / 云端 base_url / 已选模型，不进 config.yaml。
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_BASE_URL = os.environ.get("MOZILCODE_CLOUD_URL", "http://127.0.0.1:8000").rstrip("/")
SESSION_FILE = Path.home() / ".mozilcode" / "account.yaml"


@dataclass(frozen=True)
class AccountSession:
    base_url: str
    token: str
    email: str = ""
    role: str = "user"
    user_id: int | None = None
    selected_model: str = ""

    @property
    def logged_in(self) -> bool:
        return bool(self.token and self.base_url)

    def gateway_base_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/gateway"

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "token": self.token,
            "email": self.email,
            "role": self.role,
            "user_id": self.user_id,
            "selected_model": self.selected_model,
        }


def _coerce_session(raw: dict[str, Any]) -> AccountSession | None:
    token = str(raw.get("token") or "").strip()
    base_url = str(raw.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    if not token or not base_url:
        return None
    user_id_raw = raw.get("user_id")
    user_id: int | None
    if isinstance(user_id_raw, int) and not isinstance(user_id_raw, bool):
        user_id = user_id_raw
    else:
        try:
            user_id = int(user_id_raw) if user_id_raw is not None else None
        except (TypeError, ValueError):
            user_id = None
    return AccountSession(
        base_url=base_url,
        token=token,
        email=str(raw.get("email") or "").strip(),
        role=str(raw.get("role") or "user").strip() or "user",
        user_id=user_id,
        selected_model=str(raw.get("selected_model") or "").strip(),
    )


def load_session(path: Path | None = None) -> AccountSession | None:
    target = path or SESSION_FILE
    if not target.exists():
        return None
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(raw, dict):
        return None
    return _coerce_session(raw)


def save_session(session: AccountSession, path: Path | None = None) -> None:
    target = path or SESSION_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(
        session.to_dict(),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    fd, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clear_session(path: Path | None = None) -> None:
    target = path or SESSION_FILE
    if target.exists():
        target.unlink()


def with_selected_model(session: AccountSession, model: str) -> AccountSession:
    return AccountSession(
        base_url=session.base_url,
        token=session.token,
        email=session.email,
        role=session.role,
        user_id=session.user_id,
        selected_model=model.strip(),
    )