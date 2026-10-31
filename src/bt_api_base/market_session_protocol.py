"""Neutral product-session schedules and provider event-time projections.

The schedule describes half-open UTC session windows and explicit local event
dates. It contains no exchange-native field names or framework bar-grid types.
Clock quality remains separate from schedule membership: a matching window
cannot make an unqualified event fresh.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from bt_api_base.futures_market_protocol import FuturesProductKey
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.market_tick_protocol import (
    MarketClockQuality,
    MarketFreshnessStatus,
    MarketTickEvent,
)
from bt_api_base.service_protocol import MAX_REFERENCE_BYTES


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_MAX_SESSION_WINDOWS = 100_000
_MAX_SESSION_DAYS = 10_000
_MAX_EVENT_SESSION_DATES = 3
_MAX_ROUTE_NAME_BYTES = 256
_MAX_ENVIRONMENT_BYTES = 128


class MarketSessionContractError(ValueError):
    """Finite, value-free validation failure for neutral session contracts."""

    _CODES = frozenset(
        {
            "MARKET_SESSION_VALUE_INVALID",
            "MARKET_SESSION_SCHEDULE_INVALID",
            "MARKET_SESSION_RESOLUTION_INVALID",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in self._CODES else "MARKET_SESSION_VALUE_INVALID"
        super().__init__(self.code)


class MarketSessionProviderRouteError(ValueError):
    """Finite, value-free error for neutral provider-route composition."""

    _CODES = frozenset(
        {
            "MARKET_SESSION_PROVIDER_ROUTE_INVALID",
            "MARKET_SESSION_PROVIDER_CLIENT_UNAVAILABLE",
            "MARKET_SESSION_PROVIDER_ENVIRONMENT_INVALID",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in self._CODES
            else "MARKET_SESSION_PROVIDER_ROUTE_INVALID"
        )
        super().__init__(self.code)


class MarketSessionResolutionStatus(str, Enum):
    """Whether the event-to-schedule projection is resolved."""

    COMPLETE = "complete"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class MarketSessionSegmentKind(str, Enum):
    """Neutral classification of an event relative to continuous sessions."""

    CONTINUOUS = "continuous"
    OPENING_AUCTION_BASELINE = "opening_auction_baseline"
    OUTSIDE = "outside"
    UNKNOWN = "unknown"


def _route_text(value: Any, *, max_bytes: int) -> bool:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= max_bytes
    except UnicodeEncodeError:
        return False


@dataclass(frozen=True)
class SelectedMarketSessionRoute:
    """SDK-selected route passed opaquely to a provider-owned resolver factory.

    ``exchange_name`` is the SDK route key, which may be a capability key such
    as ``CTP___FUTURE`` and therefore need not equal ``instrument.venue``.
    Provider packages alone may inspect the exact ``client`` type.
    """

    exchange_name: str
    client: object = field(repr=False, compare=False)
    instrument: MarketInstrumentKey
    environment: Optional[str] = None

    def __post_init__(self) -> None:
        if not _route_text(self.exchange_name, max_bytes=_MAX_ROUTE_NAME_BYTES):
            raise MarketSessionProviderRouteError("MARKET_SESSION_PROVIDER_ROUTE_INVALID")
        if self.client is None:
            raise MarketSessionProviderRouteError(
                "MARKET_SESSION_PROVIDER_CLIENT_UNAVAILABLE"
            )
        if type(self.instrument) is not MarketInstrumentKey:
            raise MarketSessionProviderRouteError("MARKET_SESSION_PROVIDER_ROUTE_INVALID")
        if self.environment is not None and not _route_text(
            self.environment,
            max_bytes=_MAX_ENVIRONMENT_BYTES,
        ):
            raise MarketSessionProviderRouteError(
                "MARKET_SESSION_PROVIDER_ENVIRONMENT_INVALID"
            )


def _text(value: Any) -> bool:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= MAX_REFERENCE_BYTES
    except UnicodeEncodeError:
        return False


def _date(value: Any) -> bool:
    return type(value) is date


def _utc_datetime(value: Any) -> bool:
    return (
        type(value) is datetime
        and value.tzinfo is not None
        and value.utcoffset() == timedelta(0)
    )


def _calendar_identity(calendar_ref: Any, calendar_digest: Any) -> bool:
    return (
        _text(calendar_ref)
        and type(calendar_digest) is str
        and _SHA256_RE.fullmatch(calendar_digest) is not None
    )


@dataclass(frozen=True)
class MarketSessionWindow:
    """One half-open UTC interval for a product TradingDate.

    ``event_session_dates`` records which exchange-local event dates may label
    timestamps in this interval. This explicitly represents sessions crossing
    midnight without requiring consumers to infer a local date from UTC.
    """

    trading_date: date
    session_date: date
    event_session_dates: tuple[date, ...]
    start_at_utc: datetime
    end_at_utc: datetime
    session_id: str

    def __post_init__(self) -> None:
        if type(self.event_session_dates) not in (tuple, list):
            raise MarketSessionContractError("MARKET_SESSION_SCHEDULE_INVALID")
        dates = tuple(self.event_session_dates)
        if (
            not _date(self.trading_date)
            or not _date(self.session_date)
            or not dates
            or len(dates) > _MAX_EVENT_SESSION_DATES
            or any(not _date(item) for item in dates)
            or tuple(sorted(set(dates))) != dates
            or self.session_date not in dates
            or not _utc_datetime(self.start_at_utc)
            or not _utc_datetime(self.end_at_utc)
            or self.start_at_utc >= self.end_at_utc
            or not _text(self.session_id)
        ):
            raise MarketSessionContractError("MARKET_SESSION_SCHEDULE_INVALID")
        object.__setattr__(self, "event_session_dates", dates)


@dataclass(frozen=True)
class MarketSessionCalendar:
    """A bounded, explicit schedule for one exact neutral instrument/product."""

    instrument: MarketInstrumentKey
    product: FuturesProductKey
    trading_dates: tuple[date, ...]
    windows: tuple[MarketSessionWindow, ...]
    calendar_ref: str
    calendar_digest: str
    complete: bool

    def __post_init__(self) -> None:
        if type(self.trading_dates) not in (tuple, list) or type(self.windows) not in (
            tuple,
            list,
        ):
            raise MarketSessionContractError("MARKET_SESSION_SCHEDULE_INVALID")
        days = tuple(self.trading_dates)
        windows = tuple(self.windows)
        if (
            type(self.instrument) is not MarketInstrumentKey
            or type(self.product) is not FuturesProductKey
            or self.instrument.venue != self.product.venue
            or len(days) > _MAX_SESSION_DAYS
            or any(not _date(item) for item in days)
            or tuple(sorted(set(days))) != days
            or len(windows) > _MAX_SESSION_WINDOWS
            or any(type(item) is not MarketSessionWindow for item in windows)
            or not _calendar_identity(self.calendar_ref, self.calendar_digest)
            or type(self.complete) is not bool
        ):
            raise MarketSessionContractError("MARKET_SESSION_SCHEDULE_INVALID")
        if any(window.trading_date not in days for window in windows):
            raise MarketSessionContractError("MARKET_SESSION_SCHEDULE_INVALID")
        ordered = tuple(sorted(windows, key=lambda item: item.start_at_utc))
        if ordered != windows or any(
            current.start_at_utc < previous.end_at_utc
            for previous, current in zip(windows, windows[1:])
        ):
            raise MarketSessionContractError("MARKET_SESSION_SCHEDULE_INVALID")
        if self.complete and (
            not days
            or any(not any(window.trading_date == day for window in windows) for day in days)
        ):
            raise MarketSessionContractError("MARKET_SESSION_SCHEDULE_INVALID")
        object.__setattr__(self, "trading_dates", days)
        object.__setattr__(self, "windows", windows)


@dataclass(frozen=True)
class MarketSessionResolution:
    """Neutral result of resolving one event against one session calendar."""

    status: MarketSessionResolutionStatus
    instrument: MarketInstrumentKey
    product: FuturesProductKey
    trading_date: Optional[date]
    session_date: Optional[date]
    event_session_date: Optional[date]
    event_time_utc: Optional[datetime]
    session_id: Optional[str]
    segment_kind: MarketSessionSegmentKind
    calendar_ref: Optional[str]
    calendar_digest: Optional[str]
    source_clock_quality: MarketClockQuality
    receive_clock_quality: MarketClockQuality
    freshness_status: MarketFreshnessStatus
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.blockers) not in (tuple, list):
            raise MarketSessionContractError("MARKET_SESSION_RESOLUTION_INVALID")
        blockers = tuple(self.blockers)
        has_calendar = self.calendar_ref is not None or self.calendar_digest is not None
        if (
            type(self.status) is not MarketSessionResolutionStatus
            or type(self.instrument) is not MarketInstrumentKey
            or type(self.product) is not FuturesProductKey
            or self.instrument.venue != self.product.venue
            or (self.trading_date is not None and not _date(self.trading_date))
            or (self.session_date is not None and not _date(self.session_date))
            or (self.event_session_date is not None and not _date(self.event_session_date))
            or (self.event_time_utc is not None and not _utc_datetime(self.event_time_utc))
            or (self.session_id is not None and not _text(self.session_id))
            or type(self.segment_kind) is not MarketSessionSegmentKind
            or (has_calendar and not _calendar_identity(self.calendar_ref, self.calendar_digest))
            or type(self.source_clock_quality) is not MarketClockQuality
            or type(self.receive_clock_quality) is not MarketClockQuality
            or type(self.freshness_status) is not MarketFreshnessStatus
            or any(not _text(item) for item in blockers)
            or len(set(blockers)) != len(blockers)
        ):
            raise MarketSessionContractError("MARKET_SESSION_RESOLUTION_INVALID")

        if self.status is MarketSessionResolutionStatus.COMPLETE:
            if (
                self.trading_date is None
                or self.session_date is None
                or self.event_session_date is None
                or self.event_time_utc is None
                or not has_calendar
                or self.segment_kind is MarketSessionSegmentKind.UNKNOWN
                or self.source_clock_quality is not MarketClockQuality.VERIFIED
                or self.receive_clock_quality is not MarketClockQuality.VERIFIED
                or self.freshness_status is not MarketFreshnessStatus.FRESH
                or blockers
            ):
                raise MarketSessionContractError("MARKET_SESSION_RESOLUTION_INVALID")
            if self.segment_kind is MarketSessionSegmentKind.CONTINUOUS and self.session_id is None:
                raise MarketSessionContractError("MARKET_SESSION_RESOLUTION_INVALID")
            if self.segment_kind is not MarketSessionSegmentKind.CONTINUOUS and self.session_id is not None:
                raise MarketSessionContractError("MARKET_SESSION_RESOLUTION_INVALID")
        else:
            if self.segment_kind is not MarketSessionSegmentKind.UNKNOWN or not blockers:
                raise MarketSessionContractError("MARKET_SESSION_RESOLUTION_INVALID")
            if self.session_id is not None:
                raise MarketSessionContractError("MARKET_SESSION_RESOLUTION_INVALID")

        if self.freshness_status is MarketFreshnessStatus.FRESH and (
            self.source_clock_quality is not MarketClockQuality.VERIFIED
            or self.receive_clock_quality is not MarketClockQuality.VERIFIED
            or self.event_time_utc is None
        ):
            raise MarketSessionContractError("MARKET_SESSION_RESOLUTION_INVALID")
        object.__setattr__(self, "blockers", blockers)

    @property
    def clock_qualified(self) -> bool:
        """Whether the represented event has verified source and receive clocks."""

        return (
            self.source_clock_quality is MarketClockQuality.VERIFIED
            and self.receive_clock_quality is MarketClockQuality.VERIFIED
            and self.freshness_status is MarketFreshnessStatus.FRESH
            and self.event_time_utc is not None
        )


@runtime_checkable
class MarketSessionResolver(Protocol):
    """Provider-neutral resolver selected by the SDK for one route/instrument."""

    def resolve(
        self,
        event: MarketTickEvent,
        calendar: MarketSessionCalendar,
    ) -> MarketSessionResolution:
        """Resolve an authenticated market event against a neutral calendar."""


class MarketSessionProviderFactory(Protocol):
    """Construct one provider-owned resolver for a selected SDK route."""

    def __call__(
        self,
        route: SelectedMarketSessionRoute,
        /,
    ) -> MarketSessionResolver:
        ...


@runtime_checkable
class MarketSessionProviderRegistryPort(Protocol):
    """Minimal neutral registration port consumed by provider packages."""

    def register(
        self,
        exchange_name: str,
        factory: MarketSessionProviderFactory,
        /,
    ) -> None:
        """Register one factory under an exact SDK route key."""


__all__ = [
    "MarketSessionCalendar",
    "MarketSessionContractError",
    "MarketSessionProviderFactory",
    "MarketSessionProviderRegistryPort",
    "MarketSessionProviderRouteError",
    "MarketSessionResolution",
    "MarketSessionResolutionStatus",
    "MarketSessionResolver",
    "MarketSessionSegmentKind",
    "MarketSessionWindow",
    "SelectedMarketSessionRoute",
]
