"""Neutral, bounded contracts for fixed-duration historical market bars."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from bt_api_base.account_protocol import (
    _canonical_json_bytes,
    _check_decimal,
    _check_utc_timestamp,
    _require_exact_mapping,
)
from bt_api_base.market_protocol import MarketSubscriptionKey

MAX_MARKET_HISTORY_PAGE_BYTES = 512 * 1024
MAX_MARKET_HISTORY_BARS = 1000

_TIMEFRAME_PATTERN = re.compile(r"([1-9][0-9]{0,11})([smhdw])\Z", re.ASCII)
_TIMEFRAME_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_MAX_DATETIME_SPAN = datetime.max - datetime.min
_MAX_FIXED_TIMEFRAME_SECONDS = _MAX_DATETIME_SPAN.days * 86400 + _MAX_DATETIME_SPAN.seconds


def _fixed_timeframe_seconds(key: MarketSubscriptionKey) -> int:
    if type(key) is not MarketSubscriptionKey:
        raise TypeError("key must be a MarketSubscriptionKey")
    if key.channel != "bar":
        raise ValueError("historical requests require a bar subscription key")
    if key.timeframe is None:
        raise ValueError("bar subscription key must declare a fixed-duration timeframe")
    match = _TIMEFRAME_PATTERN.fullmatch(key.timeframe)
    if match is None:
        raise ValueError("timeframe must be a positive integer followed by s, m, h, d, or w")
    seconds = int(match.group(1)) * _TIMEFRAME_UNIT_SECONDS[match.group(2)]
    if seconds > _MAX_FIXED_TIMEFRAME_SECONDS:
        raise ValueError("timeframe exceeds the representable UTC timestamp range")
    return seconds


def _require_tuple(value: Any, field: str) -> tuple[Any, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    if len(value) > MAX_MARKET_HISTORY_BARS:
        raise ValueError(f"{field} exceeds the bar limit")
    return value


def _dict_array(value: Any, field: str) -> tuple[Any, ...]:
    if type(value) not in (list, tuple):
        raise TypeError(f"{field} must be an array")
    if len(value) > MAX_MARKET_HISTORY_BARS:
        raise ValueError(f"{field} exceeds the bar limit")
    return tuple(value)


def _time(value: str, field: str) -> datetime:
    return _check_utc_timestamp(value, field)[1]


@dataclass(frozen=True)
class MarketBar:
    """One closed OHLCV interval; decimal lexemes are preserved as strings."""

    open_time_utc: str
    close_time_utc: str
    open: str
    high: str
    low: str
    close: str
    volume: str
    open_interest: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "open_time_utc",
            "close_time_utc",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "open_interest",
        }
    )

    def __post_init__(self) -> None:
        opened = _time(self.open_time_utc, "open_time_utc")
        closed = _time(self.close_time_utc, "close_time_utc")
        if closed <= opened:
            raise ValueError("close_time_utc must follow open_time_utc")

        open_value = Decimal(_check_decimal(self.open, "open"))
        high_value = Decimal(_check_decimal(self.high, "high"))
        low_value = Decimal(_check_decimal(self.low, "low"))
        close_value = Decimal(_check_decimal(self.close, "close"))
        volume_value = Decimal(_check_decimal(self.volume, "volume"))
        open_interest_value = (
            None
            if self.open_interest is None
            else Decimal(_check_decimal(self.open_interest, "open_interest"))
        )

        if high_value < max(open_value, low_value, close_value):
            raise ValueError("high must be at least open, low, and close")
        if low_value > min(open_value, high_value, close_value):
            raise ValueError("low must be at most open, high, and close")
        if volume_value < 0:
            raise ValueError("volume must be nonnegative")
        if open_interest_value is not None and open_interest_value < 0:
            raise ValueError("open_interest must be nonnegative")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "open_time_utc": self.open_time_utc,
            "close_time_utc": self.close_time_utc,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "open_interest": self.open_interest,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> MarketBar:
        raw = _require_exact_mapping(mapping, cls._FIELDS, "market_bar")
        return cls(
            open_time_utc=raw["open_time_utc"],
            close_time_utc=raw["close_time_utc"],
            open=raw["open"],
            high=raw["high"],
            low=raw["low"],
            close=raw["close"],
            volume=raw["volume"],
            open_interest=raw["open_interest"],
        )


@dataclass(frozen=True)
class MarketHistoryRequest:
    """Inclusive-start, exclusive-end request for one explicit fixed bar duration."""

    key: MarketSubscriptionKey
    start_time_utc: str
    end_time_utc: str
    limit: int

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"key", "start_time_utc", "end_time_utc", "limit"}
    )

    def __post_init__(self) -> None:
        _fixed_timeframe_seconds(self.key)
        start = _time(self.start_time_utc, "start_time_utc")
        end = _time(self.end_time_utc, "end_time_utc")
        if start >= end:
            raise ValueError("start_time_utc must precede end_time_utc")
        if type(self.limit) is not int:
            raise TypeError("limit must be an integer")
        if not 1 <= self.limit <= MAX_MARKET_HISTORY_BARS:
            raise ValueError("limit must be between 1 and 1000")

    @property
    def bar_duration_seconds(self) -> int:
        """The exact fixed duration represented by the key timeframe."""
        return _fixed_timeframe_seconds(self.key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key.to_dict(),
            "start_time_utc": self.start_time_utc,
            "end_time_utc": self.end_time_utc,
            "limit": self.limit,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> MarketHistoryRequest:
        raw = _require_exact_mapping(mapping, cls._FIELDS, "market_history_request")
        return cls(
            key=MarketSubscriptionKey.from_dict(raw["key"]),
            start_time_utc=raw["start_time_utc"],
            end_time_utc=raw["end_time_utc"],
            limit=raw["limit"],
        )


@dataclass(frozen=True)
class MarketHistoryPage:
    """One bounded history page with explicit exhaustion or continuation semantics.

    ``complete`` means the provider exhausted the requested interval. It does
    not claim that every interval contains a bar; gaps can represent no trades.
    """

    request: MarketHistoryRequest
    bars: tuple[MarketBar, ...]
    complete: bool
    next_start_time_utc: str | None
    observed_at_utc: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"request", "bars", "complete", "next_start_time_utc", "observed_at_utc"}
    )

    def __post_init__(self) -> None:
        if type(self.request) is not MarketHistoryRequest:
            raise TypeError("request must be a MarketHistoryRequest")
        bars = _require_tuple(self.bars, "bars")
        if len(bars) > self.request.limit:
            raise ValueError("page contains more bars than the request limit")
        if any(type(bar) is not MarketBar for bar in bars):
            raise TypeError("bars entries must be MarketBar values")
        if type(self.complete) is not bool:
            raise TypeError("complete must be a bool")

        observed = _time(self.observed_at_utc, "observed_at_utc")
        request_start = _time(self.request.start_time_utc, "start_time_utc")
        request_end = _time(self.request.end_time_utc, "end_time_utc")
        if request_end > observed:
            raise ValueError("request end must not follow page observation time")

        previous_open: datetime | None = None
        previous_close: datetime | None = None
        for bar in bars:
            opened = _time(bar.open_time_utc, "open_time_utc")
            closed = _time(bar.close_time_utc, "close_time_utc")
            if opened < request_start:
                raise ValueError("bar opens before the requested interval")
            if closed > request_end:
                raise ValueError("bar closes after the requested interval")
            if closed > observed:
                raise ValueError("bar closes after page observation time")
            duration = closed - opened
            duration_seconds = duration.days * 86400 + duration.seconds
            if duration.microseconds != 0 or duration_seconds != self.request.bar_duration_seconds:
                raise ValueError("bar duration does not match the requested timeframe")
            if previous_open is not None and opened <= previous_open:
                raise ValueError("bars must be sorted by unique open time")
            if previous_close is not None and opened < previous_close:
                raise ValueError("bars must not overlap")
            previous_open = opened
            previous_close = closed

        if self.complete:
            if self.next_start_time_utc is not None:
                raise ValueError("complete pages must not carry a continuation")
        else:
            if not bars:
                raise ValueError("incomplete pages must contain at least one bar")
            if self.next_start_time_utc is None:
                raise ValueError("incomplete pages require a continuation")
            next_start = _time(self.next_start_time_utc, "next_start_time_utc")
            if not request_start < next_start < request_end:
                raise ValueError("continuation must advance within the requested interval")
            if next_start != previous_close:
                raise ValueError("continuation must equal the last bar close time")

        if len(_canonical_json_bytes(self.to_dict())) > MAX_MARKET_HISTORY_PAGE_BYTES:
            raise ValueError("serialized page exceeds the byte limit")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "bars": [bar.to_dict() for bar in self.bars],
            "complete": self.complete,
            "next_start_time_utc": self.next_start_time_utc,
            "observed_at_utc": self.observed_at_utc,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> MarketHistoryPage:
        raw = _require_exact_mapping(mapping, cls._FIELDS, "market_history_page")
        bars = tuple(MarketBar.from_dict(item) for item in _dict_array(raw["bars"], "bars"))
        continuation = raw["next_start_time_utc"]
        return cls(
            request=MarketHistoryRequest.from_dict(raw["request"]),
            bars=bars,
            complete=raw["complete"],
            next_start_time_utc=continuation,
            observed_at_utc=raw["observed_at_utc"],
        )


__all__ = [
    "MAX_MARKET_HISTORY_BARS",
    "MAX_MARKET_HISTORY_PAGE_BYTES",
    "MarketBar",
    "MarketHistoryPage",
    "MarketHistoryRequest",
]
