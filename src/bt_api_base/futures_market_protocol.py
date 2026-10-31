"""Provider-neutral futures catalog and quote/depth snapshot contracts.

These DTOs contain canonical identities and normalized values only. Provider
native product classes, request identifiers, callback state, and native keys
belong in the selected SDK provider package. Provider event date/time fields
are preserved for audit; they are not receive timestamps or a freshness clock.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar

from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.query_protocol import QueryCompleteness
from bt_api_base.service_protocol import MAX_REFERENCE_BYTES

FUTURES_SESSION_FAMILY = "futures_session"
FUTURES_CATALOG_FAMILY = "futures_catalog"
FUTURES_PRODUCT_UNIVERSE_FAMILY = "futures_product_universe"
FUTURES_QUOTES_FAMILY = "futures_quotes"
FUTURES_DEPTH_FAMILY = "futures_depth"
FUTURES_MARKET_FAMILIES = frozenset(
    {
        FUTURES_SESSION_FAMILY,
        FUTURES_CATALOG_FAMILY,
        FUTURES_PRODUCT_UNIVERSE_FAMILY,
        FUTURES_QUOTES_FAMILY,
        FUTURES_DEPTH_FAMILY,
    }
)
_DISPOSITION_REASON_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z", re.ASCII)


class FuturesAssetType(str, Enum):
    """Neutral product category, independent of a provider's native class."""

    COMMODITY = "commodity"
    FINANCIAL = "financial"
    INDEX = "index"
    OTHER = "other"
    UNKNOWN = "unknown"


class FuturesContractKind(str, Enum):
    """Normalized contract distinction needed by consumers."""

    FUTURE = "future"
    OPTION = "option"
    NON_FUTURES = "non_futures"
    UNKNOWN = "unknown"


class FuturesCatalogDisposition(str, Enum):
    """Whether a catalog row belongs to the requested futures universe."""

    INCLUDED = "included"
    EXCLUDED = "excluded"
    UNKNOWN = "unknown"


class FuturesSessionStatus(str, Enum):
    """Provider-observed session state; no status is inferred from wall time."""

    ACTIVE = "active"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class FuturesQuantityUnit(str, Enum):
    """Unit carried by quote quantities used for cross-provider comparison."""

    CONTRACTS = "contracts"
    BASE_ASSET = "base_asset"
    QUOTE_ASSET = "quote_asset"
    CURRENCY = "currency"
    UNKNOWN = "unknown"


class FuturesVolumeSemantics(str, Enum):
    """Time aggregation carried by a quote's trade-volume value."""

    CUMULATIVE_TRADING_DAY = "cumulative_trading_day"
    INTERVAL_DELTA = "interval_delta"
    UNKNOWN = "unknown"


class FuturesFreshnessStatus(str, Enum):
    """Quality of a market-data clock, separate from query completeness."""

    UNAVAILABLE = "unavailable"


def _check_text(value: Any, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be valid UTF-8") from exc
    if (
        not encoded
        or len(encoded) > MAX_REFERENCE_BYTES
        or value != value.strip()
        or not value.isprintable()
    ):
        raise ValueError(f"{field_name} must be non-empty printable UTF-8 within the byte limit")
    return value


def _check_optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _check_text(value, field_name)


def _require_mapping(value: Any, fields: frozenset[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError(f"{name} must be a string-keyed mapping")
    if set(value) != fields:
        raise ValueError(f"{name} has an invalid field set")
    return value


def _freeze_json(value: Any) -> Any:
    """Freeze already-bounded JSON filters for immutable coverage records."""
    if value is None or type(value) in (bool, int, float, str):
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("coverage filter keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if type(value) in (tuple, list):
        return tuple(_freeze_json(item) for item in value)
    raise TypeError("coverage filters must contain JSON values")


def _check_date(value: Any, field_name: str) -> date:
    if type(value) is not date:
        raise TypeError(f"{field_name} must be a datetime.date")
    return value


def _check_optional_date(value: Any, field_name: str) -> date | None:
    if value is None:
        return None
    return _check_date(value, field_name)


def _parse_date(value: Any, field_name: str) -> date:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date string") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use canonical YYYY-MM-DD form")
    return parsed


def _check_decimal(value: Any, field_name: str, *, nonnegative: bool = False) -> Decimal:
    if type(value) is not Decimal:
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    encoded = format(value, "f")
    if len(encoded) > 256:
        raise ValueError(f"{field_name} exceeds the decimal string limit")
    if nonnegative and value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _parse_decimal(value: Any, field_name: str, *, nonnegative: bool = False) -> Decimal:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be encoded as a decimal string")
    if not value or len(value) > 256 or value != value.strip():
        raise ValueError(f"{field_name} has an invalid decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} has an invalid decimal string") from exc
    return _check_decimal(parsed, field_name, nonnegative=nonnegative)


def _check_provider_event_time(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    checked = _check_text(value, field_name)
    # This is an exchange/provider label only. Validate its shape without
    # assigning a timezone or interpreting it as a local receive timestamp.
    if len(checked) != 8 or checked[2] != ":" or checked[5] != ":":
        raise ValueError(f"{field_name} must use HH:MM:SS form")
    digits = checked[:2] + checked[3:5] + checked[6:]
    if not digits.isdigit():
        raise ValueError(f"{field_name} must use HH:MM:SS form")
    hour, minute, second = int(digits[:2]), int(digits[2:4]), int(digits[4:])
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError(f"{field_name} is outside HH:MM:SS range")
    return checked


def _check_event_millisecond(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 999:
        raise ValueError(f"{field_name} must be an integer from 0 to 999")
    return value


def _check_instrument(value: Any, field_name: str = "instrument") -> MarketInstrumentKey:
    if type(value) is not MarketInstrumentKey:
        raise TypeError(f"{field_name} must be a MarketInstrumentKey")
    return value


@dataclass(frozen=True)
class FuturesProductKey:
    """Canonical product identity; product IDs are scoped by venue."""

    venue: str
    product_id: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"venue", "product_id"})

    def __post_init__(self) -> None:
        _check_text(self.venue, "venue")
        _check_text(self.product_id, "product_id")

    def to_dict(self) -> dict[str, str]:
        return {"venue": self.venue, "product_id": self.product_id}

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> FuturesProductKey:
        raw = _require_mapping(mapping, cls._FIELDS, "product")
        return cls(venue=raw["venue"], product_id=raw["product_id"])


@dataclass(frozen=True)
class FuturesSessionRecord:
    """Provider-observed trading day for a venue or the selected route.

    ``venue=None`` is a route-wide session fact. It is useful when the SDK
    owns one authenticated session trading day shared across the route but
    cannot claim exchange-specific open/closed state.
    """

    venue: str | None
    environment: str
    trading_day: date
    session_status: FuturesSessionStatus

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"venue", "environment", "trading_day", "session_status"}
    )

    def __post_init__(self) -> None:
        _check_optional_text(self.venue, "venue")
        _check_text(self.environment, "environment")
        _check_date(self.trading_day, "trading_day")
        if type(self.session_status) is not FuturesSessionStatus:
            raise TypeError("session_status must be a FuturesSessionStatus")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "venue": self.venue,
            "environment": self.environment,
            "trading_day": self.trading_day.isoformat(),
            "session_status": self.session_status.value,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> FuturesSessionRecord:
        raw = _require_mapping(mapping, cls._FIELDS, "futures session record")
        try:
            status = FuturesSessionStatus(raw["session_status"])
        except (ValueError, TypeError) as exc:
            raise ValueError("session_status is not a supported neutral value") from exc
        return cls(
            venue=_check_optional_text(raw["venue"], "venue"),
            environment=raw["environment"],
            trading_day=_parse_date(raw["trading_day"], "trading_day"),
            session_status=status,
        )


@dataclass(frozen=True)
class FuturesCatalogRecord:
    """Normalized contract row with explicit classification and reason code.

    ``disposition_reason`` is a short neutral code, never a provider-native
    class name or raw classification value.
    """

    instrument: MarketInstrumentKey
    product: FuturesProductKey
    asset_type: FuturesAssetType
    contract_kind: FuturesContractKind
    is_trading: bool | None
    expiry_date: date | None
    disposition: FuturesCatalogDisposition
    disposition_reason: str
    underlying_instrument_id: str | None = None
    option_right: str | None = None
    strike_price: Decimal | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "instrument",
            "product",
            "asset_type",
            "contract_kind",
            "is_trading",
            "expiry_date",
            "disposition",
            "disposition_reason",
            "underlying_instrument_id",
            "option_right",
            "strike_price",
        }
    )

    def __post_init__(self) -> None:
        instrument = _check_instrument(self.instrument)
        if type(self.product) is not FuturesProductKey:
            raise TypeError("product must be a FuturesProductKey")
        if instrument.venue != self.product.venue:
            raise ValueError("product venue must match instrument venue")
        if type(self.asset_type) is not FuturesAssetType:
            raise TypeError("asset_type must be a FuturesAssetType")
        if type(self.contract_kind) is not FuturesContractKind:
            raise TypeError("contract_kind must be a FuturesContractKind")
        if self.is_trading is not None and type(self.is_trading) is not bool:
            raise TypeError("is_trading must be a bool or None")
        _check_optional_date(self.expiry_date, "expiry_date")
        if type(self.disposition) is not FuturesCatalogDisposition:
            raise TypeError("disposition must be a FuturesCatalogDisposition")
        _check_text(self.disposition_reason, "disposition_reason")
        if _DISPOSITION_REASON_PATTERN.fullmatch(self.disposition_reason) is None:
            raise ValueError("disposition_reason must be a lower-case neutral reason code")
        if self.contract_kind is FuturesContractKind.NON_FUTURES:
            if self.disposition is not FuturesCatalogDisposition.EXCLUDED:
                raise ValueError("known non-futures contracts must be excluded")
        if self.contract_kind is FuturesContractKind.UNKNOWN:
            if self.disposition is FuturesCatalogDisposition.INCLUDED:
                raise ValueError("unknown contract kinds cannot be included")
        if self.asset_type is FuturesAssetType.UNKNOWN:
            if self.disposition is FuturesCatalogDisposition.INCLUDED:
                raise ValueError("unknown asset types cannot be included")
        _check_optional_text(self.underlying_instrument_id, "underlying_instrument_id")
        _check_optional_text(self.option_right, "option_right")
        if self.option_right is not None and self.option_right not in ("call", "put", "unknown"):
            raise ValueError("option_right must be call, put, unknown, or None")
        if self.strike_price is not None:
            _check_decimal(self.strike_price, "strike_price")

    @property
    def product_id(self) -> str:
        """Convenience accessor for the product component of ``product``."""
        return self.product.product_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument.to_dict(),
            "product": self.product.to_dict(),
            "asset_type": self.asset_type.value,
            "contract_kind": self.contract_kind.value,
            "is_trading": self.is_trading,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "disposition": self.disposition.value,
            "disposition_reason": self.disposition_reason,
            "underlying_instrument_id": self.underlying_instrument_id,
            "option_right": self.option_right,
            "strike_price": format(self.strike_price, "f") if self.strike_price is not None else None,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> FuturesCatalogRecord:
        raw = _require_mapping(mapping, cls._FIELDS, "futures catalog record")
        try:
            asset_type = FuturesAssetType(raw["asset_type"])
            contract_kind = FuturesContractKind(raw["contract_kind"])
            disposition = FuturesCatalogDisposition(raw["disposition"])
        except (ValueError, TypeError) as exc:
            raise ValueError("catalog classification contains an unsupported neutral value") from exc
        expiry = (
            None
            if raw["expiry_date"] is None
            else _parse_date(raw["expiry_date"], "expiry_date")
        )
        strike = (
            None
            if raw["strike_price"] is None
            else _parse_decimal(raw["strike_price"], "strike_price")
        )
        return cls(
            instrument=MarketInstrumentKey.from_dict(raw["instrument"]),
            product=FuturesProductKey.from_dict(raw["product"]),
            asset_type=asset_type,
            contract_kind=contract_kind,
            is_trading=raw["is_trading"],
            expiry_date=expiry,
            disposition=disposition,
            disposition_reason=raw["disposition_reason"],
            underlying_instrument_id=raw["underlying_instrument_id"],
            option_right=raw["option_right"],
            strike_price=strike,
        )


@dataclass(frozen=True)
class FuturesQuoteRecord:
    """Normalized quote row; provider event components are audit-only."""

    instrument: MarketInstrumentKey
    trading_day: date
    last_price: Decimal | None = None
    open_interest: Decimal | None = None
    volume: Decimal | None = None
    open_interest_unit: FuturesQuantityUnit = FuturesQuantityUnit.UNKNOWN
    volume_unit: FuturesQuantityUnit = FuturesQuantityUnit.UNKNOWN
    volume_semantics: FuturesVolumeSemantics = FuturesVolumeSemantics.UNKNOWN
    bid_price: Decimal | None = None
    bid_volume: Decimal | None = None
    ask_price: Decimal | None = None
    ask_volume: Decimal | None = None
    provider_event_date: date | None = None
    provider_event_time: str | None = None
    provider_event_millisecond: int | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "instrument",
            "trading_day",
            "last_price",
            "open_interest",
            "volume",
            "open_interest_unit",
            "volume_unit",
            "volume_semantics",
            "bid_price",
            "bid_volume",
            "ask_price",
            "ask_volume",
            "provider_event_date",
            "provider_event_time",
            "provider_event_millisecond",
        }
    )

    def __post_init__(self) -> None:
        _check_instrument(self.instrument)
        _check_date(self.trading_day, "trading_day")
        _check_optional_date(self.provider_event_date, "provider_event_date")
        _check_provider_event_time(self.provider_event_time, "provider_event_time")
        _check_event_millisecond(self.provider_event_millisecond, "provider_event_millisecond")
        for field_name in ("open_interest_unit", "volume_unit"):
            if type(getattr(self, field_name)) is not FuturesQuantityUnit:
                raise TypeError(f"{field_name} must be a FuturesQuantityUnit")
        if type(self.volume_semantics) is not FuturesVolumeSemantics:
            raise TypeError("volume_semantics must be a FuturesVolumeSemantics")
        for field_name in ("last_price", "bid_price", "ask_price"):
            value = getattr(self, field_name)
            if value is not None:
                _check_decimal(value, field_name)
        for field_name in ("open_interest", "volume", "bid_volume", "ask_volume"):
            value = getattr(self, field_name)
            if value is not None:
                _check_decimal(value, field_name, nonnegative=True)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "instrument": self.instrument.to_dict(),
            "trading_day": self.trading_day.isoformat(),
            "provider_event_date": (
                self.provider_event_date.isoformat() if self.provider_event_date else None
            ),
            "provider_event_time": self.provider_event_time,
            "provider_event_millisecond": self.provider_event_millisecond,
            "open_interest_unit": self.open_interest_unit.value,
            "volume_unit": self.volume_unit.value,
            "volume_semantics": self.volume_semantics.value,
        }
        for field_name in (
            "last_price",
            "open_interest",
            "volume",
            "bid_price",
            "bid_volume",
            "ask_price",
            "ask_volume",
        ):
            value = getattr(self, field_name)
            result[field_name] = format(value, "f") if value is not None else None
        return result

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> FuturesQuoteRecord:
        raw = _require_mapping(mapping, cls._FIELDS, "futures quote record")
        try:
            open_interest_unit = FuturesQuantityUnit(raw["open_interest_unit"])
            volume_unit = FuturesQuantityUnit(raw["volume_unit"])
            volume_semantics = FuturesVolumeSemantics(raw["volume_semantics"])
        except (TypeError, ValueError) as exc:
            raise ValueError("quote unit or volume semantics is not a supported neutral value") from exc
        decimals = {
            field_name: (
                None
                if raw[field_name] is None
                else _parse_decimal(
                    raw[field_name],
                    field_name,
                    nonnegative=field_name
                    in {"open_interest", "volume", "bid_volume", "ask_volume"},
                )
            )
            for field_name in (
                "last_price",
                "open_interest",
                "volume",
                "bid_price",
                "bid_volume",
                "ask_price",
                "ask_volume",
            )
        }
        return cls(
            instrument=MarketInstrumentKey.from_dict(raw["instrument"]),
            trading_day=_parse_date(raw["trading_day"], "trading_day"),
            open_interest_unit=open_interest_unit,
            volume_unit=volume_unit,
            volume_semantics=volume_semantics,
            provider_event_date=(
                None
                if raw["provider_event_date"] is None
                else _parse_date(raw["provider_event_date"], "provider_event_date")
            ),
            provider_event_time=raw["provider_event_time"],
            provider_event_millisecond=raw["provider_event_millisecond"],
            **decimals,
        )


@dataclass(frozen=True)
class FuturesDepthLevel:
    """One exact-price level on a provider-supplied depth image."""

    price: Decimal
    volume: Decimal

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"price", "volume"})

    def __post_init__(self) -> None:
        _check_decimal(self.price, "price")
        _check_decimal(self.volume, "volume", nonnegative=True)

    def to_dict(self) -> dict[str, str]:
        return {"price": format(self.price, "f"), "volume": format(self.volume, "f")}

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> FuturesDepthLevel:
        raw = _require_mapping(mapping, cls._FIELDS, "futures depth level")
        return cls(
            price=_parse_decimal(raw["price"], "price"),
            volume=_parse_decimal(raw["volume"], "volume", nonnegative=True),
        )


@dataclass(frozen=True)
class FuturesDepthRecord:
    """One provider-observed depth image for a canonical instrument."""

    instrument: MarketInstrumentKey
    trading_day: date
    bids: tuple[FuturesDepthLevel, ...]
    asks: tuple[FuturesDepthLevel, ...]
    complete_state: bool
    volume_unit: FuturesQuantityUnit = FuturesQuantityUnit.UNKNOWN
    provider_event_date: date | None = None
    provider_event_time: str | None = None
    provider_event_millisecond: int | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "instrument",
            "trading_day",
            "bids",
            "asks",
            "complete_state",
            "volume_unit",
            "provider_event_date",
            "provider_event_time",
            "provider_event_millisecond",
        }
    )

    def __post_init__(self) -> None:
        _check_instrument(self.instrument)
        _check_date(self.trading_day, "trading_day")
        for field_name in ("bids", "asks"):
            values = getattr(self, field_name)
            if type(values) not in (tuple, list):
                raise TypeError(f"{field_name} must be a tuple or list")
            levels = tuple(values)
            if any(type(level) is not FuturesDepthLevel for level in levels):
                raise TypeError(f"{field_name} must contain FuturesDepthLevel values")
            object.__setattr__(self, field_name, levels)
        if any(self.bids[index].price <= self.bids[index + 1].price for index in range(len(self.bids) - 1)):
            raise ValueError("bids must be ordered by strictly descending price")
        if any(self.asks[index].price >= self.asks[index + 1].price for index in range(len(self.asks) - 1)):
            raise ValueError("asks must be ordered by strictly ascending price")
        if type(self.complete_state) is not bool:
            raise TypeError("complete_state must be a bool")
        if type(self.volume_unit) is not FuturesQuantityUnit:
            raise TypeError("volume_unit must be a FuturesQuantityUnit")
        _check_optional_date(self.provider_event_date, "provider_event_date")
        _check_provider_event_time(self.provider_event_time, "provider_event_time")
        _check_event_millisecond(self.provider_event_millisecond, "provider_event_millisecond")

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument.to_dict(),
            "trading_day": self.trading_day.isoformat(),
            # QuerySnapshot freezes JSON arrays to tuples; tuple equality keeps
            # this canonical projection stable at its validation boundary.
            "bids": tuple(level.to_dict() for level in self.bids),
            "asks": tuple(level.to_dict() for level in self.asks),
            "complete_state": self.complete_state,
            "volume_unit": self.volume_unit.value,
            "provider_event_date": (
                self.provider_event_date.isoformat() if self.provider_event_date else None
            ),
            "provider_event_time": self.provider_event_time,
            "provider_event_millisecond": self.provider_event_millisecond,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> FuturesDepthRecord:
        raw = _require_mapping(mapping, cls._FIELDS, "futures depth record")
        for name in ("bids", "asks"):
            if type(raw[name]) not in (tuple, list):
                raise TypeError(f"{name} must be a sequence")
        try:
            volume_unit = FuturesQuantityUnit(raw["volume_unit"])
        except (TypeError, ValueError) as exc:
            raise ValueError("depth quantity unit is not a supported neutral value") from exc
        return cls(
            instrument=MarketInstrumentKey.from_dict(raw["instrument"]),
            trading_day=_parse_date(raw["trading_day"], "trading_day"),
            bids=tuple(FuturesDepthLevel.from_dict(item) for item in raw["bids"]),
            asks=tuple(FuturesDepthLevel.from_dict(item) for item in raw["asks"]),
            complete_state=raw["complete_state"],
            volume_unit=volume_unit,
            provider_event_date=(
                None
                if raw["provider_event_date"] is None
                else _parse_date(raw["provider_event_date"], "provider_event_date")
            ),
            provider_event_time=raw["provider_event_time"],
            provider_event_millisecond=raw["provider_event_millisecond"],
        )


@dataclass(frozen=True)
class FuturesMarketSnapshotRequest:
    """Exact bounded scope for one catalog and quote/depth snapshot batch.

    ``venues=None`` asks the selected provider route for its complete venue
    universe; the provider must attest that scope explicitly. ``trading_day``
    may be omitted because the provider session family supplies one day per
    venue. Consumers must not substitute the local wall-clock date.
    ``require_product_universe`` asks for product coverage including products
    with no returned contract rows; a complete instrument catalog alone does
    not satisfy that request.
    """

    request_ref: str
    environment: str
    trading_day: date | None = None
    venues: tuple[str, ...] | None = None
    products: tuple[FuturesProductKey, ...] | None = None
    instruments: tuple[MarketInstrumentKey, ...] | None = None
    contract_kinds: tuple[FuturesContractKind, ...] = (FuturesContractKind.FUTURE,)
    require_active_session: bool = False
    require_product_universe: bool = False
    include_depth: bool = False
    depth_levels: int = 5
    required_quote_fields: tuple[str, ...] = ("open_interest", "volume")
    required_open_interest_unit: FuturesQuantityUnit | None = FuturesQuantityUnit.CONTRACTS
    required_volume_unit: FuturesQuantityUnit | None = FuturesQuantityUnit.CONTRACTS
    required_volume_semantics: FuturesVolumeSemantics | None = (
        FuturesVolumeSemantics.CUMULATIVE_TRADING_DAY
    )
    required_depth_volume_unit: FuturesQuantityUnit | None = FuturesQuantityUnit.CONTRACTS

    _QUOTE_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "last_price",
            "open_interest",
            "volume",
            "bid_price",
            "bid_volume",
            "ask_price",
            "ask_volume",
        }
    )

    def __post_init__(self) -> None:
        _check_text(self.request_ref, "request_ref")
        if len(self.request_ref.encode("utf-8")) > MAX_REFERENCE_BYTES - len(
            ".product-universe"
        ):
            raise ValueError("request_ref is too long for family references")
        _check_text(self.environment, "environment")
        _check_optional_date(self.trading_day, "trading_day")
        if self.venues is not None:
            venues = _check_text_tuple(self.venues, "venues")
            if not venues:
                raise ValueError("venues must be None or a non-empty tuple")
            object.__setattr__(self, "venues", venues)
        if self.products is not None:
            products = _check_exact_tuple(self.products, FuturesProductKey, "products")
            if not products:
                raise ValueError("products must be None or a non-empty tuple")
            if len({(item.venue, item.product_id) for item in products}) != len(products):
                raise ValueError("products must not contain duplicate product identities")
            object.__setattr__(self, "products", products)
        if self.instruments is not None:
            instruments = _check_exact_tuple(
                self.instruments,
                MarketInstrumentKey,
                "instruments",
            )
            if not instruments:
                raise ValueError("instruments must be None or a non-empty tuple")
            identities = tuple(_instrument_identity(item) for item in instruments)
            if len(set(identities)) != len(identities):
                raise ValueError("instruments must not contain duplicate identities")
            object.__setattr__(self, "instruments", instruments)
        if type(self.contract_kinds) not in (tuple, list):
            raise TypeError("contract_kinds must be a tuple or list")
        kinds = tuple(self.contract_kinds)
        if not kinds or any(type(item) is not FuturesContractKind for item in kinds):
            raise ValueError("contract_kinds must contain supported contract kinds")
        if FuturesContractKind.UNKNOWN in kinds or FuturesContractKind.NON_FUTURES in kinds:
            raise ValueError("contract_kinds cannot request unknown or non-futures values")
        if len(set(kinds)) != len(kinds):
            raise ValueError("contract_kinds must not contain duplicates")
        object.__setattr__(self, "contract_kinds", kinds)
        if type(self.require_active_session) is not bool:
            raise TypeError("require_active_session must be a bool")
        if type(self.require_product_universe) is not bool:
            raise TypeError("require_product_universe must be a bool")
        if self.require_product_universe and self.instruments is not None:
            raise ValueError(
                "a product universe request cannot be combined with an instrument filter"
            )
        if type(self.include_depth) is not bool:
            raise TypeError("include_depth must be a bool")
        if type(self.depth_levels) is not int or not 1 <= self.depth_levels <= 1000:
            raise ValueError("depth_levels must be between 1 and 1000")
        quote_fields = _check_text_tuple(self.required_quote_fields, "required_quote_fields")
        if not quote_fields or not set(quote_fields).issubset(self._QUOTE_FIELDS):
            raise ValueError("required_quote_fields contains an unsupported quote field")
        object.__setattr__(self, "required_quote_fields", quote_fields)
        for field_name in ("required_open_interest_unit", "required_volume_unit"):
            value = getattr(self, field_name)
            if value is not None:
                if type(value) is not FuturesQuantityUnit:
                    raise TypeError(f"{field_name} must be a FuturesQuantityUnit or None")
                if value is FuturesQuantityUnit.UNKNOWN:
                    raise ValueError(f"{field_name} cannot require an unknown unit")
        if self.required_volume_semantics is not None:
            if type(self.required_volume_semantics) is not FuturesVolumeSemantics:
                raise TypeError(
                    "required_volume_semantics must be a FuturesVolumeSemantics or None"
                )
            if self.required_volume_semantics is FuturesVolumeSemantics.UNKNOWN:
                raise ValueError("required_volume_semantics cannot require unknown")
        if self.required_depth_volume_unit is not None:
            if type(self.required_depth_volume_unit) is not FuturesQuantityUnit:
                raise TypeError("required_depth_volume_unit must be a FuturesQuantityUnit or None")
            if self.required_depth_volume_unit is FuturesQuantityUnit.UNKNOWN:
                raise ValueError("required_depth_volume_unit cannot require unknown")
        if self.venues is not None:
            allowed = set(self.venues)
            if any(product.venue not in allowed for product in self.products or ()):
                raise ValueError("product venue is outside the requested venue scope")
            if any(item.venue not in allowed for item in self.instruments or ()):
                raise ValueError("instrument venue is outside the requested venue scope")
        if any(item.environment != self.environment for item in self.instruments or ()):
            raise ValueError("instrument environment must match request environment")
        if len({item.provider for item in self.instruments or ()}) > 1:
            raise ValueError("instrument filter cannot mix provider identities")

    @property
    def family_request_refs(self) -> Mapping[str, str]:
        refs = {
            FUTURES_SESSION_FAMILY: self.request_ref + ".session",
            FUTURES_CATALOG_FAMILY: self.request_ref + ".catalog",
        }
        if self.require_product_universe:
            refs[FUTURES_PRODUCT_UNIVERSE_FAMILY] = self.request_ref + ".product-universe"
        refs[FUTURES_QUOTES_FAMILY] = self.request_ref + ".quotes"
        if self.include_depth:
            refs[FUTURES_DEPTH_FAMILY] = self.request_ref + ".depth"
        return MappingProxyType(refs)

    def filters_for(self, family: str) -> dict[str, Any]:
        """Return canonical JSON filters for one requested query family."""
        if family not in self.family_request_refs:
            raise ValueError("family is not part of this snapshot request")
        filters: dict[str, Any] = {
            "environment": self.environment,
            "trading_day": self.trading_day.isoformat() if self.trading_day else None,
            "venues": list(self.venues) if self.venues is not None else None,
        }
        if family == FUTURES_SESSION_FAMILY:
            filters["require_active_session"] = self.require_active_session
        if family == FUTURES_PRODUCT_UNIVERSE_FAMILY:
            filters["products"] = (
                [item.to_dict() for item in self.products]
                if self.products is not None
                else None
            )
        if family not in (FUTURES_SESSION_FAMILY, FUTURES_PRODUCT_UNIVERSE_FAMILY):
            filters.update(
                {
                    "products": (
                        [item.to_dict() for item in self.products]
                        if self.products is not None
                        else None
                    ),
                    "instruments": (
                        [item.to_dict() for item in self.instruments]
                        if self.instruments is not None
                        else None
                    ),
                    "contract_kinds": [item.value for item in self.contract_kinds],
                }
            )
        if family == FUTURES_QUOTES_FAMILY:
            filters["required_quote_fields"] = list(self.required_quote_fields)
            filters["required_open_interest_unit"] = (
                self.required_open_interest_unit.value
                if self.required_open_interest_unit is not None
                else None
            )
            filters["required_volume_unit"] = (
                self.required_volume_unit.value
                if self.required_volume_unit is not None
                else None
            )
            filters["required_volume_semantics"] = (
                self.required_volume_semantics.value
                if self.required_volume_semantics is not None
                else None
            )
        if family == FUTURES_DEPTH_FAMILY:
            filters["depth_levels"] = self.depth_levels
            filters["required_depth_volume_unit"] = (
                self.required_depth_volume_unit.value
                if self.required_depth_volume_unit is not None
                else None
            )
        return filters


def _check_text_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if type(value) not in (tuple, list):
        raise TypeError(f"{field_name} must be a tuple or list")
    values = tuple(_check_text(item, field_name) for item in value)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


def _check_exact_tuple(value: Any, item_type: type, field_name: str) -> tuple[Any, ...]:
    if type(value) not in (tuple, list):
        raise TypeError(f"{field_name} must be a tuple or list")
    values = tuple(value)
    if any(type(item) is not item_type for item in values):
        raise TypeError(f"{field_name} contains an invalid item type")
    return values


def _instrument_identity(value: MarketInstrumentKey) -> tuple[str, ...]:
    return (
        value.provider,
        value.venue,
        value.environment,
        value.product_type,
        value.instrument_id,
        value.native_symbol,
    )


# Query-family validation is imported lazily by query_protocol after its own
# module has finished initializing. The base DTO module intentionally avoids
# importing provider packages or query implementations at module import time.


@dataclass(frozen=True)
class FuturesFamilyCoverage:
    """Exact request, batch, source, and scope facts for one family snapshot."""

    family: str
    request_ref: str
    batch_ref: str | None
    filters: Mapping[str, Any]
    completeness: QueryCompleteness
    scope_complete: bool | None
    source_ref: str | None
    generation: str | None
    snapshot_ref: str | None
    started_at: datetime | None
    completed_at: datetime | None
    observed_at: datetime | None
    records_digest: str | None
    record_count: int | None
    blockers: tuple[str, ...] = ()
    continuation_ref: str | None = None

    def __post_init__(self) -> None:
        _check_text(self.family, "family")
        _check_text(self.request_ref, "request_ref")
        if self.family not in FUTURES_MARKET_FAMILIES:
            raise ValueError("family is not a published futures family")
        if not isinstance(self.filters, Mapping):
            raise TypeError("filters must be a mapping")
        frozen_filters = _freeze_json(self.filters)
        if not isinstance(frozen_filters, Mapping):
            raise TypeError("filters must be a mapping")
        object.__setattr__(self, "filters", frozen_filters)
        if type(self.completeness) is not QueryCompleteness:
            raise TypeError("completeness must be a QueryCompleteness")
        if self.scope_complete is not None and type(self.scope_complete) is not bool:
            raise TypeError("scope_complete must be a bool or None")
        for field_name in (
            "batch_ref",
            "source_ref",
            "generation",
            "snapshot_ref",
            "continuation_ref",
        ):
            _check_optional_text(getattr(self, field_name), field_name)
        for field_name in ("started_at", "completed_at", "observed_at"):
            value = getattr(self, field_name)
            if value is not None:
                if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{field_name} must be timezone-aware UTC or None")
                if value.utcoffset().total_seconds() != 0:
                    raise ValueError(f"{field_name} must be timezone-aware UTC or None")
        if self.started_at is not None and self.completed_at is not None:
            if self.started_at > self.completed_at:
                raise ValueError("started_at must not be after completed_at")
        if self.completed_at is not None and self.observed_at is not None:
            if self.observed_at < self.completed_at:
                raise ValueError("observed_at must not be before completed_at")
        if self.records_digest is not None:
            if type(self.records_digest) is not str or len(self.records_digest) != 64:
                raise ValueError("records_digest must be a SHA-256 digest or None")
            try:
                bytes.fromhex(self.records_digest)
            except ValueError as exc:
                raise ValueError("records_digest must be a SHA-256 digest or None") from exc
            if self.records_digest.lower() != self.records_digest:
                raise ValueError("records_digest must be lower-case")
        if self.record_count is not None and (
            type(self.record_count) is not int or self.record_count < 0
        ):
            raise ValueError("record_count must be a non-negative integer or None")
        blockers = _check_text_tuple(self.blockers, "blockers")
        object.__setattr__(self, "blockers", blockers)

    @property
    def complete(self) -> bool:
        return (
            self.completeness is QueryCompleteness.COMPLETE
            and not self.blockers
            and self.continuation_ref is None
            and self.scope_complete is True
            and self.batch_ref is not None
            and self.source_ref is not None
            and self.generation is not None
            and self.snapshot_ref is not None
            and self.started_at is not None
            and self.completed_at is not None
            and self.observed_at is not None
            and self.records_digest is not None
            and self.record_count is not None
        )


@dataclass(frozen=True)
class FuturesMissingQuoteFields:
    """Required quote fields absent for one expected instrument."""

    instrument: MarketInstrumentKey
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        _check_instrument(self.instrument)
        fields = _check_text_tuple(self.fields, "fields")
        if not fields:
            raise ValueError("fields must not be empty")
        object.__setattr__(self, "fields", fields)


@dataclass(frozen=True)
class FuturesQuoteUnitMismatch:
    """A quote quantity whose unit does not satisfy the requested contract."""

    instrument: MarketInstrumentKey
    field: str
    required_unit: FuturesQuantityUnit
    actual_unit: FuturesQuantityUnit

    def __post_init__(self) -> None:
        _check_instrument(self.instrument)
        if self.field not in ("open_interest", "volume"):
            raise ValueError("field must be open_interest or volume")
        if type(self.required_unit) is not FuturesQuantityUnit:
            raise TypeError("required_unit must be a FuturesQuantityUnit")
        if type(self.actual_unit) is not FuturesQuantityUnit:
            raise TypeError("actual_unit must be a FuturesQuantityUnit")
        if self.required_unit is FuturesQuantityUnit.UNKNOWN:
            raise ValueError("required_unit cannot be unknown")


@dataclass(frozen=True)
class FuturesQuoteSemanticMismatch:
    """A quote value whose aggregation semantics do not meet the request."""

    instrument: MarketInstrumentKey
    field: str
    required_semantics: FuturesVolumeSemantics
    actual_semantics: FuturesVolumeSemantics

    def __post_init__(self) -> None:
        _check_instrument(self.instrument)
        if self.field != "volume":
            raise ValueError("field must be volume")
        if type(self.required_semantics) is not FuturesVolumeSemantics:
            raise TypeError("required_semantics must be a FuturesVolumeSemantics")
        if type(self.actual_semantics) is not FuturesVolumeSemantics:
            raise TypeError("actual_semantics must be a FuturesVolumeSemantics")
        if self.required_semantics is FuturesVolumeSemantics.UNKNOWN:
            raise ValueError("required_semantics cannot be unknown")


@dataclass(frozen=True)
class FuturesDepthUnitMismatch:
    """Depth quantity unit that differs from the requested unit."""

    instrument: MarketInstrumentKey
    required_unit: FuturesQuantityUnit
    actual_unit: FuturesQuantityUnit

    def __post_init__(self) -> None:
        _check_instrument(self.instrument)
        if type(self.required_unit) is not FuturesQuantityUnit:
            raise TypeError("required_unit must be a FuturesQuantityUnit")
        if type(self.actual_unit) is not FuturesQuantityUnit:
            raise TypeError("actual_unit must be a FuturesQuantityUnit")
        if self.required_unit is FuturesQuantityUnit.UNKNOWN:
            raise ValueError("required_unit cannot be unknown")


@dataclass(frozen=True)
class FuturesMarketSnapshotCoverage:
    """Request-bound cross-family identity and completeness facts.

    A product universe is separate from the instrument contract universe. The
    former must be requested explicitly and cannot be inferred from catalog
    rows, since those rows necessarily name an instrument.
    """

    request: FuturesMarketSnapshotRequest
    batch_ref: str
    source_ref: str | None
    generation: str | None
    session: FuturesFamilyCoverage
    catalog: FuturesFamilyCoverage
    quotes: FuturesFamilyCoverage
    product_universe: FuturesFamilyCoverage | None
    depth: FuturesFamilyCoverage | None
    expected_instruments: tuple[MarketInstrumentKey, ...]
    product_keys: tuple[FuturesProductKey, ...] = ()
    missing_products: tuple[FuturesProductKey, ...] = ()
    unexpected_products: tuple[FuturesProductKey, ...] = ()
    missing_quote_instruments: tuple[MarketInstrumentKey, ...] = ()
    missing_depth_instruments: tuple[MarketInstrumentKey, ...] = ()
    missing_quote_fields: tuple[FuturesMissingQuoteFields, ...] = ()
    quote_unit_mismatches: tuple[FuturesQuoteUnitMismatch, ...] = ()
    quote_semantic_mismatches: tuple[FuturesQuoteSemanticMismatch, ...] = ()
    depth_unit_mismatches: tuple[FuturesDepthUnitMismatch, ...] = ()
    unclassified_instruments: tuple[MarketInstrumentKey, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.request) is not FuturesMarketSnapshotRequest:
            raise TypeError("request must be a FuturesMarketSnapshotRequest")
        _check_text(self.batch_ref, "batch_ref")
        _check_optional_text(self.source_ref, "source_ref")
        _check_optional_text(self.generation, "generation")
        blockers = _check_text_tuple(self.blockers, "blockers")
        object.__setattr__(self, "blockers", blockers)
        for field_name in ("session", "catalog", "quotes"):
            if type(getattr(self, field_name)) is not FuturesFamilyCoverage:
                raise TypeError(f"{field_name} must be a FuturesFamilyCoverage")
        if self.product_universe is not None and type(
            self.product_universe
        ) is not FuturesFamilyCoverage:
            raise TypeError("product_universe must be a FuturesFamilyCoverage or None")
        if self.depth is not None and type(self.depth) is not FuturesFamilyCoverage:
            raise TypeError("depth must be a FuturesFamilyCoverage or None")
        if self.session.family != FUTURES_SESSION_FAMILY:
            raise ValueError("session coverage has the wrong family")
        if self.catalog.family != FUTURES_CATALOG_FAMILY:
            raise ValueError("catalog coverage has the wrong family")
        if self.quotes.family != FUTURES_QUOTES_FAMILY:
            raise ValueError("quotes coverage has the wrong family")
        if (
            self.product_universe is not None
            and self.product_universe.family != FUTURES_PRODUCT_UNIVERSE_FAMILY
        ):
            raise ValueError("product_universe coverage has the wrong family")
        if self.depth is not None and self.depth.family != FUTURES_DEPTH_FAMILY:
            raise ValueError("depth coverage has the wrong family")
        families_by_name = {
            self.session.family: self.session,
            self.catalog.family: self.catalog,
            self.quotes.family: self.quotes,
        }
        if self.product_universe is not None:
            families_by_name[self.product_universe.family] = self.product_universe
        if self.depth is not None:
            families_by_name[self.depth.family] = self.depth
        expected_refs = self.request.family_request_refs
        if set(families_by_name) != set(expected_refs):
            raise ValueError("family coverage set does not match the snapshot request")
        for family, expected_ref in expected_refs.items():
            coverage = families_by_name[family]
            if coverage.request_ref != expected_ref:
                raise ValueError("family coverage request_ref does not match the request")
            expected_filters = _freeze_json(self.request.filters_for(family))
            if coverage.filters != expected_filters:
                raise ValueError("family coverage filters do not match the request")
        if self.request.require_product_universe != (self.product_universe is not None):
            raise ValueError("product universe coverage does not match the request")
        for field_name in ("product_keys", "missing_products", "unexpected_products"):
            values = _check_exact_tuple(
                getattr(self, field_name),
                FuturesProductKey,
                field_name,
            )
            identities = tuple((item.venue, item.product_id) for item in values)
            if len(set(identities)) != len(identities):
                raise ValueError(f"{field_name} contains duplicate product keys")
            object.__setattr__(self, field_name, values)
        if not self.request.require_product_universe and (
            self.product_keys or self.missing_products or self.unexpected_products
        ):
            raise ValueError("product keys require a product universe request")
        if self.request.require_product_universe and self.request.products is not None:
            requested_products = {
                (item.venue, item.product_id) for item in self.request.products
            }
            actual_products = {(item.venue, item.product_id) for item in self.product_keys}
            expected_missing = requested_products - actual_products
            expected_unexpected = actual_products - requested_products
            actual_missing = {(item.venue, item.product_id) for item in self.missing_products}
            actual_unexpected = {
                (item.venue, item.product_id) for item in self.unexpected_products
            }
            if actual_missing != expected_missing or actual_unexpected != expected_unexpected:
                raise ValueError("product keys do not match the requested product scope")
        for field_name in (
            "expected_instruments",
            "missing_quote_instruments",
            "missing_depth_instruments",
            "unclassified_instruments",
        ):
            values = _check_exact_tuple(
                getattr(self, field_name),
                MarketInstrumentKey,
                field_name,
            )
            identities = tuple(_instrument_identity(item) for item in values)
            if len(set(identities)) != len(identities):
                raise ValueError(f"{field_name} contains duplicate instruments")
            object.__setattr__(self, field_name, values)
        missing_fields = _check_exact_tuple(
            self.missing_quote_fields,
            FuturesMissingQuoteFields,
            "missing_quote_fields",
        )
        object.__setattr__(self, "missing_quote_fields", missing_fields)
        unit_mismatches = _check_exact_tuple(
            self.quote_unit_mismatches,
            FuturesQuoteUnitMismatch,
            "quote_unit_mismatches",
        )
        object.__setattr__(self, "quote_unit_mismatches", unit_mismatches)
        semantic_mismatches = _check_exact_tuple(
            self.quote_semantic_mismatches,
            FuturesQuoteSemanticMismatch,
            "quote_semantic_mismatches",
        )
        object.__setattr__(self, "quote_semantic_mismatches", semantic_mismatches)
        depth_mismatches = _check_exact_tuple(
            self.depth_unit_mismatches,
            FuturesDepthUnitMismatch,
            "depth_unit_mismatches",
        )
        object.__setattr__(self, "depth_unit_mismatches", depth_mismatches)

    @property
    def scope_complete(self) -> bool:
        families = (self.session, self.catalog, self.quotes)
        if self.product_universe is not None:
            families += (self.product_universe,)
        if self.depth is not None:
            families += (self.depth,)
        if self.source_ref is None or self.generation is None:
            return False
        return all(
            item.complete
            and item.batch_ref == self.batch_ref
            and item.source_ref == self.source_ref
            and item.generation == self.generation
            for item in families
        )

    @property
    def complete(self) -> bool:
        return (
            self.scope_complete
            and not self.blockers
            and not self.missing_products
            and not self.unexpected_products
            and not self.missing_quote_instruments
            and not self.missing_depth_instruments
            and not self.missing_quote_fields
            and not self.quote_unit_mismatches
            and not self.quote_semantic_mismatches
            and not self.depth_unit_mismatches
            and not self.unclassified_instruments
        )

    @property
    def product_universe_complete(self) -> bool | None:
        """Whether requested product-key coverage is complete, if requested."""
        if self.product_universe is None:
            return None
        return (
            self.product_universe.complete
            and self.product_universe.batch_ref == self.batch_ref
            and self.product_universe.source_ref == self.source_ref
            and self.product_universe.generation == self.generation
            and not self.missing_products
            and not self.unexpected_products
        )


__all__ = [
    "FUTURES_CATALOG_FAMILY",
    "FUTURES_DEPTH_FAMILY",
    "FUTURES_MARKET_FAMILIES",
    "FUTURES_PRODUCT_UNIVERSE_FAMILY",
    "FUTURES_QUOTES_FAMILY",
    "FUTURES_SESSION_FAMILY",
    "FuturesAssetType",
    "FuturesCatalogDisposition",
    "FuturesCatalogRecord",
    "FuturesContractKind",
    "FuturesDepthLevel",
    "FuturesDepthRecord",
    "FuturesDepthUnitMismatch",
    "FuturesFamilyCoverage",
    "FuturesFreshnessStatus",
    "FuturesMarketSnapshotCoverage",
    "FuturesMarketSnapshotRequest",
    "FuturesMissingQuoteFields",
    "FuturesProductKey",
    "FuturesQuoteRecord",
    "FuturesQuantityUnit",
    "FuturesQuoteUnitMismatch",
    "FuturesQuoteSemanticMismatch",
    "FuturesSessionRecord",
    "FuturesSessionStatus",
    "FuturesVolumeSemantics",
]
