"""Neutral contracts for composing authenticated market tick clients.

Provider packages select or adapt a source for an exact SDK-selected route.
They do not construct service clients, authenticated source descriptors, clock
claims, freshness claims, or Backtrader objects. The parent SDK owns runtime
composition and binds the provider adapter to a configured source request.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey


class MarketTickProviderRouteError(ValueError):
    """Finite route errors shared by provider registration factories."""

    _CODES = frozenset(
        {
            "MARKET_TICK_PROVIDER_ROUTE_INVALID",
            "MARKET_TICK_PROVIDER_CLIENT_UNAVAILABLE",
            "MARKET_TICK_PROVIDER_ENVIRONMENT_INVALID",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in self._CODES
            else "MARKET_TICK_PROVIDER_ROUTE_INVALID"
        )
        super().__init__(self.code)


class MarketTickSourceBindingError(ValueError):
    """Finite errors while validating a neutral provider source adapter."""

    _CODES = frozenset(
        {
            "MARKET_TICK_SOURCE_BINDING_INVALID",
            "MARKET_TICK_SOURCE_INSTRUMENT_MISMATCH",
            "MARKET_TICK_SOURCE_CHANNEL_UNSUPPORTED",
            "MARKET_TICK_SOURCE_ADAPTER_INVALID",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in self._CODES
            else "MARKET_TICK_SOURCE_BINDING_INVALID"
        )
        super().__init__(self.code)


def _valid_text(value: object, *, maximum_bytes: int) -> bool:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= maximum_bytes
    except UnicodeEncodeError:
        return False


@dataclass(frozen=True)
class SelectedMarketTickRoute:
    """Exact route selected by the parent SDK before provider adaptation.

    ``client`` is opaque to the parent composer. Provider packages may inspect
    it only within their registered adapter factory. Its presence is not a
    market-source identity or authorization claim.
    """

    exchange_name: str
    client: object = field(repr=False, compare=False)
    instrument: MarketInstrumentKey
    environment: str | None = None

    def __post_init__(self) -> None:
        if not _valid_text(self.exchange_name, maximum_bytes=256):
            raise MarketTickProviderRouteError("MARKET_TICK_PROVIDER_ROUTE_INVALID")
        if self.client is None:
            raise MarketTickProviderRouteError("MARKET_TICK_PROVIDER_CLIENT_UNAVAILABLE")
        if type(self.instrument) is not MarketInstrumentKey:
            raise MarketTickProviderRouteError("MARKET_TICK_PROVIDER_ROUTE_INVALID")
        if self.environment is not None:
            if self.environment not in {"production", "demo", "testnet"}:
                raise MarketTickProviderRouteError(
                    "MARKET_TICK_PROVIDER_ENVIRONMENT_INVALID"
                )
            if self.instrument.environment != self.environment:
                raise MarketTickProviderRouteError("MARKET_TICK_PROVIDER_ROUTE_INVALID")


@runtime_checkable
class MarketTickProviderAdapter(Protocol):
    """Map a configured provider source to a neutral subscription key.

    Source and entitlement references are supplied by the trusted parent
    runtime factory from its explicit configuration. An adapter must not
    invent those values or interpret them as write authority.
    """

    def create_subscription_key(
        self,
        instrument: MarketInstrumentKey,
        *,
        source_ref: str,
        entitlement_ref: str,
        channel: str,
    ) -> MarketSubscriptionKey:
        """Return the neutral key for the exact instrument and source request."""


@dataclass(frozen=True)
class MarketTickSourceBinding:
    """Provider-owned adapter for one exact neutral instrument and tick lane.

    This object contains no source descriptor, session generation, event
    cursor, clock qualification, freshness, entitlement, or authority claim.
    ``provider_adapter`` remains inside the SDK runtime composition and is
    never passed into Backtrader.
    """

    instrument: MarketInstrumentKey
    channel: str
    provider_adapter: MarketTickProviderAdapter = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.instrument) is not MarketInstrumentKey:
            raise MarketTickSourceBindingError("MARKET_TICK_SOURCE_BINDING_INVALID")
        if type(self.channel) is not str or self.channel != "tick":
            raise MarketTickSourceBindingError("MARKET_TICK_SOURCE_CHANNEL_UNSUPPORTED")
        if not isinstance(self.provider_adapter, MarketTickProviderAdapter):
            raise MarketTickSourceBindingError("MARKET_TICK_SOURCE_ADAPTER_INVALID")


@runtime_checkable
class MarketTickProviderFactory(Protocol):
    """Construct one neutral source binding for the SDK-selected route."""

    def __call__(self, route: SelectedMarketTickRoute, /) -> MarketTickSourceBinding:
        """Return a provider adapter without constructing a client/projector."""


@runtime_checkable
class MarketTickProviderRegistryPort(Protocol):
    """Minimal route registration surface consumed by provider packages."""

    def register(self, exchange_name: str, factory: MarketTickProviderFactory, /) -> None:
        """Register one factory under one exact SDK route name."""


__all__ = [
    "MarketTickProviderAdapter",
    "MarketTickProviderFactory",
    "MarketTickProviderRegistryPort",
    "MarketTickProviderRouteError",
    "MarketTickSourceBinding",
    "MarketTickSourceBindingError",
    "SelectedMarketTickRoute",
]
