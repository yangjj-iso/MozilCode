from __future__ import annotations

from types import SimpleNamespace

from mozilcode.client.error_mapping import ProviderErrorMapper
from mozilcode.client.errors import (
    AuthenticationError,
    LLMError,
    NetworkError,
    RateLimitError,
)


class _AuthError(Exception):
    pass


class _RateLimitError(Exception):
    pass


class _ConnectionError(Exception):
    pass


class _StatusError(Exception):
    status_code = 503
    message = "service unavailable"


def _mapper() -> ProviderErrorMapper:
    return ProviderErrorMapper(
        authentication_errors=(_AuthError,),
        rate_limit_errors=(_RateLimitError,),
        connection_errors=(_ConnectionError,),
        status_errors=(_StatusError,),
    )


def test_provider_error_mapper_exposes_handled_error_tuple() -> None:
    assert _mapper().handled_errors == (
        _AuthError,
        _RateLimitError,
        _ConnectionError,
        _StatusError,
    )


def test_provider_error_mapper_normalizes_authentication_errors() -> None:
    error = _mapper().to_llm_error(_AuthError("bad key"))

    assert isinstance(error, AuthenticationError)
    assert str(error) == "Invalid API key: bad key"


def test_provider_error_mapper_normalizes_rate_limit_errors() -> None:
    source = _RateLimitError("slow down")
    source.response = SimpleNamespace(headers={"retry-after": "4"})

    error = _mapper().to_llm_error(source)

    assert isinstance(error, RateLimitError)
    assert error.retry_after == 4
    assert str(error) == "Rate limited. Retry after 4s."


def test_provider_error_mapper_normalizes_connection_errors() -> None:
    error = _mapper().to_llm_error(_ConnectionError("connection reset"))

    assert isinstance(error, NetworkError)
    assert str(error) == "Network error: connection reset"


def test_provider_error_mapper_normalizes_status_errors() -> None:
    error = _mapper().to_llm_error(_StatusError())

    assert isinstance(error, LLMError)
    assert str(error) == "API error (503): service unavailable"
