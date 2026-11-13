"""Versioned structural declarations for Execution parent terms and children.

These shapes are not a complete parent.submit contract. They neither authenticate
identity nor grant authority, establish source or market facts, or guarantee
identifier uniqueness. Child attribution applies only to ordinary real Execution
children, not Risk-native operations or internal transfers.

Decimal wire text is limited to 4096 characters to bound serialization. This
structural limit does not imply compatibility with downstream authority limits
(such as 42 integer and 42 fractional digits), which require separate checks.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import ClassVar

from bt_api_base.market_protocol import MarketInstrumentKey

_DECIMAL_TEXT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z", re.ASCII)
_MAX_DECIMAL_TEXT = 4096
_SIDES = frozenset({"buy", "sell"})
_OFFSETS = frozenset({"open", "close", "close_today", "close_yesterday"})
_QUANTITY_UNITS = frozenset({"base", "contracts", "lots", "native"})
_INSTRUMENT_FIELDS = frozenset(
    {"provider", "venue", "environment", "product_type", "instrument_id", "native_symbol"}
)


class ExecutionParentProtocolError(ValueError):
    """Finite validation code that does not echo supplied values."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _ref(value: object) -> bool:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= 256
    except UnicodeError:
        return False


def _enum(value: object, values: frozenset[str]) -> bool:
    return type(value) is str and value in values


def _positive_decimal(value: object) -> bool:
    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        return False
    _, digits, exponent = value.as_tuple()
    # Compute the fixed-point length before formatting: large exponents must
    # not allocate the string that will be rejected. No context arithmetic.
    if exponent >= 0:
        size = len(digits) + exponent
    elif len(digits) + exponent > 0:
        size = len(digits) + 1
    else:
        size = 2 - exponent
    return size <= _MAX_DECIMAL_TEXT


def _wire_decimal(value: object) -> Decimal:
    if (
        type(value) is not str
        or len(value) > _MAX_DECIMAL_TEXT
        or _DECIMAL_TEXT.fullmatch(value) is None
    ):
        raise ValueError
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError from None
    if not _positive_decimal(result):
        raise ValueError
    return result


def _exact_mapping(value: object, fields: frozenset[str]) -> bool:
    if not isinstance(value, Mapping):
        return False
    keys = list(value)
    return (
        all(type(key) is str for key in keys) and len(keys) == len(fields) and set(keys) == fields
    )


@dataclass(frozen=True)
class LimitParentTerms:
    """Basic terms of a single limit parent; all fields remain untrusted claims."""

    account_scope: str
    strategy_scope: str
    parent_ref: str
    instrument: MarketInstrumentKey
    side: str
    offset: str
    quantity_unit: str
    quantity: Decimal
    limit_price: Decimal
    order_type: str
    schema_version: int = 1

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "account_scope",
            "strategy_scope",
            "parent_ref",
            "instrument",
            "side",
            "offset",
            "quantity_unit",
            "quantity",
            "limit_price",
            "order_type",
        }
    )

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or any(
                not _ref(item)
                for item in (self.account_scope, self.strategy_scope, self.parent_ref)
            )
            or type(self.instrument) is not MarketInstrumentKey
            or not _enum(self.side, _SIDES)
            or not _enum(self.offset, _OFFSETS)
            or not _enum(self.quantity_unit, _QUANTITY_UNITS)
            or type(self.order_type) is not str
            or self.order_type != "limit"
            or not _positive_decimal(self.quantity)
            or not _positive_decimal(self.limit_price)
        ):
            raise ExecutionParentProtocolError("INVALID_PARENT_TERMS")

    def to_mapping(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "account_scope": self.account_scope,
            "strategy_scope": self.strategy_scope,
            "parent_ref": self.parent_ref,
            "instrument": self.instrument.to_dict(),
            "side": self.side,
            "offset": self.offset,
            "quantity_unit": self.quantity_unit,
            "quantity": format(self.quantity, "f"),
            "limit_price": format(self.limit_price, "f"),
            "order_type": self.order_type,
        }

    @classmethod
    def from_mapping(cls, value: Mapping) -> LimitParentTerms:
        try:
            if not _exact_mapping(value, cls._FIELDS):
                raise ValueError
            instrument = value["instrument"]
            if not _exact_mapping(instrument, _INSTRUMENT_FIELDS):
                raise ValueError
            return cls(
                schema_version=value["schema_version"],
                account_scope=value["account_scope"],
                strategy_scope=value["strategy_scope"],
                parent_ref=value["parent_ref"],
                instrument=MarketInstrumentKey.from_dict(instrument),
                side=value["side"],
                offset=value["offset"],
                quantity_unit=value["quantity_unit"],
                quantity=_wire_decimal(value["quantity"]),
                limit_price=_wire_decimal(value["limit_price"]),
                order_type=value["order_type"],
            )
        except (TypeError, ValueError, KeyError):
            raise ExecutionParentProtocolError("INVALID_PARENT_TERMS") from None


@dataclass(frozen=True)
class ExecutionChildAttribution:
    """Single-parent attribution claim for one ordinary real Execution child."""

    account_scope: str
    strategy_scope: str
    parent_ref: str
    child_id: str
    request_key: str
    schema_version: int = 1

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "account_scope",
            "strategy_scope",
            "parent_ref",
            "child_id",
            "request_key",
        }
    )

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or any(
                not _ref(item)
                for item in (
                    self.account_scope,
                    self.strategy_scope,
                    self.parent_ref,
                    self.child_id,
                    self.request_key,
                )
            )
            or self.child_id != self.request_key
        ):
            raise ExecutionParentProtocolError("INVALID_CHILD_ATTRIBUTION")

    def to_mapping(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "account_scope": self.account_scope,
            "strategy_scope": self.strategy_scope,
            "parent_ref": self.parent_ref,
            "child_id": self.child_id,
            "request_key": self.request_key,
        }

    @classmethod
    def from_mapping(cls, value: Mapping) -> ExecutionChildAttribution:
        try:
            if not _exact_mapping(value, cls._FIELDS):
                raise ValueError
            return cls(**dict(value))
        except (TypeError, ValueError, KeyError):
            raise ExecutionParentProtocolError("INVALID_CHILD_ATTRIBUTION") from None


__all__ = ["ExecutionChildAttribution", "ExecutionParentProtocolError", "LimitParentTerms"]
