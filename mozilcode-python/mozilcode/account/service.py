"""账号领域服务：登录态、目录、provider 合成。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mozilcode.account.client import (
    AccountClientError,
    CatalogModel,
    fetch_models,
    login as cloud_login,
    normalize_base_url,
)
from mozilcode.account.providers import (
    build_account_providers,
    is_account_provider_name,
)
from mozilcode.account.session import (
    DEFAULT_BASE_URL,
    AccountSession,
    clear_session,
    load_session,
    save_session,
    with_selected_model,
)
from mozilcode.config import ProviderConfig


@dataclass(frozen=True)
class AccountStatus:
    logged_in: bool
    base_url: str
    email: str = ""
    role: str = ""
    user_id: int | None = None
    selected_model: str = ""
    session_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "logged_in": self.logged_in,
            "base_url": self.base_url,
            "email": self.email,
            "role": self.role,
            "user_id": self.user_id,
            "selected_model": self.selected_model,
            "session_path": self.session_path,
        }


def session_path() -> Path:
    from mozilcode.account.session import SESSION_FILE

    return SESSION_FILE


def get_status(path: Path | None = None) -> AccountStatus:
    session = load_session(path)
    if session is None:
        return AccountStatus(
            logged_in=False,
            base_url=DEFAULT_BASE_URL,
            session_path=str(path or session_path()),
        )
    return AccountStatus(
        logged_in=True,
        base_url=session.base_url,
        email=session.email,
        role=session.role,
        user_id=session.user_id,
        selected_model=session.selected_model,
        session_path=str(path or session_path()),
    )


def sign_in(
    *,
    email: str,
    password: str,
    base_url: str | None = None,
    register: bool = False,
    path: Path | None = None,
) -> AccountSession:
    previous = load_session(path)
    session = cloud_login(
        email=email,
        password=password,
        base_url=base_url,
        register=register,
    )
    if previous and previous.base_url == session.base_url and previous.email == session.email:
        session = with_selected_model(session, previous.selected_model)
    save_session(session, path)
    return session


def sign_out(path: Path | None = None) -> None:
    clear_session(path)


def list_catalog(path: Path | None = None) -> list[CatalogModel]:
    session = load_session(path)
    if session is None:
        raise AccountClientError("not signed in", status_code=401)
    return fetch_models(session)


def select_model(model_name: str, path: Path | None = None) -> AccountSession:
    session = load_session(path)
    if session is None:
        raise AccountClientError("not signed in", status_code=401)
    name = model_name.strip()
    if not name:
        raise AccountClientError("model required")
    models = fetch_models(session)
    if not any(m.name == name for m in models):
        raise AccountClientError(f"model not available: {name}")
    updated = with_selected_model(session, name)
    save_session(updated, path)
    return updated


def load_account_providers(path: Path | None = None) -> list[ProviderConfig]:
    session = load_session(path)
    if session is None:
        return []
    try:
        models = fetch_models(session)
    except AccountClientError:
        # 离线/过期：若已选模型，仍用 JWT 合成单入口，让运行期报清晰鉴权错误。
        if not session.selected_model:
            return []
        models = [
            CatalogModel(
                name=session.selected_model,
                display_name=session.selected_model,
            )
        ]
    return build_account_providers(session, models)


def filter_local_providers(providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """保存 config 时剔除账号托管 provider，避免 JWT 写入 config.yaml。"""
    result: list[dict[str, Any]] = []
    for item in providers:
        name = str(item.get("name") or "")
        if is_account_provider_name(name) or item.get("managed") == "account":
            continue
        result.append(item)
    return result


def provider_payload(provider: ProviderConfig) -> dict[str, Any]:
    managed = "account" if is_account_provider_name(provider.name) else "local"
    return {
        "name": provider.name,
        "protocol": provider.protocol,
        "base_url": provider.base_url if managed == "local" else "(mozilcode gateway)",
        "model": provider.model,
        "api_key": "",
        "api_key_set": bool(provider.api_key),
        "thinking": provider.thinking,
        "context_window": provider.context_window,
        "max_output_tokens": provider.max_output_tokens,
        "managed": managed,
        "display_name": provider.model,
    }


def default_base_url() -> str:
    return normalize_base_url(DEFAULT_BASE_URL)