from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from mozilcode.a2a.qq_official import DEFAULT_INTENTS, OfficialQQConfig
from mozilcode.a2a.telegram_official import TelegramBotConfig

log = logging.getLogger(__name__)

DAEMON_SETTINGS_FILE = Path.home() / ".mozilcode" / "daemon_settings.json"
QQBOT_PROVIDER = "official"
TELEGRAMBOT_PROVIDER = "telegram-official"


def default_daemon_settings() -> dict:
    return {
        "mcp_servers": [],
        "disabled_skills": [],
        "qqbot": {},
        "telegrambot": {},
    }


def load_daemon_settings() -> dict:
    try:
        data = json.loads(DAEMON_SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return normalize_daemon_settings(data)
    except Exception:
        pass
    return normalize_daemon_settings({})


def normalize_daemon_settings(data: dict | None) -> dict:
    normalized = default_daemon_settings()
    if isinstance(data, dict):
        normalized.update(data)
    normalized.setdefault("mcp_servers", [])
    normalized.setdefault("disabled_skills", [])
    normalized.setdefault("qqbot", {})
    normalized.setdefault("telegrambot", {})
    return normalized


def save_daemon_settings(data: dict) -> None:
    try:
        DAEMON_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        DAEMON_SETTINGS_FILE.write_text(
            json.dumps(normalize_daemon_settings(data), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("Failed to save daemon settings: %s", e)


def coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def coerce_int(value: Any, default: int, *, minimum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    if minimum is not None:
        number = max(minimum, number)
    return number


def split_id_list(value: Any) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value]
    else:
        raw = str(value)
        for sep in [",", ";", "，", "；", "\r", "\n", "\t"]:
            raw = raw.replace(sep, " ")
        items = [item.strip() for item in raw.split(" ")]
    clean = {item for item in items if item}
    return clean or None


def id_list_text(value: Any) -> str:
    ids = split_id_list(value)
    if not ids:
        return ""
    return "\n".join(sorted(ids))


def normalize_qqbot_settings(raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "provider": QQBOT_PROVIDER,
        "enabled": coerce_bool(raw.get("enabled"), False),
        "app_id": str(raw.get("app_id") or "").strip(),
        "app_secret": str(raw.get("app_secret") or "").strip(),
        "command_prefix": str(raw.get("command_prefix") or "/mew").strip(),
        "allowed_users": id_list_text(raw.get("allowed_users")),
        "allowed_groups": id_list_text(raw.get("allowed_groups")),
        "intents": coerce_int(raw.get("intents"), DEFAULT_INTENTS, minimum=0),
    }


def qqbot_settings_from_payload(body: dict, current: dict | None = None) -> dict:
    current = current if isinstance(current, dict) else {}
    merged = {**current, **(body or {})}
    secret = body.get("app_secret") if isinstance(body, dict) else None
    if secret is None or not str(secret).strip():
        merged["app_secret"] = str(current.get("app_secret") or "").strip()
    return normalize_qqbot_settings(merged)


def resolve_qqbot_config(settings: dict | None = None) -> tuple[bool, OfficialQQConfig, dict]:
    data = settings if isinstance(settings, dict) else load_daemon_settings()
    raw = data.get("qqbot") if isinstance(data, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    saved = bool(raw)
    normalized = normalize_qqbot_settings(raw)
    env_cfg = OfficialQQConfig.from_env()
    enabled = coerce_bool(raw.get("enabled"), False) if saved else OfficialQQConfig.enabled_from_env()

    cfg = OfficialQQConfig.from_env()
    cfg.app_id = normalized["app_id"] or env_cfg.app_id
    cfg.app_secret = normalized["app_secret"] or env_cfg.app_secret
    if saved and "command_prefix" in raw:
        cfg.command_prefix = normalized["command_prefix"]
    if saved and "allowed_users" in raw:
        cfg.allowed_users = split_id_list(normalized["allowed_users"])
    if saved and "allowed_groups" in raw:
        cfg.allowed_groups = split_id_list(normalized["allowed_groups"])
    if saved and "intents" in raw:
        cfg.intents = normalized["intents"]
    return enabled, cfg, normalized


def public_qqbot_status(app: Any | None = None, settings: dict | None = None) -> dict:
    enabled, cfg, _normalized = resolve_qqbot_config(settings)
    gateway = getattr(app.state, "qq_official_gateway", None) if app is not None else None
    status = gateway.status() if gateway is not None else {}
    return {
        "provider": QQBOT_PROVIDER,
        "enabled": enabled,
        "configured": cfg.is_configured(),
        "running": False,
        "session_ready": False,
        "bot_username": "",
        "last_sequence": None,
        "last_error": "",
        "app_id": cfg.app_id,
        "app_secret_set": bool(cfg.app_secret),
        "command_prefix": cfg.command_prefix,
        "allowed_users": id_list_text(cfg.allowed_users),
        "allowed_groups": id_list_text(cfg.allowed_groups),
        "intents": cfg.intents,
        "shard": [cfg.shard_id, cfg.shard_count],
        "config_path": str(DAEMON_SETTINGS_FILE),
        **status,
    }


def normalize_telegrambot_settings(raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "provider": TELEGRAMBOT_PROVIDER,
        "enabled": coerce_bool(raw.get("enabled"), False),
        "bot_token": str(raw.get("bot_token") or "").strip(),
        "command_prefix": str(raw.get("command_prefix") or "/mew").strip(),
        "allowed_users": id_list_text(raw.get("allowed_users")),
        "allowed_chats": id_list_text(raw.get("allowed_chats")),
    }


def telegrambot_settings_from_payload(body: dict, current: dict | None = None) -> dict:
    current = current if isinstance(current, dict) else {}
    merged = {**current, **(body or {})}
    token = body.get("bot_token") if isinstance(body, dict) else None
    if token is None or not str(token).strip():
        merged["bot_token"] = str(current.get("bot_token") or "").strip()
    return normalize_telegrambot_settings(merged)


def resolve_telegrambot_config(settings: dict | None = None) -> tuple[bool, TelegramBotConfig, dict]:
    data = settings if isinstance(settings, dict) else load_daemon_settings()
    raw = data.get("telegrambot") if isinstance(data, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    saved = bool(raw)
    normalized = normalize_telegrambot_settings(raw)
    env_cfg = TelegramBotConfig.from_env()
    enabled = coerce_bool(raw.get("enabled"), False) if saved else TelegramBotConfig.enabled_from_env()

    cfg = TelegramBotConfig.from_env()
    cfg.bot_token = normalized["bot_token"] or env_cfg.bot_token
    if saved and "command_prefix" in raw:
        cfg.command_prefix = normalized["command_prefix"]
    if saved and "allowed_users" in raw:
        cfg.allowed_users = split_id_list(normalized["allowed_users"])
    if saved and "allowed_chats" in raw:
        cfg.allowed_chats = split_id_list(normalized["allowed_chats"])
    return enabled, cfg, normalized


def public_telegrambot_status(app: Any | None = None, settings: dict | None = None) -> dict:
    enabled, cfg, _normalized = resolve_telegrambot_config(settings)
    gateway = getattr(app.state, "telegram_bot_runner", None) if app is not None else None
    status = gateway.status() if gateway is not None else {}
    return {
        "provider": TELEGRAMBOT_PROVIDER,
        "enabled": enabled,
        "configured": cfg.is_configured(),
        "running": False,
        "session_ready": False,
        "bot_username": "",
        "last_update_id": None,
        "last_error": "",
        "bot_token_set": bool(cfg.bot_token),
        "command_prefix": cfg.command_prefix,
        "allowed_users": id_list_text(cfg.allowed_users),
        "allowed_chats": id_list_text(cfg.allowed_chats),
        "config_path": str(DAEMON_SETTINGS_FILE),
        **status,
    }
