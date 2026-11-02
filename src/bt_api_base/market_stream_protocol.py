"""Neutral contracts for SDK-owned live market stream subscriptions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

from bt_api_base.market_protocol import (
    MarketInstrumentKey,
    MarketSourceDescriptor,
    MarketSubscriptionKey,
)
from bt_api_base.market_tick_protocol import MarketEventCursor

DEFAULT_MARKET_STREAM_QUEUE_CAPACITY = 1024
MAX_MARKET_STREAM_QUEUE_CAPACITY = 65536
_RECOVERY_CODES = frozenset(
    {
        "CONSUMER_QUEUE_OVERFLOW",
        "EVENT_SOURCE_MISMATCH",
        "MARKET_CURSOR_DISCONTINUITY",
        "PROVIDER_POLL_FAILED",
        "PROVIDER_RESYNC_FAILED",
        "PROVIDER_RESYNC_REQUIRED",
        "RESYNC_BINDING_UNVERIFIED",
        "ROUTE_CHANGED",
    }
)


class MarketStreamContractError(ValueError):
    """Finite validation failure for provider-neutral stream DTOs."""

    _CODES = frozenset(
        {
            "MARKET_STREAM_REQUEST_INVALID",
            "MARKET_STREAM_SUBSCRIPTION_INVALID",
            "MARKET_STREAM_RESULT_INVALID",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in self._CODES else "MARKET_STREAM_REQUEST_INVALID"
        super().__init__(self.code)


class MarketStreamState(str, Enum):
    """Operational state of one exact SDK stream subscription."""

    ACTIVE = "active"
    RECOVERY_REQUIRED = "recovery_required"
    CLEANUP_UNVERIFIED = "cleanup_unverified"


class MarketStreamIdentityStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class MarketStreamIdentityReceipt:
    """Neutral SDK identity projection for a provider-issued channel start."""

    status: MarketStreamIdentityStatus
    start_receipt: object | None
    source_descriptor: Optional[MarketSourceDescriptor]
    cursor: Optional[MarketEventCursor]
    projector_state: MarketStreamState
    resync_required: Optional[bool]
    unavailable_code: Optional[str]

    def __post_init__(self) -> None:
        if (
            type(self.status) is not MarketStreamIdentityStatus
            or type(self.projector_state) is not MarketStreamState
            or (self.cursor is not None and type(self.cursor) is not MarketEventCursor)
            or (self.source_descriptor is not None and type(self.source_descriptor) is not MarketSourceDescriptor)
            or (self.resync_required is not None and type(self.resync_required) is not bool)
        ):
            raise MarketStreamContractError("MARKET_STREAM_SUBSCRIPTION_INVALID")
        if self.status is MarketStreamIdentityStatus.AVAILABLE:
            if (
                self.start_receipt is None
                or type(self.source_descriptor) is not MarketSourceDescriptor
                or self.unavailable_code is not None
                or self.projector_state is MarketStreamState.CLEANUP_UNVERIFIED
                or (
                    self.cursor is not None
                    and (
                        self.cursor.stream_id != self.source_descriptor.stream_id
                        or self.cursor.epoch != self.source_descriptor.epoch
                    )
                )
            ):
                raise MarketStreamContractError("MARKET_STREAM_SUBSCRIPTION_INVALID")
        elif (
            self.start_receipt is not None
            or self.source_descriptor is not None
            or self.cursor is not None
            or type(self.unavailable_code) is not str
            or self.unavailable_code not in {
                "ROUTE_CHANGED",
                "START_RECEIPT_UNAVAILABLE",
                "SOURCE_DESCRIPTOR_UNAVAILABLE",
                "PROVIDER_UNAVAILABLE",
            }
        ):
            raise MarketStreamContractError("MARKET_STREAM_SUBSCRIPTION_INVALID")

    @property
    def key(self) -> Optional[MarketSubscriptionKey]:
        source = self.source_descriptor
        return source.key if source is not None else None


@runtime_checkable
class MarketStreamEvent(Protocol):
    """Structural view of an SDK event bound to its exact source and cursor."""

    @property
    def source(self) -> MarketSourceDescriptor: ...

    @property
    def cursor(self) -> MarketEventCursor: ...

    @property
    def key(self) -> MarketSubscriptionKey: ...


@runtime_checkable
class MarketStreamIdentity(Protocol):
    """Structural view of the exact identity object issued by a stream."""

    status: object
    start_receipt: object
    cursor: Optional[MarketEventCursor]
    projector_state: object
    resync_required: Optional[bool]
    unavailable_code: Optional[str]

    @property
    def source_descriptor(self) -> Optional[MarketSourceDescriptor]: ...

    @property
    def key(self) -> Optional[MarketSubscriptionKey]: ...


@dataclass(frozen=True)
class MarketStreamRequest:
    """Request one channel on an already-selected exact SDK route.

    ``exchange_name`` and ``instrument`` select a route; they do not supply
    source, entitlement, subscription epoch, or write authority. The SDK and
    provider adapter must bind those facts before returning a subscription.
    Consumers may ask for a channel that a provider does not support; the
    SDK must report that capability as unavailable rather than falling back
    to an untyped event queue.
    """

    exchange_name: str
    instrument: MarketInstrumentKey
    channel: str = "tick"
    depth: Optional[int] = None
    queue_capacity: int = DEFAULT_MARKET_STREAM_QUEUE_CAPACITY

    def __post_init__(self) -> None:
        if not _valid_text(self.exchange_name, 256):
            raise MarketStreamContractError("MARKET_STREAM_REQUEST_INVALID")
        if type(self.instrument) is not MarketInstrumentKey:
            raise MarketStreamContractError("MARKET_STREAM_REQUEST_INVALID")
        if not _valid_text(self.channel, 64):
            raise MarketStreamContractError("MARKET_STREAM_REQUEST_INVALID")
        if self.depth is not None and (
            type(self.depth) is not int or not 1 <= self.depth <= 1000
        ):
            raise MarketStreamContractError("MARKET_STREAM_REQUEST_INVALID")
        if self.channel == "tick" and self.depth is not None:
            raise MarketStreamContractError("MARKET_STREAM_REQUEST_INVALID")
        if (
            type(self.queue_capacity) is not int
            or not 1 <= self.queue_capacity <= MAX_MARKET_STREAM_QUEUE_CAPACITY
        ):
            raise MarketStreamContractError("MARKET_STREAM_REQUEST_INVALID")


@dataclass(frozen=True, eq=False)
class MarketStreamSubscription:
    """Opaque process-local handle issued after an exact source was started.

    The object identity is the consumer token. A caller-created instance is
    not accepted by an SDK owner unless it is the same issued object. The
    source and optional cursor are the exact start facts; poll results carry
    the current source after any explicitly acknowledged resynchronization.
    """

    token: object = field(repr=False)
    request: MarketStreamRequest
    key: MarketSubscriptionKey
    initial_source: MarketSourceDescriptor
    initial_cursor: Optional[MarketEventCursor] = None

    def __post_init__(self) -> None:
        if (
            self.token is None
            or type(self.request) is not MarketStreamRequest
            or type(self.key) is not MarketSubscriptionKey
            or type(self.initial_source) is not MarketSourceDescriptor
            or (self.initial_cursor is not None and type(self.initial_cursor) is not MarketEventCursor)
            or self.key.instrument != self.request.instrument
            or self.key.channel != self.request.channel
            or self.key.depth != self.request.depth
            or self.initial_source.key != self.key
            or (
                self.initial_cursor is not None
                and (
                    self.initial_cursor.stream_id != self.initial_source.stream_id
                    or self.initial_cursor.epoch != self.initial_source.epoch
                )
            )
        ):
            raise MarketStreamContractError("MARKET_STREAM_SUBSCRIPTION_INVALID")


@dataclass(frozen=True)
class MarketStreamPollResult:
    """One bounded delivery from an SDK-owned subscription queue.

    ``cursor`` is the last event delivered in this result, if any.
    ``dropped_events`` is the cumulative number dropped for this subscription.
    """

    subscription: MarketStreamSubscription
    source: MarketSourceDescriptor
    cursor: Optional[MarketEventCursor]
    events: tuple[MarketStreamEvent, ...]
    state: MarketStreamState
    queue_depth: int
    dropped_events: int
    recovery_code: Optional[str] = None

    def __post_init__(self) -> None:
        if (
            type(self.subscription) is not MarketStreamSubscription
            or type(self.source) is not MarketSourceDescriptor
            or self.source.key != self.subscription.key
            or (self.cursor is not None and type(self.cursor) is not MarketEventCursor)
            or type(self.events) is not tuple
            or any(not isinstance(event, MarketStreamEvent) for event in self.events)
            or type(self.state) is not MarketStreamState
            or type(self.queue_depth) is not int
            or self.queue_depth < 0
            or type(self.dropped_events) is not int
            or self.dropped_events < 0
            or (
                self.recovery_code is not None
                and self.recovery_code not in _RECOVERY_CODES
            )
        ):
            raise MarketStreamContractError("MARKET_STREAM_RESULT_INVALID")
        if self.cursor is not None and (
            self.cursor.stream_id != self.source.stream_id
            or self.cursor.epoch != self.source.epoch
        ):
            raise MarketStreamContractError("MARKET_STREAM_RESULT_INVALID")
        previous_sequence = None
        for event in self.events:
            if (
                type(event.source) is not MarketSourceDescriptor
                or type(event.cursor) is not MarketEventCursor
                or type(event.key) is not MarketSubscriptionKey
                or event.source != self.source
                or event.key != self.source.key
                or event.cursor.stream_id != self.source.stream_id
                or event.cursor.epoch != self.source.epoch
                or (
                    previous_sequence is not None
                    and event.cursor.sequence != previous_sequence + 1
                )
            ):
                raise MarketStreamContractError("MARKET_STREAM_RESULT_INVALID")
            previous_sequence = event.cursor.sequence
        if (self.events[-1].cursor if self.events else None) != self.cursor:
            raise MarketStreamContractError("MARKET_STREAM_RESULT_INVALID")
        if (self.state is MarketStreamState.RECOVERY_REQUIRED) != (
            self.recovery_code is not None
        ):
            raise MarketStreamContractError("MARKET_STREAM_RESULT_INVALID")


@runtime_checkable
class MarketStreamPort(Protocol):
    """SDK owner for exact source-bound subscriptions and bounded queues.

    The SDK queue is the source handoff buffer. ``pump`` only appends source
    events; ``poll`` consumes at most its requested event count. Consumers can
    inspect ``queue_depth`` without consuming and must not mirror the complete
    SDK queue in a second unbounded queue. A start bootstrap latest event, when
    present, is the first item in that same SDK queue.

    Operations that touch a live subscription are restricted to the creating
    owner thread. Once all subscriptions have been successfully closed there
    are no thread-bound provider resources, so a terminal ``close`` may be
    called from another thread as a no-op.
    """

    @property
    def supported_channels(self) -> tuple[str, ...]: ...

    def subscribe(self, request: MarketStreamRequest) -> MarketStreamSubscription: ...

    def poll(
        self,
        subscription: MarketStreamSubscription,
        *,
        timeout_ms: int = 0,
        max_events: int = 100,
    ) -> MarketStreamPollResult: ...

    def pump(
        self,
        subscription: MarketStreamSubscription,
        *,
        timeout_ms: int = 0,
        max_source_reads: int = 128,
    ) -> MarketStreamPollResult:
        """Read source events into the SDK queue without consuming that queue."""
        ...

    def stream_identity(
        self, subscription: MarketStreamSubscription
    ) -> MarketStreamIdentity: ...

    def queue_depth(self, subscription: MarketStreamSubscription) -> int:
        """Return this SDK queue's current depth without polling or consuming."""
        ...

    def accept_resync(
        self,
        subscription: MarketStreamSubscription,
        *,
        acknowledge_data_loss: bool,
    ) -> MarketStreamPollResult: ...

    def unsubscribe(self, subscription: MarketStreamSubscription) -> bool: ...

    def close(self) -> None: ...


@runtime_checkable
class MarketStreamSelector(Protocol):
    """Optional selector for the one market stream owner of an SDK facade."""

    def market_stream(self) -> MarketStreamPort: ...


def _valid_text(value: object, maximum_bytes: int) -> bool:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= maximum_bytes
    except UnicodeEncodeError:
        return False


__all__ = [
    "DEFAULT_MARKET_STREAM_QUEUE_CAPACITY",
    "MAX_MARKET_STREAM_QUEUE_CAPACITY",
    "MarketStreamContractError",
    "MarketStreamEvent",
    "MarketStreamIdentityReceipt",
    "MarketStreamIdentityStatus",
    "MarketStreamPollResult",
    "MarketStreamPort",
    "MarketStreamRequest",
    "MarketStreamSelector",
    "MarketStreamIdentity",
    "MarketStreamState",
    "MarketStreamSubscription",
]
