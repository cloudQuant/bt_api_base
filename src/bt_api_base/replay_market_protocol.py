"""Explicit replay-only market tick facts, separate from live market events."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, ClassVar, Optional, Protocol, runtime_checkable

from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import MAX_REFERENCE_BYTES

REPLAY_MARKET_TICK_SCHEMA = "sdk.replay.market.tick"
REPLAY_MARKET_TICK_SCHEMA_VERSION = 1
REPLAY_MARKET_TICK_SCHEMA_VERSION_TEXT = "sdk.replay.market.tick.v1"


class ReplayMarketContractError(ValueError):
    """Finite, value-free error raised while validating replay market contracts."""

    _CODES = frozenset(
        {
            "REPLAY_MARKET_FIELD_SET_INVALID",
            "REPLAY_MARKET_VALUE_INVALID",
            "REPLAY_MARKET_INSTRUMENT_INVALID",
            "REPLAY_MARKET_TIME_INVALID",
            "REPLAY_MARKET_SEQUENCE_INVALID",
            "REPLAY_MARKET_VOLUME_INVALID",
            "REPLAY_MARKET_PORT_INVALID",
            "REPLAY_MARKET_BINDING_MISMATCH",
            "REPLAY_MARKET_SEQUENCE_GAP",
            "REPLAY_MARKET_SYMBOL_MISMATCH",
            "REPLAY_MARKET_POLL_INVALID",
            "REPLAY_MARKET_EOF_WATERMARK_INVALID",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in self._CODES else "REPLAY_MARKET_VALUE_INVALID"
        super().__init__(self.code)


class ReplayMarketMode(str, Enum):
    """Non-live origin labels carried by replay records."""

    REPLAY = "replay"
    SYNTHETIC = "synthetic"


class ReplayVolumeSemantics(str, Enum):
    """Meaning of volume fields on one replay tick."""

    DELTA = "delta"
    CUMULATIVE = "cumulative"
    UNKNOWN = "unknown"


class ReplayMarketPollStatus(str, Enum):
    """One terminally unambiguous result from a finite replay source poll."""

    EVENT = "event"
    EOF = "eof"


def _text(value: Any, *, field: str) -> str:
    if type(value) is not str:
        raise ReplayMarketContractError("REPLAY_MARKET_VALUE_INVALID")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ReplayMarketContractError("REPLAY_MARKET_VALUE_INVALID") from exc
    if (
        not encoded
        or len(encoded) > MAX_REFERENCE_BYTES
        or value != value.strip()
        or not value.isprintable()
    ):
        raise ReplayMarketContractError("REPLAY_MARKET_VALUE_INVALID")
    return value


def _number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ReplayMarketContractError("REPLAY_MARKET_VALUE_INVALID")
    result = float(value)
    if not math.isfinite(result):
        raise ReplayMarketContractError("REPLAY_MARKET_VALUE_INVALID")
    return result


def _iso_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if type(value) is date:
        return value
    if type(value) is str:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ReplayMarketContractError("REPLAY_MARKET_VALUE_INVALID") from exc
    raise ReplayMarketContractError("REPLAY_MARKET_VALUE_INVALID")


def _require_exact_mapping(value: Any, fields: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ReplayMarketContractError("REPLAY_MARKET_FIELD_SET_INVALID")
    if set(value) != fields:
        raise ReplayMarketContractError("REPLAY_MARKET_FIELD_SET_INVALID")
    return value


@dataclass(frozen=True)
class ReplayMarketTickEvent:
    """Immutable replay input with no live receive-clock or authorization fields.

    ``source_ref``, ``replay_epoch`` and ``sequence`` describe only the replay
    source. They are not a provider source descriptor, a live generation,
    subscription epoch, ingress cursor, freshness proof, or execution grant.
    """

    mode: ReplayMarketMode
    source_ref: str
    replay_epoch: str
    instrument: MarketInstrumentKey
    event_time_utc: datetime
    sequence: int
    last_price: Optional[float] = None
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    lower_limit: Optional[float] = None
    upper_limit: Optional[float] = None
    delta_volume: Optional[float] = None
    cumulative_volume: Optional[float] = None
    volume_semantics: ReplayVolumeSemantics = ReplayVolumeSemantics.UNKNOWN
    turnover: Optional[float] = None
    open_interest: Optional[float] = None
    trading_day: Optional[date] = None
    event_session_date: Optional[date] = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "schema_version",
            "mode",
            "source_ref",
            "replay_epoch",
            "instrument",
            "event_time_utc",
            "sequence",
            "last_price",
            "bid_price",
            "ask_price",
            "bid_size",
            "ask_size",
            "lower_limit",
            "upper_limit",
            "delta_volume",
            "cumulative_volume",
            "volume_semantics",
            "turnover",
            "open_interest",
            "trading_day",
            "event_session_date",
        }
    )

    def __post_init__(self) -> None:
        mode = self.mode
        if type(mode) is str:
            try:
                mode = ReplayMarketMode(mode)
            except ValueError as exc:
                raise ReplayMarketContractError("REPLAY_MARKET_VALUE_INVALID") from exc
            object.__setattr__(self, "mode", mode)
        if type(mode) is not ReplayMarketMode:
            raise ReplayMarketContractError("REPLAY_MARKET_VALUE_INVALID")
        _text(self.source_ref, field="source_ref")
        _text(self.replay_epoch, field="replay_epoch")
        if type(self.instrument) is not MarketInstrumentKey:
            raise ReplayMarketContractError("REPLAY_MARKET_INSTRUMENT_INVALID")
        if (
            not isinstance(self.event_time_utc, datetime)
            or self.event_time_utc.tzinfo is None
            or self.event_time_utc.utcoffset() is None
        ):
            raise ReplayMarketContractError("REPLAY_MARKET_TIME_INVALID")
        object.__setattr__(self, "event_time_utc", self.event_time_utc.astimezone(timezone.utc))
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ReplayMarketContractError("REPLAY_MARKET_SEQUENCE_INVALID")
        semantics = self.volume_semantics
        if type(semantics) is str:
            try:
                semantics = ReplayVolumeSemantics(semantics)
            except ValueError as exc:
                raise ReplayMarketContractError("REPLAY_MARKET_VOLUME_INVALID") from exc
            object.__setattr__(self, "volume_semantics", semantics)
        if type(semantics) is not ReplayVolumeSemantics:
            raise ReplayMarketContractError("REPLAY_MARKET_VOLUME_INVALID")
        for field in (
            "last_price",
            "bid_price",
            "ask_price",
            "bid_size",
            "ask_size",
            "lower_limit",
            "upper_limit",
            "delta_volume",
            "cumulative_volume",
            "turnover",
            "open_interest",
        ):
            value = _number(getattr(self, field))
            if field in {"bid_size", "ask_size", "delta_volume", "cumulative_volume", "turnover", "open_interest"}:
                if value is not None and value < 0.0:
                    raise ReplayMarketContractError("REPLAY_MARKET_VALUE_INVALID")
            object.__setattr__(self, field, value)
        if semantics is ReplayVolumeSemantics.DELTA and self.delta_volume is None:
            raise ReplayMarketContractError("REPLAY_MARKET_VOLUME_INVALID")
        if semantics is ReplayVolumeSemantics.CUMULATIVE and self.cumulative_volume is None:
            raise ReplayMarketContractError("REPLAY_MARKET_VOLUME_INVALID")
        object.__setattr__(self, "trading_day", _iso_date(self.trading_day))
        object.__setattr__(self, "event_session_date", _iso_date(self.event_session_date))

    def to_dict(self) -> dict[str, Any]:
        """Return the exact JSON-ready replay wire representation."""
        return {
            "schema": REPLAY_MARKET_TICK_SCHEMA,
            "schema_version": REPLAY_MARKET_TICK_SCHEMA_VERSION,
            "mode": self.mode.value,
            "source_ref": self.source_ref,
            "replay_epoch": self.replay_epoch,
            "instrument": self.instrument.to_dict(),
            "event_time_utc": self.event_time_utc.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
            "sequence": self.sequence,
            "last_price": self.last_price,
            "bid_price": self.bid_price,
            "ask_price": self.ask_price,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "lower_limit": self.lower_limit,
            "upper_limit": self.upper_limit,
            "delta_volume": self.delta_volume,
            "cumulative_volume": self.cumulative_volume,
            "volume_semantics": self.volume_semantics.value,
            "turnover": self.turnover,
            "open_interest": self.open_interest,
            "trading_day": self.trading_day.isoformat() if self.trading_day else None,
            "event_session_date": (
                self.event_session_date.isoformat() if self.event_session_date else None
            ),
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> ReplayMarketTickEvent:
        """Load only the exact replay wire schema and field set."""
        raw = _require_exact_mapping(mapping, cls._FIELDS)
        if (
            raw["schema"] != REPLAY_MARKET_TICK_SCHEMA
            or type(raw["schema_version"]) is not int
            or raw["schema_version"] != REPLAY_MARKET_TICK_SCHEMA_VERSION
        ):
            raise ReplayMarketContractError("REPLAY_MARKET_FIELD_SET_INVALID")
        event_time = raw["event_time_utc"]
        if type(event_time) is not str:
            raise ReplayMarketContractError("REPLAY_MARKET_TIME_INVALID")
        try:
            parsed_time = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReplayMarketContractError("REPLAY_MARKET_TIME_INVALID") from exc
        return cls(
            mode=raw["mode"],
            source_ref=raw["source_ref"],
            replay_epoch=raw["replay_epoch"],
            instrument=MarketInstrumentKey.from_dict(raw["instrument"]),
            event_time_utc=parsed_time,
            sequence=raw["sequence"],
            last_price=raw["last_price"],
            bid_price=raw["bid_price"],
            ask_price=raw["ask_price"],
            bid_size=raw["bid_size"],
            ask_size=raw["ask_size"],
            lower_limit=raw["lower_limit"],
            upper_limit=raw["upper_limit"],
            delta_volume=raw["delta_volume"],
            cumulative_volume=raw["cumulative_volume"],
            volume_semantics=raw["volume_semantics"],
            turnover=raw["turnover"],
            open_interest=raw["open_interest"],
            trading_day=raw["trading_day"],
            event_session_date=raw["event_session_date"],
        )


@dataclass(frozen=True)
class ReplayMarketTickPollResult:
    """Atomic event-or-EOF result for a local replay tick source.

    EOF carries the source's terminal event-time bound. It is not a receive
    time, host observation, clock calibration, or freshness assertion.
    ``None`` is reserved for an empty replay source with no event-time facts.
    """

    status: ReplayMarketPollStatus
    event: Optional[ReplayMarketTickEvent] = None
    final_event_time_watermark_utc: Optional[datetime] = None

    def __post_init__(self) -> None:
        status = self.status
        if type(status) is str:
            try:
                status = ReplayMarketPollStatus(status)
            except ValueError as exc:
                raise ReplayMarketContractError("REPLAY_MARKET_POLL_INVALID") from exc
            object.__setattr__(self, "status", status)
        if type(status) is not ReplayMarketPollStatus:
            raise ReplayMarketContractError("REPLAY_MARKET_POLL_INVALID")
        if status is ReplayMarketPollStatus.EVENT:
            if (
                type(self.event) is not ReplayMarketTickEvent
                or self.final_event_time_watermark_utc is not None
            ):
                raise ReplayMarketContractError("REPLAY_MARKET_POLL_INVALID")
            return
        if self.event is not None:
            raise ReplayMarketContractError("REPLAY_MARKET_POLL_INVALID")
        watermark = self.final_event_time_watermark_utc
        if watermark is not None:
            if (
                not isinstance(watermark, datetime)
                or watermark.tzinfo is None
                or watermark.utcoffset() is None
            ):
                raise ReplayMarketContractError("REPLAY_MARKET_EOF_WATERMARK_INVALID")
            object.__setattr__(
                self,
                "final_event_time_watermark_utc",
                watermark.astimezone(timezone.utc),
            )


@runtime_checkable
class ReplayMarketTickPort(Protocol):
    """Finite local replay source; lifecycle never starts a live SDK client.

    The port must return ``EVENT`` for a tick and a sticky ``EOF`` result with
    its terminal event-time watermark when exhausted. These operations are
    distinct from Store lifecycle, subscribe, or live market methods.
    """

    @property
    def replay_mode(self) -> ReplayMarketMode:
        """Return the exact non-live source mode."""

    @property
    def replay_source_ref(self) -> str:
        """Return the source identity bound to every emitted event."""

    @property
    def replay_epoch(self) -> str:
        """Return the source epoch bound to every emitted event."""

    @property
    def instrument(self) -> MarketInstrumentKey:
        """Return the one instrument served by this port."""

    def start_replay(self, symbol: str) -> None:
        """Start only the finite local replay reader for the bound instrument."""

    def poll_replay_tick(self, symbol: str) -> ReplayMarketTickPollResult:
        """Return one event or the terminal EOF and final event-time bound."""

    def close_replay(self, symbol: str) -> None:
        """Close only the local replay reader; never connect to a live SDK."""


__all__ = [
    "REPLAY_MARKET_TICK_SCHEMA",
    "REPLAY_MARKET_TICK_SCHEMA_VERSION",
    "REPLAY_MARKET_TICK_SCHEMA_VERSION_TEXT",
    "ReplayMarketContractError",
    "ReplayMarketMode",
    "ReplayMarketPollStatus",
    "ReplayMarketTickEvent",
    "ReplayMarketTickPollResult",
    "ReplayMarketTickPort",
    "ReplayVolumeSemantics",
]
