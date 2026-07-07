from __future__ import annotations

from typing import TYPE_CHECKING

from mozilcode.config import ProviderConfig

if TYPE_CHECKING:
    from mozilcode.client import LLMClient


MODEL_ALIAS_MAP = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6-20250514",
    "opus": "claude-opus-4-6-20250514",
}


def resolve_subagent_model_override(
    requested_model: str | None,
    definition_model: str,
) -> str | None:
    model = requested_model or (
        definition_model if definition_model != "inherit" else None
    )
    if model == "inherit":
        return None
    return model


def build_subagent_provider_config(
    provider_config: ProviderConfig,
    model_alias: str,
) -> ProviderConfig:
    model_id = MODEL_ALIAS_MAP.get(model_alias, model_alias)
    return ProviderConfig(
        name=f"sub-{model_alias}",
        protocol=provider_config.protocol,
        base_url=provider_config.base_url,
        model=model_id,
        api_key=provider_config.api_key,
        context_window=provider_config.context_window,
        max_output_tokens=provider_config.max_output_tokens,
    )


def create_subagent_client(
    provider_config: ProviderConfig | None,
    model_alias: str,
) -> LLMClient | None:
    if provider_config is None:
        return None

    from mozilcode.client import create_client

    config = build_subagent_provider_config(provider_config, model_alias)
    try:
        return create_client(config)
    except Exception:
        return None
