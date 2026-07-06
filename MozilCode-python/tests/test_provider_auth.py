from __future__ import annotations

from mozilcode.client import _is_local_base_url, _resolve_openai_api_key
from mozilcode.config import ProviderConfig
from mozilcode.provider_auth import (
    LOCAL_OPENAI_API_KEY,
    is_local_base_url,
    resolve_openai_api_key,
)


def _provider(**overrides) -> ProviderConfig:
    base = {
        "name": "openai",
        "protocol": "openai",
        "base_url": "https://api.example.test/v1",
        "model": "gpt-test",
        "api_key": "",
    }
    base.update(overrides)
    return ProviderConfig(**base)


def test_local_base_url_detection_supports_loopback_hosts() -> None:
    assert is_local_base_url("http://127.0.0.1:8080/v1") is True
    assert is_local_base_url("http://localhost:8080/v1") is True
    assert is_local_base_url("http://[::1]:8080/v1") is True


def test_local_base_url_detection_rejects_remote_or_invalid_urls() -> None:
    assert is_local_base_url("https://api.example.test/v1") is False
    assert is_local_base_url("not a url") is False


def test_openai_api_key_uses_explicit_key_first() -> None:
    config = _provider(
        base_url="http://127.0.0.1:8080/v1",
        api_key="explicit-key",
    )

    assert resolve_openai_api_key(config) == "explicit-key"


def test_openai_api_key_allows_local_provider_without_key() -> None:
    config = _provider(base_url="http://127.0.0.1:8080/v1")

    assert resolve_openai_api_key(config) == LOCAL_OPENAI_API_KEY


def test_openai_api_key_keeps_remote_provider_empty_without_key() -> None:
    config = _provider(base_url="https://api.example.test/v1")

    assert resolve_openai_api_key(config) == ""


def test_client_keeps_provider_auth_helper_exports() -> None:
    assert _is_local_base_url is is_local_base_url
    assert _resolve_openai_api_key is resolve_openai_api_key
