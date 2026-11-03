"""Versioned MessagePack wire contract v1 for cross-process market data and fill facts.

Iteration 60, step 60.08. The Gateway path encodes the Base neutral
containers once on the publishing side and decodes them once on each
receiving process into the same frozen Base objects (``MarketTickPayload``,
``MarketBar``). The direct path never imports this module's codec dependency:
``msgpack`` is imported lazily inside :func:`encode_message` and
:func:`decode_message` only (plan INV-01).

Contract v1:

* Envelope: a map with exactly ``schema_id``, ``major``, ``minor``, ``kind``,
  ``stream`` (``stream_id``, ``epoch``, ``sequence``), ``data`` and an
  optional ``ext`` (provider-namespaced extensions). Unknown top-level or
  ``data`` keys are rejected: a field that could change the meaning of a
  message is never silently ignored. An unknown ``major`` is rejected; a
  newer ``minor`` is rejected unless the receiver supports it.
* Numbers: prices, sizes and other decimals travel as canonical decimal
  strings (``-?(0|[1-9][0-9]*)(\\.[0-9]*[1-9])?``): no exponent, no NaN or
  infinity, no ``-0``, no leading zeros, no trailing fractional zeros, at most
  40 significant characters. Binary floats are rejected anywhere in a message.
  Integers are limited to the signed 64-bit range.
* Strict decoding: exactly one complete object (trailing bytes rejected),
  text map keys only, duplicate keys rejected, MessagePack extension types
  rejected, bounded message size, nesting depth and container lengths.
* ``sequence`` is a positive 64-bit integer; a stream must change ``epoch``
  before it would wrap.
* Minor 1 permits a tick quality rule reference to be null for observation
  only. Minor 0 requires the reference. New readers accept valid minor 0;
  old readers reject minor 1, and the changed registry digest fences peers.
* Minor 2 adds typed account snapshots and independently scoped position and
  open-order rows. A row does not assert complete snapshot coverage.
* Minor 3 adds account-scoped provider order and trade observations. They
  do not authenticate their source or establish a strategy/intent binding.

Field values are data, not proof: a decoded message does not authenticate its
source or grant trading permission (plan INV-05).
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from bt_api_base.account_protocol import (
    AccountBalance,
    AccountKey,
    AccountObservation,
    AccountOpenOrder,
    AccountPosition,
    AccountResourceKey,
    AccountValuation,
)
from bt_api_base.account_book_protocol import (
    StrategyAccountBookSnapshot,
    StrategyFinancialLedgerCut,
    StrategyFinancialWatermark,
    StrategyPositionCost,
)
from bt_api_base.account_row_observation_protocol import (
    AccountOpenOrderObservation,
    AccountPositionObservation,
)
from bt_api_base.execution_command_wire_protocol import (
    StrategyCancelCommand,
    StrategyCommandResult,
    StrategySubmitCommand,
)
from bt_api_base.execution_query_protocol import ExecutionOrderRecord, ExecutionTradeRecord
from bt_api_base.execution_row_observation_protocol import (
    AccountExecutionOrderObservation,
    AccountExecutionTradeObservation,
)
from bt_api_base.market_history_protocol import MarketBar
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.market_tick_protocol import (
    MARKET_TICK_SCHEMA_VERSION,
    MarketClockQuality,
    MarketFreshnessStatus,
    MarketTickPayload,
)
from bt_api_base.paper_fill_protocol import (
    MANAGED_PAPER_FILL_V2_FIELDS,
    MANAGED_PAPER_FILL_V2_SCHEMA,
)

__all__ = [
    "MAX_MESSAGE_BYTES",
    "SCHEMA_ID",
    "SUPPORTED_MAJOR",
    "SUPPORTED_MINOR",
    "StreamPosition",
    "WireCodecError",
    "WireMessageV1",
    "account_observation_from_typed_map",
    "account_observation_to_typed_map",
    "canonical_decimal",
    "codec_backend",
    "DEFAULT_DECIMAL_FIELDS",
    "command_fingerprint",
    "decode_message",
    "encode_message",
    "parse_decimal",
    "schema_digest",
]

SCHEMA_ID = "bt_api.wire.v1"
SUPPORTED_MAJOR = 1
SUPPORTED_MINOR = 4
MAX_MESSAGE_BYTES = 64 * 1024
MAX_DEPTH = 8
MAX_CONTAINER_LEN = 256
MAX_STR_LEN = 4096
_MAX_DECIMAL_CHARS = 40
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1

_DECIMAL_RE = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?")
_EXT_KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_ENVELOPE_KEYS = frozenset({"schema_id", "major", "minor", "kind", "stream", "data"})
_STREAM_KEYS = frozenset({"stream_id", "epoch", "sequence"})
ACCOUNT_OBSERVATION_MAP_SCHEMA = "bt_api.account.observation.map"
_ACCOUNT_OBSERVATION_MAP_VERSION = 1


class WireCodecError(ValueError):
    """Finite, value-free wire contract failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclasses.dataclass(frozen=True)
class StreamPosition:
    """Stream identity carried with every message."""

    stream_id: str
    epoch: str
    sequence: int

    def __post_init__(self) -> None:
        for name in ("stream_id", "epoch"):
            value = getattr(self, name)
            if type(value) is not str or not value or len(value) > MAX_STR_LEN:
                raise WireCodecError("WIRE_STREAM_INVALID")
        if type(self.sequence) is not int or not 1 <= self.sequence <= _INT64_MAX:
            raise WireCodecError("WIRE_STREAM_INVALID")


@dataclasses.dataclass(frozen=True)
class WireMessageV1:
    """One decoded message: a frozen Base container plus its stream identity."""

    kind: str
    payload: Any
    stream: StreamPosition
    minor: int
    extensions: Mapping[str, Mapping[str, Any]]


# ---------------------------------------------------------------------------
# Decimal grammar
# ---------------------------------------------------------------------------


def canonical_decimal(value: Any) -> str:
    """Return the canonical v1 decimal lexeme for a finite number."""

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise WireCodecError("WIRE_DECIMAL_INVALID")
    try:
        number = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except (InvalidOperation, ValueError):
        raise WireCodecError("WIRE_DECIMAL_INVALID") from None
    if not number.is_finite():
        raise WireCodecError("WIRE_DECIMAL_INVALID")
    if number == 0:
        return "0"
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if not _DECIMAL_RE.fullmatch(text) or len(text) > _MAX_DECIMAL_CHARS:
        raise WireCodecError("WIRE_DECIMAL_INVALID")
    return text


def parse_decimal(text: Any) -> Decimal:
    """Parse a canonical v1 decimal lexeme; anything else is rejected."""

    if (
        type(text) is not str
        or len(text) > _MAX_DECIMAL_CHARS
        or text == "-0"
        or not _DECIMAL_RE.fullmatch(text)
    ):
        raise WireCodecError("WIRE_DECIMAL_INVALID")
    return Decimal(text)


# ---------------------------------------------------------------------------
# Kind registry
# ---------------------------------------------------------------------------

_TICK_FLOATS = frozenset(
    {
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
        "source_clock_error_ms",
        "receive_clock_error_ms",
    }
)
_TICK_ENUMS = {
    "source_clock_quality": MarketClockQuality,
    "receive_clock_quality": MarketClockQuality,
    "freshness_status": MarketFreshnessStatus,
}
_TICK_TUPLES = frozenset({"freshness_reason_codes", "quality_flags"})
_TICK_FIELDS = tuple(f.name for f in dataclasses.fields(MarketTickPayload))
_INSTRUMENT_FIELDS = tuple(f.name for f in dataclasses.fields(MarketInstrumentKey))
_BAR_FIELDS = tuple(f.name for f in dataclasses.fields(MarketBar))


def _encode_tick(payload: MarketTickPayload) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name in _TICK_FIELDS:
        value = getattr(payload, name)
        if name == "instrument":
            data[name] = {key: getattr(value, key) for key in _INSTRUMENT_FIELDS}
        elif name in _TICK_FLOATS:
            data[name] = None if value is None else canonical_decimal(value)
        elif name in _TICK_ENUMS:
            data[name] = value.value
        elif name in _TICK_TUPLES:
            data[name] = list(value)
        else:
            data[name] = value
    return data


def _decode_tick(data: Mapping[str, Any]) -> MarketTickPayload:
    if set(data) != set(_TICK_FIELDS):
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    values: dict[str, Any] = {}
    for name in _TICK_FIELDS:
        raw = data[name]
        if name == "instrument":
            if not isinstance(raw, Mapping) or set(raw) != set(_INSTRUMENT_FIELDS):
                raise WireCodecError("WIRE_FIELD_SET_INVALID")
            values[name] = MarketInstrumentKey(**raw)
        elif name in _TICK_FLOATS:
            values[name] = None if raw is None else float(parse_decimal(raw))
        elif name in _TICK_ENUMS:
            try:
                values[name] = _TICK_ENUMS[name](raw)
            except ValueError:
                raise WireCodecError("WIRE_ENUM_INVALID") from None
        elif name in _TICK_TUPLES:
            if not isinstance(raw, list):
                raise WireCodecError("WIRE_VALUE_INVALID")
            values[name] = tuple(raw)
        else:
            values[name] = raw
    return MarketTickPayload(**values)


def _encode_bar(payload: MarketBar) -> dict[str, Any]:
    return {name: getattr(payload, name) for name in _BAR_FIELDS}


def _decode_bar(data: Mapping[str, Any]) -> MarketBar:
    if set(data) != set(_BAR_FIELDS):
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    for name in ("open", "high", "low", "close", "volume", "open_interest"):
        if data[name] is not None:
            parse_decimal(data[name])
    return MarketBar(**data)


_FILL_DECIMALS = ("quantity", "price", "commission")
_FILL_INTEGERS = ("match_time_ns", "event_sequence", "quote_cursor")


def _encode_fill(payload: Mapping[str, Any]) -> dict[str, Any]:
    if set(payload) != MANAGED_PAPER_FILL_V2_FIELDS:
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    if payload["schema"] != MANAGED_PAPER_FILL_V2_SCHEMA:
        raise WireCodecError("WIRE_SCHEMA_UNSUPPORTED")
    data = dict(payload)
    for name in _FILL_DECIMALS:
        data[name] = canonical_decimal(Decimal(data[name]) if type(data[name]) is str else data[name])
    return data


def _decode_fill(data: Mapping[str, Any]) -> Mapping[str, Any]:
    if set(data) != MANAGED_PAPER_FILL_V2_FIELDS:
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    if data["schema"] != MANAGED_PAPER_FILL_V2_SCHEMA:
        raise WireCodecError("WIRE_SCHEMA_UNSUPPORTED")
    for name in _FILL_DECIMALS:
        if parse_decimal(data[name]) < 0:
            raise WireCodecError("WIRE_DECIMAL_INVALID")
    for name in MANAGED_PAPER_FILL_V2_FIELDS:
        value = data[name]
        if name in _FILL_INTEGERS:
            if type(value) is not int or value < 0:
                raise WireCodecError("WIRE_VALUE_INVALID")
        elif type(value) is not str or not value:
            raise WireCodecError("WIRE_VALUE_INVALID")
    # Frozen view: received fill facts are shared read-only (INV-11).
    return MappingProxyType(dict(data))


class _FillFact:
    """Kind marker: encode a ``managed_paper_fill.v2`` mapping."""


_ACCOUNT_DECIMALS = {
    "balances": ("total", "available", "locked"),
    "positions": ("quantity", "average_price"),
    "open_orders": ("quantity", "filled_quantity", "limit_price", "stop_price"),
    "valuation": ("available_cash", "equity"),
}

# Normative registry for the semantics of minor-2 account messages. Changes to
# these rules (including changes in account_protocol validators) MUST update
# this revision/manifest and the compatible wire version as appropriate.
# The digest binds this declared contract, not arbitrary Python source code;
# behavioural regression tests are still required to detect implementation
# drift from the declaration.
_ACCOUNT_WIRE_SEMANTICS = {
    "revision": 1,
    "common": {
        "source_is_not_authority": True,
        "decimal_format": "canonical-signed-base10-no-exponent-no-negative-zero",
        "decimal_max_characters": _MAX_DECIMAL_CHARS,
        "utc_timestamp": "explicit-Z-up-to-6-fractional-digits",
        "max_message_bytes": MAX_MESSAGE_BYTES,
        "max_depth": MAX_DEPTH,
        "max_array_and_map_length": MAX_CONTAINER_LEN,
        "max_string_bytes": MAX_STR_LEN,
    },
    "account_scope": {
        "provider_and_environment": "exact-match",
        "venue": "exact-match-except-ctp-simnow",
        "ctp_simnow_instrument_venues": ["CFFEX", "CZCE", "DCE", "GFEX", "INE", "SHFE"],
        "instrument_and_resource_product_type": "exact-match",
        "account_key_is_provider_claim_not_authority": True,
    },
    "snapshot": {
        "consistency": ["multi_query", "provider_atomic"],
        "coverage": "nonempty-unique-resources-containing-all-rows",
        "balances_complete_and_positions_complete": "exact-bool",
        "open_orders": "missing-means-unknown-present-empty-is-not-missing",
        "open_orders_complete": "true-only-if-open-orders-present",
        "row_uniqueness": "balance-resource-currency-position-resource-instrument-side-order-resource-instrument-id",
        "time_order": "started-at-most-completed-each-row-at-most-completed",
    },
    "balance": {
        "total_available_locked": "each-optional-signed-decimal",
        "missing_differs_from_zero": True,
    },
    "valuation": {
        "available_cash_and_equity": "each-optional-signed-decimal",
        "currency_conversion_implied": False,
    },
    "position": {
        "sides": ["long", "net", "short"],
        "quantity": "required-signed-net-nonnegative-long-short",
        "average_price": "optional-signed-decimal",
        "missing_row_means_zero": False,
        "single_row_proves_complete_snapshot": False,
    },
    "open_order": {
        "sides": ["buy", "sell"],
        "position_sides": ["long", "net", "short"],
        "statuses": ["open", "partially_filled"],
        "quantity": "positive",
        "filled_quantity": "at-least-zero-and-less-than-quantity",
        "status_filled_relation": "open-zero-partially-filled-positive",
        "limit_and_stop_price": "optional-signed-decimal",
        "reduce_only": "exact-bool-or-null",
        "time_order": "created-at-most-observed",
        "terminal_or_strategy_ownership": False,
    },
}


def _account_decimal_fields(data: Mapping[str, Any]):
    """Visit known numeric fields only; the account DTO validates all fields."""
    for group, names in _ACCOUNT_DECIMALS.items():
        rows = data.get(group)
        if rows is None:
            continue
        if group == "valuation":
            rows = (rows,)
        for row in rows:
            for name in names:
                yield row, name


_ACCOUNT_DTO_TYPES = frozenset(
    {
        AccountKey,
        AccountResourceKey,
        AccountBalance,
        AccountPosition,
        AccountOpenOrder,
        AccountValuation,
        AccountObservation,
        AccountPositionObservation,
        AccountOpenOrderObservation,
        MarketInstrumentKey,
    }
)


def _check_account_declared_state(root: Any) -> None:
    """Do not silently omit attached attributes from a known account DTO.

    This checks representability, not trust: frozen dataclasses can still be
    modified by Python reflection and a decoded value is not source evidence.
    """
    stack = [root]
    seen: set[int] = set()
    while stack:
        item = stack.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if type(item) in _ACCOUNT_DTO_TYPES:
            declared = dataclasses.fields(item)
            if set(vars(item)) != {field.name for field in declared}:
                raise ValueError("account data contains unsupported fields")
            # Equality with a deserialized value is not enough: Python can
            # compare a tuple subclass equal to a tuple despite violating an
            # exact-type contract. Re-run this known DTO's own validation on
            # its actual current fields before serializing anything.
            type(item)(**{field.name: getattr(item, field.name) for field in declared})
            stack.extend(getattr(item, field.name) for field in declared)
        elif type(item) in (tuple, list):
            stack.extend(item)


def _encode_account(payload: AccountObservation) -> dict[str, Any]:
    try:
        _check_account_declared_state(payload)
        data = payload.to_dict()
        # Frozen dataclasses can still be modified through low-level Python
        # APIs. Do not publish a structurally invalid or out-of-scope DTO.
        if AccountObservation.from_dict(data) != payload:
            raise ValueError("account snapshot cannot be represented faithfully")
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise WireCodecError("WIRE_PAYLOAD_INVALID") from None
    for row, name in _account_decimal_fields(data):
        if row[name] is not None:
            row[name] = canonical_decimal(row[name])
    return data


def _check_account_wire_bounds(root: Any) -> None:
    """Apply the decoder's collection/string limits before publishing."""
    stack = [root]
    while stack:
        value = stack.pop()
        if type(value) is dict:
            if len(value) > MAX_CONTAINER_LEN:
                raise WireCodecError("WIRE_VALUE_INVALID")
            stack.extend(value.keys())
            stack.extend(value.values())
        elif type(value) is list:
            if len(value) > MAX_CONTAINER_LEN:
                raise WireCodecError("WIRE_VALUE_INVALID")
            stack.extend(value)
        elif type(value) is str:
            try:
                encoded = value.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                raise WireCodecError("WIRE_VALUE_INVALID") from None
            if len(encoded) > MAX_STR_LEN:
                raise WireCodecError("WIRE_VALUE_INVALID")


def _decode_account(data: Mapping[str, Any]) -> AccountObservation:
    # Check the exact decimal wire spelling before constructing any DTO.
    # Malformed containers or absent fields still fail through the DTO's
    # exact field-set validation; no partially constructed DTO is returned.
    try:
        for row, name in _account_decimal_fields(data):
            if row[name] is not None:
                parse_decimal(row[name])
        return AccountObservation.from_dict(data)
    except WireCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise WireCodecError("WIRE_PAYLOAD_INVALID") from None


def _encode_account_row(payload: Any, field: str, decimal_group: str) -> dict[str, Any]:
    try:
        _check_account_declared_state(payload)
        data = payload.to_dict()
        if type(payload).from_dict(data) != payload:
            raise ValueError("account row cannot be represented faithfully")
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise WireCodecError("WIRE_PAYLOAD_INVALID") from None
    row = data[field]
    for name in _ACCOUNT_DECIMALS[decimal_group]:
        if row[name] is not None:
            row[name] = canonical_decimal(row[name])
    return data


def _decode_account_row(data: Mapping[str, Any], field: str, decimal_group: str, cls: Any) -> Any:
    try:
        row = data[field]
        for name in _ACCOUNT_DECIMALS[decimal_group]:
            if row[name] is not None:
                parse_decimal(row[name])
        return cls.from_dict(data)
    except WireCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise WireCodecError("WIRE_PAYLOAD_INVALID") from None


def _encode_position(payload: AccountPositionObservation) -> dict[str, Any]:
    return _encode_account_row(payload, "position", "positions")


def _decode_position(data: Mapping[str, Any]) -> AccountPositionObservation:
    return _decode_account_row(data, "position", "positions", AccountPositionObservation)


def _encode_open_order(payload: AccountOpenOrderObservation) -> dict[str, Any]:
    return _encode_account_row(payload, "open_order", "open_orders")


def _decode_open_order(data: Mapping[str, Any]) -> AccountOpenOrderObservation:
    return _decode_account_row(data, "open_order", "open_orders", AccountOpenOrderObservation)


_EXECUTION_ROW_DECIMALS = {
    "order": ("quantity", "filled_quantity", "limit_price"),
    "trade": ("quantity", "price"),
}


def _encode_execution_row(payload: Any, field: str) -> dict[str, Any]:
    try:
        data = payload.to_dict()
        if type(payload).from_dict(data) != payload:
            raise ValueError("execution observation cannot be represented faithfully")
        row = data[field]
        for name in _EXECUTION_ROW_DECIMALS[field]:
            if row[name] is not None:
                row[name] = canonical_decimal(row[name])
        return data
    except WireCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise WireCodecError("WIRE_PAYLOAD_INVALID") from None


def _decode_execution_row(data: Mapping[str, Any], field: str, cls: Any) -> Any:
    try:
        row = data[field]
        for name in _EXECUTION_ROW_DECIMALS[field]:
            if row[name] is not None:
                parse_decimal(row[name])
        return cls.from_dict(data)
    except WireCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise WireCodecError("WIRE_PAYLOAD_INVALID") from None


def _encode_execution_order(value: AccountExecutionOrderObservation) -> dict[str, Any]:
    return _encode_execution_row(value, "order")


def _decode_execution_order(data: Mapping[str, Any]) -> AccountExecutionOrderObservation:
    return _decode_execution_row(data, "order", AccountExecutionOrderObservation)


def _encode_execution_trade(value: AccountExecutionTradeObservation) -> dict[str, Any]:
    return _encode_execution_row(value, "trade")


def _decode_execution_trade(data: Mapping[str, Any]) -> AccountExecutionTradeObservation:
    return _decode_execution_row(data, "trade", AccountExecutionTradeObservation)


def _encode_strategy_command(payload: Any) -> dict[str, Any]:
    try:
        data = payload.to_dict()
        if type(payload).from_dict(data) != payload:
            raise ValueError("command cannot be represented faithfully")
        if type(payload) is StrategySubmitCommand:
            for name in ("quantity", "limit_price"):
                if data[name] is not None:
                    data[name] = canonical_decimal(data[name])
        return data
    except WireCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise WireCodecError("WIRE_PAYLOAD_INVALID") from None


def _decode_strategy_command(data: Mapping[str, Any], cls: Any) -> Any:
    try:
        if cls is StrategySubmitCommand:
            for name in ("quantity", "limit_price"):
                if data[name] is not None:
                    parse_decimal(data[name])
        return cls.from_dict(data)
    except WireCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise WireCodecError("WIRE_PAYLOAD_INVALID") from None


def _decode_strategy_submit(data: Mapping[str, Any]) -> StrategySubmitCommand:
    return _decode_strategy_command(data, StrategySubmitCommand)


def _decode_strategy_cancel(data: Mapping[str, Any]) -> StrategyCancelCommand:
    return _decode_strategy_command(data, StrategyCancelCommand)


def _decode_strategy_result(data: Mapping[str, Any]) -> StrategyCommandResult:
    return _decode_strategy_command(data, StrategyCommandResult)


# ---------------------------------------------------------------------------
# Strategy account book snapshot (minor 4, acceptance report G5)
# ---------------------------------------------------------------------------

_BOOK_FIELDS = tuple(f.name for f in dataclasses.fields(StrategyAccountBookSnapshot))
_BOOK_DECIMAL_MAPS = (
    "positions",
    "fees_since_baseline",
    "cash_by_currency",
    "cumulative_fees_by_currency",
)
_COST_FIELDS = tuple(f.name for f in dataclasses.fields(StrategyPositionCost))
_COST_DECIMALS = ("quantity", "cost_basis", "average_cost")
_CUT_FIELDS = tuple(f.name for f in dataclasses.fields(StrategyFinancialLedgerCut))
_WATERMARK_FIELDS = tuple(f.name for f in dataclasses.fields(StrategyFinancialWatermark))


def _decimal_or_none(value: Any) -> str | None:
    return None if value is None else canonical_decimal(value)


def _encode_strategy_book(snapshot: StrategyAccountBookSnapshot) -> dict[str, Any]:
    """Every snapshot field, Decimals as canonical lexemes; nothing dropped."""

    data: dict[str, Any] = {}
    for name in _BOOK_FIELDS:
        value = getattr(snapshot, name)
        if name in _BOOK_DECIMAL_MAPS:
            value = {key: canonical_decimal(amount) for key, amount in value.items()}
        elif name == "position_costs":
            value = {
                key: {
                    field: (
                        _decimal_or_none(getattr(cost, field))
                        if field in _COST_DECIMALS
                        else getattr(cost, field)
                    )
                    for field in _COST_FIELDS
                }
                for key, cost in value.items()
            }
        elif name == "financial_ledger_cut" and value is not None:
            value = {
                "account_key": value.account_key,
                "owner_directory_revision": value.owner_directory_revision,
                "captured_at_ns": value.captured_at_ns,
                "watermarks": [
                    {field: getattr(mark, field) for field in _WATERMARK_FIELDS}
                    for mark in value.watermarks
                ],
            }
        data[name] = value
    # The wire form must reproduce the snapshot exactly (numerically equal
    # Decimals, same rows); otherwise the snapshot is not representable.
    try:
        faithful = _decode_strategy_book(data) == snapshot
    except WireCodecError:
        raise
    except Exception:
        faithful = False
    if not faithful:
        raise WireCodecError("WIRE_PAYLOAD_INVALID")
    return data


def _exact_keys(value: Any, fields: tuple[str, ...]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    return value


def _decimal_rows(value: Any) -> dict[str, Decimal]:
    if not isinstance(value, dict):
        raise WireCodecError("WIRE_PAYLOAD_INVALID")
    return {key: parse_decimal(amount) for key, amount in value.items()}


def _decode_strategy_book(data: Mapping[str, Any]) -> StrategyAccountBookSnapshot:
    body = dict(_exact_keys(data, _BOOK_FIELDS))
    for name in _BOOK_DECIMAL_MAPS:
        body[name] = _decimal_rows(body[name])
    costs = body["position_costs"]
    if not isinstance(costs, dict):
        raise WireCodecError("WIRE_PAYLOAD_INVALID")
    parsed_costs = {}
    for key, raw in costs.items():
        row = dict(_exact_keys(raw, _COST_FIELDS))
        for field in _COST_DECIMALS:
            if row[field] is not None:
                row[field] = parse_decimal(row[field])
        parsed_costs[key] = StrategyPositionCost(**row)
    body["position_costs"] = parsed_costs
    cut = body["financial_ledger_cut"]
    if cut is not None:
        cut = dict(_exact_keys(cut, _CUT_FIELDS))
        marks = cut["watermarks"]
        if type(marks) is not list:
            raise WireCodecError("WIRE_PAYLOAD_INVALID")
        cut["watermarks"] = tuple(
            StrategyFinancialWatermark(**_exact_keys(mark, _WATERMARK_FIELDS)) for mark in marks
        )
        body["financial_ledger_cut"] = StrategyFinancialLedgerCut(**cut)
    return StrategyAccountBookSnapshot(**body)


_KINDS = {
    "tick": (MarketTickPayload, _encode_tick, _decode_tick),
    "bar": (MarketBar, _encode_bar, _decode_bar),
    "fill": (_FillFact, _encode_fill, _decode_fill),
    "account": (AccountObservation, _encode_account, _decode_account),
    "account_position": (AccountPositionObservation, _encode_position, _decode_position),
    "account_open_order": (AccountOpenOrderObservation, _encode_open_order, _decode_open_order),
    "execution_order": (AccountExecutionOrderObservation, _encode_execution_order, _decode_execution_order),
    "execution_trade": (AccountExecutionTradeObservation, _encode_execution_trade, _decode_execution_trade),
    "strategy_submit": (StrategySubmitCommand, _encode_strategy_command, _decode_strategy_submit),
    "strategy_cancel": (StrategyCancelCommand, _encode_strategy_command, _decode_strategy_cancel),
    "strategy_result": (StrategyCommandResult, _encode_strategy_command, _decode_strategy_result),
    "strategy_account_book": (
        StrategyAccountBookSnapshot,
        _encode_strategy_book,
        _decode_strategy_book,
    ),
}


def schema_digest() -> str:
    """Digest of the v1 kind registry, compared in the connection handshake.

    Two peers with the same version but different field tables must refuse
    to talk instead of interpreting messages differently.
    """

    registry = {
        "schema_id": SCHEMA_ID,
        "major": SUPPORTED_MAJOR,
        "minor": SUPPORTED_MINOR,
        "account_wire_semantics": _ACCOUNT_WIRE_SEMANTICS,
        "account_observation_rpc_map": {
            "schema_id": ACCOUNT_OBSERVATION_MAP_SCHEMA,
            "schema_version": _ACCOUNT_OBSERVATION_MAP_VERSION,
            "kind": "account",
            "source_decimal_spelling": "preserve-exactly-or-reject",
            "cursor": "rpc-snapshot-cursor-not-a-stream-sequence",
        },
        "kinds": {
            "tick": {
                "payload_schema_version": MARKET_TICK_SCHEMA_VERSION,
                "quality_contract_ref": "nullable-v2-non-executable-when-null",
                "fields": list(_TICK_FIELDS),
                "instrument": list(_INSTRUMENT_FIELDS),
                "decimals": sorted(_TICK_FLOATS),
                "enums": {k: [m.value for m in v] for k, v in sorted(_TICK_ENUMS.items())},
            },
            "bar": {"fields": list(_BAR_FIELDS)},
            "fill": {
                "schema": MANAGED_PAPER_FILL_V2_SCHEMA,
                "fields": sorted(MANAGED_PAPER_FILL_V2_FIELDS),
                "decimals": list(_FILL_DECIMALS),
                "integers": list(_FILL_INTEGERS),
            },
            "account": {
                "introduced_minor": 2,
                "observation_fields": sorted(AccountObservation._FIELDS),
                "without_open_orders_fields": sorted(AccountObservation._LEGACY_FIELDS),
                "account_key_fields": sorted(AccountKey._FIELDS),
                "resource_fields": sorted(AccountResourceKey._FIELDS),
                "instrument_fields": list(_INSTRUMENT_FIELDS),
                "balance_fields": sorted(AccountBalance._FIELDS),
                "position_fields": sorted(AccountPosition._FIELDS),
                "open_order_fields": sorted(AccountOpenOrder._FIELDS),
                "valuation_fields": sorted(AccountValuation._FIELDS),
                "decimals": _ACCOUNT_DECIMALS,
            },
            "account_position": {
                "introduced_minor": 2,
                "fields": sorted(AccountPositionObservation._FIELDS),
                "account_key_fields": sorted(AccountKey._FIELDS),
                "resource_fields": sorted(AccountResourceKey._FIELDS),
                "instrument_fields": list(_INSTRUMENT_FIELDS),
                "position_fields": sorted(AccountPosition._FIELDS),
                "decimals": _ACCOUNT_DECIMALS["positions"],
            },
            "account_open_order": {
                "introduced_minor": 2,
                "fields": sorted(AccountOpenOrderObservation._FIELDS),
                "account_key_fields": sorted(AccountKey._FIELDS),
                "resource_fields": sorted(AccountResourceKey._FIELDS),
                "instrument_fields": list(_INSTRUMENT_FIELDS),
                "open_order_fields": sorted(AccountOpenOrder._FIELDS),
                "decimals": _ACCOUNT_DECIMALS["open_orders"],
            },
            "execution_order": {
                "introduced_minor": 3,
                "fields": sorted(AccountExecutionOrderObservation._FIELDS),
                "account_fields": sorted(AccountKey._FIELDS),
                "row_fields": [f.name for f in dataclasses.fields(ExecutionOrderRecord)],
                "decimal_fields": _EXECUTION_ROW_DECIMALS["order"],
                "semantics_revision": 1,
                "semantics": {
                    "status": ["open", "partially_filled", "partially_filled_canceled",
                               "partially_filled_terminal", "terminal_unfilled", "unknown", "filled",
                               "canceled", "rejected", "trigger_pending", "triggered"],
                    "quantity": "positive; filled-nonnegative-and-at-most-quantity",
                    "scope": "exact-provider-environment-product-and-account-venue-with-ctp-simnow-rule",
                    "binding": "declared-only; independently-verify-source-and-intent",
                    "terminality": "provider-status-is-unverified; quantity-and-terminal-proof-required",
                },
            },
            "execution_trade": {
                "introduced_minor": 3,
                "fields": sorted(AccountExecutionTradeObservation._FIELDS),
                "account_fields": sorted(AccountKey._FIELDS),
                "row_fields": [f.name for f in dataclasses.fields(ExecutionTradeRecord)],
                "decimal_fields": _EXECUTION_ROW_DECIMALS["trade"],
                "semantics_revision": 1,
                "semantics": {
                    "quantity_and_price": "positive-canonical-decimal",
                    "scope": "exact-provider-environment-product-and-account-venue-with-ctp-simnow-rule",
                    "order_binding": "declared-only; independently-verify-source-and-order",
                    "fees": "not-present-and-not-implied-zero",
                },
            },
            "strategy_submit": {
                "introduced_minor": 3,
                "fields": [f.name for f in dataclasses.fields(StrategySubmitCommand)],
                "account_fields": sorted(AccountKey._FIELDS),
                "instrument_fields": list(_INSTRUMENT_FIELDS),
                "decimal_fields": ["quantity", "limit_price"],
                "semantics_revision": 1,
                "semantics": {
                    "sides": ["buy", "sell"],
                    "order_types": ["market", "limit"],
                    "time_in_force": ["GTC", "GFD", "DAY", "IOC", "FOK"],
                    "quantity_units": ["base", "contracts", "lots", "native"],
                    "quantity_and_limit_price": "positive-canonical-decimal; market-has-no-limit",
                    "price_currency": "optional; None-means-unknown-not-zero-or-default",
                    "position_side": ["long", "short", "net", None],
                    "position_effect": ["open", "close", "close_today", "close_yesterday", None],
                    "position_mode": ["net", "dual_side", None],
                    "hedge_class": ["speculation", "arbitrage", "hedge", None],
                    "reduce_only": "exact-bool; true-conflicts-with-explicit-open-effect",
                    "deadline": "optional-utc-epoch-ns; None-does-not-prove-validity",
                    "authorization": "not-provided; source-scope-and-idempotency-must-be-verified",
                    "unrepresentable_fields": "must-be-rejected-by-converter-never-dropped",
                },
            },
            "strategy_cancel": {
                "introduced_minor": 3,
                "fields": [f.name for f in dataclasses.fields(StrategyCancelCommand)],
                "account_fields": sorted(AccountKey._FIELDS),
                "instrument_fields": list(_INSTRUMENT_FIELDS),
                "semantics_revision": 1,
                "semantics": "client-order-id-required; no-authority-or-provider-identity-proof",
            },
            "strategy_account_book": {
                "introduced_minor": 4,
                "fields": list(_BOOK_FIELDS),
                "decimal_maps": list(_BOOK_DECIMAL_MAPS),
                "position_cost_fields": list(_COST_FIELDS),
                "position_cost_decimals": list(_COST_DECIMALS),
                "ledger_cut_fields": list(_CUT_FIELDS),
                "watermark_fields": list(_WATERMARK_FIELDS),
                "semantics_revision": 1,
                "semantics": {
                    "decimals": "canonical-lexeme; numerically-exact-round-trip-or-reject",
                    "rows": "at-most-wire-container-limit; larger-books-are-refused",
                    "financials": "only-with-complete-financial-cut; else-no-financial-rows",
                    "authority": "declared-only; route-and-owner-binding-verified-by-caller",
                },
            },
            "strategy_result": {
                "introduced_minor": 3,
                "fields": [f.name for f in dataclasses.fields(StrategyCommandResult)],
                "account_fields": sorted(AccountKey._FIELDS),
                "semantics_revision": 1,
                "semantics": {
                    "operation": ["submit", "cancel"],
                    "outcome": ["unknown", "accepted", "rejected"],
                    "accepted": "acknowledgement-only-not-terminal-or-authentication-proof",
                    "unknown": "not-safe-resubmit-or-rejection",
                    "observed_at": "optional-utc-epoch-ns-with-optional-source-precision-ns",
                },
            },
        },
    }
    blob = json.dumps(registry, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Encode / decode
# ---------------------------------------------------------------------------


def codec_backend() -> str:
    """Return ``"c"`` when msgpack's C extension is active, else ``"python"``.

    Wire contract v1 is only a performance improvement over JSON with the C
    extension (iteration 60.10 measurement); deployments should check this.
    """
    try:
        import msgpack
    except ImportError:
        return "python"
    return (
        "c"
        if getattr(msgpack.unpackb, "__module__", None) == "msgpack._cmsgpack"
        and getattr(msgpack.Packer, "__module__", None) == "msgpack._cmsgpack"
        else "python"
    )


def _msgpack() -> Any:
    try:
        import msgpack
    except ImportError:  # pragma: no cover - exercised only without the extra
        raise WireCodecError("WIRE_CODEC_UNAVAILABLE") from None
    return msgpack


def _check_extensions(extensions: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(extensions, Mapping) or len(extensions) > 16:
        raise WireCodecError("WIRE_EXTENSION_INVALID")
    checked: dict[str, dict[str, Any]] = {}
    for provider, fields in extensions.items():
        if type(provider) is not str or not _EXT_KEY_RE.fullmatch(provider):
            raise WireCodecError("WIRE_EXTENSION_INVALID")
        if not isinstance(fields, Mapping) or len(fields) > 64:
            raise WireCodecError("WIRE_EXTENSION_INVALID")
        values: dict[str, Any] = {}
        for key, value in fields.items():
            if type(key) is not str or not _EXT_KEY_RE.fullmatch(key):
                raise WireCodecError("WIRE_EXTENSION_INVALID")
            if value is not None and type(value) not in (str, int, bool):
                raise WireCodecError("WIRE_EXTENSION_INVALID")
            values[key] = value
        checked[provider] = values
    return checked


def encode_message(
    kind: str,
    payload: Any,
    *,
    stream: StreamPosition,
    extensions: Mapping[str, Mapping[str, Any]] | None = None,
) -> bytes:
    """Encode one frozen Base container into a v1 MessagePack message."""

    if type(kind) is not str:
        raise WireCodecError("WIRE_KIND_INVALID")
    entry = _KINDS.get(kind)
    if entry is None:
        raise WireCodecError("WIRE_KIND_INVALID")
    if entry[0] is _FillFact:
        if not isinstance(payload, Mapping):
            raise WireCodecError("WIRE_KIND_INVALID")
    elif type(payload) is not entry[0]:
        raise WireCodecError("WIRE_KIND_INVALID")
    if type(stream) is not StreamPosition:
        raise WireCodecError("WIRE_STREAM_INVALID")
    message: dict[str, Any] = {
        "schema_id": SCHEMA_ID,
        "major": SUPPORTED_MAJOR,
        "minor": SUPPORTED_MINOR,
        "kind": kind,
        "stream": {
            "stream_id": stream.stream_id,
            "epoch": stream.epoch,
            "sequence": stream.sequence,
        },
        "data": entry[1](payload),
    }
    if extensions:
        message["ext"] = _check_extensions(extensions)
    if kind in {"account", "account_position", "account_open_order", "execution_order", "execution_trade", "strategy_submit", "strategy_cancel", "strategy_result", "strategy_account_book"}:
        _check_values(message)
        _check_account_wire_bounds(message)
    data = _msgpack().packb(message, use_bin_type=True)
    if len(data) > MAX_MESSAGE_BYTES:
        raise WireCodecError("WIRE_MESSAGE_TOO_LARGE")
    return data


def _no_duplicates(pairs: list[tuple[Any, Any]]) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key, value in pairs:
        if type(key) is not str:
            raise WireCodecError("WIRE_MAP_KEY_INVALID")
        if key in result:
            raise WireCodecError("WIRE_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_ext(code: int, data: bytes) -> Any:
    raise WireCodecError("WIRE_EXTENSION_TYPE_INVALID")


_PLAIN_SCALARS = frozenset({str, bool, type(None)})


def _check_values(root: Any) -> None:
    """Reject floats, binary, out-of-range integers and over-deep nesting.

    Iterative with a fast path for the common scalar types: this check runs
    on every received message, so it avoids per-value recursion.
    """
    stack = [(root, 0)]
    pop = stack.pop
    push = stack.append
    while stack:
        value, depth = pop()
        if depth > MAX_DEPTH:
            raise WireCodecError("WIRE_DEPTH_EXCEEDED")
        kind = type(value)
        if kind in _PLAIN_SCALARS:
            continue
        if kind is int:
            if not _INT64_MIN <= value <= _INT64_MAX:
                raise WireCodecError("WIRE_INTEGER_RANGE")
        elif kind is dict:
            child = depth + 1
            for item in value.values():
                push((item, child))
        elif kind is list:
            child = depth + 1
            for item in value:
                push((item, child))
        elif kind is float:
            raise WireCodecError("WIRE_FLOAT_FORBIDDEN")
        else:
            raise WireCodecError("WIRE_VALUE_INVALID")


def _plain_typed_map(value: Any, depth: int = 0) -> Any:
    """Copy a service-frozen value while enforcing typed map limits.

    ``WireEnvelope`` freezes maps and lists as mapping proxies and tuples;
    only those exact built-in representations are accepted here.
    """
    if depth > MAX_DEPTH:
        raise WireCodecError("WIRE_DEPTH_EXCEEDED")
    kind = type(value)
    if kind in (dict, MappingProxyType):
        if len(value) > MAX_CONTAINER_LEN:
            raise WireCodecError("WIRE_VALUE_INVALID")
        result = {}
        for key, item in value.items():
            if type(key) is not str:
                raise WireCodecError("WIRE_MAP_KEY_INVALID")
            result[key] = _plain_typed_map(item, depth + 1)
        return result
    if kind in (tuple, list):
        if len(value) > MAX_CONTAINER_LEN:
            raise WireCodecError("WIRE_VALUE_INVALID")
        return [_plain_typed_map(item, depth + 1) for item in value]
    if value is None or kind in (str, bool):
        return value
    if kind is int and _INT64_MIN <= value <= _INT64_MAX:
        return value
    raise WireCodecError("WIRE_VALUE_INVALID")


def _check_typed_map_bounds(value: dict[str, Any]) -> None:
    _check_values(value)
    _check_account_wire_bounds(value)
    # A conservative text-size bound also caps the map before it enters the
    # independently bounded service envelope, without packing it twice.
    try:
        size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise WireCodecError("WIRE_VALUE_INVALID") from None
    if size > MAX_MESSAGE_BYTES:
        raise WireCodecError("WIRE_MESSAGE_TOO_LARGE")


def account_observation_to_typed_map(observation: AccountObservation) -> dict[str, Any]:
    """Create an account RPC value without a fictitious stream sequence.

    Decimal spelling is preserved exactly or rejected: changing it would
    change the existing journal snapshot's equal-cursor identity. This map is
    only data; service authentication and account authorization remain with
    the caller and receiver.
    """
    if type(observation) is not AccountObservation:
        raise WireCodecError("WIRE_KIND_INVALID")
    data = _encode_account(observation)
    if data != observation.to_dict():
        raise WireCodecError("WIRE_DECIMAL_NONCANONICAL")
    result = {
        "schema_id": ACCOUNT_OBSERVATION_MAP_SCHEMA,
        "schema_version": _ACCOUNT_OBSERVATION_MAP_VERSION,
        "major": SUPPORTED_MAJOR,
        "minor": SUPPORTED_MINOR,
        "kind": "account",
        "registry_digest": schema_digest(),
        "data": data,
    }
    _check_typed_map_bounds(result)
    return result


def account_observation_from_typed_map(value: Any) -> AccountObservation:
    """Validate and rebuild an account observation in an authenticated RPC."""
    raw = _plain_typed_map(value)
    if type(raw) is not dict or set(raw) != {
        "schema_id", "schema_version", "major", "minor", "kind", "registry_digest", "data"
    }:
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    _check_typed_map_bounds(raw)
    if raw["schema_id"] != ACCOUNT_OBSERVATION_MAP_SCHEMA or raw["kind"] != "account":
        raise WireCodecError("WIRE_SCHEMA_UNSUPPORTED")
    if (
        type(raw["schema_version"]) is not int
        or raw["schema_version"] != _ACCOUNT_OBSERVATION_MAP_VERSION
        or type(raw["major"]) is not int
        or raw["major"] != SUPPORTED_MAJOR
        or type(raw["minor"]) is not int
        or raw["minor"] != SUPPORTED_MINOR
        or type(raw["registry_digest"]) is not str
        or raw["registry_digest"] != schema_digest()
    ):
        raise WireCodecError("WIRE_SCHEMA_UNSUPPORTED")
    if type(raw["data"]) is not dict:
        raise WireCodecError("WIRE_PAYLOAD_INVALID")
    return _decode_account(raw["data"])


def decode_message(
    data: bytes, *, supported_minor: int = SUPPORTED_MINOR
) -> WireMessageV1:
    """Strictly decode one v1 message into its frozen Base container."""

    if type(supported_minor) is not int or not 0 <= supported_minor <= SUPPORTED_MINOR:
        raise WireCodecError("WIRE_MINOR_UNSUPPORTED")
    if type(data) is not bytes:
        raise WireCodecError("WIRE_FRAME_INVALID")
    if len(data) > MAX_MESSAGE_BYTES:
        raise WireCodecError("WIRE_MESSAGE_TOO_LARGE")
    msgpack = _msgpack()
    try:
        message = msgpack.unpackb(
            data,
            raw=False,
            use_list=True,
            strict_map_key=False,  # key type is checked by _no_duplicates
            object_pairs_hook=_no_duplicates,
            ext_hook=_reject_ext,
            max_str_len=MAX_STR_LEN,
            max_bin_len=0,
            max_array_len=MAX_CONTAINER_LEN,
            max_map_len=MAX_CONTAINER_LEN,
            max_ext_len=0,
        )
    except WireCodecError:
        raise
    except msgpack.ExtraData:
        raise WireCodecError("WIRE_TRAILING_BYTES") from None
    except Exception:
        raise WireCodecError("WIRE_FRAME_INVALID") from None
    if not isinstance(message, dict):
        raise WireCodecError("WIRE_FRAME_INVALID")
    _check_values(message)

    keys = set(message)
    if not _ENVELOPE_KEYS.issubset(keys) or keys - _ENVELOPE_KEYS - {"ext"}:
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    if message["schema_id"] != SCHEMA_ID:
        raise WireCodecError("WIRE_SCHEMA_UNSUPPORTED")
    major, minor = message["major"], message["minor"]
    if type(major) is not int or major != SUPPORTED_MAJOR:
        raise WireCodecError("WIRE_MAJOR_UNSUPPORTED")
    if type(minor) is not int or minor < 0 or minor > supported_minor:
        raise WireCodecError("WIRE_MINOR_UNSUPPORTED")
    if type(message["kind"]) is not str:
        raise WireCodecError("WIRE_KIND_INVALID")
    entry = _KINDS.get(message["kind"])
    if entry is None:
        raise WireCodecError("WIRE_KIND_INVALID")
    stream = message["stream"]
    if not isinstance(stream, dict) or set(stream) != _STREAM_KEYS:
        raise WireCodecError("WIRE_STREAM_INVALID")
    position = StreamPosition(stream["stream_id"], stream["epoch"], stream["sequence"])
    body = message["data"]
    if not isinstance(body, dict):
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    if message["kind"] in {"account", "account_position", "account_open_order"} and minor < 2:
        raise WireCodecError("WIRE_MINOR_UNSUPPORTED")
    if message["kind"] in {"execution_order", "execution_trade", "strategy_submit", "strategy_cancel", "strategy_result"} and minor < 3:
        raise WireCodecError("WIRE_MINOR_UNSUPPORTED")
    if message["kind"] == "strategy_account_book" and minor < 4:
        raise WireCodecError("WIRE_MINOR_UNSUPPORTED")
    # A legacy v1.0 tick required a concrete rule reference. Do not let a
    # producer claim the older version while sending a v1.1 null value.
    if (
        message["kind"] == "tick"
        and minor == 0
        and "quality_contract_ref" in body
        and body["quality_contract_ref"] is None
    ):
        raise WireCodecError("WIRE_PAYLOAD_INVALID")
    try:
        payload = entry[2](body)
    except WireCodecError:
        raise
    except Exception:
        # Base container validation rejected the values.
        raise WireCodecError("WIRE_PAYLOAD_INVALID") from None
    extensions = _check_extensions(message.get("ext", {}))
    return WireMessageV1(
        kind=message["kind"],
        payload=payload,
        stream=position,
        minor=minor,
        extensions=extensions,
    )


# ---------------------------------------------------------------------------
# Command identity
# ---------------------------------------------------------------------------


DEFAULT_DECIMAL_FIELDS = frozenset(
    {
        "quantity",
        "price",
        "limit_price",
        "stop_price",
        "trigger_price",
        "notional",
        "amount",
    }
)


def command_fingerprint(
    command: Mapping[str, Any], *, decimal_fields: frozenset[str] = DEFAULT_DECIMAL_FIELDS
) -> str:
    """Semantic fingerprint used for "same command ID, same content" checks.

    Equivalent encodings produce the same fingerprint: key order, absent vs.
    ``None`` optional fields, and numerically equal values of the declared
    ``decimal_fields`` (``"1.50"``, ``1.5``, ``Decimal("1.5")``) all agree.
    Every other string, including identifiers such as ``"007"``, is compared
    verbatim. Any change of account, route, strategy, command type or
    business parameter changes the fingerprint.
    """

    if not isinstance(command, Mapping):
        raise WireCodecError("WIRE_VALUE_INVALID")

    def normalize(value: Any, key: str | None) -> Any:
        if key in decimal_fields and value is not None and not isinstance(value, bool):
            return {"$d": canonical_decimal(value)}
        if isinstance(value, Mapping):
            if any(type(item) is not str for item in value):
                raise WireCodecError("WIRE_MAP_KEY_INVALID")
            return {k: normalize(v, k) for k, v in value.items() if v is not None}
        if isinstance(value, (list, tuple)):
            return [normalize(item, None) for item in value]
        if isinstance(value, enum.Enum):
            return value.value
        if value is None or isinstance(value, (bool, str, int)):
            return value
        if isinstance(value, (float, Decimal)):
            return {"$d": canonical_decimal(value)}
        raise WireCodecError("WIRE_VALUE_INVALID")

    canonical = normalize(dict(command), None)
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()
