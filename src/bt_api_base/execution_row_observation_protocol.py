"""Account-scoped execution observations; not identity or permission proof.

The enclosed order/trade record describes a provider observation only.  Its
binding fields remain declarations and require independent source and intent
verification at the receiver. A trade record does not include fee facts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any, ClassVar

from bt_api_base.account_protocol import AccountKey, account_venue_contains_instrument_venue
from bt_api_base.execution_query_protocol import ExecutionOrderRecord, ExecutionTradeRecord


def _check_scope(account: AccountKey, record: Any) -> None:
    instrument = record.instrument
    if (
        instrument.provider != account.provider
        or instrument.environment != account.environment
        or not account_venue_contains_instrument_venue(account, instrument.venue)
        or instrument.product_type != record.resource.product_type
    ):
        raise ValueError("execution observation does not match the account scope")


def _fields(value: object, expected: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError("execution observation must be a string-keyed mapping")
    if set(value) != expected:
        raise ValueError("execution observation has an invalid field set")
    return value


def _require_declared_state(account: Any, row: Any, wrapper: Any) -> None:
    """Reject attached fields that these DTOs cannot represent on the wire.

    Frozen dataclasses are not a reflection or security boundary; checking the
    instance state avoids silently dropping an extension attached in process.
    Exact type and value validation still happens in each DTO's constructor.
    """
    for obj in (wrapper, account, row, row.resource, row.instrument):
        if set(vars(obj)) != {field.name for field in fields(obj)}:
            raise ValueError("execution observation contains unsupported fields")


@dataclass(frozen=True)
class AccountExecutionOrderObservation:
    """One account-scoped provider order observation, not terminality proof.

    Provider state and cumulative quantity can disagree. Such discrepancies
    are retained as observations for reconciliation; consumers must bind the
    trusted source and independently confirm terminality and quantity before
    treating even a ``filled`` declaration as a terminal order fact.
    """

    account_key: AccountKey
    order: ExecutionOrderRecord
    _FIELDS: ClassVar[frozenset[str]] = frozenset({"account_key", "order"})

    def __post_init__(self) -> None:
        if type(self.account_key) is not AccountKey or type(self.order) is not ExecutionOrderRecord:
            raise TypeError("expected an AccountKey and ExecutionOrderRecord")
        _check_scope(self.account_key, self.order)

    def to_dict(self) -> dict[str, Any]:
        _require_declared_state(self.account_key, self.order, self)
        return {"account_key": self.account_key.to_dict(), "order": self.order.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AccountExecutionOrderObservation:
        raw = _fields(value, cls._FIELDS)
        return cls(
            AccountKey.from_dict(raw["account_key"]), ExecutionOrderRecord.from_dict(raw["order"])
        )


@dataclass(frozen=True)
class AccountExecutionTradeObservation:
    """One account-scoped execution observation; fees remain separately unknown."""

    account_key: AccountKey
    trade: ExecutionTradeRecord
    _FIELDS: ClassVar[frozenset[str]] = frozenset({"account_key", "trade"})

    def __post_init__(self) -> None:
        if type(self.account_key) is not AccountKey or type(self.trade) is not ExecutionTradeRecord:
            raise TypeError("expected an AccountKey and ExecutionTradeRecord")
        _check_scope(self.account_key, self.trade)

    def to_dict(self) -> dict[str, Any]:
        _require_declared_state(self.account_key, self.trade, self)
        return {"account_key": self.account_key.to_dict(), "trade": self.trade.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AccountExecutionTradeObservation:
        raw = _fields(value, cls._FIELDS)
        return cls(
            AccountKey.from_dict(raw["account_key"]), ExecutionTradeRecord.from_dict(raw["trade"])
        )


__all__ = ("AccountExecutionOrderObservation", "AccountExecutionTradeObservation")
