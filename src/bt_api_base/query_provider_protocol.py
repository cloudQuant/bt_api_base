"""Neutral route and registry contracts for provider query-port composition.

The SDK selects a route and an opaque client before invoking a provider-owned
factory. Provider distributions depend on these base contracts only; this
module must not import an SDK facade or any provider package.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from bt_api_base.query_protocol import ProviderQueryPort


class QueryProviderRouteError(ValueError):
    """Finite, value-free route validation error shared by query composers."""

    _CODES = frozenset(
        {
            "QUERY_PROVIDER_ROUTE_INVALID",
            "QUERY_PROVIDER_ROUTE_CLIENT_UNAVAILABLE",
            "QUERY_PROVIDER_ENVIRONMENT_INVALID",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in self._CODES else "QUERY_PROVIDER_ROUTE_INVALID"
        super().__init__(self.code)


def _valid_text(value: object, *, max_bytes: int) -> bool:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= max_bytes
    except UnicodeEncodeError:
        return False


@dataclass(frozen=True)
class SelectedQueryRoute:
    """SDK-selected neutral route with an opaque provider client.

    ``client`` is already selected by the SDK. Provider packages may interpret
    its exact type inside their own registration factory, but the SDK composer
    never inspects provider-specific attributes or credentials.
    """

    exchange_name: str
    client: object = field(repr=False, compare=False)
    environment: str | None = None

    def __post_init__(self) -> None:
        if not _valid_text(self.exchange_name, max_bytes=256):
            raise QueryProviderRouteError("QUERY_PROVIDER_ROUTE_INVALID")
        if self.client is None:
            raise QueryProviderRouteError("QUERY_PROVIDER_ROUTE_CLIENT_UNAVAILABLE")
        if self.environment is not None and not _valid_text(
            self.environment,
            max_bytes=128,
        ):
            raise QueryProviderRouteError("QUERY_PROVIDER_ENVIRONMENT_INVALID")


class QueryProviderFactory(Protocol):
    """Construct one provider-neutral query port for a selected route."""

    def __call__(self, route: SelectedQueryRoute, /) -> ProviderQueryPort:
        ...


@runtime_checkable
class QueryProviderRegistryPort(Protocol):
    """Minimal neutral registration port consumed by provider packages."""

    def register(self, exchange_name: str, factory: QueryProviderFactory, /) -> None:
        """Register a provider factory under one exact SDK route key."""


__all__ = [
    "QueryProviderFactory",
    "QueryProviderRegistryPort",
    "QueryProviderRouteError",
    "SelectedQueryRoute",
]
