from __future__ import annotations

import importlib
from typing import Any

from mozilcode.config import MemoryConfig, MemoryProviderConfig
from mozilcode.memory.auto_memory import MemoryManager
from mozilcode.memory.providers.base import MemoryProvider
from mozilcode.memory.providers.hub import MemoryHub
from mozilcode.memory.providers.markdown import MarkdownMemoryProvider


class MemoryProviderLoadError(Exception):
    pass


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
    for provider_config in provider_configs:
        if not provider_config.enabled:
            continue
        providers.append(_load_provider(provider_config, project_root, legacy_manager=legacy_manager))
    return MemoryHub(providers=providers) if providers else None


def _load_provider(
    provider_config: MemoryProviderConfig,
    project_root: str,
    *,
    legacy_manager: MemoryManager | None = None,
) -> MemoryProvider:
    config = provider_config.config or {}
    if provider_config.type == "builtin.markdown":
        provider = MarkdownMemoryProvider(project_root, config, manager=legacy_manager)
        provider.name = provider_config.name or provider.name
        return provider
    if provider_config.type == "python":
        return _load_python_provider(provider_config, project_root)
    raise MemoryProviderLoadError(f"Unsupported memory provider type: {provider_config.type}")


def _load_python_provider(provider_config: MemoryProviderConfig, project_root: str) -> MemoryProvider:
    module_name = provider_config.module
    class_name = provider_config.class_name
    if not module_name or not class_name:
        raise MemoryProviderLoadError("Python memory provider requires module and class")
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    try:
        provider = cls(project_root=project_root, config=provider_config.config)
    except TypeError:
        provider = cls(provider_config.config)
    if not getattr(provider, "name", ""):
        provider.name = provider_config.name
    return provider
