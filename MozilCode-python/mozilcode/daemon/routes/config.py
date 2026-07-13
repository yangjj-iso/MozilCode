"""Routes for model provider configuration management."""

from __future__ import annotations

from dataclasses import dataclass
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.daemon.request_body import (
    BodyFieldError,
    parse_json_object,
    bool_field,
    required_string_field,
    string_field,
)
from mozilcode.daemon.request_context import daemon_server
from mozilcode.daemon.responses import bad_request_response
from mozilcode.config.validator import CURRENT_CONFIG_SCHEMA_VERSION

USER_CONFIG_FILE = Path.home() / ".mozilcode" / "config.yaml"
VALID_PROTOCOLS = {"anthropic", "openai", "openai-compat"}
VALID_PERMISSION_MODES = {
    "default",
    "acceptEdits",
    "plan",
    "bypassPermissions",
    "custom",
    "dontAsk",
}


@dataclass(frozen=True)
class SaveConfigBody:
    providers: list[dict[str, Any]]
    permission_mode: str


def _parse_provider_entry(entry: dict[str, Any], index: int) -> dict[str, Any]:
    label = f"Provider #{index + 1}"
    name = required_string_field(entry, "name")
    protocol = required_string_field(entry, "protocol")
    if protocol not in VALID_PROTOCOLS:
        raise BodyFieldError(
            f"{label}: invalid protocol '{protocol}', must be one of: {', '.join(sorted(VALID_PROTOCOLS))}"
        )
    base_url = required_string_field(entry, "base_url")
    model = required_string_field(entry, "model")
    api_key = string_field(entry, "api_key")
    thinking = bool_field(entry, "thinking", False)
    context_window = entry.get("context_window", 0)
    if not isinstance(context_window, int) or isinstance(context_window, bool):
        raise BodyFieldError(f"{label}: context_window must be an integer")
    max_output_tokens = entry.get("max_output_tokens", 0)
    if not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool):
        raise BodyFieldError(f"{label}: max_output_tokens must be an integer")
    return {
        "name": name,
        "protocol": protocol,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "thinking": thinking,
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
        "_clear_api_key": bool_field(entry, "clear_api_key", False),
        "previous_name": string_field(entry, "previous_name", ""),
    }


def _parse_save_config_body(payload: dict[str, Any]) -> SaveConfigBody:
    raw_providers = payload.get("providers")
    if not isinstance(raw_providers, list) or not raw_providers:
        raise BodyFieldError("At least one provider must be configured")
    providers = [_parse_provider_entry(p, i) for i, p in enumerate(raw_providers)]
    seen = set()
    for p in providers:
        if p["name"] in seen:
            raise BodyFieldError(f"Provider '{p['name']}': duplicate name")
        seen.add(p["name"])
    permission_mode = string_field(payload, "permission_mode", "default")
    if permission_mode not in VALID_PERMISSION_MODES:
        raise BodyFieldError(
            f"Invalid permission_mode '{permission_mode}', "
            f"must be one of: {', '.join(sorted(VALID_PERMISSION_MODES))}"
        )
    return SaveConfigBody(providers=providers, permission_mode=permission_mode)


def _provider_to_dict(p: Any) -> dict[str, Any]:
    return {
        "name": p.name,
        "protocol": p.protocol,
        "base_url": p.base_url,
        "model": p.model,
        "api_key": "",
        "api_key_set": bool(p.api_key),
        "thinking": p.thinking,
        "context_window": p.context_window,
        "max_output_tokens": p.max_output_tokens,
    }


def _config_payload(server: Any) -> dict[str, Any]:
    application = server.config_application_status()
    if server.config is None:
        return {
            "configured": False,
            "config_path": str(USER_CONFIG_FILE),
            "providers": [],
            "permission_mode": "default",
            **application,
        }
    return {
        "configured": True,
        "config_path": str(USER_CONFIG_FILE),
        "providers": [_provider_to_dict(p) for p in server.config.providers],
        "permission_mode": server.config.permission_mode,
        **application,
    }


def _read_raw_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return raw
    except yaml.YAMLError:
        return {}


def _write_raw_config(path: Path, raw: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(
        raw, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def get_config(request: Request) -> JSONResponse:
    server = daemon_server(request)
    return JSONResponse(_config_payload(server))


async def save_config(request: Request) -> JSONResponse:
    server = daemon_server(request)
    parsed = await parse_json_object(request, _parse_save_config_body)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()

    config_path = USER_CONFIG_FILE
    previous_exists = config_path.exists()
    previous_raw = _read_raw_config(config_path)
    raw = _read_raw_config(config_path)
    existing = raw.get("providers", [])
    existing_by_name = {
        item.get("name"): item
        for item in existing
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    providers: list[dict[str, Any]] = []
    for provider in body.providers:
        previous_name = provider.get("previous_name") or provider["name"]
        previous = existing_by_name.get(previous_name)
        clear_key = provider.pop("_clear_api_key", False)
        if not provider["api_key"] and not clear_key and isinstance(previous, dict):
            provider["api_key"] = previous.get("api_key", "")
        provider.pop("previous_name", None)
        providers.append(provider)
    raw["providers"] = providers
    raw["permission_mode"] = body.permission_mode
    raw.setdefault("schema_version", CURRENT_CONFIG_SCHEMA_VERSION)

    try:
        _write_raw_config(config_path, raw)
        from mozilcode.config import load_config
        server.config = load_config()
    except Exception as exc:
        if previous_exists:
            _write_raw_config(config_path, previous_raw)
        elif config_path.exists():
            config_path.unlink()
        return bad_request_response(f"Configuration was not applied: {exc}")

    return JSONResponse(_config_payload(server))
