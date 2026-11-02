"""Neutral provider contract for one multi-channel market stream session."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol, runtime_checkable

from bt_api_base.market_protocol import (
    MarketInstrumentKey,
    MarketSourceDescriptor,
    MarketSubscriptionKey,
)
from bt_api_base.market_stream_protocol import (
    MarketStreamEvent,
    MarketStreamRequest,
)
from bt_api_base.market_tick_protocol import MarketEventCursor


_CHANNELS = frozenset({"tick", "orderbook"})


class MarketStreamProviderContractError(ValueError):
    """Finite, value-free provider registration/session contract failure."""

    _CODES = frozenset(
        {
            "MARKET_STREAM_PROVIDER_ROUTE_INVALID",
            "MARKET_STREAM_PROVIDER_CHANNEL_INVALID",
            "MARKET_STREAM_PROVIDER_CHANNEL_UNAVAILABLE",
            "MARKET_STREAM_PROVIDER_ADAPTER_INVALID",
            "MARKET_STREAM_PROVIDER_SESSION_INVALID",
            "MARKET_STREAM_PROVIDER_BINDING_INVALID",
            "MARKET_STREAM_PROVIDER_EVENT_INVALID",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in self._CODES
            else "MARKET_STREAM_PROVIDER_ROUTE_INVALID"
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
class SelectedMarketStreamRoute:
    """Exact BtApi-selected route context supplied to one provider factory.

    ``client`` is the selected route object by identity. It is not a source
    receipt or authorization grant. Provider session creation must not create
    a second BtApi or request client.
    """

    exchange_name: str
    client: object = field(repr=False, compare=False)
    instrument: MarketInstrumentKey
    environment: str | None = None

    def __post_init__(self) -> None:
        if (
            not _valid_text(self.exchange_name, maximum_bytes=256)
            or self.client is None
            or type(self.instrument) is not MarketInstrumentKey
            or (
                self.environment is not None
                and (
                    not _valid_text(self.environment, maximum_bytes=64)
                    or self.instrument.environment != self.environment
                )
            )
        ):
            raise MarketStreamProviderContractError("MARKET_STREAM_PROVIDER_ROUTE_INVALID")


@dataclass(frozen=True)
class MarketStreamChannelCapability:
    """A provider's pre-I/O declaration for one supported neutral channel.

    Advertising ``orderbook`` means that the provider can deliver a complete
    initial/recovery snapshot and detect/recover its native sequence gaps at
    the requested depth. This declaration must not perform network or account
    I/O. Unknown channels are never inferred from a generic event queue.
    """

    channel: str
    max_depth: int | None = None

    def __post_init__(self) -> None:
        if type(self.channel) is not str or self.channel not in _CHANNELS:
            raise MarketStreamProviderContractError("MARKET_STREAM_PROVIDER_CHANNEL_INVALID")
        if self.channel == "tick":
            if self.max_depth is not None:
                raise MarketStreamProviderContractError("MARKET_STREAM_PROVIDER_CHANNEL_INVALID")
        elif type(self.max_depth) is not int or not 1 <= self.max_depth <= 1000:
            raise MarketStreamProviderContractError("MARKET_STREAM_PROVIDER_CHANNEL_INVALID")

    def supports(self, request: MarketStreamRequest) -> bool:
        if type(request) is not MarketStreamRequest or request.channel != self.channel:
            return False
        if self.channel == "tick":
            return request.depth is None
        return request.depth is not None and request.depth <= self.max_depth


@dataclass(frozen=True)
class MarketStreamProviderBinding:
    """Pure adapter binding for one exact route and instrument."""

    instrument: MarketInstrumentKey
    adapter: "MarketStreamProviderAdapter" = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            type(self.instrument) is not MarketInstrumentKey
            or not isinstance(self.adapter, MarketStreamProviderAdapter)
        ):
            raise MarketStreamProviderContractError("MARKET_STREAM_PROVIDER_ADAPTER_INVALID")


@dataclass(frozen=True, eq=False)
class MarketStreamProviderChannelBinding:
    """One provider-issued channel subscription inside a shared session."""

    token: object = field(repr=False)
    request: MarketStreamRequest
    key: MarketSubscriptionKey
    source: MarketSourceDescriptor
    initial_cursor: Optional[MarketEventCursor]
    initial_events: tuple[MarketStreamEvent, ...]
    recovery_required: bool = False

    def __post_init__(self) -> None:
        if (
            self.token is None
            or type(self.request) is not MarketStreamRequest
            or type(self.key) is not MarketSubscriptionKey
            or type(self.source) is not MarketSourceDescriptor
            or (self.initial_cursor is not None and type(self.initial_cursor) is not MarketEventCursor)
            or type(self.initial_events) is not tuple
            or type(self.recovery_required) is not bool
            or self.key.instrument != self.request.instrument
            or self.key.channel != self.request.channel
            or self.key.depth != self.request.depth
            or self.source.key != self.key
            or (
                self.initial_cursor is not None
                and (
                    self.initial_cursor.stream_id != self.source.stream_id
                    or self.initial_cursor.epoch != self.source.epoch
                )
            )
            or any(not isinstance(event, MarketStreamEvent) for event in self.initial_events)
            or any(
                event.source != self.source or event.key != self.key
                for event in self.initial_events
            )
        ):
            raise MarketStreamProviderContractError("MARKET_STREAM_PROVIDER_BINDING_INVALID")
        previous = None
        for event in self.initial_events:
            if (
                type(event.source) is not MarketSourceDescriptor
                or type(event.cursor) is not MarketEventCursor
                or event.cursor.stream_id != self.source.stream_id
                or event.cursor.epoch != self.source.epoch
                or (previous is not None and event.cursor.sequence != previous + 1)
            ):
                raise MarketStreamProviderContractError("MARKET_STREAM_PROVIDER_EVENT_INVALID")
            previous = event.cursor.sequence
        if self.initial_events and self.initial_events[-1].cursor != self.initial_cursor:
            raise MarketStreamProviderContractError("MARKET_STREAM_PROVIDER_BINDING_INVALID")


@runtime_checkable
class MarketStreamProviderSession(Protocol):
    """One provider source session multiplexing channels for one instrument.

    ``poll`` is session-wide and may return events for multiple channel keys.
    The SDK owner validates and dispatches every returned event into each
    channel's single bounded queue before returning to a channel consumer.
    Provider-native sequences remain in channel event DTOs; SDK cursors are
    contiguous accepted-event ordinals within each source epoch.

    The session's producer-side handoff queue must be bounded. Overflow may
    never silently discard events: the session must wake the SDK owner and
    either raise a finite provider failure or surface an explicit recovery
    event/state so every affected channel is marked recovery-required.
    """

    def subscribe(
        self,
        request: MarketStreamRequest,
        /,
    ) -> MarketStreamProviderChannelBinding:
        """Start exactly one supported channel within this shared session."""

    def poll(
        self,
        *,
        timeout_ms: int,
        max_events: int,
    ) -> tuple[MarketStreamEvent, ...]:
        """Read a bounded mixed-channel batch without dropping other channels."""

    def resync(
        self,
        binding: MarketStreamProviderChannelBinding,
        *,
        acknowledge_data_loss: bool,
    ) -> MarketStreamProviderChannelBinding:
        """Return a newly source-bound recovery snapshot for the exact channel."""

    def unsubscribe(self, binding: MarketStreamProviderChannelBinding, /) -> bool:
        """Stop exactly this channel without closing sibling subscriptions."""

    def close(self) -> bool:
        """Close the one shared provider transport after channels are removed."""


@runtime_checkable
class MarketStreamProviderAdapter(Protocol):
    """Provider adapter for an SDK-selected route and instrument."""

    def capabilities(self) -> tuple[MarketStreamChannelCapability, ...]:
        """Declare route capabilities without network, account, or stream I/O."""

    def open_session(
        self,
        *,
        wake_callback: Callable[[], None],
    ) -> MarketStreamProviderSession:
        """Create a local session shell without network or account I/O.

        The first session ``subscribe`` starts the transport with the already
        capability-checked request; later channel subscriptions join that same
        provider session. The callback only wakes SDK waiters; provider source
        events remain in the session queue and are consumed by bounded poll.
        """


@runtime_checkable
class MarketStreamProviderFactory(Protocol):
    """Construct a pure route-bound provider adapter without I/O."""

    def __call__(
        self,
        route: SelectedMarketStreamRoute,
        /,
    ) -> MarketStreamProviderBinding: ...


@runtime_checkable
class MarketStreamProviderRegistryPort(Protocol):
    """Exact-route registration surface used by provider package entrypoints."""

    def register(
        self,
        exchange_name: str,
        factory: MarketStreamProviderFactory,
        /,
    ) -> None: ...


__all__ = [
    "MarketStreamChannelCapability",
    "MarketStreamProviderAdapter",
    "MarketStreamProviderBinding",
    "MarketStreamProviderChannelBinding",
    "MarketStreamProviderContractError",
    "MarketStreamProviderFactory",
    "MarketStreamProviderRegistryPort",
    "MarketStreamProviderSession",
    "SelectedMarketStreamRoute",
]
