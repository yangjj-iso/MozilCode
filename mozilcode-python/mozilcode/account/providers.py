"""把账号会话 + 云端目录合成本地 ProviderConfig。

本地只持 JWT；上游密钥始终留在云端 gateway。
"""

from __future__ import annotations

from mozilcode.account.client import CatalogModel
from mozilcode.account.session import AccountSession
from mozilcode.config import ProviderConfig

ACCOUNT_PROVIDER_PREFIX = "account:"


def account_provider_name(model_name: str) -> str:
    return f"{ACCOUNT_PROVIDER_PREFIX}{model_name}"


def is_account_provider_name(name: str) -> bool:
    return name.startswith(ACCOUNT_PROVIDER_PREFIX)


def catalog_name_from_provider(name: str) -> str:
    if is_account_provider_name(name):
        return name[len(ACCOUNT_PROVIDER_PREFIX) :]
    return name


def provider_from_catalog_model(
    session: AccountSession,
    model: CatalogModel,
) -> ProviderConfig:
    # Gateway 是 OpenAI Chat Completions 兼容面；本地统一走 openai-compat。
    return ProviderConfig(
        name=account_provider_name(model.name),
        protocol="openai-compat",
        base_url=session.gateway_base_url(),
        model=model.name,  # gateway 按 body.model 解析目录
        api_key=session.token,
        thinking=model.thinking,
        context_window=0,
        max_output_tokens=0,
    )


def build_account_providers(
    session: AccountSession,
    models: list[CatalogModel],
) -> list[ProviderConfig]:
    if not session.logged_in or not models:
        return []
    providers = [provider_from_catalog_model(session, m) for m in models]
    if session.selected_model:
        selected = account_provider_name(session.selected_model)
        providers.sort(key=lambda p: 0 if p.name == selected else 1)
    return providers


def merge_account_providers(
    account_providers: list[ProviderConfig],
    local_providers: list[ProviderConfig],
) -> list[ProviderConfig]:
    """本地模型优先；同名本地条目被账号侧覆盖（JWT 更新）。

    设计理由：用户显式配置的本地 providers 应作为默认（providers[0]）；
    账号 gateway providers 作为补充列在后面，用户可在 GUI 中切换选择。
    若本地 config.yaml 中残留了与账号同名的 stale 条目，账号版本（含
    有效 JWT）覆盖之。
    """
    if not account_providers:
        return list(local_providers)
    if not local_providers:
        return list(account_providers)
    account_names = {p.name for p in account_providers}
    local_filtered = [p for p in local_providers if p.name not in account_names]
    return [*local_filtered, *account_providers]
