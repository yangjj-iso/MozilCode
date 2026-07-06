from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DAEMON_SETTINGS_FILE = Path.home() / ".mozilcode" / "daemon_settings.json"


def default_daemon_settings() -> dict:
    return {
        "mcp_servers": [],
        "disabled_skills": [],
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
