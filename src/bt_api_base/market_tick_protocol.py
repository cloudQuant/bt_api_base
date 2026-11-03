"""Provider-neutral tick facts and explicit data-clock qualification."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Optional

from bt_api_base.market_protocol import MarketInstrumentKey, MarketSourceDescriptor

MARKET_TICK_SCHEMA = "sdk.market.tick"
MARKET_TICK_SCHEMA_VERSION = 2


class MarketTickContractError(ValueError):
    """Finite, value-free failure while validating a market tick contract."""

    _CODES = frozenset(
        {
            "MARKET_TICK_FIELD_SET_INVALID",
            "MARKET_TICK_VALUE_INVALID",
            "MARKET_TICK_INSTRUMENT_INVALID",
            "MARKET_TICK_CLOCK_INVALID",
            "MARKET_TICK_SOURCE_BINDING_MISMATCH",
            "MARKET_TICK_CURSOR_INVALID",
            "MARKET_TICK_FRESHNESS_INVALID",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in self._CODES else "MARKET_TICK_VALUE_INVALID"
        super().__init__(self.code)


class MarketClockQuality(str, Enum):
    """Qualification of a clock observation, separate from clock identity."""

    UNKNOWN = "unknown"
    VERIFIED = "verified"


class MarketFreshnessStatus(str, Enum):
    """Freshness result; identity and timestamps alone never imply FRESH."""

    UNAVAILABLE = "unavailable"
    FRESH = "fresh"
    STALE = "stale"


# Exact ``str`` values that already passed ``_text``. ``_text`` is a pure
# function of the value (``field`` is unused), so a remembered value passes
# again with the same result. Stream-constant identifiers (sources, clock ids,
# quality labels) hit it on every tick. Bounded: cleared when full.
_TEXT_OK: set[str] = set()
_MEMO_LIMIT = 4096


def _text(value: Any, field: str, *, optional: bool = False) -> Optional[str]:
    if value is None and optional:
        return None
    if type(value) is str and value in _TEXT_OK:
        return value
    _checked_text(value)
    if len(_TEXT_OK) >= _MEMO_LIMIT:
        _TEXT_OK.clear()
    _TEXT_OK.add(value)
    return value


def _checked_text(value: Any) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise MarketTickContractError("MARKET_TICK_VALUE_INVALID")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise MarketTickContractError("MARKET_TICK_VALUE_INVALID") from exc
    if len(encoded) > 4096 or not value.isprintable():
        raise MarketTickContractError("MARKET_TICK_VALUE_INVALID")
    return value


def _utc_text(value: Any, field: str, *, optional: bool = False) -> Optional[str]:
    # Per-tick timestamps are unique: validated without the ``_text`` memo.
    if value is None and optional:
        return None
    text = _checked_text(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MarketTickContractError("MARKET_TICK_CLOCK_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MarketTickContractError("MARKET_TICK_CLOCK_INVALID")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


# Exact ``str`` input -> normalized date text, for inputs ``_date_text``
# accepted (a pure function of the value). Trading dates repeat for a session.
_DATE_TEXT: dict[str, str] = {}


def _date_text(value: Any, field: str) -> Optional[str]:
    if type(value) is str:
        known = _DATE_TEXT.get(value)
        if known is not None:
            return known
    text = _text(value, field, optional=True)
    if text is None:
        return None
    try:
        result = date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise MarketTickContractError("MARKET_TICK_VALUE_INVALID") from exc
    if len(_DATE_TEXT) >= _MEMO_LIMIT:
        _DATE_TEXT.clear()
    _DATE_TEXT[text] = result
    return result


def _number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise MarketTickContractError("MARKET_TICK_VALUE_INVALID")
    result = float(value)
    if not math.isfinite(result):
        raise MarketTickContractError("MARKET_TICK_VALUE_INVALID")
    return result


def _nonnegative_clock_error(value: Any) -> Optional[float]:
    result = _number(value)
    if result is not None and result < 0.0:
        raise MarketTickContractError("MARKET_TICK_CLOCK_INVALID")
    return result


def _nonnegative_int(value: Any, *, optional: bool = False) -> Optional[int]:
    if value is None and optional:
        return None
    if type(value) is not int or value < 0:
        raise MarketTickContractError("MARKET_TICK_VALUE_INVALID")
    return value


def _enum(value: Any, enum_type: type[Enum], code: str) -> Enum:
    if type(value) is enum_type:
        return value
    if type(value) is str:
        # The same exact-value lookup ``enum_type(value)`` makes (these enums
        # define no aliases or ``_missing_``).
        member = _ENUM_BY_VALUE[enum_type].get(value)
        if member is not None:
            return member
    raise MarketTickContractError(code)


_ENUM_BY_VALUE: dict[type, dict[str, Enum]] = {
    enum_type: {member.value: member for member in enum_type}
    for enum_type in (MarketClockQuality, MarketFreshnessStatus)
}


@dataclass(frozen=True)
class MarketEventCursor:
    """Authenticated consumer cursor for one market stream epoch."""

    stream_id: str
    epoch: str
    sequence: int

    def __post_init__(self) -> None:
        _text(self.stream_id, "stream_id")
        _text(self.epoch, "epoch")
        if type(self.sequence) is not int or self.sequence <= 0:
            raise MarketTickContractError("MARKET_TICK_CURSOR_INVALID")


@dataclass(frozen=True)
class MarketTickPayload:
    """Neutral quote facts projected by a provider adapter before Hub binding.

    This payload is data, not an authenticated event. The consuming SDK must
    bind it to the authenticated source descriptor and wire cursor before it
    can be passed to Backtrader. Schema v2 allows a missing quality rule as
    ``None`` for observation only; it can never be execution eligible. Valid
    schema v1 mappings remain readable and require a non-empty rule reference.
    """

    instrument: MarketInstrumentKey
    last_price: Optional[float]
    bid_price: Optional[float]
    ask_price: Optional[float]
    bid_size: Optional[float]
    ask_size: Optional[float]
    lower_limit: Optional[float]
    upper_limit: Optional[float]
    turnover: Optional[float]
    open_interest: Optional[float]
    delta_volume: Optional[float]
    cumulative_volume: Optional[float]
    volume_complete: bool
    volume_quality: str
    continuity_status: str
    trading_date: Optional[str]
    event_session_date: Optional[str]
    provider_event_time_utc: Optional[str]
    event_time_provenance: str
    received_at_utc: Optional[str]
    received_monotonic_ns: Optional[int]
    provider_source: str
    quality_contract_ref: Optional[str]
    provider_connection_generation: int
    provider_sequence: int
    provider_subscription_epoch: int
    clock_domain_id: str
    clock_source_session_id: str
    clock_source: str
    source_clock_quality: MarketClockQuality = MarketClockQuality.UNKNOWN
    receive_clock_quality: MarketClockQuality = MarketClockQuality.UNKNOWN
    source_clock_error_ms: Optional[float] = None
    receive_clock_error_ms: Optional[float] = None
    freshness_status: MarketFreshnessStatus = MarketFreshnessStatus.UNAVAILABLE
    freshness_reason_codes: tuple[str, ...] = (
        "GENERIC_EVENT_TIME_NOT_BOUND",
        "SOURCE_CLOCK_CALIBRATION_NOT_PROVIDED",
    )
    execution_eligible: bool = False
    quality_flags: tuple[str, ...] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "schema_version",
            "instrument",
            "last_price",
            "bid_price",
            "ask_price",
            "bid_size",
            "ask_size",
            "lower_limit",
            "upper_limit",
            "turnover",
            "open_interest",
            "delta_volume",
            "cumulative_volume",
            "volume_complete",
            "volume_quality",
            "continuity_status",
            "trading_date",
            "event_session_date",
            "provider_event_time_utc",
            "event_time_provenance",
            "received_at_utc",
            "received_monotonic_ns",
            "provider_source",
            "quality_contract_ref",
            "provider_connection_generation",
            "provider_sequence",
            "provider_subscription_epoch",
            "clock_domain_id",
            "clock_source_session_id",
            "clock_source",
            "source_clock_quality",
            "receive_clock_quality",
            "source_clock_error_ms",
            "receive_clock_error_ms",
            "freshness_status",
            "freshness_reason_codes",
            "execution_eligible",
            "quality_flags",
        }
    )

    def __post_init__(self) -> None:
        # Validation and normalization live in ``_normalize_tick_fields`` so
        # that ``from_dict`` applies exactly the same rules, in the same order.
        _normalize_tick_fields(self.__dict__)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "MarketTickPayload":
        kind = type(raw)
        if kind is dict or kind is MappingProxyType:
            # Plain mappings (including frozen wire payloads): the same field
            # set checks as below, made with C-level set operations.
            if raw.keys() != cls._FIELDS or set(map(type, raw)) != _STR_TYPE:
                raise MarketTickContractError("MARKET_TICK_FIELD_SET_INVALID")
        elif (
            not isinstance(raw, Mapping)
            or any(type(key) is not str for key in raw)
            or set(raw) != cls._FIELDS
        ):
            raise MarketTickContractError("MARKET_TICK_FIELD_SET_INVALID")
        if (
            type(raw.get("schema")) is not str
            or raw.get("schema") != MARKET_TICK_SCHEMA
            or type(raw.get("schema_version")) is not int
            or raw.get("schema_version") not in (1, MARKET_TICK_SCHEMA_VERSION)
            # A JSON array: a list, or the tuple a frozen wire envelope holds.
            or type(raw.get("freshness_reason_codes")) not in (list, tuple)
            or type(raw.get("quality_flags")) not in (list, tuple)
        ):
            raise MarketTickContractError("MARKET_TICK_VALUE_INVALID")
        # Schema v1 required a concrete rule reference; null is a v2 value.
        if raw["schema_version"] == 1 and raw["quality_contract_ref"] is None:
            raise MarketTickContractError("MARKET_TICK_VALUE_INVALID")
        instrument = _instrument_from_dict(raw["instrument"])
        if cls is not MarketTickPayload or not (kind is dict or kind is MappingProxyType):
            # Subclasses and other Mapping types keep the constructor path.
            return cls(
                instrument=instrument,
                **{name: raw[name] for name in _TICK_FIELD_NAMES if name != "instrument"},
            )
        # Exactly ``cls(instrument=instrument, <field>=raw[<field>], ...)``:
        # every field is supplied, and the constructor's only logic is
        # ``__post_init__`` -> ``_normalize_tick_fields`` on these values.
        values = dict(raw)
        del values["schema"]
        del values["schema_version"]
        values["instrument"] = instrument
        _normalize_tick_fields(values)
        payload = object.__new__(MarketTickPayload)
        payload.__dict__.update(values)
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MARKET_TICK_SCHEMA,
            "schema_version": MARKET_TICK_SCHEMA_VERSION,
            "instrument": self.instrument.to_dict(),
            "last_price": self.last_price,
            "bid_price": self.bid_price,
            "ask_price": self.ask_price,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "lower_limit": self.lower_limit,
            "upper_limit": self.upper_limit,
            "turnover": self.turnover,
            "open_interest": self.open_interest,
            "delta_volume": self.delta_volume,
            "cumulative_volume": self.cumulative_volume,
            "volume_complete": self.volume_complete,
            "volume_quality": self.volume_quality,
            "continuity_status": self.continuity_status,
            "trading_date": self.trading_date,
            "event_session_date": self.event_session_date,
            "provider_event_time_utc": self.provider_event_time_utc,
            "event_time_provenance": self.event_time_provenance,
            "received_at_utc": self.received_at_utc,
            "received_monotonic_ns": self.received_monotonic_ns,
            "provider_source": self.provider_source,
            "quality_contract_ref": self.quality_contract_ref,
            "provider_connection_generation": self.provider_connection_generation,
            "provider_sequence": self.provider_sequence,
            "provider_subscription_epoch": self.provider_subscription_epoch,
            "clock_domain_id": self.clock_domain_id,
            "clock_source_session_id": self.clock_source_session_id,
            "clock_source": self.clock_source,
            "source_clock_quality": self.source_clock_quality.value,
            "receive_clock_quality": self.receive_clock_quality.value,
            "source_clock_error_ms": self.source_clock_error_ms,
            "receive_clock_error_ms": self.receive_clock_error_ms,
            "freshness_status": self.freshness_status.value,
            "freshness_reason_codes": list(self.freshness_reason_codes),
            "execution_eligible": self.execution_eligible,
            "quality_flags": list(self.quality_flags),
        }


_STR_TYPE = frozenset({str})
_NUMBER_FIELDS = (
    "last_price",
    "bid_price",
    "ask_price",
    "bid_size",
    "ask_size",
    "lower_limit",
    "upper_limit",
    "turnover",
    "open_interest",
    "delta_volume",
    "cumulative_volume",
)
_REQUIRED_TEXT_FIELDS = (
    "volume_quality",
    "continuity_status",
    "provider_source",
    "clock_domain_id",
    "clock_source_session_id",
    "clock_source",
)
_PROVENANCE_VALUES = frozenset({"provider_reported", "unavailable"})
_TICK_FIELD_NAMES = tuple(field.name for field in fields(MarketTickPayload))


def _normalize_tick_fields(v: dict[str, Any]) -> None:
    """Validate and normalize ``MarketTickPayload`` field values in place.

    The single implementation of the payload contract: ``__post_init__``
    applies it to the instance dict and ``from_dict`` to the decoded values.
    Checks run in a fixed order, so the first failing rule decides the code.
    """

    if type(v["instrument"]) is not MarketInstrumentKey:
        raise MarketTickContractError("MARKET_TICK_INSTRUMENT_INVALID")
    for name in _NUMBER_FIELDS:
        value = v[name]
        if value is not None:
            if type(value) is float:
                # ``_number`` of a float is the float itself when finite;
                # ``x - x`` is 0.0 exactly for finite x and NaN otherwise.
                if value - value != 0.0:
                    raise MarketTickContractError("MARKET_TICK_VALUE_INVALID")
            else:
                v[name] = _number(value)
    v["source_clock_error_ms"] = _nonnegative_clock_error(v["source_clock_error_ms"])
    v["receive_clock_error_ms"] = _nonnegative_clock_error(v["receive_clock_error_ms"])
    for name in _REQUIRED_TEXT_FIELDS:
        _text(v[name], name)
    _text(v["quality_contract_ref"], "quality_contract_ref", optional=True)
    v["trading_date"] = _date_text(v["trading_date"], "trading_date")
    v["event_session_date"] = _date_text(v["event_session_date"], "event_session_date")
    provider_event_time_utc = _utc_text(
        v["provider_event_time_utc"], "provider_event_time_utc", optional=True
    )
    v["provider_event_time_utc"] = provider_event_time_utc
    provenance = v["event_time_provenance"]
    if type(provenance) is not str or provenance not in _PROVENANCE_VALUES:
        raise MarketTickContractError("MARKET_TICK_CLOCK_INVALID")
    if (provider_event_time_utc is None) != (provenance == "unavailable"):
        raise MarketTickContractError("MARKET_TICK_CLOCK_INVALID")
    received_at_utc = _utc_text(v["received_at_utc"], "received_at_utc", optional=True)
    v["received_at_utc"] = received_at_utc
    received_monotonic_ns = _nonnegative_int(v["received_monotonic_ns"], optional=True)
    v["received_monotonic_ns"] = received_monotonic_ns
    for name in ("provider_connection_generation", "provider_sequence"):
        if _nonnegative_int(v[name]) == 0:
            raise MarketTickContractError("MARKET_TICK_VALUE_INVALID")
    if _nonnegative_int(v["provider_subscription_epoch"]) == 0:
        raise MarketTickContractError("MARKET_TICK_VALUE_INVALID")
    if type(v["volume_complete"]) is not bool or type(v["execution_eligible"]) is not bool:
        raise MarketTickContractError("MARKET_TICK_VALUE_INVALID")
    source_quality = _enum(
        v["source_clock_quality"], MarketClockQuality, "MARKET_TICK_CLOCK_INVALID"
    )
    v["source_clock_quality"] = source_quality
    receive_quality = _enum(
        v["receive_clock_quality"], MarketClockQuality, "MARKET_TICK_CLOCK_INVALID"
    )
    v["receive_clock_quality"] = receive_quality
    status = _enum(v["freshness_status"], MarketFreshnessStatus, "MARKET_TICK_FRESHNESS_INVALID")
    v["freshness_status"] = status
    raw_reasons = v["freshness_reason_codes"]
    if type(raw_reasons) not in (tuple, list):
        raise MarketTickContractError("MARKET_TICK_FRESHNESS_INVALID")
    reasons = tuple(raw_reasons)
    if any(type(reason) is not str or not reason for reason in reasons):
        raise MarketTickContractError("MARKET_TICK_FRESHNESS_INVALID")
    if status is MarketFreshnessStatus.UNAVAILABLE and not reasons:
        raise MarketTickContractError("MARKET_TICK_FRESHNESS_INVALID")
    if status is not MarketFreshnessStatus.UNAVAILABLE:
        if (
            source_quality is not MarketClockQuality.VERIFIED
            or receive_quality is not MarketClockQuality.VERIFIED
            or provider_event_time_utc is None
            or received_at_utc is None
            or received_monotonic_ns is None
            or v["source_clock_error_ms"] is None
            or v["receive_clock_error_ms"] is None
        ):
            raise MarketTickContractError("MARKET_TICK_FRESHNESS_INVALID")
    if v["execution_eligible"] and (
        v["quality_contract_ref"] is None
        or status is not MarketFreshnessStatus.FRESH
        or source_quality is not MarketClockQuality.VERIFIED
        or receive_quality is not MarketClockQuality.VERIFIED
    ):
        raise MarketTickContractError("MARKET_TICK_FRESHNESS_INVALID")
    v["freshness_reason_codes"] = reasons
    raw_flags = v["quality_flags"]
    if type(raw_flags) not in (tuple, list):
        raise MarketTickContractError("MARKET_TICK_VALUE_INVALID")
    flags = tuple(raw_flags)
    if any(type(flag) is not str or not flag for flag in flags):
        raise MarketTickContractError("MARKET_TICK_VALUE_INVALID")
    v["quality_flags"] = flags


class _InstrumentCache:
    """Last instrument mapping accepted by ``MarketTickPayload.from_dict``."""

    __slots__ = ("last",)

    def __init__(self) -> None:
        self.last: tuple[dict[str, str], MarketInstrumentKey] | None = None


_INSTRUMENT_CACHE = _InstrumentCache()


def _instrument_from_dict(raw: Any) -> MarketInstrumentKey:
    """``MarketInstrumentKey.from_dict`` reusing the last equal parsed key.

    The shortcut applies only to a plain mapping whose keys and values are
    all exact ``str``: such a mapping equal to the last accepted one has the
    same items, so parsing it again yields an equal key. Anything else is
    parsed (and rejected) by ``from_dict`` itself.
    """

    kind = type(raw)
    if kind is dict or kind is MappingProxyType:
        cached = _INSTRUMENT_CACHE.last
        plain = (
            set(map(type, raw)) == _STR_TYPE and set(map(type, raw.values())) == _STR_TYPE
        )
        if plain and cached is not None and raw == cached[0]:
            return cached[1]
        key = MarketInstrumentKey.from_dict(raw)
        if plain:
            _INSTRUMENT_CACHE.last = (dict(raw), key)
        return key
    return MarketInstrumentKey.from_dict(raw)


@dataclass(frozen=True)
class DataClockBinding:
    """Bind provider clock observations to one authenticated source/cursor."""

    source: MarketSourceDescriptor
    cursor: MarketEventCursor
    provider_event_time_utc: Optional[str]
    received_at_utc: Optional[str]
    received_monotonic_ns: Optional[int]
    source_clock_quality: MarketClockQuality
    receive_clock_quality: MarketClockQuality
    source_clock_error_ms: Optional[float]
    receive_clock_error_ms: Optional[float]
    freshness_status: MarketFreshnessStatus
    freshness_reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.source) is not MarketSourceDescriptor:
            raise MarketTickContractError("MARKET_TICK_SOURCE_BINDING_MISMATCH")
        if type(self.cursor) is not MarketEventCursor:
            raise MarketTickContractError("MARKET_TICK_CURSOR_INVALID")
        if self.cursor.stream_id != self.source.stream_id or self.cursor.epoch != self.source.epoch:
            raise MarketTickContractError("MARKET_TICK_SOURCE_BINDING_MISMATCH")
        object.__setattr__(
            self,
            "provider_event_time_utc",
            _utc_text(self.provider_event_time_utc, "provider_event_time_utc", optional=True),
        )
        object.__setattr__(
            self, "received_at_utc", _utc_text(self.received_at_utc, "received_at_utc", optional=True)
        )
        object.__setattr__(
            self,
            "received_monotonic_ns",
            _nonnegative_int(self.received_monotonic_ns, optional=True),
        )
        for name in ("source_clock_quality", "receive_clock_quality"):
            object.__setattr__(
                self,
                name,
                _enum(getattr(self, name), MarketClockQuality, "MARKET_TICK_CLOCK_INVALID"),
            )
        for name in ("source_clock_error_ms", "receive_clock_error_ms"):
            object.__setattr__(self, name, _nonnegative_clock_error(getattr(self, name)))
        status = _enum(
            self.freshness_status,
            MarketFreshnessStatus,
            "MARKET_TICK_FRESHNESS_INVALID",
        )
        object.__setattr__(self, "freshness_status", status)
        if type(self.freshness_reason_codes) not in (tuple, list):
            raise MarketTickContractError("MARKET_TICK_FRESHNESS_INVALID")
        reasons = tuple(self.freshness_reason_codes)
        if any(type(reason) is not str or not reason for reason in reasons):
            raise MarketTickContractError("MARKET_TICK_FRESHNESS_INVALID")
        if status is MarketFreshnessStatus.UNAVAILABLE and not reasons:
            raise MarketTickContractError("MARKET_TICK_FRESHNESS_INVALID")
        if status is not MarketFreshnessStatus.UNAVAILABLE and (
            self.source_clock_quality is not MarketClockQuality.VERIFIED
            or self.receive_clock_quality is not MarketClockQuality.VERIFIED
            or self.provider_event_time_utc is None
            or self.received_at_utc is None
            or self.received_monotonic_ns is None
            or self.source_clock_error_ms is None
            or self.receive_clock_error_ms is None
        ):
            raise MarketTickContractError("MARKET_TICK_FRESHNESS_INVALID")
        object.__setattr__(self, "freshness_reason_codes", reasons)


@dataclass(frozen=True)
class MarketTickEvent:
    """A neutral tick payload bound to one source descriptor and wire cursor."""

    source: MarketSourceDescriptor
    cursor: MarketEventCursor
    data: MarketTickPayload
    clock: DataClockBinding

    def __post_init__(self) -> None:
        if type(self.source) is not MarketSourceDescriptor or type(self.data) is not MarketTickPayload:
            raise MarketTickContractError("MARKET_TICK_SOURCE_BINDING_MISMATCH")
        if type(self.cursor) is not MarketEventCursor or type(self.clock) is not DataClockBinding:
            raise MarketTickContractError("MARKET_TICK_CURSOR_INVALID")
        if (
            self.source.key.instrument != self.data.instrument
            or self.source.connection_generation != self.data.provider_connection_generation
            or self.source.source != self.data.provider_source
            or self.source.clock_domain_id != self.data.clock_domain_id
            or self.source.clock_source_session_id != self.data.clock_source_session_id
            or self.source.clock_source != self.data.clock_source
            or self.clock.source != self.source
            or self.clock.cursor != self.cursor
            or self.clock.provider_event_time_utc != self.data.provider_event_time_utc
            or self.clock.received_at_utc != self.data.received_at_utc
            or self.clock.received_monotonic_ns != self.data.received_monotonic_ns
            or self.clock.source_clock_quality != self.data.source_clock_quality
            or self.clock.receive_clock_quality != self.data.receive_clock_quality
            or self.clock.source_clock_error_ms != self.data.source_clock_error_ms
            or self.clock.receive_clock_error_ms != self.data.receive_clock_error_ms
            or self.clock.freshness_status != self.data.freshness_status
            or self.clock.freshness_reason_codes != self.data.freshness_reason_codes
        ):
            raise MarketTickContractError("MARKET_TICK_SOURCE_BINDING_MISMATCH")
        if self.cursor.stream_id != self.source.stream_id or self.cursor.epoch != self.source.epoch:
            raise MarketTickContractError("MARKET_TICK_SOURCE_BINDING_MISMATCH")

    @property
    def key(self):
        return self.source.key

    @property
    def freshness_available(self) -> bool:
        return self.clock.freshness_status is MarketFreshnessStatus.FRESH

    @property
    def data_clock_qualified(self) -> bool:
        return (
            self.clock.source_clock_quality is MarketClockQuality.VERIFIED
            and self.clock.receive_clock_quality is MarketClockQuality.VERIFIED
            and self.clock.freshness_status is MarketFreshnessStatus.FRESH
        )


def market_tick_payload_from_wire(data: Any) -> "MarketTickPayload":
    """``MarketTickPayload`` from a decoded wire envelope's (frozen) ``data``.

    Decoded envelope payloads are recursively frozen (``MappingProxyType`` and
    ``tuple``). This is exactly ``MarketTickPayload.from_dict`` applied to the
    plain copy of ``data``: ``from_dict`` reads only top-level fields and the
    ``instrument`` mapping, and requires the two array fields to be lists, so
    only those two arrays are converted instead of thawing the whole tree.
    Every validation of ``from_dict`` runs unchanged.
    """

    if not isinstance(data, Mapping):
        raise MarketTickContractError("MARKET_TICK_FIELD_SET_INVALID")
    raw = dict(data)
    for name in ("freshness_reason_codes", "quality_flags"):
        value = raw.get(name)
        if type(value) is tuple:
            raw[name] = [_plain_wire(item) for item in value]
    instrument = raw.get("instrument")
    if isinstance(instrument, Mapping) and type(instrument) is not dict:
        raw["instrument"] = {key: _plain_wire(item) for key, item in instrument.items()}
    return MarketTickPayload.from_dict(raw)


def _plain_wire(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_wire(item) for key, item in value.items()}
    if type(value) in (tuple, list):
        return [_plain_wire(item) for item in value]
    return value


def bind_market_tick_event(
    data: MarketTickPayload, source: MarketSourceDescriptor, cursor: MarketEventCursor
) -> MarketTickEvent:
    """Bind a provider-neutral payload only after the SDK authenticates source/cursor."""

    if type(data) is not MarketTickPayload or type(source) is not MarketSourceDescriptor:
        raise MarketTickContractError("MARKET_TICK_SOURCE_BINDING_MISMATCH")
    if type(cursor) is not MarketEventCursor:
        raise MarketTickContractError("MARKET_TICK_CURSOR_INVALID")
    if (
        source.key.instrument != data.instrument
        or source.connection_generation != data.provider_connection_generation
        or source.source != data.provider_source
        or source.clock_domain_id != data.clock_domain_id
        or source.clock_source_session_id != data.clock_source_session_id
        or source.clock_source != data.clock_source
        or cursor.stream_id != source.stream_id
        or cursor.epoch != source.epoch
    ):
        raise MarketTickContractError("MARKET_TICK_SOURCE_BINDING_MISMATCH")
    # Every ``DataClockBinding``/``MarketTickEvent`` check is already decided
    # here: the types and source/cursor/fact bindings are checked above, and
    # the clock fields are copied from an exact ``MarketTickPayload`` whose
    # constructor validated them with the same rules (the normalizations are
    # idempotent on its normalized values). Re-running those constructors
    # would repeat the work with the same result, so the bound objects are
    # assembled directly. ``tests/test_market_tick_hot_path_equivalence.py``
    # proves equality with the constructor-built objects.
    clock = object.__new__(DataClockBinding)
    clock.__dict__.update(
        source=source,
        cursor=cursor,
        provider_event_time_utc=data.provider_event_time_utc,
        received_at_utc=data.received_at_utc,
        received_monotonic_ns=data.received_monotonic_ns,
        source_clock_quality=data.source_clock_quality,
        receive_clock_quality=data.receive_clock_quality,
        source_clock_error_ms=data.source_clock_error_ms,
        receive_clock_error_ms=data.receive_clock_error_ms,
        freshness_status=data.freshness_status,
        freshness_reason_codes=data.freshness_reason_codes,
    )
    event = object.__new__(MarketTickEvent)
    event.__dict__.update(source=source, cursor=cursor, data=data, clock=clock)
    return event


__all__ = [
    "DataClockBinding",
    "MARKET_TICK_SCHEMA",
    "MARKET_TICK_SCHEMA_VERSION",
    "MarketClockQuality",
    "MarketEventCursor",
    "MarketFreshnessStatus",
    "MarketTickContractError",
    "MarketTickEvent",
    "MarketTickPayload",
    "bind_market_tick_event",
    "market_tick_payload_from_wire",
]
