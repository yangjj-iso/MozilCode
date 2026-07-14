"""已移除产品能力清单与配置/路由防护。

阻止重新引入已下线的 GUI/cloud 等配置段或路由。"""

from __future__ import annotations

from collections.abc import Mapping
import re

REMOVED_CONFIG_SECTIONS = frozenset(
    {
        "accounts",
        "auth",
        "bot_adapters",
        "bots",
        "cloud",
        "frontend",
        "gui",
        "hosted_models",
        "login",
        "official_models",
        "qqbot",
        "telegrambot",
    }
)

REMOVED_ROUTE_TERMS = frozenset(
    {
        "auth",
        "cloud",
        "frontend",
        "hosted",
        "login",
        "official",
    }
)

REMOVED_APP_SHELL_PATHS = frozenset({"/app", "/cloud", "/login", "/models"})

REMOVED_MANAGEMENT_PATHS = frozenset(
    {
        "/api/auth/login",
        "/api/cloud/status",
        "/api/models/official",
        "/api/settings/gui",
    }
)

_ROUTE_TERM_RE = re.compile(r"[a-z0-9]+")


def find_removed_config_sections(raw: Mapping[object, object]) -> tuple[str, ...]:
    """Return unsupported top-level config sections in stable order."""
    return tuple(
        sorted(k for k in raw if isinstance(k, str) and k in REMOVED_CONFIG_SECTIONS)
    )


def removed_route_terms(path: str) -> tuple[str, ...]:
    """Return removed product surface terms found as path tokens."""
    terms = set(_ROUTE_TERM_RE.findall(path.lower()))
    return tuple(sorted(terms & REMOVED_ROUTE_TERMS))


def find_removed_route_paths(paths: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Return route paths that would reintroduce GUI/cloud/bot management surfaces."""
    removed = []
    for path in paths:
        if path in REMOVED_APP_SHELL_PATHS or path in REMOVED_MANAGEMENT_PATHS:
            removed.append(path)
            continue
        if removed_route_terms(path):
            removed.append(path)
    return tuple(removed)


def assert_no_removed_route_paths(paths: list[str] | tuple[str, ...]) -> None:
    """Fail fast if a daemon route exposes a removed product surface."""
    removed = find_removed_route_paths(paths)
    if removed:
        raise RuntimeError(
            "Removed GUI/cloud/bot route(s) are not supported: "
            + ", ".join(removed)
        )
