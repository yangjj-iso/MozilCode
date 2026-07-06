"""Product surfaces that are intentionally absent from MozilCode."""

from __future__ import annotations

from collections.abc import Mapping

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


def find_removed_config_sections(raw: Mapping[object, object]) -> tuple[str, ...]:
    """Return unsupported top-level config sections in stable order."""
    return tuple(
        sorted(k for k in raw if isinstance(k, str) and k in REMOVED_CONFIG_SECTIONS)
    )
