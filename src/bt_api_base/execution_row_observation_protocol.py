"""Account-scoped execution observations; not identity or permission proof.

The enclosed order/trade record describes a provider observation only.  Its
binding fields remain declarations and require independent source and intent
verification at the receiver. A trade record does not include fee facts; a
trade observation may carry the provider's fee for that fill next to it
(``fee``/``fee_currency``, iteration 60 R3, account execution event v2).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from decimal import Decimal
from typing import Any, ClassVar

from bt_api_base.account_protocol import AccountKey, account_venue_contains_instrument_venue
from bt_api_base.execution_query_protocol import (
    ExecutionOrderRecord,
    ExecutionTradeRecord,
    _decimal as _fee_decimal,
    _text as _fee_text,
)


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
    """One account-scoped execution observation, optionally with its provider fee.

    ``fee`` (non-negative decimal string) and ``fee_currency`` are the
    provider's fee for this one fill, present together or not at all. Absent
    means unknown, never zero. A later report of the same fill with another
    fee is a fee correction (a new fact, see :func:`execution_observation_fact_id`).
    """

    account_key: AccountKey
    trade: ExecutionTradeRecord
    fee: str | None = None
    fee_currency: str | None = None
    _FIELDS: ClassVar[frozenset[str]] = frozenset({"account_key", "trade"})
    _FEE_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"account_key", "trade", "fee", "fee_currency"}
    )

    def __post_init__(self) -> None:
        if type(self.account_key) is not AccountKey or type(self.trade) is not ExecutionTradeRecord:
            raise TypeError("expected an AccountKey and ExecutionTradeRecord")
        _check_scope(self.account_key, self.trade)
        if (self.fee is None) != (self.fee_currency is None):
            raise ValueError("fee and fee_currency must be present together")
        if self.fee is not None:
            _fee_decimal(self.fee, "fee")
            _fee_text(self.fee_currency, "fee_currency")

    def to_dict(self) -> dict[str, Any]:
        _require_declared_state(self.account_key, self.trade, self)
        result: dict[str, Any] = {
            "account_key": self.account_key.to_dict(),
            "trade": self.trade.to_dict(),
        }
        if self.fee is not None:
            result["fee"] = self.fee
            result["fee_currency"] = self.fee_currency
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AccountExecutionTradeObservation:
        if isinstance(value, Mapping) and set(value) == cls._FEE_FIELDS:
            raw = _fields(value, cls._FEE_FIELDS)
            if raw["fee"] is None or raw["fee_currency"] is None:
                raise ValueError("an encoded fee must be present with its currency")
            return cls(
                AccountKey.from_dict(raw["account_key"]),
                ExecutionTradeRecord.from_dict(raw["trade"]),
                raw["fee"],
                raw["fee_currency"],
            )
        raw = _fields(value, cls._FIELDS)
        return cls(
            AccountKey.from_dict(raw["account_key"]), ExecutionTradeRecord.from_dict(raw["trade"])
        )


# ---------------------------------------------------------------------------
# Account-journal event envelope (iteration 60, R2-C)
# ---------------------------------------------------------------------------
#
# A Gateway account owner publishes each observation as one journal event.
# The event id is a *fact id*: it is derived from the provider fact (order
# identity, state and cumulative quantity; or trade identity) and not from the
# observation time, so a provider redelivering the same fact maps to the same
# id. ``fact_digest`` covers every field except ``observed_at_utc`` (decimals
# normalized); two observations with one fact id and different digests are a
# conflict that a consumer must not silently merge. Neither value proves the
# fact, its source, or any intent binding.

#
# Version 2 (iteration 60 R3): a trade event may carry the provider fee of the
# fill; the trade fact id includes the fee, so a corrected fee is a new fact
# (a fee correction) instead of a conflict. Version 1 events (schema
# ``...execution_event.v1``, kind ``account.execution_trade.v1``) are refused
# explicitly: they cannot say whether a fee was absent or unknown.

EXECUTION_ORDER_EVENT_KIND = "account.execution_order.v1"
EXECUTION_TRADE_EVENT_KIND = "account.execution_trade.v2"
EXECUTION_EVENT_SCHEMA = "bt_api.account.execution_event.v2"
EXECUTION_EVENT_KINDS = frozenset({EXECUTION_ORDER_EVENT_KIND, EXECUTION_TRADE_EVENT_KIND})
_RETIRED_EVENT_KINDS = frozenset({"account.execution_trade.v1"})
_RETIRED_EVENT_SCHEMAS = frozenset({"bt_api.account.execution_event.v1"})
_EVENT_FIELDS = frozenset({"schema", "fact_id", "fact_digest", "observation"})
_DECIMAL_FIELDS = frozenset({"quantity", "filled_quantity", "limit_price", "price"})

ExecutionObservation = AccountExecutionOrderObservation | AccountExecutionTradeObservation


def _normal_decimal(value: object) -> object:
    if type(value) is not str:
        return value
    number = Decimal(value)
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _row(observation: object) -> tuple[str, Mapping[str, Any], str]:
    if type(observation) is AccountExecutionOrderObservation:
        account = observation.account_key.account_key_id
        return EXECUTION_ORDER_EVENT_KIND, observation.order.to_dict(), account
    if type(observation) is AccountExecutionTradeObservation:
        account = observation.account_key.account_key_id
        return EXECUTION_TRADE_EVENT_KIND, observation.trade.to_dict(), account
    raise TypeError("expected an account execution observation")


def execution_observation_fact_id(observation: ExecutionObservation) -> str:
    """Stable id of the provider fact: same fact, same id, across redeliveries."""

    kind, row, account = _row(observation)
    instrument = row["instrument"]
    if kind == EXECUTION_ORDER_EVENT_KIND:
        parts = [
            "order",
            account,
            instrument,
            row["order_id"],
            row["status"],
            _normal_decimal(row["filled_quantity"]),
            _normal_decimal(row["quantity"]),
        ]
        return "xo-" + _digest(parts)[:48]
    fee = None if observation.fee is None else _normal_decimal(observation.fee)
    return "xt-" + _digest(
        ["trade", account, instrument, row["trade_id"], fee, observation.fee_currency]
    )[:48]


def execution_observation_fact_digest(observation: ExecutionObservation) -> str:
    """Digest of every fact field except the observation time."""

    kind, row, _account = _row(observation)
    content = {
        key: (_normal_decimal(value) if key in _DECIMAL_FIELDS else value)
        for key, value in row.items()
        if key != "observed_at_utc"
    }
    if kind == EXECUTION_TRADE_EVENT_KIND:
        fee = None if observation.fee is None else _normal_decimal(observation.fee)
        content = {"row": content, "fee": fee, "fee_currency": observation.fee_currency}
    return _digest([kind, observation.account_key.to_dict(), content])


def execution_observation_event(
    observation: ExecutionObservation,
) -> tuple[str, str, dict[str, Any]]:
    """Return ``(kind, event_id, payload)`` for one account-journal event."""

    kind, _row_value, _account = _row(observation)
    fact_id = execution_observation_fact_id(observation)
    return (
        kind,
        fact_id,
        {
            "schema": EXECUTION_EVENT_SCHEMA,
            "fact_id": fact_id,
            "fact_digest": execution_observation_fact_digest(observation),
            "observation": observation.to_dict(),
        },
    )


def execution_observation_from_event(
    kind: object, event_id: object, payload: object
) -> ExecutionObservation:
    """Decode and re-derive one journal event; any inconsistency is rejected."""

    if kind in _RETIRED_EVENT_KINDS:
        raise ValueError("execution event version 1 is no longer accepted")
    if type(kind) is not str or kind not in EXECUTION_EVENT_KINDS:
        raise ValueError("unsupported execution event kind")
    raw = _fields(payload, _EVENT_FIELDS)
    if raw["schema"] in _RETIRED_EVENT_SCHEMAS:
        raise ValueError("execution event version 1 is no longer accepted")
    if raw["schema"] != EXECUTION_EVENT_SCHEMA:
        raise ValueError("unsupported execution event schema")
    decoder = (
        AccountExecutionOrderObservation
        if kind == EXECUTION_ORDER_EVENT_KIND
        else AccountExecutionTradeObservation
    )
    observation = decoder.from_dict(_plain(raw["observation"]))
    fact_id = execution_observation_fact_id(observation)
    if event_id != fact_id or raw["fact_id"] != fact_id:
        raise ValueError("execution event id does not match its fact")
    if raw["fact_digest"] != execution_observation_fact_digest(observation):
        raise ValueError("execution event digest does not match its fact")
    return observation


# ---------------------------------------------------------------------------
# Strategy attribution of provider client order ids (iteration 60 R3)
# ---------------------------------------------------------------------------
#
# A Gateway account owner routes execution observations to a strategy's stream
# by a verified client-order-id prefix. The order-entry owner that generates the
# provider client order id and the Gateway routing configuration both derive the
# prefix from the strategy reference with this one function, so neither side
# types it by hand. The prefix is an attribution label, not authentication.

#
# Version 2: the prefix and the full id are lowercase alphanumeric only and
# the full id is at most 32 characters, the strictest common venue grammar
# (OKX ``clOrdId``: up to 32 alphanumerics; Binance ``newClientOrderId``: up to
# 36 of ``[.A-Z:/a-z0-9_-]``). Version 1 (``s`` + 8 hex + ``-``) was rejected by
# OKX and its 45-character Risk ids by Binance.

STRATEGY_CLIENT_ORDER_PREFIX_SCHEMA = "bt_api.strategy-client-order-prefix.v2"
STRATEGY_CLIENT_ORDER_PREFIX_LENGTH = 10
STRATEGY_CLIENT_ORDER_ID_LENGTH = 32


def strategy_client_order_prefix(strategy_ref: str) -> str:
    """The deterministic client-order-id prefix of ``strategy_ref``.

    ``s`` plus 9 lowercase hex digits (10 alphanumeric characters).
    """

    if (
        type(strategy_ref) is not str
        or not strategy_ref
        or strategy_ref != strategy_ref.strip()
        or len(strategy_ref) > 256
    ):
        raise ValueError("strategy_ref must be a non-empty trimmed string")
    digest = hashlib.sha256(
        (STRATEGY_CLIENT_ORDER_PREFIX_SCHEMA + "\0" + strategy_ref).encode("utf-8")
    ).hexdigest()
    return "s" + digest[: STRATEGY_CLIENT_ORDER_PREFIX_LENGTH - 1]


def strategy_client_order_id(strategy_ref: str, digest_hex: str) -> str:
    """A venue-safe provider client order id attributed to ``strategy_ref``.

    The strategy prefix followed by the first 22 digits of the caller's
    lowercase hex digest of the order identity: 32 lowercase alphanumerics.
    """

    width = STRATEGY_CLIENT_ORDER_ID_LENGTH - STRATEGY_CLIENT_ORDER_PREFIX_LENGTH
    if (
        type(digest_hex) is not str
        or len(digest_hex) < width
        or any(char not in "0123456789abcdef" for char in digest_hex)
    ):
        raise ValueError("digest_hex must be lowercase hex of at least 22 digits")
    return strategy_client_order_prefix(strategy_ref) + digest_hex[:width]


def _plain(value: Any) -> Any:
    """Copy frozen mappings/sequences (for example a journal replay) into JSON types."""

    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


__all__ = (
    "AccountExecutionOrderObservation",
    "AccountExecutionTradeObservation",
    "EXECUTION_EVENT_KINDS",
    "EXECUTION_EVENT_SCHEMA",
    "EXECUTION_ORDER_EVENT_KIND",
    "EXECUTION_TRADE_EVENT_KIND",
    "ExecutionObservation",
    "execution_observation_event",
    "execution_observation_fact_digest",
    "execution_observation_fact_id",
    "execution_observation_from_event",
    "STRATEGY_CLIENT_ORDER_ID_LENGTH",
    "STRATEGY_CLIENT_ORDER_PREFIX_LENGTH",
    "STRATEGY_CLIENT_ORDER_PREFIX_SCHEMA",
    "strategy_client_order_id",
    "strategy_client_order_prefix",
)
