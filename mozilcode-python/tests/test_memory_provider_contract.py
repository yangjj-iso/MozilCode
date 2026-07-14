"""记忆 Provider 契约校验测试。"""

from __future__ import annotations

import pytest

from mozilcode.memory.providers import BaseMemoryProvider, MemoryProviderLoadError
from mozilcode.memory.providers.contract import (
    normalized_loaded_provider_name,
    provider_constructor_kwargs,
    validate_provider_contract,
)


class _CompleteProvider(BaseMemoryProvider):
    name = " complete "
    kind = "test.complete"
    version = "1.0"


class _IncompleteProvider:
    name = "incomplete"
    kind = "test.incomplete"
    version = "1.0"


def test_provider_contract_accepts_base_provider_subclasses() -> None:
    validate_provider_contract(_CompleteProvider(), "test:Complete")


def test_provider_contract_rejects_missing_methods() -> None:
    with pytest.raises(MemoryProviderLoadError, match="required method\\(s\\)"):
        validate_provider_contract(_IncompleteProvider(), "test:Incomplete")


def test_loaded_provider_name_is_trimmed_in_place() -> None:
    provider = _CompleteProvider()

    assert normalized_loaded_provider_name(provider) == "complete"
    assert provider.name == "complete"


def test_constructor_kwargs_injects_only_supported_names() -> None:
    class Provider:
        def __init__(self, project_root: str, config: dict) -> None:
            pass

    kwargs = provider_constructor_kwargs(
        Provider,
        "D:/project",
        {"top_k": 3},
        legacy_manager=object(),
    )

    assert kwargs == {"project_root": "D:/project", "config": {"top_k": 3}}


def test_constructor_kwargs_passes_all_available_to_kwargs_constructor() -> None:
    class Provider:
        def __init__(self, **kwargs) -> None:
            pass

    manager = object()
    kwargs = provider_constructor_kwargs(
        Provider,
        "D:/project",
        {},
        legacy_manager=manager,
    )

    assert kwargs == {"project_root": "D:/project", "config": {}, "manager": manager}


def test_constructor_kwargs_rejects_unknown_required_parameters() -> None:
    class Provider:
        def __init__(self, dsn: str) -> None:
            pass

    with pytest.raises(MemoryProviderLoadError, match="unrecognized required"):
        provider_constructor_kwargs(Provider, "D:/project", {}, legacy_manager=None)
