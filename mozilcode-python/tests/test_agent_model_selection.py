"""子 Agent 模型选择与客户端构建测试。"""

from __future__ import annotations

from mozilcode.agents.model_selection import (
    build_subagent_provider_config,
    create_subagent_client,
    resolve_subagent_model_override,
    select_subagent_client,
)
from mozilcode.config import ProviderConfig


def test_resolve_subagent_model_override_prefers_request() -> None:
    assert resolve_subagent_model_override("haiku", "sonnet") == "haiku"


def test_resolve_subagent_model_override_uses_definition_model() -> None:
    assert resolve_subagent_model_override(None, "sonnet") == "sonnet"


def test_resolve_subagent_model_override_ignores_inherit() -> None:
    assert resolve_subagent_model_override(None, "inherit") is None
    assert resolve_subagent_model_override("inherit", "sonnet") is None


def test_build_subagent_provider_config_maps_alias_and_preserves_runtime_limits() -> None:
    parent = ProviderConfig(
        name="main",
        protocol="anthropic",
        base_url="https://api.example.test",
        model="parent-model",
        api_key="key",
        context_window=123_000,
        max_output_tokens=4096,
    )

    child = build_subagent_provider_config(parent, "haiku")

    assert child.name == "sub-haiku"
    assert child.protocol == parent.protocol
    assert child.base_url == parent.base_url
    assert child.api_key == parent.api_key
    assert child.model == "claude-haiku-4-5-20251001"
    assert child.context_window == 123_000
    assert child.max_output_tokens == 4096


def test_build_subagent_provider_config_keeps_unknown_model_id() -> None:
    parent = ProviderConfig(
        name="main",
        protocol="openai",
        base_url="https://api.example.test/v1",
        model="parent-model",
    )

    child = build_subagent_provider_config(parent, "custom-model")

    assert child.model == "custom-model"


def test_create_subagent_client_returns_none_without_provider() -> None:
    assert create_subagent_client(None, "haiku") is None


def test_create_subagent_client_returns_none_when_client_creation_fails(monkeypatch) -> None:
    parent = ProviderConfig(
        name="main",
        protocol="openai",
        base_url="https://api.example.test/v1",
        model="parent-model",
    )

    def fail(_config):
        raise RuntimeError("bad config")

    monkeypatch.setattr("mozilcode.client.create_client", fail)

    assert create_subagent_client(parent, "haiku") is None


def test_create_subagent_client_returns_created_client(monkeypatch) -> None:
    parent = ProviderConfig(
        name="main",
        protocol="openai",
        base_url="https://api.example.test/v1",
        model="parent-model",
    )
    created = object()
    captured = {}

    def fake_create_client(config):
        captured["config"] = config
        return created

    monkeypatch.setattr("mozilcode.client.create_client", fake_create_client)

    assert create_subagent_client(parent, "sonnet") is created
    assert captured["config"].model == "claude-sonnet-4-6-20250514"


def test_select_subagent_client_returns_parent_when_no_override() -> None:
    parent_client = object()

    assert (
        select_subagent_client(
            parent_client=parent_client,
            provider_config=None,
            requested_model=None,
            definition_model="inherit",
        )
        is parent_client
    )


def test_select_subagent_client_returns_created_override(monkeypatch) -> None:
    parent = ProviderConfig(
        name="main",
        protocol="openai",
        base_url="https://api.example.test/v1",
        model="parent-model",
    )
    parent_client = object()
    created = object()

    monkeypatch.setattr(
        "mozilcode.agents.model_selection.create_subagent_client",
        lambda _provider, _model: created,
    )

    assert (
        select_subagent_client(
            parent_client=parent_client,
            provider_config=parent,
            requested_model="haiku",
            definition_model="inherit",
        )
        is created
    )


def test_select_subagent_client_falls_back_when_override_creation_fails(monkeypatch) -> None:
    parent = ProviderConfig(
        name="main",
        protocol="openai",
        base_url="https://api.example.test/v1",
        model="parent-model",
    )
    parent_client = object()

    monkeypatch.setattr(
        "mozilcode.agents.model_selection.create_subagent_client",
        lambda _provider, _model: None,
    )

    assert (
        select_subagent_client(
            parent_client=parent_client,
            provider_config=parent,
            requested_model=None,
            definition_model="sonnet",
        )
        is parent_client
    )
