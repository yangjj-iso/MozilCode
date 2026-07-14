"""内置模型 context window 查表策略。"""

from __future__ import annotations

DEFAULT_CONTEXT_WINDOW = 200_000

# Built-in "model-name substring -> context window" mapping. This is the third
# layer of ProviderConfig.get_context_window()'s fallback chain, after explicit
# config and provider-fetched metadata.
MODEL_CONTEXT_WINDOWS: tuple[tuple[str, int], ...] = (
    ("1m", 1_000_000),
    ("gpt-4.1", 1_000_000),
    ("gpt-4o", 128_000),
    ("gpt-4-turbo", 128_000),
    ("o1", 200_000),
    ("o3", 200_000),
    ("o4", 200_000),
    ("gpt-3.5", 16_385),
    ("claude", 200_000),
)


def lookup_model_context_window(model: str) -> int:
    """Return the built-in context window for a model name, or 0 if unknown."""
    normalized = model.lower()
    for substring, window in MODEL_CONTEXT_WINDOWS:
        if substring in normalized:
            return window
    return 0
