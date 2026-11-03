"""Account-scoped execution observations; not identity or permission proof.

The enclosed order/trade record describes a provider observation only.  Its
binding fields remain declarations and require independent source and intent
verification at the receiver. A trade record does not include fee facts.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from decimal import Decimal
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

EXECUTION_ORDER_EVENT_KIND = "account.execution_order.v1"
EXECUTION_TRADE_EVENT_KIND = "account.execution_trade.v1"
EXECUTION_EVENT_SCHEMA = "bt_api.account.execution_event.v1"
EXECUTION_EVENT_KINDS = frozenset({EXECUTION_ORDER_EVENT_KIND, EXECUTION_TRADE_EVENT_KIND})
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
    return "xt-" + _digest(["trade", account, instrument, row["trade_id"]])[:48]


def execution_observation_fact_digest(observation: ExecutionObservation) -> str:
    """Digest of every fact field except the observation time."""

    kind, row, _account = _row(observation)
    content = {
        key: (_normal_decimal(value) if key in _DECIMAL_FIELDS else value)
        for key, value in row.items()
        if key != "observed_at_utc"
    }
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

    if type(kind) is not str or kind not in EXECUTION_EVENT_KINDS:
        raise ValueError("unsupported execution event kind")
    raw = _fields(payload, _EVENT_FIELDS)
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
)
