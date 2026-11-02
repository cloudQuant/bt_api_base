"""Neutral exact-route contract for historical market-bar providers."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from bt_api_base.market_history_protocol import MarketHistoryPage, MarketHistoryRequest
from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey


_FIXED_TIMEFRAME = re.compile(r"[1-9][0-9]{0,11}[smhdw]\Z", re.ASCII)


class MarketHistoryProviderContractError(ValueError):
    """Finite, value-free provider route and binding contract failure."""

    _CODES = frozenset(
        {
            "MARKET_HISTORY_PROVIDER_ROUTE_INVALID",
            "MARKET_HISTORY_PROVIDER_TIMEFRAME_UNAVAILABLE",
            "MARKET_HISTORY_PROVIDER_BINDING_INVALID",
            "MARKET_HISTORY_PROVIDER_ADAPTER_INVALID",
            "MARKET_HISTORY_PROVIDER_POLICY_INVALID",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in self._CODES
            else "MARKET_HISTORY_PROVIDER_ROUTE_INVALID"
        )
        super().__init__(self.code)


def _valid_text(value: object, *, maximum_bytes: int) -> bool:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= maximum_bytes
    except UnicodeEncodeError:
        return False


def _valid_timeout_seconds(value: object) -> bool:
    if type(value) is int:
        return 0 < value <= 300
    return (
        type(value) is float
        and math.isfinite(value)
        and 0 < value <= 300.0
    )


@dataclass(frozen=True)
class SelectedMarketHistoryRoute:
    """SDK-selected exact route passed to one provider factory.

    The selected client is opaque to the SDK router. Provider code may unwrap
    its own exact client type. This route object carries no authorization or
    historical-data completeness claim.
    """

    exchange_name: str
    client: object = field(repr=False, compare=False)
    instrument: MarketInstrumentKey
    timeframe: str
    environment: str | None = None

    def __post_init__(self) -> None:
        if (
            not _valid_text(self.exchange_name, maximum_bytes=256)
            or self.client is None
            or type(self.instrument) is not MarketInstrumentKey
            or type(self.timeframe) is not str
            or _FIXED_TIMEFRAME.fullmatch(self.timeframe) is None
            or (
                self.environment is not None
                and (
                    not _valid_text(self.environment, maximum_bytes=128)
                    or self.instrument.environment != self.environment
                )
            )
        ):
            raise MarketHistoryProviderContractError("MARKET_HISTORY_PROVIDER_ROUTE_INVALID")


@runtime_checkable
class MarketHistoryProviderAdapter(Protocol):
    """Provider-owned page source for one selected route and key."""

    def fetch(
        self,
        request: MarketHistoryRequest,
        timeout_seconds: float,
        /,
    ) -> MarketHistoryPage:
        """Return one exact page or raise a finite provider-owned error."""


@dataclass(frozen=True)
class MarketHistoryProviderBinding:
    """Provider-issued source key, adapter, and bounded collection policy."""

    key: MarketSubscriptionKey
    adapter: MarketHistoryProviderAdapter = field(repr=False, compare=False)
    default_limit: int
    page_size: int
    max_pages: int
    max_rows: int
    request_timeout_seconds: float

    def __post_init__(self) -> None:
        if type(self.key) is not MarketSubscriptionKey or self.key.channel != "bar":
            raise MarketHistoryProviderContractError("MARKET_HISTORY_PROVIDER_BINDING_INVALID")
        if not isinstance(self.adapter, MarketHistoryProviderAdapter):
            raise MarketHistoryProviderContractError("MARKET_HISTORY_PROVIDER_ADAPTER_INVALID")
        if (
            type(self.default_limit) is not int
            or not 1 <= self.default_limit <= 1_000_000
            or type(self.page_size) is not int
            or not 1 <= self.page_size <= 1000
            or type(self.max_pages) is not int
            or not 1 <= self.max_pages <= 10_000
            or type(self.max_rows) is not int
            or not self.default_limit <= self.max_rows <= 1_000_000
            or not _valid_timeout_seconds(self.request_timeout_seconds)
        ):
            raise MarketHistoryProviderContractError("MARKET_HISTORY_PROVIDER_POLICY_INVALID")


class MarketHistoryProviderFactory(Protocol):
    """Construct a provider-owned history binding without network I/O."""

    def __call__(
        self,
        route: SelectedMarketHistoryRoute,
        /,
    ) -> MarketHistoryProviderBinding: ...


@runtime_checkable
class MarketHistoryProviderRegistryPort(Protocol):
    """Exact route registration surface for provider package entrypoints."""

    def register(
        self,
        exchange_name: str,
        factory: MarketHistoryProviderFactory,
        /,
    ) -> None: ...


__all__ = [
    "MarketHistoryProviderAdapter",
    "MarketHistoryProviderBinding",
    "MarketHistoryProviderContractError",
    "MarketHistoryProviderFactory",
    "MarketHistoryProviderRegistryPort",
    "SelectedMarketHistoryRoute",
]
