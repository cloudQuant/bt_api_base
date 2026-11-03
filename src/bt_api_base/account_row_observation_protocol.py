"""Single provider account rows scoped to a declared account key.

These are data, not authentication or journal evidence.  A position row is
not a complete account snapshot, and the absence of a row does not mean zero.
An open-order row is not a terminal order event or a strategy binding.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from bt_api_base.account_protocol import (
    AccountKey,
    AccountOpenOrder,
    AccountPosition,
    account_venue_contains_instrument_venue,
)


def _check_scope(account_key: AccountKey, row: AccountPosition | AccountOpenOrder) -> None:
    instrument = row.instrument
    if (
        instrument.provider != account_key.provider
        or not account_venue_contains_instrument_venue(account_key, instrument.venue)
        or instrument.environment != account_key.environment
        or instrument.product_type != row.resource.product_type
    ):
        raise ValueError("account row does not match the account scope")


def _fields(value: object, expected: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError("account row observation must be a string-keyed mapping")
    if set(value) != expected:
        raise ValueError("account row observation has an invalid field set")
    return value


@dataclass(frozen=True)
class AccountPositionObservation:
    """One account-scoped position row, without a completeness assertion."""

    account_key: AccountKey
    position: AccountPosition

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"account_key", "position"})

    def __post_init__(self) -> None:
        if type(self.account_key) is not AccountKey or type(self.position) is not AccountPosition:
            raise TypeError("expected an AccountKey and AccountPosition")
        _check_scope(self.account_key, self.position)

    def to_dict(self) -> dict[str, Any]:
        return {"account_key": self.account_key.to_dict(), "position": self.position.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AccountPositionObservation:
        raw = _fields(value, cls._FIELDS)
        return cls(
            AccountKey.from_dict(raw["account_key"]), AccountPosition.from_dict(raw["position"])
        )


@dataclass(frozen=True)
class AccountOpenOrderObservation:
    """One open-order row, without terminal or strategy ownership claims."""

    account_key: AccountKey
    open_order: AccountOpenOrder

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"account_key", "open_order"})

    def __post_init__(self) -> None:
        if (
            type(self.account_key) is not AccountKey
            or type(self.open_order) is not AccountOpenOrder
        ):
            raise TypeError("expected an AccountKey and AccountOpenOrder")
        _check_scope(self.account_key, self.open_order)

    def to_dict(self) -> dict[str, Any]:
        return {"account_key": self.account_key.to_dict(), "open_order": self.open_order.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AccountOpenOrderObservation:
        raw = _fields(value, cls._FIELDS)
        return cls(
            AccountKey.from_dict(raw["account_key"]), AccountOpenOrder.from_dict(raw["open_order"])
        )


__all__ = ("AccountPositionObservation", "AccountOpenOrderObservation")
