"""Neutral, bounded account snapshot contracts for provider and service adapters.

These values describe provider-reported account facts. They carry no strategy
ownership, session generation, journal cursor, or freshness decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import MAX_REFERENCE_BYTES

MAX_ACCOUNT_OBSERVATION_BYTES = 512 * 1024
MAX_ACCOUNT_ROWS = 2048
MAX_DECIMAL_BYTES = 128

_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z", re.ASCII)
_UTC_TIMESTAMP_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z\Z",
    re.ASCII,
)


def _check_text(value: Any, field: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} must be a string")
    if not value or len(value) > MAX_REFERENCE_BYTES or value != value.strip():
        raise ValueError(f"{field} must be non-empty and within the byte limit")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} must be printable UTF-8") from exc
    if len(encoded) > MAX_REFERENCE_BYTES or not value.isprintable():
        raise ValueError(f"{field} must be printable UTF-8 within the byte limit")
    return value


def _check_optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _check_text(value, field)


def _check_decimal(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise TypeError(f"{field} must be a decimal string" + (" or None" if optional else ""))
    if not value or len(value) > MAX_DECIMAL_BYTES or not _DECIMAL_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be a bounded finite decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a bounded finite decimal string") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return value


def _check_utc_timestamp(value: Any, field: str) -> tuple[str, datetime]:
    if type(value) is not str:
        raise TypeError(f"{field} must be an explicit UTC timestamp string")
    if len(value) > 32 or not _UTC_TIMESTAMP_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must use an explicit UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid UTC timestamp") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError(f"{field} must be an aware UTC timestamp")
    return value, parsed


def _require_exact_mapping(value: Any, fields: frozenset[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError(f"{name} must be a string-keyed mapping")
    if set(value) != fields:
        raise ValueError(f"{name} has an invalid field set")
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _require_tuple(value: Any, field: str) -> tuple[Any, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    if len(value) > MAX_ACCOUNT_ROWS:
        raise ValueError(f"{field} exceeds the row limit")
    return value


def _dict_array(value: Any, field: str) -> tuple[Any, ...]:
    # JSON decoders produce lists; direct Python callers may also provide tuples.
    if type(value) not in (list, tuple):
        raise TypeError(f"{field} must be an array")
    if len(value) > MAX_ACCOUNT_ROWS:
        raise ValueError(f"{field} exceeds the row limit")
    return tuple(value)


@dataclass(frozen=True)
class AccountKey:
    """Stable provider account owner identity, independent of strategy/API key/product."""

    provider: str
    venue: str
    environment: str
    account_id: str
    subaccount_id: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"provider", "venue", "environment", "account_id", "subaccount_id"}
    )

    def __post_init__(self) -> None:
        for field in ("provider", "venue", "environment", "account_id"):
            _check_text(getattr(self, field), field)
        _check_optional_text(self.subaccount_id, "subaccount_id")

    @property
    def account_key_id(self) -> str:
        """Return a process-stable digest of every account-owner identity dimension."""
        digest = hashlib.sha256(_canonical_json_bytes(self.to_dict())).hexdigest()
        return f"account-{digest}"

    def to_dict(self) -> dict[str, str | None]:
        return {
            "provider": self.provider,
            "venue": self.venue,
            "environment": self.environment,
            "account_id": self.account_id,
            "subaccount_id": self.subaccount_id,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> AccountKey:
        raw = _require_exact_mapping(mapping, cls._FIELDS, "account_key")
        return cls(
            provider=raw["provider"],
            venue=raw["venue"],
            environment=raw["environment"],
            account_id=raw["account_id"],
            subaccount_id=raw["subaccount_id"],
        )


@dataclass(frozen=True)
class AccountResourceKey:
    """A product/margin resource inside one provider account session."""

    product_type: str
    margin_pool: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"product_type", "margin_pool"})

    def __post_init__(self) -> None:
        _check_text(self.product_type, "product_type")
        _check_text(self.margin_pool, "margin_pool")

    def to_dict(self) -> dict[str, str]:
        return {"product_type": self.product_type, "margin_pool": self.margin_pool}

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> AccountResourceKey:
        raw = _require_exact_mapping(mapping, cls._FIELDS, "account_resource")
        return cls(product_type=raw["product_type"], margin_pool=raw["margin_pool"])


@dataclass(frozen=True)
class AccountBalance:
    """Provider-reported balance facts for one resource and currency."""

    resource: AccountResourceKey
    currency: str
    total: str | None
    available: str | None
    locked: str | None
    observed_at_utc: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"resource", "currency", "total", "available", "locked", "observed_at_utc"}
    )

    def __post_init__(self) -> None:
        if type(self.resource) is not AccountResourceKey:
            raise TypeError("resource must be an AccountResourceKey")
        _check_text(self.currency, "currency")
        _check_decimal(self.total, "total", optional=True)
        _check_decimal(self.available, "available", optional=True)
        _check_decimal(self.locked, "locked", optional=True)
        _check_utc_timestamp(self.observed_at_utc, "observed_at_utc")

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource.to_dict(),
            "currency": self.currency,
            "total": self.total,
            "available": self.available,
            "locked": self.locked,
            "observed_at_utc": self.observed_at_utc,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> AccountBalance:
        raw = _require_exact_mapping(mapping, cls._FIELDS, "account_balance")
        return cls(
            resource=AccountResourceKey.from_dict(raw["resource"]),
            currency=raw["currency"],
            total=raw["total"],
            available=raw["available"],
            locked=raw["locked"],
            observed_at_utc=raw["observed_at_utc"],
        )


@dataclass(frozen=True)
class AccountPosition:
    """Provider-reported position facts; no strategy or virtual-book attribution."""

    resource: AccountResourceKey
    instrument: MarketInstrumentKey
    side: str
    quantity: str
    qty_unit: str
    average_price: str | None
    price_currency: str | None
    observed_at_utc: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "resource",
            "instrument",
            "side",
            "quantity",
            "qty_unit",
            "average_price",
            "price_currency",
            "observed_at_utc",
        }
    )

    def __post_init__(self) -> None:
        if type(self.resource) is not AccountResourceKey:
            raise TypeError("resource must be an AccountResourceKey")
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be a MarketInstrumentKey")
        if type(self.side) is not str:
            raise TypeError("side must be a string")
        if self.side not in {"net", "long", "short"}:
            raise ValueError("side must be one of net, long, or short")
        quantity = _check_decimal(self.quantity, "quantity")
        assert quantity is not None
        if self.side in {"long", "short"} and Decimal(quantity) < 0:
            raise ValueError("long and short quantities must be nonnegative")
        _check_text(self.qty_unit, "qty_unit")
        _check_decimal(self.average_price, "average_price", optional=True)
        _check_optional_text(self.price_currency, "price_currency")
        _check_utc_timestamp(self.observed_at_utc, "observed_at_utc")

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource.to_dict(),
            "instrument": self.instrument.to_dict(),
            "side": self.side,
            "quantity": self.quantity,
            "qty_unit": self.qty_unit,
            "average_price": self.average_price,
            "price_currency": self.price_currency,
            "observed_at_utc": self.observed_at_utc,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> AccountPosition:
        raw = _require_exact_mapping(mapping, cls._FIELDS, "account_position")
        return cls(
            resource=AccountResourceKey.from_dict(raw["resource"]),
            instrument=MarketInstrumentKey.from_dict(raw["instrument"]),
            side=raw["side"],
            quantity=raw["quantity"],
            qty_unit=raw["qty_unit"],
            average_price=raw["average_price"],
            price_currency=raw["price_currency"],
            observed_at_utc=raw["observed_at_utc"],
        )


@dataclass(frozen=True)
class AccountOpenOrder:
    """Provider-reported open order, without strategy ownership attribution.

    ``side`` is the order action (buy or sell). ``position_side`` describes the
    provider's position-mode leg: ``net`` for one-way position mode, or
    ``long``/``short`` for an explicit hedged leg. It is not inferred from the
    order action. Order identifiers are scoped by resource and instrument.
    """

    resource: AccountResourceKey
    instrument: MarketInstrumentKey
    order_id: str
    side: str
    position_side: str
    order_type: str
    status: str
    quantity: str
    filled_quantity: str
    qty_unit: str
    created_at_utc: str
    observed_at_utc: str
    client_order_id: str | None = None
    limit_price: str | None = None
    stop_price: str | None = None
    price_currency: str | None = None
    reduce_only: bool | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "resource",
            "instrument",
            "order_id",
            "side",
            "position_side",
            "order_type",
            "status",
            "quantity",
            "filled_quantity",
            "qty_unit",
            "created_at_utc",
            "observed_at_utc",
            "client_order_id",
            "limit_price",
            "stop_price",
            "price_currency",
            "reduce_only",
        }
    )

    def __post_init__(self) -> None:
        if type(self.resource) is not AccountResourceKey:
            raise TypeError("resource must be an AccountResourceKey")
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be a MarketInstrumentKey")
        _check_text(self.order_id, "order_id")
        _check_optional_text(self.client_order_id, "client_order_id")
        if type(self.side) is not str:
            raise TypeError("side must be a string")
        if self.side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if type(self.position_side) is not str:
            raise TypeError("position_side must be a string")
        if self.position_side not in {"net", "long", "short"}:
            raise ValueError("position_side must be net, long, or short")
        _check_text(self.order_type, "order_type")
        if type(self.status) is not str:
            raise TypeError("status must be a string")
        if self.status not in {"open", "partially_filled"}:
            raise ValueError("status must be open or partially_filled")

        quantity = _check_decimal(self.quantity, "quantity")
        filled_quantity = _check_decimal(self.filled_quantity, "filled_quantity")
        assert quantity is not None and filled_quantity is not None
        quantity_value = Decimal(quantity)
        filled_value = Decimal(filled_quantity)
        if quantity_value <= 0:
            raise ValueError("quantity must be positive")
        if filled_value < 0:
            raise ValueError("filled_quantity must be nonnegative")
        if filled_value >= quantity_value:
            raise ValueError("filled_quantity must be less than quantity")
        if self.status == "open" and filled_value != 0:
            raise ValueError("open orders must have zero filled_quantity")
        if self.status == "partially_filled" and filled_value == 0:
            raise ValueError("partially_filled orders must have positive filled_quantity")
        _check_text(self.qty_unit, "qty_unit")

        for field in ("limit_price", "stop_price"):
            _check_decimal(getattr(self, field), field, optional=True)
        _check_optional_text(self.price_currency, "price_currency")
        if self.reduce_only is not None and type(self.reduce_only) is not bool:
            raise TypeError("reduce_only must be a bool or None")

        _, created = _check_utc_timestamp(self.created_at_utc, "created_at_utc")
        _, observed = _check_utc_timestamp(self.observed_at_utc, "observed_at_utc")
        if created > observed:
            raise ValueError("created_at_utc must not follow observed_at_utc")

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource.to_dict(),
            "instrument": self.instrument.to_dict(),
            "order_id": self.order_id,
            "side": self.side,
            "position_side": self.position_side,
            "order_type": self.order_type,
            "status": self.status,
            "quantity": self.quantity,
            "filled_quantity": self.filled_quantity,
            "qty_unit": self.qty_unit,
            "created_at_utc": self.created_at_utc,
            "observed_at_utc": self.observed_at_utc,
            "client_order_id": self.client_order_id,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "price_currency": self.price_currency,
            "reduce_only": self.reduce_only,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> AccountOpenOrder:
        raw = _require_exact_mapping(mapping, cls._FIELDS, "account_open_order")
        return cls(
            resource=AccountResourceKey.from_dict(raw["resource"]),
            instrument=MarketInstrumentKey.from_dict(raw["instrument"]),
            order_id=raw["order_id"],
            side=raw["side"],
            position_side=raw["position_side"],
            order_type=raw["order_type"],
            status=raw["status"],
            quantity=raw["quantity"],
            filled_quantity=raw["filled_quantity"],
            qty_unit=raw["qty_unit"],
            created_at_utc=raw["created_at_utc"],
            observed_at_utc=raw["observed_at_utc"],
            client_order_id=raw["client_order_id"],
            limit_price=raw["limit_price"],
            stop_price=raw["stop_price"],
            price_currency=raw["price_currency"],
            reduce_only=raw["reduce_only"],
        )


@dataclass(frozen=True)
class AccountValuation:
    """Optional valuation explicitly reported by the provider in one currency."""

    currency: str
    available_cash: str | None
    equity: str | None
    observed_at_utc: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"currency", "available_cash", "equity", "observed_at_utc"}
    )

    def __post_init__(self) -> None:
        _check_text(self.currency, "currency")
        _check_decimal(self.available_cash, "available_cash", optional=True)
        _check_decimal(self.equity, "equity", optional=True)
        _check_utc_timestamp(self.observed_at_utc, "observed_at_utc")

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "available_cash": self.available_cash,
            "equity": self.equity,
            "observed_at_utc": self.observed_at_utc,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> AccountValuation:
        raw = _require_exact_mapping(mapping, cls._FIELDS, "account_valuation")
        return cls(
            currency=raw["currency"],
            available_cash=raw["available_cash"],
            equity=raw["equity"],
            observed_at_utc=raw["observed_at_utc"],
        )


@dataclass(frozen=True)
class AccountObservation:
    """Bounded provider snapshot with explicit resource coverage and completeness."""

    account_key: AccountKey
    observation_id: str
    coverage: tuple[AccountResourceKey, ...]
    balances: tuple[AccountBalance, ...]
    positions: tuple[AccountPosition, ...]
    valuation: AccountValuation | None
    started_at_utc: str
    completed_at_utc: str
    consistency: str
    balances_complete: bool
    positions_complete: bool
    open_orders: tuple[AccountOpenOrder, ...] | None = None
    open_orders_complete: bool = False

    _LEGACY_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "account_key",
            "observation_id",
            "coverage",
            "balances",
            "positions",
            "valuation",
            "started_at_utc",
            "completed_at_utc",
            "consistency",
            "balances_complete",
            "positions_complete",
        }
    )
    _FIELDS: ClassVar[frozenset[str]] = _LEGACY_FIELDS | frozenset(
        {"open_orders", "open_orders_complete"}
    )

    def __post_init__(self) -> None:
        if type(self.account_key) is not AccountKey:
            raise TypeError("account_key must be an AccountKey")
        _check_text(self.observation_id, "observation_id")
        coverage = _require_tuple(self.coverage, "coverage")
        balances = _require_tuple(self.balances, "balances")
        positions = _require_tuple(self.positions, "positions")
        open_orders = (
            None if self.open_orders is None else _require_tuple(self.open_orders, "open_orders")
        )
        if not coverage:
            raise ValueError("coverage must not be empty")
        if any(type(item) is not AccountResourceKey for item in coverage):
            raise TypeError("coverage entries must be AccountResourceKey values")
        if len(set(coverage)) != len(coverage):
            raise ValueError("coverage contains duplicates")
        if any(type(item) is not AccountBalance for item in balances):
            raise TypeError("balances entries must be AccountBalance values")
        if any(type(item) is not AccountPosition for item in positions):
            raise TypeError("positions entries must be AccountPosition values")
        if open_orders is not None and any(
            type(item) is not AccountOpenOrder for item in open_orders
        ):
            raise TypeError("open_orders entries must be AccountOpenOrder values")
        if self.valuation is not None and type(self.valuation) is not AccountValuation:
            raise TypeError("valuation must be an AccountValuation or None")
        if type(self.consistency) is not str:
            raise TypeError("consistency must be a string")
        if self.consistency not in {
            "provider_atomic",
            "multi_query",
        }:
            raise ValueError("consistency must be provider_atomic or multi_query")
        if type(self.balances_complete) is not bool:
            raise TypeError("balances_complete must be a bool")
        if type(self.positions_complete) is not bool:
            raise TypeError("positions_complete must be a bool")
        if type(self.open_orders_complete) is not bool:
            raise TypeError("open_orders_complete must be a bool")
        if open_orders is None and self.open_orders_complete:
            raise ValueError("open_orders_complete requires open_orders facts")

        _, started = _check_utc_timestamp(self.started_at_utc, "started_at_utc")
        _, completed = _check_utc_timestamp(self.completed_at_utc, "completed_at_utc")
        if started > completed:
            raise ValueError("started_at_utc must not follow completed_at_utc")

        coverage_set = set(coverage)
        balance_keys: set[tuple[AccountResourceKey, str]] = set()
        for balance in balances:
            if balance.resource not in coverage_set:
                raise ValueError("balance resource is outside observation coverage")
            row_time = _check_utc_timestamp(balance.observed_at_utc, "observed_at_utc")[1]
            if row_time > completed:
                raise ValueError("balance observation time must not follow completion")
            row_key = (balance.resource, balance.currency)
            if row_key in balance_keys:
                raise ValueError("duplicate balance row")
            balance_keys.add(row_key)

        position_keys: set[tuple[AccountResourceKey, MarketInstrumentKey, str]] = set()
        for position in positions:
            if position.resource not in coverage_set:
                raise ValueError("position resource is outside observation coverage")
            instrument = position.instrument
            if (
                instrument.provider != self.account_key.provider
                or instrument.venue != self.account_key.venue
                or instrument.environment != self.account_key.environment
            ):
                raise ValueError("position instrument does not match the account identity")
            if instrument.product_type != position.resource.product_type:
                raise ValueError("position instrument product_type does not match its resource")
            row_time = _check_utc_timestamp(position.observed_at_utc, "observed_at_utc")[1]
            if row_time > completed:
                raise ValueError("position observation time must not follow completion")
            row_key = (position.resource, instrument, position.side)
            if row_key in position_keys:
                raise ValueError("duplicate position row")
            position_keys.add(row_key)

        order_keys: set[tuple[AccountResourceKey, MarketInstrumentKey, str]] = set()
        for order in open_orders or ():
            if order.resource not in coverage_set:
                raise ValueError("open order resource is outside observation coverage")
            instrument = order.instrument
            if (
                instrument.provider != self.account_key.provider
                or instrument.venue != self.account_key.venue
                or instrument.environment != self.account_key.environment
            ):
                raise ValueError("open order instrument does not match the account identity")
            if instrument.product_type != order.resource.product_type:
                raise ValueError("open order instrument product_type does not match its resource")
            created_at = _check_utc_timestamp(order.created_at_utc, "created_at_utc")[1]
            observed_at = _check_utc_timestamp(order.observed_at_utc, "observed_at_utc")[1]
            if created_at > observed_at:
                raise ValueError("open order created_at_utc must not follow observed_at_utc")
            if observed_at > completed:
                raise ValueError("open order observation time must not follow completion")
            row_key = (order.resource, instrument, order.order_id)
            if row_key in order_keys:
                raise ValueError("duplicate open order row")
            order_keys.add(row_key)

        if self.valuation is not None:
            valuation_time = _check_utc_timestamp(
                self.valuation.observed_at_utc, "observed_at_utc"
            )[1]
            if valuation_time > completed:
                raise ValueError("valuation observation time must not follow completion")

        if len(_canonical_json_bytes(self.to_dict())) > MAX_ACCOUNT_OBSERVATION_BYTES:
            raise ValueError("serialized observation exceeds the byte limit")

    def to_dict(self) -> dict[str, Any]:
        result = {
            "account_key": self.account_key.to_dict(),
            "observation_id": self.observation_id,
            "coverage": [item.to_dict() for item in self.coverage],
            "balances": [item.to_dict() for item in self.balances],
            "positions": [item.to_dict() for item in self.positions],
            "valuation": None if self.valuation is None else self.valuation.to_dict(),
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "consistency": self.consistency,
            "balances_complete": self.balances_complete,
            "positions_complete": self.positions_complete,
        }
        if self.open_orders is not None:
            result["open_orders"] = [item.to_dict() for item in self.open_orders]
            result["open_orders_complete"] = self.open_orders_complete
        return result

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> AccountObservation:
        if isinstance(mapping, Mapping) and all(type(key) is str for key in mapping):
            supplied_fields = frozenset(mapping)
            expected_fields = (
                cls._LEGACY_FIELDS if supplied_fields == cls._LEGACY_FIELDS else cls._FIELDS
            )
        else:
            expected_fields = cls._LEGACY_FIELDS
        raw = _require_exact_mapping(mapping, expected_fields, "account_observation")
        coverage = tuple(
            AccountResourceKey.from_dict(item) for item in _dict_array(raw["coverage"], "coverage")
        )
        balances = tuple(
            AccountBalance.from_dict(item) for item in _dict_array(raw["balances"], "balances")
        )
        positions = tuple(
            AccountPosition.from_dict(item) for item in _dict_array(raw["positions"], "positions")
        )
        has_open_orders = "open_orders" in raw
        open_orders = (
            tuple(
                AccountOpenOrder.from_dict(item)
                for item in _dict_array(raw["open_orders"], "open_orders")
            )
            if has_open_orders
            else None
        )
        valuation_raw = raw["valuation"]
        valuation = None if valuation_raw is None else AccountValuation.from_dict(valuation_raw)
        return cls(
            account_key=AccountKey.from_dict(raw["account_key"]),
            observation_id=raw["observation_id"],
            coverage=coverage,
            balances=balances,
            positions=positions,
            valuation=valuation,
            started_at_utc=raw["started_at_utc"],
            completed_at_utc=raw["completed_at_utc"],
            consistency=raw["consistency"],
            balances_complete=raw["balances_complete"],
            positions_complete=raw["positions_complete"],
            open_orders=open_orders,
            open_orders_complete=raw["open_orders_complete"] if has_open_orders else False,
        )


__all__ = [
    "MAX_ACCOUNT_OBSERVATION_BYTES",
    "MAX_ACCOUNT_ROWS",
    "AccountBalance",
    "AccountKey",
    "AccountOpenOrder",
    "AccountObservation",
    "AccountPosition",
    "AccountResourceKey",
    "AccountValuation",
]
