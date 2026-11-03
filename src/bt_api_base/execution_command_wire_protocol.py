"""Restricted neutral strategy command declarations for optional transport.

These DTOs do not reserve an idempotency key, authenticate a principal, prove
an account/strategy binding, authorize dispatch or establish provider truth.
The SDK must independently establish all those facts before doing any work.
They support only the explicit fields and enum values below. In particular,
venue-native identity, authorization labels, bulk/conditional orders and
arbitrary extensions are not representable. An adapter must reject rather than
drop SDK request fields which this contract cannot represent.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from bt_api_base.account_protocol import AccountKey, account_venue_contains_instrument_venue
from bt_api_base.execution_query_protocol import _decimal, _text
from bt_api_base.market_protocol import MarketInstrumentKey

_MAX_INT64 = 2**63 - 1
_QUANTITY_UNITS = frozenset({"base", "contracts", "lots", "native"})
_TIME_IN_FORCE = frozenset({"GTC", "GFD", "DAY", "IOC", "FOK"})
_POSITION_SIDE = frozenset({"long", "short", "net"})
_EFFECT = frozenset({"open", "close", "close_today", "close_yesterday"})
_POSITION_MODE = frozenset({"net", "dual_side"})
_HEDGE_CLASS = frozenset({"speculation", "arbitrage", "hedge"})


def _scope(account: Any, instrument: Any) -> None:
    if type(account) is not AccountKey or type(instrument) is not MarketInstrumentKey:
        raise TypeError("expected an AccountKey and MarketInstrumentKey")
    if (
        instrument.provider != account.provider
        or instrument.environment != account.environment
        or not account_venue_contains_instrument_venue(account, instrument.venue)
    ):
        raise ValueError("instrument does not match the account scope")


def _refs(obj: Any) -> None:
    for name in ("route", "strategy_ref", "run_id", "request_id", "idempotency_key"):
        _text(getattr(obj, name), name)


def _optional_enum(value: Any, allowed: frozenset[str], name: str) -> None:
    if value is not None and (type(value) is not str or value not in allowed):
        raise ValueError(name + " is unsupported")


def _optional_ns(value: Any, name: str) -> None:
    if value is not None and (type(value) is not int or not 0 < value <= _MAX_INT64):
        raise ValueError(name + " must be a positive signed-64-bit integer or None")


def _mapping(value: Any, cls: Any) -> dict[str, Any]:
    expected = {field.name for field in fields(cls)}
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError("command must be a string-keyed mapping")
    if set(value) != expected:
        raise ValueError("command must have exactly the supported fields")
    result = dict(value)
    result["account_key"] = AccountKey.from_dict(result["account_key"])
    if "instrument" in result:
        result["instrument"] = MarketInstrumentKey.from_dict(result["instrument"])
    return result


def _to_dict(value: Any) -> dict[str, Any]:
    if set(vars(value)) != {field.name for field in fields(value)}:
        raise ValueError("command contains unsupported fields")
    if set(vars(value.account_key)) != AccountKey._FIELDS:
        raise ValueError("account key contains unsupported fields")
    instrument = getattr(value, "instrument", None)
    if instrument is not None and set(vars(instrument)) != MarketInstrumentKey._FIELDS:
        raise ValueError("instrument contains unsupported fields")
    result = {field.name: getattr(value, field.name) for field in fields(value)}
    result["account_key"] = value.account_key.to_dict()
    if "instrument" in result:
        result["instrument"] = value.instrument.to_dict()
    return result


@dataclass(frozen=True)
class StrategySubmitCommand:
    """A restricted strategy submit declaration; not a verified order intent.

    Quantity is an exact decimal string in ``quantity_unit``. A limit price is
    an exact decimal string in ``price_currency`` if specified, otherwise its
    currency is unknown. A market order has neither. The optional UTC epoch-ns
    deadline is a caller declaration; None does not establish validity.
    """

    account_key: AccountKey
    instrument: MarketInstrumentKey
    route: str
    strategy_ref: str
    run_id: str
    request_id: str
    idempotency_key: str
    client_order_id: str
    side: str
    order_type: str
    quantity: str
    quantity_unit: str
    limit_price: str | None
    price_currency: str | None
    time_in_force: str
    valid_until_utc_ns: int | None
    reduce_only: bool
    position_side: str | None
    position_effect: str | None
    position_mode: str | None
    hedge_class: str | None

    def __post_init__(self) -> None:
        _scope(self.account_key, self.instrument)
        _refs(self)
        _text(self.client_order_id, "client_order_id")
        if type(self.side) is not str or self.side not in {"buy", "sell"}:
            raise ValueError("side is unsupported")
        if type(self.order_type) is not str or self.order_type not in {"market", "limit"}:
            raise ValueError("order_type is unsupported")
        _decimal(self.quantity, "quantity", positive=True)
        if type(self.quantity_unit) is not str or self.quantity_unit not in _QUANTITY_UNITS:
            raise ValueError("quantity_unit is unsupported")
        _decimal(self.limit_price, "limit_price", optional=True, positive=True)
        _text(self.price_currency, "price_currency", optional=True)
        if (self.order_type == "limit") != (self.limit_price is not None):
            raise ValueError("order_type and limit_price do not match")
        if self.limit_price is None and self.price_currency is not None:
            raise ValueError("market order cannot carry a limit price currency")
        if type(self.time_in_force) is not str or self.time_in_force not in _TIME_IN_FORCE:
            raise ValueError("time_in_force is unsupported")
        _optional_ns(self.valid_until_utc_ns, "valid_until_utc_ns")
        if type(self.reduce_only) is not bool:
            raise TypeError("reduce_only must be a bool")
        _optional_enum(self.position_side, _POSITION_SIDE, "position_side")
        _optional_enum(self.position_effect, _EFFECT, "position_effect")
        _optional_enum(self.position_mode, _POSITION_MODE, "position_mode")
        _optional_enum(self.hedge_class, _HEDGE_CLASS, "hedge_class")
        if self.reduce_only and self.position_effect == "open":
            raise ValueError("reduce_only conflicts with opening a position")

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StrategySubmitCommand:
        return cls(**_mapping(value, cls))


@dataclass(frozen=True)
class StrategyCancelCommand:
    """A correlated cancel declaration; the client ID is still unverified."""

    account_key: AccountKey
    instrument: MarketInstrumentKey
    route: str
    strategy_ref: str
    run_id: str
    request_id: str
    idempotency_key: str
    client_order_id: str
    provider_order_ref: str | None
    valid_until_utc_ns: int | None

    def __post_init__(self) -> None:
        _scope(self.account_key, self.instrument)
        _refs(self)
        _text(self.client_order_id, "client_order_id")
        _text(self.provider_order_ref, "provider_order_ref", optional=True)
        _optional_ns(self.valid_until_utc_ns, "valid_until_utc_ns")

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StrategyCancelCommand:
        return cls(**_mapping(value, cls))


@dataclass(frozen=True)
class StrategyCommandResult:
    """A command outcome declaration, never provider order terminality proof.

    ``accepted`` is an acknowledgement only; it does not mean filled or even
    prove that an authenticated provider accepted anything. ``unknown`` must
    not be interpreted as rejection or safe permission to resubmit.
    """

    account_key: AccountKey
    route: str
    strategy_ref: str
    run_id: str
    request_id: str
    idempotency_key: str
    operation: str
    outcome: str
    provider_order_ref: str | None
    reason_code: str | None
    observed_at_utc_ns: int | None
    source_precision_ns: int | None

    def __post_init__(self) -> None:
        if type(self.account_key) is not AccountKey:
            raise TypeError("account_key must be an AccountKey")
        _refs(self)
        if type(self.operation) is not str or self.operation not in {"submit", "cancel"}:
            raise ValueError("operation is unsupported")
        if type(self.outcome) is not str or self.outcome not in {"unknown", "accepted", "rejected"}:
            raise ValueError("outcome is unsupported")
        _text(self.provider_order_ref, "provider_order_ref", optional=True)
        _text(self.reason_code, "reason_code", optional=True)
        _optional_ns(self.observed_at_utc_ns, "observed_at_utc_ns")
        _optional_ns(self.source_precision_ns, "source_precision_ns")
        if self.observed_at_utc_ns is None and self.source_precision_ns is not None:
            raise ValueError("source precision requires an observed time")

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StrategyCommandResult:
        return cls(**_mapping(value, cls))


__all__ = ("StrategySubmitCommand", "StrategyCancelCommand", "StrategyCommandResult")
