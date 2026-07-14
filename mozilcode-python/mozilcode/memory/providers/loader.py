"""按配置构建 MemoryHub 并加载 Provider。"""

from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any

from mozilcode.config import MemoryConfig, MemoryProviderConfig
from mozilcode.memory.auto_memory import MemoryManager
from mozilcode.memory.providers.base import MemoryProvider
from mozilcode.memory.providers.contract import (
    MemoryProviderLoadError,
    normalized_loaded_provider_name,
    provider_constructor_kwargs,
    validate_provider_contract,
)
from mozilcode.memory.providers.hub import MemoryHub


BUILTIN_MEMORY_PROVIDERS = {
    "builtin.markdown": "mozilcode.memory.providers.markdown:MarkdownMemoryProvider",
}


def build_memory_hub(
    memory_config: MemoryConfig | None,
    project_root: str,
    *,
    legacy_manager: MemoryManager | None = None,
) -> MemoryHub | None:
    if memory_config is not None and not memory_config.enabled:
        return None

    provider_configs = (
        memory_config.providers
        if memory_config is not None and memory_config.providers
        else [MemoryProviderConfig(name="markdown", type="builtin.markdown", enabled=True)]
    )
    providers: list[MemoryProvider] = []
    seen_names: set[str] = set()
    seen_loaded_names: set[str] = set()
    for provider_config in provider_configs:
        if not provider_config.enabled:
            continue
        name = provider_config.name.strip()
        if not name:
            raise MemoryProviderLoadError("Memory provider name is required")
        if name in seen_names:
            raise MemoryProviderLoadError(
                f"Duplicate memory provider name: {name}"
            )
        seen_names.add(name)
        provider_config = replace(provider_config, name=name)
        provider = _load_provider(
            provider_config,
            project_root,
            legacy_manager=legacy_manager,
        )
        loaded_name = normalized_loaded_provider_name(provider)
        if loaded_name in seen_loaded_names:
            raise MemoryProviderLoadError(
                f"Duplicate loaded memory provider name: {loaded_name}"
            )
        seen_loaded_names.add(loaded_name)
        providers.append(provider)
    return MemoryHub(providers=providers) if providers else None


def _load_provider(
    provider_config: MemoryProviderConfig,
    project_root: str,
    *,
    legacy_manager: MemoryManager | None = None,
) -> MemoryProvider:
    config = provider_config.config or {}
    if provider_config.type in BUILTIN_MEMORY_PROVIDERS:
        provider = _load_class_provider(
            BUILTIN_MEMORY_PROVIDERS[provider_config.type],
            project_root,
            config,
            legacy_manager=legacy_manager,
        )
        if provider_config.name:
            provider.name = provider_config.name
        return provider
    if provider_config.type == "python":
        return _load_python_provider(provider_config, project_root)
    raise MemoryProviderLoadError(f"Unsupported memory provider type: {provider_config.type}")


def _load_python_provider(provider_config: MemoryProviderConfig, project_root: str) -> MemoryProvider:
    module_name = provider_config.module
    class_name = provider_config.class_name
    if not module_name or not class_name:
        raise MemoryProviderLoadError("Python memory provider requires module and class")
    provider = _load_class_provider(
        f"{module_name}:{class_name}",
        project_root,
        provider_config.config,
    )
    if not getattr(provider, "name", ""):
        provider.name = provider_config.name
    return provider


def _load_class_provider(
    target: str,
    project_root: str,
    config: dict[str, Any],
    *,
    legacy_manager: MemoryManager | None = None,
) -> MemoryProvider:
    module_name, _, class_name = target.partition(":")
    if not module_name or not class_name:
        raise MemoryProviderLoadError(f"Invalid memory provider target: {target}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise MemoryProviderLoadError(
            f"Cannot import memory provider module '{module_name}': {e}"
        ) from e
    try:
        cls = getattr(module, class_name)
    except AttributeError as e:
        raise MemoryProviderLoadError(
            f"Memory provider class '{class_name}' not found in module '{module_name}'"
        ) from e
    try:
        kwargs = provider_constructor_kwargs(
            cls,
            project_root,
            config,
            legacy_manager,
        )
        provider = cls(**kwargs)
    except TypeError as e:
        raise MemoryProviderLoadError(
            f"Failed to construct memory provider {target}: {e}"
        ) from e
    validate_provider_contract(provider, target)
    return provider
