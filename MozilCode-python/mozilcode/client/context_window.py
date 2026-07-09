from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mozilcode.config import ProviderConfig

ClientFactory = Callable[[ProviderConfig], Any]


async def resolve_context_window(
    config: ProviderConfig,
    client_factory: ClientFactory,
) -> None:
    """Fetch and cache provider context window metadata when available.

    This is the second layer in ProviderConfig's context-window fallback chain:
    explicit config wins first, then fetched provider metadata, then the built-in
    mapping table, then conservative defaults.

    The resolver is intentionally best-effort. Startup must not fail because a
    provider does not expose model metadata, credentials are absent, or the
    metadata endpoint is slow.
    """
    if config.context_window > 0 or config._fetched_context_window > 0:
        return
    if config.protocol != "anthropic":
        return

    try:
        client = client_factory(config)
    except Exception:
        return

    fetch = getattr(client, "fetch_model_context_window", None)
    if fetch is None:
        return

    try:
        window = await fetch()
    except Exception:
        window = None
    if window:
        config.set_fetched_context_window(window)
