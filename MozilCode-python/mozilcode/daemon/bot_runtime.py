from __future__ import annotations

import logging
from typing import Any

from mozilcode.a2a.bridge import A2ABridge
from mozilcode.a2a.qq_official import create_official_qq_gateway
from mozilcode.a2a.telegram_official import create_telegram_bot_runner
from mozilcode.daemon.settings import (
    load_daemon_settings,
    public_qqbot_status,
    public_telegrambot_status,
    qqbot_settings_from_payload,
    resolve_qqbot_config,
    resolve_telegrambot_config,
    save_daemon_settings,
    telegrambot_settings_from_payload,
)

log = logging.getLogger(__name__)


def init_bot_state(app: Any) -> None:
    app.state.qq_official_gateway = None
    app.state.telegram_bot_runner = None


async def start_configured_bots(app: Any, bridge: A2ABridge) -> None:
    await apply_qq_official_gateway(app, bridge)
    await apply_telegram_bot_runner(app, bridge)


async def stop_configured_bots(app: Any) -> None:
    gateway = getattr(app.state, "qq_official_gateway", None)
    if gateway is not None:
        await gateway.stop()
        app.state.qq_official_gateway = None
    runner = getattr(app.state, "telegram_bot_runner", None)
    if runner is not None:
        await runner.stop()
        app.state.telegram_bot_runner = None


async def apply_qq_official_gateway(
    app: Any,
    bridge: A2ABridge,
    *,
    restart: bool = False,
) -> None:
    gateway = getattr(app.state, "qq_official_gateway", None)
    enabled, cfg, _settings = resolve_qqbot_config()

    if gateway is not None and (restart or not enabled or not cfg.is_configured()):
        await gateway.stop()
        app.state.qq_official_gateway = None
        gateway = None

    if not enabled:
        return
    if not cfg.is_configured():
        log.warning("Official QQ Gateway requested but AppID/AppSecret are not configured")
        return
    if gateway is not None:
        return

    gateway = create_official_qq_gateway(bridge, cfg)
    app.state.qq_official_gateway = gateway
    await gateway.start()
    log.info("Official QQ Gateway adapter enabled")


def qqbot_status(app: Any) -> dict:
    return public_qqbot_status(app)


async def save_qqbot_settings(app: Any, bridge: A2ABridge, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON object is required")

    data = load_daemon_settings()
    data["qqbot"] = qqbot_settings_from_payload(body, data.get("qqbot"))
    enabled, cfg, _settings = resolve_qqbot_config(data)
    if enabled and not cfg.is_configured():
        raise ValueError("启用 QQ Bot 需要 AppID 和 AppSecret")

    save_daemon_settings(data)
    await apply_qq_official_gateway(app, bridge, restart=True)
    return {"ok": True, **public_qqbot_status(app)}


async def apply_telegram_bot_runner(
    app: Any,
    bridge: A2ABridge,
    *,
    restart: bool = False,
) -> None:
    runner = getattr(app.state, "telegram_bot_runner", None)
    enabled, cfg, _settings = resolve_telegrambot_config()

    if runner is not None and (restart or not enabled or not cfg.is_configured()):
        await runner.stop()
        app.state.telegram_bot_runner = None
        runner = None

    if not enabled:
        return
    if not cfg.is_configured():
        log.warning("Telegram Bot requested but Bot token is not configured")
        return
    if runner is not None:
        return

    runner = create_telegram_bot_runner(bridge, cfg)
    app.state.telegram_bot_runner = runner
    await runner.start()
    log.info("Telegram Bot adapter enabled")


def telegrambot_status(app: Any) -> dict:
    return public_telegrambot_status(app)


async def save_telegrambot_settings(app: Any, bridge: A2ABridge, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON object is required")

    data = load_daemon_settings()
    data["telegrambot"] = telegrambot_settings_from_payload(body, data.get("telegrambot"))
    enabled, cfg, _settings = resolve_telegrambot_config(data)
    if enabled and not cfg.is_configured():
        raise ValueError("启用 Telegram Bot 需要 Bot Token")

    save_daemon_settings(data)
    await apply_telegram_bot_runner(app, bridge, restart=True)
    return {"ok": True, **public_telegrambot_status(app)}
