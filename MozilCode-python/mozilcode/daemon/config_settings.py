from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from mozilcode.config import AppConfig, load_config
from mozilcode.daemon.gui_settings import coerce_bool
from mozilcode.validator import ConfigError, validate_config_structure, validate_memory

USER_CONFIG_FILE = Path.home() / ".mozilcode" / "config.yaml"


def default_base_url(protocol: str) -> str:
    if protocol == "anthropic":
        return "https://api.anthropic.com"
    if protocol == "openai":
        return "https://api.openai.com/v1"
    return ""


def normalize_base_url(protocol: str, base_url: str) -> str:
    if protocol not in {"openai", "openai-compat"}:
        return base_url
    parsed = urlparse(base_url)
    if (
        parsed.scheme in {"http", "https"}
        and (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}
        and parsed.path in {"", "/"}
    ):
        return base_url.rstrip("/") + "/v1"
    return base_url


def public_config(config: AppConfig | None, error: str = "") -> dict:
    providers = []
    if config is not None:
        for provider in config.providers:
            providers.append({
                "name": provider.name,
                "protocol": provider.protocol,
                "base_url": provider.base_url,
                "model": provider.model,
                "api_key_set": bool(provider.api_key),
                "thinking": provider.thinking,
                "context_window": provider.context_window,
                "max_output_tokens": provider.max_output_tokens,
            })
    return {
        "configured": config is not None and bool(config.providers),
        "config_path": str(USER_CONFIG_FILE),
        "error": error,
        "providers": providers,
        "permission_mode": config.permission_mode if config is not None else "default",
    }


def provider_from_gui_entry(
    entry: dict,
    current_by_name: dict[str, Any],
    fallback: Any | None = None,
) -> dict:
    if not isinstance(entry, dict):
        raise ConfigError("Provider entries must be mappings")
    protocol = str(entry.get("protocol") or "openai").strip()
    base_url = normalize_base_url(
        protocol,
        str(entry.get("base_url") or default_base_url(protocol)).strip(),
    )
    model = str(entry.get("model") or "").strip()
    name = str(entry.get("name") or protocol or model or "default").strip()
    api_key = str(entry.get("api_key") or "").strip()
    previous_name = str(
        entry.get("previous_name") or entry.get("_previous_name") or ""
    ).strip()
    current_provider = current_by_name.get(name)
    if current_provider is None and previous_name:
        current_provider = current_by_name.get(previous_name)
    if not api_key and current_provider is not None:
        api_key = current_provider.api_key
    elif not api_key and fallback is not None:
        api_key = fallback.api_key

    return {
        "name": name,
        "protocol": protocol,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "thinking": coerce_bool(entry.get("thinking"), False),
        "context_window": int(entry.get("context_window") or 0),
        "max_output_tokens": int(entry.get("max_output_tokens") or 0),
    }


def providers_from_gui_payload(
    body: dict,
    current: AppConfig | None = None,
) -> list[dict]:
    current_providers = current.providers if current is not None else []
    current_by_name = {provider.name: provider for provider in current_providers}
    fallback = current_providers[0] if current_providers else None
    raw_providers = body.get("providers")
    if raw_providers is None:
        providers = [provider_from_gui_entry(body, current_by_name, fallback)]
    else:
        if not isinstance(raw_providers, list):
            raise ConfigError("'providers' must be a list")
        providers = [
            provider_from_gui_entry(entry, current_by_name)
            for entry in raw_providers
        ]

    names = [provider["name"] for provider in providers]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ConfigError(f"Duplicate provider names: {', '.join(duplicates)}")
    return providers


def default_config_raw() -> dict:
    return {
        "providers": [],
        "permission_mode": "default",
        "mcp_servers": [],
        "hooks": [],
        "enable_fork": False,
        "enable_verification_agent": False,
        "worktree": {
            "symlink_directories": ["node_modules", ".venv", "vendor"],
            "stale_cleanup_interval": 3600,
            "stale_cutoff_hours": 24,
        },
        "memory": {
            "enabled": True,
            "providers": [
                {
                    "name": "markdown",
                    "type": "builtin.markdown",
                    "enabled": True,
                    "config": {},
                    "module": "",
                    "class": "",
                }
            ],
        },
        "teammate_mode": "",
        "enable_coordinator_mode": False,
    }


def config_from_gui_payload(body: dict, current: AppConfig | None = None) -> dict:
    providers = providers_from_gui_payload(body, current)
    raw = app_config_to_raw(current) if current is not None else default_config_raw()
    raw["providers"] = providers
    raw["permission_mode"] = str(
        body.get("permission_mode") or raw.get("permission_mode") or "default"
    ).strip()
    if "enable_fork" in body:
        raw["enable_fork"] = coerce_bool(body.get("enable_fork"), False)
    if "enable_verification_agent" in body:
        raw["enable_verification_agent"] = coerce_bool(
            body.get("enable_verification_agent"),
            False,
        )
    if "enable_coordinator_mode" in body:
        raw["enable_coordinator_mode"] = coerce_bool(
            body.get("enable_coordinator_mode"),
            False,
        )
    validate_config_structure(raw)
    return raw


def write_user_config(raw: dict) -> AppConfig:
    USER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    USER_CONFIG_FILE.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return load_config(USER_CONFIG_FILE)


MEMORY_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "authorization",
)


def is_memory_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in MEMORY_SECRET_KEY_PARTS)


def memory_config_to_raw(memory: Any) -> dict:
    return {
        "enabled": bool(getattr(memory, "enabled", True)),
        "providers": [
            {
                "name": provider.name,
                "type": provider.type,
                "enabled": provider.enabled,
                "config": dict(provider.config or {}),
                "module": provider.module,
                "class": provider.class_name,
            }
            for provider in getattr(memory, "providers", [])
        ],
    }


def app_config_to_raw(config: AppConfig) -> dict:
    return {
        "providers": [
            {
                "name": provider.name,
                "protocol": provider.protocol,
                "base_url": provider.base_url,
                "model": provider.model,
                "api_key": provider.api_key,
                "thinking": provider.thinking,
                "context_window": provider.context_window,
                "max_output_tokens": provider.max_output_tokens,
            }
            for provider in config.providers
        ],
        "permission_mode": config.permission_mode,
        "mcp_servers": [
            {
                "name": server.name,
                "command": server.command,
                "args": server.args,
                "url": server.url,
                "headers": server.headers,
                "env": server.env,
            }
            for server in config.mcp_servers
        ],
        "hooks": list(config.raw_hooks),
        "memory": memory_config_to_raw(config.memory),
        "enable_fork": config.enable_fork,
        "enable_verification_agent": config.enable_verification_agent,
        "worktree": {
            "symlink_directories": config.worktree.symlink_directories,
            "stale_cleanup_interval": config.worktree.stale_cleanup_interval,
            "stale_cutoff_hours": config.worktree.stale_cutoff_hours,
        },
        "teammate_mode": config.teammate_mode,
        "enable_coordinator_mode": config.enable_coordinator_mode,
    }


def sanitize_memory_config(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            out[key] = "" if is_memory_secret_key(str(key)) else sanitize_memory_config(item)
        return out
    if isinstance(value, list):
        return [sanitize_memory_config(item) for item in value]
    return value


def memory_secret_fields(value: Any, prefix: str = "") -> list[str]:
    if not isinstance(value, dict):
        return []
    fields: list[str] = []
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if is_memory_secret_key(str(key)):
            fields.append(path)
        elif isinstance(item, dict):
            fields.extend(memory_secret_fields(item, path))
    return fields


def merge_memory_secrets(new_config: dict, current_config: dict) -> dict:
    merged = dict(new_config)
    for key, value in list(merged.items()):
        current_value = current_config.get(key) if isinstance(current_config, dict) else None
        if is_memory_secret_key(str(key)):
            if value is None or str(value).strip() in {"", "********"}:
                if current_value not in (None, ""):
                    merged[key] = current_value
        elif isinstance(value, dict) and isinstance(current_value, dict):
            merged[key] = merge_memory_secrets(value, current_value)
    return merged


def public_memory_settings(config: AppConfig | None, error: str = "") -> dict:
    cfg = config.memory if config is not None else None
    if cfg is None:
        return {
            "enabled": False,
            "providers": [],
            "config_path": str(USER_CONFIG_FILE),
            "error": error,
        }
    return {
        "enabled": cfg.enabled,
        "providers": [
            {
                "name": provider.name,
                "type": provider.type,
                "enabled": provider.enabled,
                "module": provider.module,
                "class": provider.class_name,
                "config": sanitize_memory_config(provider.config or {}),
                "secret_fields": memory_secret_fields(provider.config or {}),
            }
            for provider in cfg.providers
        ],
        "config_path": str(USER_CONFIG_FILE),
        "error": error,
    }


def memory_settings_from_payload(body: dict, current: AppConfig) -> dict:
    if not isinstance(body, dict):
        raise ConfigError("'memory' payload must be a mapping")
    raw_providers = body.get("providers")
    if raw_providers is None:
        raw_providers = memory_config_to_raw(current.memory)["providers"]
    if not isinstance(raw_providers, list):
        raise ConfigError("'memory.providers' must be a list")

    current_by_name = {
        provider.name: provider.config or {}
        for provider in current.memory.providers
    }
    providers: list[dict] = []
    for entry in raw_providers:
        if not isinstance(entry, dict):
            raise ConfigError("Memory provider entries must be mappings")
        name = str(entry.get("name") or "").strip()
        config_value = entry.get("config", {})
        if isinstance(config_value, str):
            try:
                config_value = json.loads(config_value or "{}")
            except json.JSONDecodeError as e:
                raise ConfigError(f"Memory provider '{name}': config must be JSON") from e
        if not isinstance(config_value, dict):
            raise ConfigError(f"Memory provider '{name}': 'config' must be a mapping")
        providers.append(
            {
                "name": name,
                "type": str(entry.get("type") or "").strip(),
                "enabled": coerce_bool(entry.get("enabled"), True),
                "config": merge_memory_secrets(
                    config_value,
                    current_by_name.get(name, {}),
                ),
                "module": str(entry.get("module") or "").strip(),
                "class": str(entry.get("class") or entry.get("class_name") or "").strip(),
            }
        )

    return validate_memory(
        {
            "enabled": coerce_bool(body.get("enabled"), current.memory.enabled),
            "providers": providers,
        }
    )
