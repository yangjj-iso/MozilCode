from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType

from mozilcode.llm_errors import (
    AuthenticationError,
    LLMError,
    NetworkError,
    rate_limit_error,
)


ExceptionTypes = tuple[type[BaseException], ...]


def _exception_tuple(value: type[BaseException] | ExceptionTypes) -> ExceptionTypes:
    if isinstance(value, tuple):
        return value
    return (value,)


@dataclass(frozen=True)
class ProviderErrorMapper:
    authentication_errors: ExceptionTypes
    rate_limit_errors: ExceptionTypes
    connection_errors: ExceptionTypes
    status_errors: ExceptionTypes

    @property
    def handled_errors(self) -> ExceptionTypes:
        return (
            *self.authentication_errors,
            *self.rate_limit_errors,
            *self.connection_errors,
            *self.status_errors,
        )

    def to_llm_error(self, error: BaseException) -> LLMError:
        if isinstance(error, self.authentication_errors):
            return AuthenticationError(f"Invalid API key: {error}")
        if isinstance(error, self.rate_limit_errors):
            return rate_limit_error(error)
        if isinstance(error, self.connection_errors):
            return NetworkError(f"Network error: {error}")
        if isinstance(error, self.status_errors):
            status_code = getattr(error, "status_code", "unknown")
            message = getattr(error, "message", str(error))
            return LLMError(f"API error ({status_code}): {message}")
        return LLMError(f"Provider error: {error}")


def provider_error_mapper(sdk: ModuleType) -> ProviderErrorMapper:
    return ProviderErrorMapper(
        authentication_errors=_exception_tuple(sdk.AuthenticationError),
        rate_limit_errors=_exception_tuple(sdk.RateLimitError),
        connection_errors=_exception_tuple(sdk.APIConnectionError),
        status_errors=_exception_tuple(sdk.APIStatusError),
    )
