"""账号会话路由：登录云端、拉模型目录、选择模型。

路径用 /api/account/*，避开 removed_capabilities 里的 auth/cloud/login 词。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.account import (
    AccountClientError,
    filter_local_providers,
    get_status,
    list_catalog,
    provider_payload,
    select_model,
    sign_in,
    sign_out,
)
from mozilcode.daemon.request_body import (
    BodyFieldError,
    bool_field,
    parse_json_object,
    required_string_field,
    string_field,
)
from mozilcode.daemon.request_context import daemon_server
from mozilcode.daemon.responses import bad_request_response


@dataclass(frozen=True)
class SignInBody:
    email: str
    password: str
    base_url: str
    register: bool


@dataclass(frozen=True)
class SelectModelBody:
    model: str


def _parse_sign_in(payload: dict[str, Any]) -> SignInBody:
    email = required_string_field(payload, "email")
    password = required_string_field(payload, "password")
    base_url = string_field(payload, "base_url", "")
    register = bool_field(payload, "register", False)
    return SignInBody(
        email=email,
        password=password,
        base_url=base_url,
        register=register,
    )


def _parse_select_model(payload: dict[str, Any]) -> SelectModelBody:
    model = required_string_field(payload, "model")
    return SelectModelBody(model=model)


def _reload_server_config(request: Request) -> None:
    server = daemon_server(request)
    from mozilcode.config import ConfigError, load_config

    try:
        server.config = load_config()
    except ConfigError:
        server.config = None


def _account_error(exc: AccountClientError) -> JSONResponse:
    status = exc.status_code if exc.status_code and 400 <= exc.status_code < 600 else 400
    return JSONResponse({"error": str(exc)}, status_code=status)


async def get_account(request: Request) -> JSONResponse:
    status = get_status()
    server = daemon_server(request)
    application = server.config_application_status()
    return JSONResponse({**status.to_dict(), **application})


async def post_account_session(request: Request) -> JSONResponse:
    parsed = await parse_json_object(request, _parse_sign_in)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()
    try:
        session = sign_in(
            email=body.email,
            password=body.password,
            base_url=body.base_url or None,
            register=body.register,
        )
    except AccountClientError as exc:
        return _account_error(exc)
    except BodyFieldError as exc:
        return bad_request_response(str(exc))

    _reload_server_config(request)
    status = get_status()
    server = daemon_server(request)
    return JSONResponse(
        {
            **status.to_dict(),
            "message": "registered" if body.register else "signed_in",
            "providers": (
                [provider_payload(p) for p in server.config.providers]
                if server.config is not None
                else []
            ),
            **server.config_application_status(),
        }
    )


async def delete_account_session(request: Request) -> JSONResponse:
    sign_out()
    _reload_server_config(request)
    status = get_status()
    return JSONResponse({**status.to_dict(), "message": "signed_out"})


async def get_account_models(request: Request) -> JSONResponse:
    try:
        models = list_catalog()
    except AccountClientError as exc:
        return _account_error(exc)
    status = get_status()
    return JSONResponse(
        {
            "models": [
                {
                    "name": m.name,
                    "display_name": m.display_name,
                    "provider": m.provider,
                    "protocol": m.protocol,
                    "model_id": m.model_id,
                    "thinking": m.thinking,
                    "selected": m.name == status.selected_model,
                }
                for m in models
            ],
            "selected_model": status.selected_model,
            "logged_in": status.logged_in,
        }
    )


async def post_account_model(request: Request) -> JSONResponse:
    parsed = await parse_json_object(request, _parse_select_model)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()
    try:
        select_model(body.model)
    except AccountClientError as exc:
        return _account_error(exc)

    _reload_server_config(request)
    status = get_status()
    server = daemon_server(request)
    return JSONResponse(
        {
            **status.to_dict(),
            "message": "model_selected",
            "providers": (
                [provider_payload(p) for p in server.config.providers]
                if server.config is not None
                else []
            ),
            **server.config_application_status(),
        }
    )


# re-export for config save filtering convenience
__all__ = [
    "delete_account_session",
    "filter_local_providers",
    "get_account",
    "get_account_models",
    "post_account_model",
    "post_account_session",
]
