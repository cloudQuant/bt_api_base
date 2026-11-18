"""Versioned neutral contracts for the independent Risk service (iteration 64).

The values here describe a request to the Risk service, the Risk service's
answer, and the shared control (kill switch) vocabulary. They are claims and
records only: they do not authenticate a caller, prove a provider or account
fact, grant a write, or prove that an order was or was not sent. The Risk
service binds every request to the authenticated principal and its installed
grants; the Gateway never checks a Risk approval.

Numbers are exact decimals carried as strings on the wire. Empty optional
fields mean "unknown", never zero. Every refusal uses a code from
``RISK_REFUSAL_CODES``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from bt_api_base.market_protocol import MarketInstrumentKey

RISK_SERVICE_SCHEMA = "bt_api.risk_service.v1"
RISK_SERVICE_V2_SCHEMA = "bt_api.risk_service.v2"
RISK_SERVICE_PORT = "service.risk_order"
RISK_ADMIN_PORT = "service.risk_admin"

# Operations a strategy or an authorized execution delegate may call.
RISK_ORDER_V2_OPERATIONS = frozenset(
    {
        "risk.order.reserve.v2",
        "risk.order.dispatch.v2",
    }
)
RISK_PARENT_OPERATIONS = frozenset(
    {
        "risk.parent.reserve",
        "risk.parent.release",
        "risk.parent.status",
    }
)
RISK_ORDER_OPERATIONS = frozenset(
    {
        "risk.order.reserve",
        "risk.order.dispatch",
        "risk.order.release",
        "risk.order.status",
        "risk.status",
    }
    | RISK_ORDER_V2_OPERATIONS
    | RISK_PARENT_OPERATIONS
)
# Operations an authorized operator may call (read and authorized changes).
RISK_ADMIN_OPERATIONS = frozenset(
    {
        "risk.admin.status",
        "risk.policy.read",
        "risk.policy.publish",
        "risk.latch.list",
        "risk.latch.release",
        "risk.unknown.list",
        "risk.counts.export",
        "risk.audit.read",
        "risk.cancel.request",
        "risk.cancel.status",
    }
)

# Finite codes. A code describes why this check refused; on its own it does not
# prove that an earlier or concurrent request with the same identity was not sent.
RISK_REFUSAL_CODES = frozenset(
    {
        # configuration and selection (checked before connecting to an account)
        "risk_selection_missing",
        "risk_selection_invalid",
        "risk_requires_gateway",
        # availability and identity
        "risk_unavailable",
        "risk_policy_unavailable",
        "risk_unauthorized",
        "risk_request_conflict",
        "risk_permit_mismatch",
        "risk_permit_expired",
        "risk_request_invalid",
        "risk_facts_unverified",
        "risk_trading_day_unavailable",
        # catalog (R-01 .. R-11)
        "risk_limit_unconfigured",
        "risk_order_quantity_exceeds_cap",
        "risk_order_notional_exceeds_cap",
        "risk_instrument_facts_unavailable",
        "risk_price_band_exceeded",
        "risk_price_band_market_order",
        "risk_reference_price_unavailable",
        "risk_position_limit_exceeded",
        "risk_position_facts_unavailable",
        "risk_closable_exceeded",
        "risk_closable_unverified",
        "risk_order_count_limit",
        "risk_self_trade",
        "risk_self_trade_unverifiable",
        "risk_duplicate_order",
        "risk_loss_limit",
        "risk_pnl_unknown",
        "risk_margin_insufficient",
        "risk_margin_facts_unavailable",
        "risk_exchange_rule_exceeded",
        "risk_exchange_rule_unavailable",
        "risk_breach_latched",
        "risk_rule_failed",
        # parent orders (64.10)
        "risk_parent_envelope_exceeded",
        "risk_parent_unavailable",
        "risk_parent_frozen",
        # Gateway answered with a definite refusal (the Gateway code is carried separately)
        "risk_gateway_refused",
    }
)

# Result outcomes of risk.order.* and risk.parent.*.
RISK_OUTCOMES = frozenset(
    {
        "DENIED",  # refused; a reserve refusal before any Gateway call is definite
        "RESERVED",  # Risk and Gateway both hold the reservation
        "DISPATCHED",  # claimed and accepted by the Gateway for dispatch (not a fill)
        "RELEASED",  # proven not sent after a reservation existed
        "TERMINAL",  # the order reached a terminal state in the observation stream
        "UNKNOWN",  # outcome not provable; worst-case occupancy is kept
        "NOT_FOUND",  # status only: no record under this identity in this scope
    }
)

# Permit states inside the Risk ledger (reported by risk.order.status).
RISK_PERMIT_STATES = frozenset(
    {
        "RESERVING",
        "RESERVED",
        "CLAIMED",
        "DISPATCHED",
        "RELEASING",
        "RELEASED",
        "DENIED",
        "UNKNOWN",
        "TERMINAL",
    }
)

SIDES = frozenset({"BUY", "SELL"})
OFFSETS = frozenset({"OPEN", "CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"})
POSITION_SIDES = frozenset({"NET", "LONG", "SHORT"})
ORIGINS = frozenset({"strategy", "execution"})

# Bound untrusted strings before hashing while following the declared vocabulary.
_MAX_ORIGIN_LENGTH = max(map(len, ORIGINS))
_MAX_SIDE_LENGTH = max(map(len, SIDES))
_MAX_POSITION_SIDE_LENGTH = max(map(len, POSITION_SIDES))
_MAX_OFFSET_LENGTH = max(map(len, OFFSETS))
_MAX_OUTCOME_LENGTH = max(map(len, RISK_OUTCOMES))
_MAX_PERMIT_STATE_LENGTH = max(map(len, RISK_PERMIT_STATES))
_MAX_REFUSAL_CODE_LENGTH = max(map(len, RISK_REFUSAL_CODES))

# Shared kill switch vocabulary (the Gateway owns control state; these are names only).
KILL_SWITCH_ACTIONS = frozenset({"FREEZE", "STOP_NEW", "DRAIN", "RESUME"})
KILL_SWITCH_SCOPES = frozenset({"account", "strategy", "instrument"})
KILL_SWITCH_RESULTS = frozenset({"APPLIED", "PARTIAL", "REJECTED", "UNKNOWN"})


class RiskServiceProtocolError(ValueError):
    """Finite validation failure that never echoes untrusted values."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise RiskServiceProtocolError(code)


def _ref(value: object, *, limit: int = 256) -> bool:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= limit
    except UnicodeError:
        return False


def _optional_ref(value: object) -> bool:
    return value is None or _ref(value)


def _trading_day(value: object) -> bool:
    if (type(value) is not str or len(value) != 8
            or not value.isascii() or not value.isdigit()):
        return False
    try:
        date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except ValueError:
        return False
    return True


def _decimal(value: object, code: str, *, positive: bool) -> Decimal:
    if type(value) is Decimal:
        number = value
    elif (type(value) is str and value and len(value) <= _DECIMAL_MAX_TEXT
          and value == value.strip()):
        try:
            number = Decimal(value)
        except InvalidOperation:
            _fail(code)
    else:
        _fail(code)
    if not number.is_finite() or (positive and number <= 0) or (not positive and number < 0):
        _fail(code)
    return number


# Bound both the coefficient and the fixed-point expansion before formatting.
# These limits narrow accepted v1 inputs; they do not change successful bytes.
_DECIMAL_MAX_DIGITS = 4096
_DECIMAL_MAX_EXPONENT = 4096
_DECIMAL_MAX_TEXT = 4096


def _decimal_text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite():
        _fail("RISK_DECIMAL_ENCODING_INVALID")
    sign, digits, exponent = value.as_tuple()
    count = len(digits)
    if count > _DECIMAL_MAX_DIGITS or abs(exponent) > _DECIMAL_MAX_EXPONENT:
        _fail("RISK_DECIMAL_ENCODING_INVALID")
    # Upper bound before normalization, including sign and decimal point.
    point = count + exponent
    if exponent >= 0:
        size = sign + count + exponent
    elif point > 0:
        size = sign + count + 1
    else:
        size = sign + 2 - point + count
    if size > _DECIMAL_MAX_TEXT:
        _fail("RISK_DECIMAL_ENCODING_INVALID")
    try:
        # Decimal's fixed-point formatter preserves all digits without consulting
        # the ambient context; normalize() would round or trap under that context.
        text = format(value, "f")
    except (ValueError, OverflowError):
        raise RiskServiceProtocolError("RISK_DECIMAL_ENCODING_INVALID") from None
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if value.is_zero() else text


def canonical_risk_json(value: Mapping) -> str:
    """Canonical JSON used for digests (sorted keys, no floats, no NaN)."""

    def check(item: object, depth: int) -> None:
        if depth > 8:
            _fail("RISK_PAYLOAD_TOO_DEEP")
        if item is None or type(item) in (bool, int, str):
            return
        if type(item) in (list, tuple):
            for element in item:
                check(element, depth + 1)
            return
        if type(item) is dict:
            for key, element in item.items():
                if type(key) is not str or not key:
                    _fail("RISK_PAYLOAD_INVALID")
                check(element, depth + 1)
            return
        _fail("RISK_PAYLOAD_INVALID")

    if type(value) is not dict:
        _fail("RISK_PAYLOAD_INVALID")
    check(value, 0)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def risk_digest(value: Mapping) -> str:
    return hashlib.sha256(canonical_risk_json(value).encode("utf-8")).hexdigest()


def _instrument_from(value: object) -> MarketInstrumentKey:
    if type(value) is MarketInstrumentKey:
        return value
    if type(value) is not dict or set(value) != set(MarketInstrumentKey._FIELDS):
        _fail("RISK_INSTRUMENT_INVALID")
    try:
        return MarketInstrumentKey(**value)
    except (TypeError, ValueError):
        _fail("RISK_INSTRUMENT_INVALID")
    raise AssertionError("unreachable")


@dataclass(frozen=True, slots=True)
class RiskOrderView:
    """The order as the Risk service evaluates it.

    The Risk host builds this from the canonical order payload it forwards and
    from the authenticated caller; a caller cannot choose the effect
    (INCREASE/REDUCE), which Risk derives from the explicit offset and trusted
    Gateway facts. ``limit_price`` is None for orders without a limit price.
    """

    account_scope: str
    route: str
    strategy_ref: str
    origin: str
    request_key: str
    instrument: MarketInstrumentKey
    side: str
    offset: str | None
    position_side: str
    quantity: Decimal
    quantity_unit: str
    order_type: str
    limit_price: Decimal | None
    time_in_force: str | None = None
    trading_day: str | None = None
    session_epoch: str | None = None
    parent_ref: str | None = None
    child_id: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            _fail("RISK_VIEW_SCHEMA_UNSUPPORTED")
        for name in (
            "account_scope",
            "route",
            "strategy_ref",
            "request_key",
            "quantity_unit",
            "order_type",
        ):
            if not _ref(getattr(self, name)):
                _fail("RISK_VIEW_INVALID")
        if (
            type(self.origin) is not str
            or len(self.origin) > _MAX_ORIGIN_LENGTH
            or self.origin not in ORIGINS
            or type(self.side) is not str
            or len(self.side) > _MAX_SIDE_LENGTH
            or self.side not in SIDES
            or type(self.position_side) is not str
            or len(self.position_side) > _MAX_POSITION_SIDE_LENGTH
            or self.position_side not in POSITION_SIDES
        ):
            _fail("RISK_VIEW_INVALID")
        if self.offset is not None and (
            type(self.offset) is not str
            or len(self.offset) > _MAX_OFFSET_LENGTH
            or self.offset not in OFFSETS
        ):
            _fail("RISK_VIEW_INVALID")
        if type(self.instrument) is not MarketInstrumentKey:
            _fail("RISK_VIEW_INVALID")
        object.__setattr__(
            self, "quantity", _decimal(self.quantity, "RISK_VIEW_INVALID", positive=True)
        )
        if self.limit_price is not None:
            object.__setattr__(
                self, "limit_price", _decimal(self.limit_price, "RISK_VIEW_INVALID", positive=True)
            )
        for name in ("time_in_force", "session_epoch"):
            if not _optional_ref(getattr(self, name)):
                _fail("RISK_VIEW_INVALID")
        if self.trading_day is not None and not _trading_day(self.trading_day):
            _fail("RISK_VIEW_INVALID")
        if (self.parent_ref is None) != (self.child_id is None):
            _fail("RISK_VIEW_INVALID")
        if self.parent_ref is not None and (not _ref(self.parent_ref) or not _ref(self.child_id)):
            _fail("RISK_VIEW_INVALID")
        if self.origin == "execution" and self.parent_ref is None:
            _fail("RISK_VIEW_INVALID")

    @property
    def is_close(self) -> bool:
        return self.offset in ("CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY")

    def to_mapping(self) -> dict:
        return {
            "schema": RISK_SERVICE_SCHEMA,
            "schema_version": self.schema_version,
            "account_scope": self.account_scope,
            "route": self.route,
            "strategy_ref": self.strategy_ref,
            "origin": self.origin,
            "request_key": self.request_key,
            "instrument": self.instrument.to_dict(),
            "side": self.side,
            "offset": self.offset,
            "position_side": self.position_side,
            "quantity": _decimal_text(self.quantity),
            "quantity_unit": self.quantity_unit,
            "order_type": self.order_type,
            "limit_price": None if self.limit_price is None else _decimal_text(self.limit_price),
            "time_in_force": self.time_in_force,
            "trading_day": self.trading_day,
            "session_epoch": self.session_epoch,
            "parent_ref": self.parent_ref,
            "child_id": self.child_id,
        }

    def digest(self) -> str:
        return risk_digest(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Mapping) -> RiskOrderView:
        if type(value) is not dict or value.get("schema") != RISK_SERVICE_SCHEMA:
            _fail("RISK_VIEW_INVALID")
        expected = {
            "schema",
            "schema_version",
            "account_scope",
            "route",
            "strategy_ref",
            "origin",
            "request_key",
            "instrument",
            "side",
            "offset",
            "position_side",
            "quantity",
            "quantity_unit",
            "order_type",
            "limit_price",
            "time_in_force",
            "trading_day",
            "session_epoch",
            "parent_ref",
            "child_id",
        }
        if set(value) != expected:
            _fail("RISK_VIEW_INVALID")
        if type(value["quantity"]) is not str or (
            value["limit_price"] is not None and type(value["limit_price"]) is not str
        ):
            _fail("RISK_VIEW_INVALID")
        return cls(
            account_scope=value["account_scope"],
            route=value["route"],
            strategy_ref=value["strategy_ref"],
            origin=value["origin"],
            request_key=value["request_key"],
            instrument=_instrument_from(value["instrument"]),
            side=value["side"],
            offset=value["offset"],
            position_side=value["position_side"],
            quantity=value["quantity"],
            quantity_unit=value["quantity_unit"],
            order_type=value["order_type"],
            limit_price=value["limit_price"],
            time_in_force=value["time_in_force"],
            trading_day=value["trading_day"],
            session_epoch=value["session_epoch"],
            parent_ref=value["parent_ref"],
            child_id=value["child_id"],
            schema_version=value["schema_version"],
        )


@dataclass(frozen=True, slots=True)
class RiskOrderResult:
    """Answer of risk.order.reserve / dispatch / release / status.

    ``code`` is a finite refusal code (``RISK_REFUSAL_CODES``) or None.
    ``gateway_code`` carries the Gateway's own finite code when the Gateway
    answered; it is a value-free identifier, never a message.
    """

    request_key: str
    outcome: str
    state: str | None = None
    permit_id: str | None = None
    reservation_id: str | None = None
    code: str | None = None
    gateway_code: str | None = None
    gateway_state: str | None = None
    policy_version: str | None = None
    view_digest: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            _fail("RISK_RESULT_INVALID")
        if (
            not _ref(self.request_key)
            or type(self.outcome) is not str
            or len(self.outcome) > _MAX_OUTCOME_LENGTH
            or self.outcome not in RISK_OUTCOMES
        ):
            _fail("RISK_RESULT_INVALID")
        if self.state is not None and (
            type(self.state) is not str
            or len(self.state) > _MAX_PERMIT_STATE_LENGTH
            or self.state not in RISK_PERMIT_STATES
        ):
            _fail("RISK_RESULT_INVALID")
        if self.code is not None and (
            type(self.code) is not str
            or len(self.code) > _MAX_REFUSAL_CODE_LENGTH
            or self.code not in RISK_REFUSAL_CODES
        ):
            _fail("RISK_RESULT_INVALID")
        if self.outcome == "DENIED" and self.code is None:
            _fail("RISK_RESULT_INVALID")
        for name in (
            "permit_id",
            "reservation_id",
            "gateway_code",
            "gateway_state",
            "policy_version",
        ):
            if not _optional_ref(getattr(self, name)):
                _fail("RISK_RESULT_INVALID")
        if self.view_digest is not None and (
            type(self.view_digest) is not str
            or len(self.view_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.view_digest)
        ):
            _fail("RISK_RESULT_INVALID")

    @property
    def definite_refusal(self) -> bool:
        """True only for a DENIED answer; it still proves nothing about other requests."""
        return self.outcome == "DENIED"

    def to_mapping(self) -> dict:
        return {
            "schema": RISK_SERVICE_SCHEMA,
            "schema_version": self.schema_version,
            "request_key": self.request_key,
            "outcome": self.outcome,
            "state": self.state,
            "permit_id": self.permit_id,
            "reservation_id": self.reservation_id,
            "code": self.code,
            "gateway_code": self.gateway_code,
            "gateway_state": self.gateway_state,
            "policy_version": self.policy_version,
            "view_digest": self.view_digest,
        }

    @classmethod
    def from_mapping(cls, value: Mapping) -> RiskOrderResult:
        expected = {
            "schema",
            "schema_version",
            "request_key",
            "outcome",
            "state",
            "permit_id",
            "reservation_id",
            "code",
            "gateway_code",
            "gateway_state",
            "policy_version",
            "view_digest",
        }
        if (
            type(value) is not dict
            or set(value) != expected
            or value.get("schema") != RISK_SERVICE_SCHEMA
        ):
            _fail("RISK_RESULT_INVALID")
        return cls(
            request_key=value["request_key"],
            outcome=value["outcome"],
            state=value["state"],
            permit_id=value["permit_id"],
            reservation_id=value["reservation_id"],
            code=value["code"],
            gateway_code=value["gateway_code"],
            gateway_state=value["gateway_state"],
            policy_version=value["policy_version"],
            view_digest=value["view_digest"],
            schema_version=value["schema_version"],
        )


@dataclass(frozen=True, slots=True)
class RiskParentView:
    """A parent order envelope as submitted by an authorized execution delegate (64.10).

    The parent has no single price: ``limit_price`` is the parent's price bound
    when the plan has one, else None. ``valid_until_trading_day`` is the last
    trading day on which children may be admitted.
    """

    account_scope: str
    route: str
    strategy_ref: str
    parent_ref: str
    instrument: MarketInstrumentKey
    side: str
    offset: str | None
    position_side: str
    total_quantity: Decimal
    quantity_unit: str
    limit_price: Decimal | None
    created_trading_day: str
    valid_until_trading_day: str
    schema_version: int = 1
    valid_until_ns: int | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version not in (1, 2):
            _fail("RISK_PARENT_INVALID")
        for name in ("account_scope", "route", "strategy_ref", "parent_ref", "quantity_unit"):
            if not _ref(getattr(self, name)):
                _fail("RISK_PARENT_INVALID")
        if (
            type(self.side) is not str
            or len(self.side) > _MAX_SIDE_LENGTH
            or self.side not in SIDES
            or type(self.position_side) is not str
            or len(self.position_side) > _MAX_POSITION_SIDE_LENGTH
            or self.position_side not in POSITION_SIDES
        ):
            _fail("RISK_PARENT_INVALID")
        if self.offset is not None and (
            type(self.offset) is not str
            or len(self.offset) > _MAX_OFFSET_LENGTH
            or self.offset not in OFFSETS
        ):
            _fail("RISK_PARENT_INVALID")
        if self.schema_version == 1:
            if self.valid_until_ns is not None:
                _fail("RISK_PARENT_INVALID")
        else:
            if (
                self.offset is None
                or type(self.valid_until_ns) is not int
                or not 0 < self.valid_until_ns <= 2**63 - 1
            ):
                _fail("RISK_PARENT_INVALID")
        if type(self.instrument) is not MarketInstrumentKey:
            _fail("RISK_PARENT_INVALID")
        object.__setattr__(
            self,
            "total_quantity",
            _decimal(self.total_quantity, "RISK_PARENT_INVALID", positive=True),
        )
        if self.limit_price is not None:
            object.__setattr__(
                self,
                "limit_price",
                _decimal(self.limit_price, "RISK_PARENT_INVALID", positive=True),
            )
        for name in ("created_trading_day", "valid_until_trading_day"):
            day = getattr(self, name)
            if not _trading_day(day):
                _fail("RISK_PARENT_INVALID")
        if self.valid_until_trading_day < self.created_trading_day:
            _fail("RISK_PARENT_INVALID")

    def to_mapping(self) -> dict:
        schema = RISK_SERVICE_V2_SCHEMA if self.schema_version == 2 else RISK_SERVICE_SCHEMA
        mapping = {
            "schema": schema,
            "schema_version": self.schema_version,
            "account_scope": self.account_scope,
            "route": self.route,
            "strategy_ref": self.strategy_ref,
            "parent_ref": self.parent_ref,
            "instrument": self.instrument.to_dict(),
            "side": self.side,
            "offset": self.offset,
            "position_side": self.position_side,
            "total_quantity": _decimal_text(self.total_quantity),
            "quantity_unit": self.quantity_unit,
            "limit_price": None if self.limit_price is None else _decimal_text(self.limit_price),
            "created_trading_day": self.created_trading_day,
            "valid_until_trading_day": self.valid_until_trading_day,
        }
        if self.schema_version == 2:
            mapping["valid_until_ns"] = self.valid_until_ns
        return mapping

    def digest(self) -> str:
        return risk_digest(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Mapping) -> RiskParentView:
        base_fields = {
            "schema",
            "schema_version",
            "account_scope",
            "route",
            "strategy_ref",
            "parent_ref",
            "instrument",
            "side",
            "offset",
            "position_side",
            "total_quantity",
            "quantity_unit",
            "limit_price",
            "created_trading_day",
            "valid_until_trading_day",
        }
        if type(value) is not dict:
            _fail("RISK_PARENT_INVALID")
        schema_version = value.get("schema_version")
        schema = value.get("schema")
        if schema_version == 1:
            if set(value) != base_fields or schema != RISK_SERVICE_SCHEMA:
                _fail("RISK_PARENT_INVALID")
            valid_until_ns = None
        elif schema_version == 2:
            if set(value) != base_fields | {"valid_until_ns"} or schema != RISK_SERVICE_V2_SCHEMA:
                _fail("RISK_PARENT_INVALID")
            valid_until_ns = value["valid_until_ns"]
        else:
            _fail("RISK_PARENT_INVALID")
        if type(value["total_quantity"]) is not str or (
            value["limit_price"] is not None and type(value["limit_price"]) is not str
        ):
            _fail("RISK_PARENT_INVALID")
        return cls(
            account_scope=value["account_scope"],
            route=value["route"],
            strategy_ref=value["strategy_ref"],
            parent_ref=value["parent_ref"],
            instrument=_instrument_from(value["instrument"]),
            side=value["side"],
            offset=value["offset"],
            position_side=value["position_side"],
            total_quantity=value["total_quantity"],
            quantity_unit=value["quantity_unit"],
            limit_price=value["limit_price"],
            created_trading_day=value["created_trading_day"],
            valid_until_trading_day=value["valid_until_trading_day"],
            schema_version=schema_version,
            valid_until_ns=valid_until_ns,
        )


CONTROL_SCOPE_SCHEMA = "bt_api.control_scope"
CONTROL_SCOPE_VERSION = 2


@dataclass(frozen=True, slots=True)
class ControlScopeV2:
    """Account or complete-instrument control scope, independent of v1 commands.

    The account reference and every instrument field are claims, not proof of
    account ownership, provider origin, or authority. Consumers must bind them
    to the authenticated account and grants before acting. No v1 scope string
    or persisted control state can be inferred or migrated from this contract.
    """

    account_scope: str
    kind: str
    schema_version: int
    instrument: MarketInstrumentKey | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != CONTROL_SCOPE_VERSION:
            _fail("CONTROL_SCOPE_SCHEMA_UNSUPPORTED")
        if not _ref(self.account_scope) or type(self.kind) is not str:
            _fail("CONTROL_SCOPE_INVALID")
        if self.kind == "account":
            if self.instrument is not None:
                _fail("CONTROL_SCOPE_INVALID")
        elif self.kind == "instrument":
            if type(self.instrument) is not MarketInstrumentKey:
                _fail("CONTROL_SCOPE_INVALID")
        else:
            _fail("CONTROL_SCOPE_INVALID")

    def to_mapping(self) -> dict:
        value = {
            "schema": CONTROL_SCOPE_SCHEMA,
            "schema_version": self.schema_version,
            "kind": self.kind,
            "account_scope": self.account_scope,
        }
        if self.kind == "instrument":
            value["instrument"] = self.instrument.to_dict()
        return value

    @classmethod
    def from_mapping(cls, value: object) -> ControlScopeV2:
        if type(value) is not dict or any(type(key) is not str for key in value):
            _fail("CONTROL_SCOPE_INVALID")
        if type(value.get("schema")) is not str or value["schema"] != CONTROL_SCOPE_SCHEMA:
            _fail("CONTROL_SCOPE_SCHEMA_UNSUPPORTED")
        if (
            type(value.get("schema_version")) is not int
            or value["schema_version"] != CONTROL_SCOPE_VERSION
        ):
            _fail("CONTROL_SCOPE_SCHEMA_UNSUPPORTED")
        kind = value.get("kind")
        fields = {"schema", "schema_version", "kind", "account_scope"}
        if kind == "instrument":
            fields.add("instrument")
        if set(value) != fields or type(kind) is not str or kind not in {"account", "instrument"}:
            _fail("CONTROL_SCOPE_INVALID")
        instrument = None
        if kind == "instrument":
            if type(value["instrument"]) is not dict or any(
                type(key) is not str for key in value["instrument"]
            ):
                _fail("CONTROL_SCOPE_INVALID")
            instrument = _instrument_from(value["instrument"])
        return cls(value["account_scope"], kind, value["schema_version"], instrument)

    def canonical_bytes(self) -> bytes:
        """UTF-8 JSON, sorted keys, no whitespace; strings are not normalized."""
        return canonical_risk_json(self.to_mapping()).encode("utf-8")

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> ControlScopeV2:
        """Decode only the exact canonical representation, rejecting duplicate keys."""
        if type(raw) is not bytes or len(raw) > 4096:
            _fail("CONTROL_SCOPE_INVALID")

        def unique_pairs(pairs: list[tuple[str, object]]) -> dict:
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate field")
                result[key] = value
            return result

        try:
            decoded = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique_pairs)
        except (UnicodeError, ValueError, RecursionError):
            _fail("CONTROL_SCOPE_INVALID")
        scope = cls.from_mapping(decoded)
        if scope.canonical_bytes() != raw:
            _fail("CONTROL_SCOPE_INVALID")
        return scope


@dataclass(frozen=True, slots=True)
class KillSwitchCommand:
    """A control request in the shared vocabulary; the Gateway decides and holds state.

    ``scope_value`` is empty for the account scope, the strategy UUID for the
    strategy scope, and the canonical instrument id for the instrument scope.
    RESUME is listed for completeness: a Risk service never resumes a cause.
    """

    command_id: str
    action: str
    scope_kind: str
    scope_value: str
    reason_code: str
    origin: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or not _ref(self.command_id)
            or self.action not in KILL_SWITCH_ACTIONS
            or self.scope_kind not in KILL_SWITCH_SCOPES
            or type(self.scope_value) is not str
            or (self.scope_kind == "account") != (self.scope_value == "")
            or (self.scope_value and not _ref(self.scope_value))
            or not _ref(self.reason_code)
            or not _ref(self.origin)
        ):
            _fail("KILL_SWITCH_COMMAND_INVALID")

    def to_mapping(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "command_id": self.command_id,
            "action": self.action,
            "scope_kind": self.scope_kind,
            "scope_value": self.scope_value,
            "reason_code": self.reason_code,
            "origin": self.origin,
        }


__all__ = [
    "CONTROL_SCOPE_SCHEMA",
    "CONTROL_SCOPE_VERSION",
    "ControlScopeV2",
    "KILL_SWITCH_ACTIONS",
    "KILL_SWITCH_RESULTS",
    "KILL_SWITCH_SCOPES",
    "KillSwitchCommand",
    "OFFSETS",
    "ORIGINS",
    "POSITION_SIDES",
    "RISK_ADMIN_OPERATIONS",
    "RISK_ADMIN_PORT",
    "RISK_ORDER_OPERATIONS",
    "RISK_ORDER_V2_OPERATIONS",
    "RISK_OUTCOMES",
    "RISK_PARENT_OPERATIONS",
    "RISK_PERMIT_STATES",
    "RISK_REFUSAL_CODES",
    "RISK_SERVICE_PORT",
    "RISK_SERVICE_SCHEMA",
    "RISK_SERVICE_V2_SCHEMA",
    "RiskOrderResult",
    "RiskOrderView",
    "RiskParentView",
    "RiskServiceProtocolError",
    "SIDES",
    "canonical_risk_json",
    "risk_digest",
]
