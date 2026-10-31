"""Provider-neutral order-rule request and decision contracts.

The decision is a short-lived, read-only rule evaluation.  It is not order
authorization, a write claim, a native reservation, or permission to dispatch.
Instrument and fee facts must be selected by the SDK/provider for the exact
instrument and account-session generation in the request.  The contract keeps
price and fee currencies explicit; numeric CTP ``ByMoney``/``ByVolume`` values
alone do not prove either currency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from typing import Literal, Protocol, runtime_checkable

from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import MAX_REFERENCE_BYTES

_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z", re.ASCII)
_POSITION_MODES = frozenset({"net", "dual_side"})
_POSITION_SIDES = frozenset({"long", "short"})
_OFFSETS = frozenset({"open", "close", "close_today", "close_yesterday"})
_FEE_ROLES = _OFFSETS
_ASSET_KINDS = frozenset({"future", "option", "unknown"})
_RULE_STATUSES = frozenset({"available", "unavailable"})
_DECISION_STATUSES = frozenset({"accepted", "rejected", "unavailable"})
_CURRENCY_STATUSES = frozenset({"verified", "unavailable"})

RuleStatus = Literal["accepted", "rejected", "unavailable"]


def _canonical_time_in_force(value: str | None) -> str:
    """Return the semantic TIF name used by the accepted-decision contract."""

    if value is None:
        return "GFD"
    canonical = value.upper().replace("-", "_")
    if canonical in {"GFD", "GOOD_FOR_DAY"}:
        return "GFD"
    return canonical


def _check_text(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise TypeError(f"{field} must be a string" + (" or None" if optional else ""))
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} must be valid UTF-8") from exc
    if not value or value != value.strip() or size > MAX_REFERENCE_BYTES or not value.isprintable():
        raise ValueError(f"{field} must be non-empty printable trimmed UTF-8 within the byte limit")
    return value


def _check_currency(value: object, field: str, *, optional: bool = False) -> str | None:
    checked = _check_text(value, field, optional=optional)
    if checked is not None and (
        checked != checked.upper()
        or len(checked) > 12
        or not checked.isascii()
        or not checked.replace("_", "").isalnum()
    ):
        raise ValueError(f"{field} must be a canonical uppercase currency code")
    return checked


def _check_decimal(
    value: object,
    field: str,
    *,
    optional: bool = False,
    positive: bool = False,
    nonnegative: bool = False,
    signed: bool = False,
) -> Decimal | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise TypeError(f"{field} must be a decimal string" + (" or None" if optional else ""))
    if not value or len(value) > 128 or value != value.strip() or not _DECIMAL_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be a bounded finite decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a bounded finite decimal string") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    if positive and number <= 0:
        raise ValueError(f"{field} must be positive")
    if nonnegative and number < 0:
        raise ValueError(f"{field} must be non-negative")
    if not signed and not positive and not nonnegative and number < 0:
        raise ValueError(f"{field} must be non-negative")
    return number


def _check_optional_utc(value: object, field: str, *, optional: bool = False) -> datetime | None:
    if value is None and optional:
        return None
    if type(value) is not datetime:
        raise TypeError(f"{field} must be a datetime" + (" or None" if optional else ""))
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be timezone-aware UTC")
    return value


@dataclass(frozen=True)
class CommissionRuleFacts:
    """One role's CTP-compatible ByMoney/ByVolume fee dimensions.

    ``by_money_rate`` is the raw decimal ratio applied to price times contract
    multiplier by the historical Broker formula. ``by_volume_amount`` is the
    raw amount per contract. These names preserve the SDK wire values; they do
    not assert a cash currency. A fee amount is usable for accounting only when
    currency, source and both dimensions are explicitly verified.
    """

    role: str
    by_money_rate: str | None
    by_volume_amount: str | None
    currency: str | None
    currency_status: str
    source_ref: str | None
    currency_source_ref: str | None = None
    session_generation: str | None = None
    currency_session_generation: str | None = None

    def __post_init__(self) -> None:
        _check_text(self.role, "role")
        if self.role not in _FEE_ROLES:
            raise ValueError("role must be open, close, close_today, or close_yesterday")
        _check_decimal(self.by_money_rate, "by_money_rate", optional=True, nonnegative=True)
        _check_decimal(self.by_volume_amount, "by_volume_amount", optional=True, nonnegative=True)
        if type(self.currency_status) is not str or self.currency_status not in _CURRENCY_STATUSES:
            raise ValueError("currency_status is invalid")
        _check_currency(self.currency, "currency", optional=True)
        _check_text(self.source_ref, "source_ref", optional=True)
        _check_text(self.currency_source_ref, "currency_source_ref", optional=True)
        _check_text(self.session_generation, "session_generation", optional=True)
        _check_text(
            self.currency_session_generation, "currency_session_generation", optional=True
        )
        if self.currency_status == "verified":
            if (
                self.currency is None
                or self.currency_source_ref is None
                or self.currency_session_generation is None
                or self.session_generation is None
                or self.currency_session_generation != self.session_generation
                or self.source_ref is None
                or self.session_generation is None
                or self.by_money_rate is None
                or self.by_volume_amount is None
            ):
                raise ValueError("verified fee facts require both dimensions and currency provenance")
        elif (
            self.currency is not None
            or self.currency_source_ref is not None
            or self.currency_session_generation is not None
        ):
            raise ValueError("unverified fee currency must be None")


@dataclass(frozen=True)
class InstrumentExecutionFacts:
    """Short-lived, exact-instrument facts for evaluating an order.

    Source and session references are opaque neutral identifiers. They must
    never contain CTP OrderRef, FrontID, SessionID, request IDs, credentials,
    or account identity. This DTO is evidence-shaped data, not a capability.
    """

    instrument: MarketInstrumentKey
    status: str
    reason_code: str | None
    session_generation: str | None
    source_ref: str | None
    observed_at_utc: datetime | None
    expires_at_utc: datetime | None
    asset_kind: str
    price_tick: str | None
    contract_multiplier: str | None
    price_currency: str | None
    price_currency_status: str
    price_currency_source_ref: str | None = None
    price_currency_session_generation: str | None = None
    option_right: str | None = None
    option_strike: str | None = None
    option_expiry: date | None = None
    option_premium_style: str | None = None
    commission_rules: tuple[CommissionRuleFacts, ...] = ()

    def __post_init__(self) -> None:
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be a MarketInstrumentKey")
        if type(self.status) is not str or self.status not in _RULE_STATUSES:
            raise ValueError("status must be available or unavailable")
        _check_text(self.reason_code, "reason_code", optional=True)
        _check_text(self.session_generation, "session_generation", optional=True)
        _check_text(self.source_ref, "source_ref", optional=True)
        _check_optional_utc(self.observed_at_utc, "observed_at_utc", optional=True)
        _check_optional_utc(self.expires_at_utc, "expires_at_utc", optional=True)
        if type(self.asset_kind) is not str or self.asset_kind not in _ASSET_KINDS:
            raise ValueError("asset_kind must be future, option, or unknown")
        _check_decimal(self.price_tick, "price_tick", optional=True, positive=True)
        _check_decimal(self.contract_multiplier, "contract_multiplier", optional=True, positive=True)
        _check_currency(self.price_currency, "price_currency", optional=True)
        _check_text(self.price_currency_source_ref, "price_currency_source_ref", optional=True)
        _check_text(
            self.price_currency_session_generation,
            "price_currency_session_generation",
            optional=True,
        )
        if (
            type(self.price_currency_status) is not str
            or self.price_currency_status not in _CURRENCY_STATUSES
        ):
            raise ValueError("price_currency_status is invalid")
        if self.price_currency_status == "verified":
            if (
                self.price_currency is None
                or self.price_currency_source_ref is None
                or self.session_generation is None
                or self.price_currency_session_generation != self.session_generation
            ):
                raise ValueError("verified price currency requires same-session provenance")
        elif (
            self.price_currency is not None
            or self.price_currency_source_ref is not None
            or self.price_currency_session_generation is not None
        ):
            raise ValueError("unverified price currency must be None")
        _check_text(self.option_right, "option_right", optional=True)
        _check_decimal(self.option_strike, "option_strike", optional=True, positive=True)
        if self.option_expiry is not None and type(self.option_expiry) is not date:
            raise TypeError("option_expiry must be a datetime.date or None")
        _check_text(self.option_premium_style, "option_premium_style", optional=True)
        if type(self.commission_rules) is not tuple or any(
            type(item) is not CommissionRuleFacts for item in self.commission_rules
        ):
            raise TypeError("commission_rules must be a tuple of CommissionRuleFacts")
        roles = tuple(item.role for item in self.commission_rules)
        if len(roles) != len(set(roles)):
            raise ValueError("commission_rules must contain one row per role")
        if self.status == "available":
            if (
                self.reason_code is not None
                or self.session_generation is None
                or self.source_ref is None
                or self.observed_at_utc is None
                or self.expires_at_utc is None
                or self.expires_at_utc <= self.observed_at_utc
                or self.asset_kind == "unknown"
            ):
                raise ValueError("available facts require exact source/session and expiry evidence")
        elif self.reason_code is None:
            raise ValueError("unavailable facts require a reason code")


@dataclass(frozen=True)
class ExecutionRuleRequest:
    """Neutral order facts needed by CTP order-rule validation.

    Position quantities are decimal strings in contracts. ``net_position_size``
    is signed; long, short, and day-bucket sizes are unsigned. Missing position
    or session facts are represented as ``None`` and must yield unavailable
    where a decision depends on them. Position quantities are projections,
    not account evidence: close evaluation also requires an SDK-issued opaque
    position evidence reference that the provider validates against the exact
    quantities, session generation, observation time, and expiry.
    """

    instrument: MarketInstrumentKey
    session_generation: str | None
    side: str
    quantity: str
    order_type: str
    time_in_force: str | None
    limit_price: str | None
    position_mode: str
    position_side: str | None
    offset: str | None
    net_position_size: str | None = None
    long_position_size: str | None = None
    short_position_size: str | None = None
    long_close_today_size: str | None = None
    long_close_yesterday_size: str | None = None
    short_close_today_size: str | None = None
    short_close_yesterday_size: str | None = None
    position_evidence_ref: str | None = None
    position_evidence_generation: str | None = None
    position_observed_at_utc: datetime | None = None
    position_expires_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be a MarketInstrumentKey")
        _check_text(self.session_generation, "session_generation", optional=True)
        _check_text(self.side, "side")
        _check_decimal(self.quantity, "quantity", positive=True)
        _check_text(self.order_type, "order_type")
        _check_text(self.time_in_force, "time_in_force", optional=True)
        _check_decimal(self.limit_price, "limit_price", optional=True, positive=True)
        if type(self.position_mode) is not str or self.position_mode not in _POSITION_MODES:
            raise ValueError("position_mode must be net or dual_side")
        if self.position_side is not None:
            _check_text(self.position_side, "position_side")
            if self.position_side not in _POSITION_SIDES:
                raise ValueError("position_side must be long or short")
        if self.offset is not None:
            _check_text(self.offset, "offset")
            if self.offset not in _OFFSETS:
                raise ValueError("offset is invalid")
        _check_decimal(self.net_position_size, "net_position_size", optional=True, signed=True)
        for field in (
            "long_position_size",
            "short_position_size",
            "long_close_today_size",
            "long_close_yesterday_size",
            "short_close_today_size",
            "short_close_yesterday_size",
        ):
            _check_decimal(getattr(self, field), field, optional=True, nonnegative=True)
        _check_text(self.position_evidence_ref, "position_evidence_ref", optional=True)
        _check_text(self.position_evidence_generation, "position_evidence_generation", optional=True)
        _check_optional_utc(self.position_observed_at_utc, "position_observed_at_utc", optional=True)
        _check_optional_utc(self.position_expires_at_utc, "position_expires_at_utc", optional=True)
        position_evidence_values = (
            self.position_evidence_ref,
            self.position_evidence_generation,
            self.position_observed_at_utc,
            self.position_expires_at_utc,
        )
        if any(value is not None for value in position_evidence_values) and not all(
            value is not None for value in position_evidence_values
        ):
            raise ValueError("position evidence fields must be supplied together")
        if (
            self.position_observed_at_utc is not None
            and self.position_expires_at_utc is not None
            and self.position_expires_at_utc <= self.position_observed_at_utc
        ):
            raise ValueError("position evidence expiry must follow its observation")


@dataclass(frozen=True)
class ExecutionRuleDecision:
    """Rule outcome bound to the exact request and the selected short-lived facts.

    ``accepted`` means only that the declared order satisfies the returned
    supported rule set and fee projection. It never grants write permission;
    the facade's independent claim and authorization contracts remain required.
    A caller must not treat the DTO's structural validity as evidence that the
    SDK has revalidated its facts or position lease at claim/dispatch time.
    """

    request: ExecutionRuleRequest
    status: str
    reason_code: str | None
    facts: InstrumentExecutionFacts | None
    normalized_position_side: str | None
    normalized_offset: str | None
    normalized_time_in_force: str | None
    commission_estimate: str | None
    commission_currency: str | None
    commission_charge_unit: str | None
    position_evidence_validated: bool

    def __post_init__(self) -> None:
        if type(self.request) is not ExecutionRuleRequest:
            raise TypeError("request must be an ExecutionRuleRequest")
        if type(self.status) is not str or self.status not in _DECISION_STATUSES:
            raise ValueError("status must be accepted, rejected, or unavailable")
        _check_text(self.reason_code, "reason_code", optional=True)
        if self.facts is not None and type(self.facts) is not InstrumentExecutionFacts:
            raise TypeError("facts must be InstrumentExecutionFacts or None")
        if self.normalized_position_side is not None:
            _check_text(self.normalized_position_side, "normalized_position_side")
            if self.normalized_position_side not in _POSITION_SIDES:
                raise ValueError("normalized_position_side is invalid")
        if self.normalized_offset is not None:
            _check_text(self.normalized_offset, "normalized_offset")
            if self.normalized_offset not in _OFFSETS:
                raise ValueError("normalized_offset is invalid")
        _check_text(self.normalized_time_in_force, "normalized_time_in_force", optional=True)
        if (
            self.normalized_time_in_force is not None
            and self.normalized_time_in_force
            != _canonical_time_in_force(self.request.time_in_force)
        ):
            raise ValueError("decision time-in-force must preserve the request semantics")
        if (
            self.request.offset is not None
            and self.normalized_offset is not None
            and self.normalized_offset != self.request.offset
        ):
            raise ValueError("decision offset must preserve an explicit request offset")
        if (
            self.request.position_side is not None
            and self.normalized_position_side is not None
            and self.normalized_position_side != self.request.position_side
        ):
            raise ValueError("decision position side must preserve an explicit request side")
        _check_decimal(self.commission_estimate, "commission_estimate", optional=True, nonnegative=True)
        _check_currency(self.commission_currency, "commission_currency", optional=True)
        _check_text(self.commission_charge_unit, "commission_charge_unit", optional=True)
        if type(self.position_evidence_validated) is not bool:
            raise TypeError("position_evidence_validated must be an exact bool")
        if self.status == "accepted":
            if (
                self.reason_code is not None
                or self.facts is None
                or self.facts.status != "available"
                or self.request.session_generation is None
                or self.facts.instrument != self.request.instrument
                or self.facts.session_generation != self.request.session_generation
                or self.facts.expires_at_utc is None
                or self.facts.price_tick is None
                or self.facts.contract_multiplier is None
                or self.facts.price_currency_status != "verified"
                or self.facts.price_currency is None
                or self.facts.price_currency != self.commission_currency
                or self.normalized_position_side is None
                or self.normalized_offset is None
                or self.normalized_time_in_force
                != _canonical_time_in_force(self.request.time_in_force)
                or self.commission_estimate is None
                or self.commission_currency is None
                or self.commission_charge_unit != "currency_amount"
            ):
                raise ValueError("accepted decision must bind exact current rules and fee facts")
            needs_position_evidence = (
                self.request.position_mode == "net" and self.request.offset is None
            ) or self.normalized_offset != "open"
            if needs_position_evidence and (
                not self.position_evidence_validated
                or self.request.position_evidence_ref is None
                or self.request.position_evidence_generation != self.request.session_generation
                or self.request.position_observed_at_utc is None
                or self.request.position_expires_at_utc is None
            ):
                raise ValueError("accepted close decision requires validated position evidence")
            _verify_fee_projection(self)
        elif self.reason_code is None:
            raise ValueError("rejected and unavailable decisions require a reason code")


def _verify_fee_projection(decision: ExecutionRuleDecision) -> None:
    """Recompute the bounded CTP fee estimate from the echoed facts."""

    request = decision.request
    facts = decision.facts
    if facts is None:
        raise ValueError("accepted decision requires facts")
    role = decision.normalized_offset
    by_role = {item.role: item for item in facts.commission_rules}
    fee = by_role.get(role or "")
    if role == "close_yesterday" and fee is None:
        fee = by_role.get("close")
    if (
        fee is None
        or fee.currency_status != "verified"
        or fee.currency != decision.commission_currency
        or fee.currency_session_generation != facts.session_generation
        or fee.session_generation != facts.session_generation
        or fee.source_ref is None
        or fee.by_money_rate is None
        or fee.by_volume_amount is None
        or facts.price_currency_session_generation != facts.session_generation
        or facts.price_currency_source_ref is None
        or request.limit_price is None
    ):
        raise ValueError("accepted decision lacks same-session complete fee facts")
    quantity = _check_decimal(request.quantity, "quantity", positive=True)
    price = _check_decimal(request.limit_price, "limit_price", positive=True)
    multiplier = _check_decimal(facts.contract_multiplier, "contract_multiplier", positive=True)
    rate = _check_decimal(fee.by_money_rate, "by_money_rate", nonnegative=True)
    amount = _check_decimal(fee.by_volume_amount, "by_volume_amount", nonnegative=True)
    tick = _check_decimal(facts.price_tick, "price_tick", positive=True)
    estimate = _check_decimal(decision.commission_estimate, "commission_estimate", nonnegative=True)
    if None in (quantity, price, multiplier, rate, amount, tick, estimate):
        raise ValueError("accepted fee calculation contains a missing value")
    with localcontext() as context:
        context.prec = 700
        scaled = price / tick
        nearest = scaled.to_integral_value(rounding=ROUND_HALF_EVEN)
        if abs(scaled - nearest) > Decimal("0.000000001"):
            raise ValueError("accepted decision price does not align with its tick")
        expected = quantity * (price * multiplier * rate + amount)
    if estimate != expected:
        raise ValueError("accepted decision fee estimate does not match its source facts")


@runtime_checkable
class ExecutionRulesPort(Protocol):
    """SDK facade capability for read-only evaluation of a neutral order request."""

    def evaluate_order_rules(self, request: ExecutionRuleRequest) -> ExecutionRuleDecision:
        """Evaluate one exact-session order without claiming or dispatching it."""
        ...


__all__ = [
    "CommissionRuleFacts",
    "ExecutionRuleDecision",
    "ExecutionRuleRequest",
    "ExecutionRulesPort",
    "InstrumentExecutionFacts",
    "RuleStatus",
]
