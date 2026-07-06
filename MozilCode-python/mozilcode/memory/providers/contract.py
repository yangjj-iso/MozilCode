from __future__ import annotations

import inspect
from typing import Any

from mozilcode.memory.providers.base import MemoryProvider


class MemoryProviderLoadError(Exception):
    pass


REQUIRED_PROVIDER_METHODS = (
    "initialize",
    "load_context",
    "observe",
    "search",
    "write",
    "clear",
    "shutdown",
)


def validate_provider_contract(provider: Any, target: str) -> None:
    for attr in ("name", "kind", "version"):
        value = getattr(provider, attr, None)
        if not isinstance(value, str) or not value.strip():
            raise MemoryProviderLoadError(
                f"Memory provider {target} must define non-empty string '{attr}'"
            )

    missing_methods = [
        method_name
        for method_name in REQUIRED_PROVIDER_METHODS
        if not callable(getattr(provider, method_name, None))
    ]
    if missing_methods:
        raise MemoryProviderLoadError(
            f"Memory provider {target} does not implement required method(s): "
            f"{', '.join(missing_methods)}"
        )


def normalized_loaded_provider_name(provider: MemoryProvider) -> str:
    name = provider.name.strip()
    if name != provider.name:
        provider.name = name
    return name


def provider_constructor_kwargs(
    cls: type,
    project_root: str,
    config: dict[str, Any],
    legacy_manager: Any | None,
) -> dict[str, Any]:
    available = {"project_root": project_root, "config": config}
    if legacy_manager is not None:
        available["manager"] = legacy_manager

    try:
        signature = inspect.signature(cls)
    except (TypeError, ValueError) as e:
        raise MemoryProviderLoadError(
            f"Cannot inspect memory provider constructor for {cls!r}: {e}"
        ) from e

    params = list(signature.parameters.values())
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params):
        return available

    supported_kinds = {
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }
    unsupported_required = [
        param.name
        for param in params
        if param.kind not in supported_kinds
        and param.default is inspect.Parameter.empty
    ]
    if unsupported_required:
        raise MemoryProviderLoadError(
            f"Unsupported memory provider constructor for {cls!r}; "
            f"required parameter(s) cannot be injected by name: "
            f"{', '.join(unsupported_required)}"
        )

    accepted = {
        param.name
        for param in params
        if param.kind in supported_kinds and param.name in available
    }
    missing = [
        param.name
        for param in params
        if param.kind in supported_kinds
        and param.default is inspect.Parameter.empty
        and param.name not in accepted
    ]
    if missing:
        raise MemoryProviderLoadError(
            f"Unsupported memory provider constructor for {cls!r}; "
            f"unrecognized required parameter(s): {', '.join(missing)}"
        )
    return {name: available[name] for name in accepted}
