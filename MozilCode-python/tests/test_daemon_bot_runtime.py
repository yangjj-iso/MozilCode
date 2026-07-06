from __future__ import annotations

from types import SimpleNamespace

import pytest

from mozilcode.daemon import bot_runtime
from mozilcode.daemon.bot_runtime import apply_qq_official_gateway
from mozilcode.daemon.bot_runtime import apply_telegram_bot_runner
from mozilcode.daemon.bot_runtime import save_qqbot_settings
from mozilcode.daemon.bot_runtime import stop_configured_bots


class _FakeConfig:
    def __init__(self, configured: bool) -> None:
        self.configured = configured

    def is_configured(self) -> bool:
        return self.configured


class _FakeRunner:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1


def _fake_app() -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(
            qq_official_gateway=None,
            telegram_bot_runner=None,
        )
    )


@pytest.mark.asyncio
async def test_apply_qq_gateway_starts_configured_gateway(monkeypatch):
    app = _fake_app()
    bridge = object()
    cfg = _FakeConfig(configured=True)
    runner = _FakeRunner()

    monkeypatch.setattr(bot_runtime, "resolve_qqbot_config", lambda: (True, cfg, {}))
    monkeypatch.setattr(
        bot_runtime,
        "create_official_qq_gateway",
        lambda actual_bridge, actual_cfg: runner,
    )

    await apply_qq_official_gateway(app, bridge)

    assert app.state.qq_official_gateway is runner
    assert runner.started == 1


@pytest.mark.asyncio
async def test_apply_telegram_runner_restarts_existing_runner(monkeypatch):
    app = _fake_app()
    bridge = object()
    old_runner = _FakeRunner()
    new_runner = _FakeRunner()
    app.state.telegram_bot_runner = old_runner

    monkeypatch.setattr(
        bot_runtime,
        "resolve_telegrambot_config",
        lambda: (True, _FakeConfig(configured=True), {}),
    )
    monkeypatch.setattr(
        bot_runtime,
        "create_telegram_bot_runner",
        lambda actual_bridge, actual_cfg: new_runner,
    )

    await apply_telegram_bot_runner(app, bridge, restart=True)

    assert old_runner.stopped == 1
    assert app.state.telegram_bot_runner is new_runner
    assert new_runner.started == 1


@pytest.mark.asyncio
async def test_stop_configured_bots_stops_and_clears_runners():
    app = _fake_app()
    qq_runner = _FakeRunner()
    telegram_runner = _FakeRunner()
    app.state.qq_official_gateway = qq_runner
    app.state.telegram_bot_runner = telegram_runner

    await stop_configured_bots(app)

    assert qq_runner.stopped == 1
    assert telegram_runner.stopped == 1
    assert app.state.qq_official_gateway is None
    assert app.state.telegram_bot_runner is None


@pytest.mark.asyncio
async def test_save_qqbot_settings_saves_then_restarts_gateway(monkeypatch):
    app = _fake_app()
    bridge = object()
    saved_settings = []
    restarts = []

    monkeypatch.setattr(bot_runtime, "load_gui_settings", lambda: {"qqbot": {}})
    monkeypatch.setattr(bot_runtime, "save_gui_settings", saved_settings.append)
    monkeypatch.setattr(
        bot_runtime,
        "resolve_qqbot_config",
        lambda settings=None: (False, _FakeConfig(configured=False), {}),
    )

    async def fake_apply(app_arg, bridge_arg, *, restart=False):
        restarts.append((app_arg, bridge_arg, restart))

    monkeypatch.setattr(bot_runtime, "apply_qq_official_gateway", fake_apply)
    monkeypatch.setattr(
        bot_runtime,
        "public_qqbot_status",
        lambda app_arg: {"enabled": False, "configured": False},
    )

    status = await save_qqbot_settings(app, bridge, {"enabled": False})

    assert status == {"ok": True, "enabled": False, "configured": False}
    assert saved_settings[0]["qqbot"]["enabled"] is False
    assert restarts == [(app, bridge, True)]


@pytest.mark.asyncio
async def test_save_qqbot_settings_rejects_non_object_payload():
    with pytest.raises(ValueError, match="JSON object is required"):
        await save_qqbot_settings(_fake_app(), object(), [])
