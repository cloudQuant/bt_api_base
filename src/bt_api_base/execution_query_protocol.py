"""Provider-neutral execution observations and instrument rate contracts.

These records are observations carried by the versioned query facade. Their
fields describe public trading facts only. They do not prove an order intent,
reserve funds, authorize dispatch, or make a provider-specific identifier
safe to expose. Providers should use opaque SDK references for order/trade
identity and keep any native identity mapping inside the provider package.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from bt_api_base.account_protocol import AccountResourceKey
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import MAX_REFERENCE_BYTES

_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z", re.ASCII)
_UTC_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z\Z",
    re.ASCII,
)
_ORDER_STATUSES = frozenset(
    {
        "open",
        "partially_filled",
        "partially_filled_canceled",
        "partially_filled_terminal",
        "terminal_unfilled",
        "unknown",
        "filled",
        "canceled",
        "rejected",
        "trigger_pending",
        "triggered",
    }
)
_CORRELATION_STATES = frozenset({"verified", "unresolved"})
_ORDER_BINDING_STATES = frozenset({"provider_order_identity", "unresolved"})
_FEE_ROLES = frozenset({"open", "close", "close_today"})
_RATE_SCOPES = frozenset({"broker_default", "account_override", "unresolved"})
_CURRENCY_STATES = frozenset({"verified", "unavailable"})
_HEDGE_CLASSES = frozenset({"speculation", "arbitrage", "hedge"})
_POSITION_EFFECTS = frozenset(
    {"open", "close", "close_today", "close_yesterday", "unavailable"}
)
_POSITION_SIDES = frozenset({"long", "short"})
_FACT_STATES = frozenset({"verified", "unavailable"})
NOTIONAL_RATE_UNIT_FRACTION_OF_NOTIONAL = "fraction_of_notional"
RATE_AMOUNT_UNIT_CURRENCY_PER_CONTRACT = "currency_per_contract"
_ORDER_FIELDS = frozenset(
    {
        "resource",
        "instrument",
        "order_id",
        "client_order_id",
        "intent_binding",
        "side",
        "position_effect",
        "position_side",
        "position_side_status",
        "order_type",
        "status",
        "quantity",
        "filled_quantity",
        "qty_unit",
        "limit_price",
        "price_currency",
        "price_currency_status",
        "created_at_utc",
        "created_at_status",
        "observed_at_utc",
    }
)
_TRADE_FIELDS = frozenset(
    {
        "resource",
        "instrument",
        "trade_id",
        "order_id",
        "order_binding",
        "side",
        "position_effect",
        "position_side",
        "position_side_status",
        "quantity",
        "qty_unit",
        "price",
        "price_currency",
        "price_currency_status",
        "traded_at_utc",
        "traded_at_status",
        "observed_at_utc",
    }
)
_COMMISSION_FIELDS = frozenset(
    {
        "resource",
        "instrument",
        "fee_role",
        "notional_rate",
        "notional_rate_unit",
        "amount_per_contract",
        "amount_unit",
        "currency",
        "currency_status",
        "schedule_scope",
    }
)
_MARGIN_FIELDS = frozenset(
    {
        "resource",
        "instrument",
        "hedge_class",
        "position_side",
        "notional_rate",
        "notional_rate_unit",
        "amount_per_contract",
        "amount_unit",
        "currency",
        "currency_status",
        "schedule_scope",
    }
)


def _text(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise TypeError(f"{field} must be a string" + (" or None" if optional else ""))
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} must be valid UTF-8") from exc
    if (
        not value
        or value != value.strip()
        or not value.isprintable()
        or size > MAX_REFERENCE_BYTES
    ):
        raise ValueError(f"{field} must be bounded, trimmed printable UTF-8")
    return value


def _decimal(value: Any, field: str, *, optional: bool = False, positive: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or not value or len(value) > 128 or value != value.strip():
        raise ValueError(f"{field} must be a bounded decimal string")
    if not _DECIMAL_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be a bounded decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a bounded decimal string") from exc
    if not number.is_finite() or (number <= 0 if positive else number < 0):
        raise ValueError(f"{field} is outside its supported range")
    return value


def _utc(value: Any, field: str) -> str:
    if type(value) is not str or not _UTC_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp ending in Z") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError(f"{field} must be UTC")
    return value


def _exact_mapping(value: Any, fields: frozenset[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} must contain exactly the published fields")
    return value


@dataclass(frozen=True)
class ExecutionOrderRecord:
    """One provider-observed order with a neutral opaque order reference.

    ``order_id`` identifies the provider-observed order only. It must not be
    a native order identity. ``intent_binding`` is independent: unresolved
    records carry no client order ID and must not be treated as linked to a
    Backtrader order or strategy intent.
    """

    resource: AccountResourceKey
    instrument: MarketInstrumentKey
    order_id: str
    client_order_id: str | None
    intent_binding: str
    side: str
    position_effect: str
    position_side: str | None
    position_side_status: str
    order_type: str
    status: str
    quantity: str
    filled_quantity: str
    qty_unit: str
    limit_price: str | None
    price_currency: str | None
    price_currency_status: str
    created_at_utc: str | None
    created_at_status: str
    observed_at_utc: str

    def __post_init__(self) -> None:
        if type(self.resource) is not AccountResourceKey:
            raise TypeError("resource must be an AccountResourceKey")
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be a MarketInstrumentKey")
        _text(self.order_id, "order_id")
        _text(self.client_order_id, "client_order_id", optional=True)
        if type(self.intent_binding) is not str or self.intent_binding not in _CORRELATION_STATES:
            raise ValueError("intent_binding must be verified or unresolved")
        if (self.intent_binding == "verified") != (self.client_order_id is not None):
            raise ValueError("verified intent binding requires a client_order_id")
        if type(self.side) is not str or self.side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if type(self.position_effect) is not str or self.position_effect not in _POSITION_EFFECTS:
            raise ValueError("position_effect is unsupported")
        _text(self.position_side, "position_side", optional=True)
        if type(self.position_side_status) is not str or self.position_side_status not in _FACT_STATES:
            raise ValueError("position_side_status is unsupported")
        if self.position_side is not None and self.position_side not in _POSITION_SIDES:
            raise ValueError("position_side must be long, short, or None")
        if (self.position_side_status == "verified") != (self.position_side is not None):
            raise ValueError("position-side status does not match position_side")
        if self.position_effect == "unavailable" and self.position_side is not None:
            raise ValueError("unavailable position effect cannot carry a position_side")
        _text(self.order_type, "order_type")
        if type(self.status) is not str or self.status not in _ORDER_STATUSES:
            raise ValueError("status is unsupported")
        quantity = _decimal(self.quantity, "quantity", positive=True)
        filled = _decimal(self.filled_quantity, "filled_quantity")
        assert quantity is not None and filled is not None
        if Decimal(filled) > Decimal(quantity):
            raise ValueError("filled_quantity must not exceed quantity")
        _text(self.qty_unit, "qty_unit")
        _decimal(self.limit_price, "limit_price", optional=True, positive=True)
        _text(self.price_currency, "price_currency", optional=True)
        if type(self.price_currency_status) is not str or self.price_currency_status not in _FACT_STATES:
            raise ValueError("price_currency_status is unsupported")
        if (self.price_currency_status == "verified") != (self.price_currency is not None):
            raise ValueError("price-currency status does not match price_currency")
        _text(self.created_at_utc, "created_at_utc", optional=True)
        if self.created_at_utc is not None:
            _utc(self.created_at_utc, "created_at_utc")
        if type(self.created_at_status) is not str or self.created_at_status not in _FACT_STATES:
            raise ValueError("created_at_status is unsupported")
        if (self.created_at_status == "verified") != (self.created_at_utc is not None):
            raise ValueError("creation-time status does not match created_at_utc")
        _utc(self.observed_at_utc, "observed_at_utc")

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource.to_dict(),
            "instrument": self.instrument.to_dict(),
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "intent_binding": self.intent_binding,
            "side": self.side,
            "position_effect": self.position_effect,
            "position_side": self.position_side,
            "position_side_status": self.position_side_status,
            "order_type": self.order_type,
            "status": self.status,
            "quantity": self.quantity,
            "filled_quantity": self.filled_quantity,
            "qty_unit": self.qty_unit,
            "limit_price": self.limit_price,
            "price_currency": self.price_currency,
            "price_currency_status": self.price_currency_status,
            "created_at_utc": self.created_at_utc,
            "created_at_status": self.created_at_status,
            "observed_at_utc": self.observed_at_utc,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> ExecutionOrderRecord:
        raw = _exact_mapping(mapping, _ORDER_FIELDS, "execution_order")
        return cls(
            resource=AccountResourceKey.from_dict(raw["resource"]),
            instrument=MarketInstrumentKey.from_dict(raw["instrument"]),
            order_id=raw["order_id"],
            client_order_id=raw["client_order_id"],
            intent_binding=raw["intent_binding"],
            side=raw["side"],
            position_effect=raw["position_effect"],
            position_side=raw["position_side"],
            position_side_status=raw["position_side_status"],
            order_type=raw["order_type"],
            status=raw["status"],
            quantity=raw["quantity"],
            filled_quantity=raw["filled_quantity"],
            qty_unit=raw["qty_unit"],
            limit_price=raw["limit_price"],
            price_currency=raw["price_currency"],
            price_currency_status=raw["price_currency_status"],
            created_at_utc=raw["created_at_utc"],
            created_at_status=raw["created_at_status"],
            observed_at_utc=raw["observed_at_utc"],
        )


@dataclass(frozen=True)
class ExecutionTradeRecord:
    """One provider-observed fill; order identity need not mean intent identity."""

    resource: AccountResourceKey
    instrument: MarketInstrumentKey
    trade_id: str
    order_id: str | None
    order_binding: str
    side: str
    position_effect: str
    position_side: str | None
    position_side_status: str
    quantity: str
    qty_unit: str
    price: str
    price_currency: str | None
    price_currency_status: str
    traded_at_utc: str | None
    traded_at_status: str
    observed_at_utc: str

    def __post_init__(self) -> None:
        if type(self.resource) is not AccountResourceKey:
            raise TypeError("resource must be an AccountResourceKey")
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be a MarketInstrumentKey")
        _text(self.trade_id, "trade_id")
        _text(self.order_id, "order_id", optional=True)
        if type(self.order_binding) is not str or self.order_binding not in _ORDER_BINDING_STATES:
            raise ValueError("order_binding is unsupported")
        if (self.order_binding == "provider_order_identity") != (self.order_id is not None):
            raise ValueError("provider-order binding requires an order_id")
        if type(self.side) is not str or self.side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if type(self.position_effect) is not str or self.position_effect not in _POSITION_EFFECTS:
            raise ValueError("position_effect is unsupported")
        _text(self.position_side, "position_side", optional=True)
        if type(self.position_side_status) is not str or self.position_side_status not in _FACT_STATES:
            raise ValueError("position_side_status is unsupported")
        if self.position_side is not None and self.position_side not in _POSITION_SIDES:
            raise ValueError("position_side must be long, short, or None")
        if (self.position_side_status == "verified") != (self.position_side is not None):
            raise ValueError("position-side status does not match position_side")
        if self.position_effect == "unavailable" and self.position_side is not None:
            raise ValueError("unavailable position effect cannot carry a position_side")
        _decimal(self.quantity, "quantity", positive=True)
        _text(self.qty_unit, "qty_unit")
        _decimal(self.price, "price", positive=True)
        _text(self.price_currency, "price_currency", optional=True)
        if type(self.price_currency_status) is not str or self.price_currency_status not in _FACT_STATES:
            raise ValueError("price_currency_status is unsupported")
        if (self.price_currency_status == "verified") != (self.price_currency is not None):
            raise ValueError("price-currency status does not match price_currency")
        _text(self.traded_at_utc, "traded_at_utc", optional=True)
        if self.traded_at_utc is not None:
            _utc(self.traded_at_utc, "traded_at_utc")
        if type(self.traded_at_status) is not str or self.traded_at_status not in _FACT_STATES:
            raise ValueError("traded_at_status is unsupported")
        if (self.traded_at_status == "verified") != (self.traded_at_utc is not None):
            raise ValueError("trade-time status does not match traded_at_utc")
        _utc(self.observed_at_utc, "observed_at_utc")

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource.to_dict(),
            "instrument": self.instrument.to_dict(),
            "trade_id": self.trade_id,
            "order_id": self.order_id,
            "order_binding": self.order_binding,
            "side": self.side,
            "position_effect": self.position_effect,
            "position_side": self.position_side,
            "position_side_status": self.position_side_status,
            "quantity": self.quantity,
            "qty_unit": self.qty_unit,
            "price": self.price,
            "price_currency": self.price_currency,
            "price_currency_status": self.price_currency_status,
            "traded_at_utc": self.traded_at_utc,
            "traded_at_status": self.traded_at_status,
            "observed_at_utc": self.observed_at_utc,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> ExecutionTradeRecord:
        raw = _exact_mapping(mapping, _TRADE_FIELDS, "execution_trade")
        return cls(
            resource=AccountResourceKey.from_dict(raw["resource"]),
            instrument=MarketInstrumentKey.from_dict(raw["instrument"]),
            trade_id=raw["trade_id"],
            order_id=raw["order_id"],
            order_binding=raw["order_binding"],
            side=raw["side"],
            position_effect=raw["position_effect"],
            position_side=raw["position_side"],
            position_side_status=raw["position_side_status"],
            quantity=raw["quantity"],
            qty_unit=raw["qty_unit"],
            price=raw["price"],
            price_currency=raw["price_currency"],
            price_currency_status=raw["price_currency_status"],
            traded_at_utc=raw["traded_at_utc"],
            traded_at_status=raw["traded_at_status"],
            observed_at_utc=raw["observed_at_utc"],
        )


@dataclass(frozen=True)
class CommissionRateRecord:
    """One commission-rate dimension; missing currency remains unavailable."""

    resource: AccountResourceKey
    instrument: MarketInstrumentKey
    fee_role: str
    notional_rate: str | None
    notional_rate_unit: str | None
    amount_per_contract: str | None
    amount_unit: str | None
    currency: str | None
    currency_status: str
    schedule_scope: str

    def __post_init__(self) -> None:
        if type(self.resource) is not AccountResourceKey:
            raise TypeError("resource must be an AccountResourceKey")
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be a MarketInstrumentKey")
        if type(self.fee_role) is not str or self.fee_role not in _FEE_ROLES:
            raise ValueError("fee_role is unsupported")
        notional = _decimal(self.notional_rate, "notional_rate", optional=True)
        amount = _decimal(self.amount_per_contract, "amount_per_contract", optional=True)
        if notional is None and amount is None:
            raise ValueError("at least one commission dimension is required")
        if (
            notional is not None
            and self.notional_rate_unit != NOTIONAL_RATE_UNIT_FRACTION_OF_NOTIONAL
        ) or (
            notional is None and self.notional_rate_unit is not None
        ):
            raise ValueError("notional_rate_unit does not match notional_rate")
        if (amount is not None and self.amount_unit != RATE_AMOUNT_UNIT_CURRENCY_PER_CONTRACT) or (
            amount is None and self.amount_unit is not None
        ):
            raise ValueError("amount_unit does not match amount_per_contract")
        _text(self.currency, "currency", optional=True)
        if type(self.currency_status) is not str or self.currency_status not in _CURRENCY_STATES:
            raise ValueError("currency_status is unsupported")
        if (self.currency_status == "verified") != (self.currency is not None):
            raise ValueError("currency verification status does not match currency value")
        if type(self.schedule_scope) is not str or self.schedule_scope not in _RATE_SCOPES:
            raise ValueError("schedule_scope is unsupported")

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource.to_dict(),
            "instrument": self.instrument.to_dict(),
            "fee_role": self.fee_role,
            "notional_rate": self.notional_rate,
            "notional_rate_unit": self.notional_rate_unit,
            "amount_per_contract": self.amount_per_contract,
            "amount_unit": self.amount_unit,
            "currency": self.currency,
            "currency_status": self.currency_status,
            "schedule_scope": self.schedule_scope,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> CommissionRateRecord:
        raw = _exact_mapping(mapping, _COMMISSION_FIELDS, "commission_rate")
        return cls(
            resource=AccountResourceKey.from_dict(raw["resource"]),
            instrument=MarketInstrumentKey.from_dict(raw["instrument"]),
            fee_role=raw["fee_role"],
            notional_rate=raw["notional_rate"],
            notional_rate_unit=raw["notional_rate_unit"],
            amount_per_contract=raw["amount_per_contract"],
            amount_unit=raw["amount_unit"],
            currency=raw["currency"],
            currency_status=raw["currency_status"],
            schedule_scope=raw["schedule_scope"],
        )


@dataclass(frozen=True)
class MarginRateRecord:
    """One margin-rate dimension; missing currency remains unavailable."""

    resource: AccountResourceKey
    instrument: MarketInstrumentKey
    hedge_class: str
    position_side: str
    notional_rate: str | None
    notional_rate_unit: str | None
    amount_per_contract: str | None
    amount_unit: str | None
    currency: str | None
    currency_status: str
    schedule_scope: str

    def __post_init__(self) -> None:
        if type(self.resource) is not AccountResourceKey:
            raise TypeError("resource must be an AccountResourceKey")
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be a MarketInstrumentKey")
        if type(self.hedge_class) is not str or self.hedge_class not in _HEDGE_CLASSES:
            raise ValueError("hedge_class is unsupported")
        if type(self.position_side) is not str or self.position_side not in {"long", "short"}:
            raise ValueError("position_side must be long or short")
        notional = _decimal(self.notional_rate, "notional_rate", optional=True)
        amount = _decimal(self.amount_per_contract, "amount_per_contract", optional=True)
        if notional is None and amount is None:
            raise ValueError("at least one margin dimension is required")
        if (
            notional is not None
            and self.notional_rate_unit != NOTIONAL_RATE_UNIT_FRACTION_OF_NOTIONAL
        ) or (
            notional is None and self.notional_rate_unit is not None
        ):
            raise ValueError("notional_rate_unit does not match notional_rate")
        if (amount is not None and self.amount_unit != RATE_AMOUNT_UNIT_CURRENCY_PER_CONTRACT) or (
            amount is None and self.amount_unit is not None
        ):
            raise ValueError("amount_unit does not match amount_per_contract")
        _text(self.currency, "currency", optional=True)
        if type(self.currency_status) is not str or self.currency_status not in _CURRENCY_STATES:
            raise ValueError("currency_status is unsupported")
        if (self.currency_status == "verified") != (self.currency is not None):
            raise ValueError("currency verification status does not match currency value")
        if type(self.schedule_scope) is not str or self.schedule_scope not in _RATE_SCOPES:
            raise ValueError("schedule_scope is unsupported")

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource.to_dict(),
            "instrument": self.instrument.to_dict(),
            "hedge_class": self.hedge_class,
            "position_side": self.position_side,
            "notional_rate": self.notional_rate,
            "notional_rate_unit": self.notional_rate_unit,
            "amount_per_contract": self.amount_per_contract,
            "amount_unit": self.amount_unit,
            "currency": self.currency,
            "currency_status": self.currency_status,
            "schedule_scope": self.schedule_scope,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> MarginRateRecord:
        raw = _exact_mapping(mapping, _MARGIN_FIELDS, "margin_rate")
        return cls(
            resource=AccountResourceKey.from_dict(raw["resource"]),
            instrument=MarketInstrumentKey.from_dict(raw["instrument"]),
            hedge_class=raw["hedge_class"],
            position_side=raw["position_side"],
            notional_rate=raw["notional_rate"],
            notional_rate_unit=raw["notional_rate_unit"],
            amount_per_contract=raw["amount_per_contract"],
            amount_unit=raw["amount_unit"],
            currency=raw["currency"],
            currency_status=raw["currency_status"],
            schedule_scope=raw["schedule_scope"],
        )


__all__ = [
    "CommissionRateRecord",
    "ExecutionOrderRecord",
    "ExecutionTradeRecord",
    "MarginRateRecord",
    "NOTIONAL_RATE_UNIT_FRACTION_OF_NOTIONAL",
    "RATE_AMOUNT_UNIT_CURRENCY_PER_CONTRACT",
]
