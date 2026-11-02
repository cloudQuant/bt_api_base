"""Provider-neutral order-book events with exact source and cursor binding."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Literal

from bt_api_base.market_protocol import MarketInstrumentKey, MarketSourceDescriptor
from bt_api_base.market_tick_protocol import (
    DataClockBinding,
    MarketClockQuality,
    MarketEventCursor,
    MarketFreshnessStatus,
)


_CONTINUITY = frozenset(
    {
        "continuous",
        "ok",
        "recovered",
        "snapshot",
        "checksum_failed",
        "disconnected",
        "gap",
        "out_of_order",
        "stale",
    }
)


class MarketOrderBookContractError(ValueError):
    """Finite failure while validating a neutral order-book event."""

    _CODES = frozenset(
        {
            "MARKET_ORDERBOOK_EVENT_INVALID",
            "MARKET_ORDERBOOK_SOURCE_MISMATCH",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in self._CODES
            else "MARKET_ORDERBOOK_EVENT_INVALID"
        )
        super().__init__(self.code)


@dataclass(frozen=True)
class MarketOrderBookLevel:
    """Exact positive Decimal price and quantity for one book level."""

    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.price) is not Decimal
            or type(self.quantity) is not Decimal
            or not self.price.is_finite()
            or not self.quantity.is_finite()
            or self.price <= 0
            or self.quantity <= 0
        ):
            raise MarketOrderBookContractError("MARKET_ORDERBOOK_EVENT_INVALID")


@dataclass(frozen=True)
class MarketOrderBookEvent:
    """One complete applied book state bound to a source and SDK cursor.

    ``snapshot_or_delta`` describes the provider update that produced this
    event. Both kinds expose the complete post-application book in ``bids``
    and ``asks``. A provider must withhold partial books until a complete
    baseline exists. Native provider sequence remains separate from the SDK
    ``cursor``; the latter orders accepted events in this exact source epoch.
    ``clock`` is the exact neutral ``DataClockBinding``. Until a separately
    qualified provider clock contract exists, both clock qualities must be
    ``UNKNOWN`` and freshness must remain ``UNAVAILABLE``; optional timestamps
    are retained only when they are observed facts.
    """

    source: MarketSourceDescriptor
    cursor: MarketEventCursor
    instrument: MarketInstrumentKey
    clock: DataClockBinding
    bids: tuple[MarketOrderBookLevel, ...]
    asks: tuple[MarketOrderBookLevel, ...]
    provider_sequence: int
    provider_previous_sequence: int | None
    snapshot_or_delta: Literal["snapshot", "delta"]
    continuity_status: str
    stale: bool
    stale_reason: str
    recovery_snapshot: bool
    complete_state: Literal[True]

    _CONTINUITY: ClassVar[frozenset[str]] = _CONTINUITY

    def __post_init__(self) -> None:
        source = self.source
        cursor = self.cursor
        if (
            type(source) is not MarketSourceDescriptor
            or type(cursor) is not MarketEventCursor
            or type(self.instrument) is not MarketInstrumentKey
            or type(self.clock) is not DataClockBinding
            or source.key.instrument != self.instrument
            or source.key.channel != "orderbook"
            or type(source.key.depth) is not int
            or source.key.depth < 1
            or cursor.stream_id != source.stream_id
            or cursor.epoch != source.epoch
            or self.clock.source != source
            or self.clock.cursor != cursor
        ):
            raise MarketOrderBookContractError("MARKET_ORDERBOOK_SOURCE_MISMATCH")
        if (
            type(self.bids) is not tuple
            or type(self.asks) is not tuple
            or not self.bids
            or not self.asks
            or len(self.bids) > source.key.depth
            or len(self.asks) > source.key.depth
            or any(type(level) is not MarketOrderBookLevel for level in self.bids + self.asks)
            or any(
                self.bids[index].price <= self.bids[index + 1].price
                for index in range(len(self.bids) - 1)
            )
            or any(
                self.asks[index].price >= self.asks[index + 1].price
                for index in range(len(self.asks) - 1)
            )
            or self.bids[0].price >= self.asks[0].price
            or type(self.provider_sequence) is not int
            or self.provider_sequence <= 0
            or (
                self.provider_previous_sequence is not None
                and (
                    type(self.provider_previous_sequence) is not int
                    or self.provider_previous_sequence < 0
                )
            )
            or self.snapshot_or_delta not in {"snapshot", "delta"}
            or type(self.continuity_status) is not str
            or self.continuity_status not in _CONTINUITY
            or type(self.stale) is not bool
            or type(self.stale_reason) is not str
            or len(self.stale_reason) > 64
            or not self.stale_reason.isascii()
            or (self.stale and not self.stale_reason)
            or (not self.stale and self.stale_reason)
            or type(self.recovery_snapshot) is not bool
            or (self.recovery_snapshot and self.snapshot_or_delta != "snapshot")
            or self.complete_state is not True
            or (
                self.snapshot_or_delta == "delta"
                and self.provider_previous_sequence is None
            )
        ):
            raise MarketOrderBookContractError("MARKET_ORDERBOOK_EVENT_INVALID")
        if (
            self.clock.freshness_status is not MarketFreshnessStatus.UNAVAILABLE
            or self.clock.source_clock_quality is not MarketClockQuality.UNKNOWN
            or self.clock.receive_clock_quality is not MarketClockQuality.UNKNOWN
            or self.clock.source_clock_error_ms is not None
            or self.clock.receive_clock_error_ms is not None
        ):
            # Clock quality/freshness needs a separately reviewed provider contract.
            raise MarketOrderBookContractError("MARKET_ORDERBOOK_EVENT_INVALID")

    @property
    def key(self):
        return self.source.key

    @property
    def freshness_status(self) -> MarketFreshnessStatus:
        return self.clock.freshness_status


__all__ = [
    "MarketOrderBookContractError",
    "MarketOrderBookEvent",
    "MarketOrderBookLevel",
]
