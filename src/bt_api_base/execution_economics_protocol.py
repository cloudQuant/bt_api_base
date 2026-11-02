"""Provider-neutral, source-bound order affordability and margin contracts.

Economics decisions are read-only preflight evidence. They do not reserve cash,
margin, or inventory and do not grant authorization, a write claim, or dispatch
permission. A caller must revalidate the short-lived evidence at the independent
claim/dispatch boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Callable, Literal, Optional, Protocol, runtime_checkable

from bt_api_base.execution_correlation_protocol import SelectedExecutionRoute
from bt_api_base.execution_rules_protocol import ExecutionRuleDecision, ExecutionRuleRequest
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import MAX_REFERENCE_BYTES

_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z", re.ASCII)
_STATUSES = frozenset({"accepted", "rejected", "unavailable"})
_REQUIREMENT_KINDS = frozenset({"cash", "margin"})
_AMOUNT_UNIT = "currency_amount"

EconomicsStatus = Literal["accepted", "rejected", "unavailable"]
RequirementKind = Literal["cash", "margin"]
EconomicsRevalidationStage = Literal["claim", "dispatch"]


def _text(value: object, field: str, *, optional: bool = False) -> str | None:
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


def _currency(value: object, *, optional: bool = False) -> str | None:
    checked = _text(value, "currency", optional=optional)
    if checked is not None and (
        checked != checked.upper()
        or len(checked) > 12
        or not checked.isascii()
        or not checked.replace("_", "").isalnum()
    ):
        raise ValueError("currency must be a canonical uppercase currency code")
    return checked


def _amount(value: object, field: str, *, optional: bool = False) -> Decimal | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise TypeError(
            f"{field} must be a decimal string" + (" or None" if optional else "")
        )
    if (
        not value
        or len(value) > 128
        or value != value.strip()
        or not _DECIMAL_PATTERN.fullmatch(value)
    ):
        raise ValueError(f"{field} must be a bounded finite decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a bounded finite decimal string") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return parsed


def _utc(value: object, field: str, *, optional: bool = False) -> datetime | None:
    if value is None and optional:
        return None
    if type(value) is not datetime:
        raise TypeError(f"{field} must be a datetime" + (" or None" if optional else ""))
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be timezone-aware UTC")
    return value


@dataclass(frozen=True)
class ExecutionEconomicsRequest:
    """Bind an affordability check to one exact accepted rule decision.

    ``quantity_unit`` is an SDK-neutral declared unit. For CTP futures/options,
    the provider uses ``contract``. The SDK must not infer it from a ticker or
    from Backtrader's local position object.
    """

    rule_request: ExecutionRuleRequest
    rule_decision: ExecutionRuleDecision
    instrument: MarketInstrumentKey
    quantity_unit: str

    def __post_init__(self) -> None:
        if type(self.rule_request) is not ExecutionRuleRequest:
            raise TypeError("rule_request must be an ExecutionRuleRequest")
        if type(self.rule_decision) is not ExecutionRuleDecision:
            raise TypeError("rule_decision must be an ExecutionRuleDecision")
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be a MarketInstrumentKey")
        _text(self.quantity_unit, "quantity_unit")
        if (
            self.instrument != self.rule_request.instrument
            or self.rule_decision.request != self.rule_request
            or self.rule_decision.status != "accepted"
        ):
            raise ValueError("economics request must bind the exact accepted rule request/decision")


@dataclass(frozen=True)
class ExecutionEconomicsDecision:
    """Short-lived cash/margin evidence for one neutral order request.

    ``available_amount`` is spendable headroom after provider-held obligations
    and configured risk buffers. ``source_ref`` binds the required cash/margin
    calculation and ``account_balance_source_ref`` binds the source of
    ``available_amount``. The SDK issuer must bind both to the same opaque
    ``account_scope_ref`` and session generation. The decision interval is the
    intersection of all bound evidence intervals and cannot extend any input's
    freshness. References are SDK-neutral opaque identifiers: they must not
    contain account identifiers, credentials, or native CTP order/session
    identifiers. They are claims for verification, not cryptographic proof by
    themselves. ``lease_ref`` identifies this read-only evidence window; it is
    not a money reservation, write claim, or dispatch capability.
    """

    request: ExecutionEconomicsRequest
    status: str
    reason_code: str | None
    requirement_kind: str | None
    instrument: MarketInstrumentKey
    evaluated_quantity: str | None
    quantity_unit: str | None
    required_amount: str | None
    available_amount: str | None
    currency: str | None
    amount_unit: str | None
    fee_included: bool
    source_ref: str | None
    account_balance_source_ref: str | None
    account_scope_ref: str | None
    session_generation: str | None
    observed_at_utc: datetime | None
    expires_at_utc: datetime | None
    lease_ref: str | None

    def __post_init__(self) -> None:
        if type(self.request) is not ExecutionEconomicsRequest:
            raise TypeError("request must be an ExecutionEconomicsRequest")
        if type(self.status) is not str or self.status not in _STATUSES:
            raise ValueError("status must be accepted, rejected, or unavailable")
        _text(self.reason_code, "reason_code", optional=True)
        if self.requirement_kind is not None and (
            type(self.requirement_kind) is not str
            or self.requirement_kind not in _REQUIREMENT_KINDS
        ):
            raise ValueError("requirement_kind must be cash, margin, or None")
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be a MarketInstrumentKey")
        _amount(self.evaluated_quantity, "evaluated_quantity", optional=True)
        _text(self.quantity_unit, "quantity_unit", optional=True)
        _amount(self.required_amount, "required_amount", optional=True)
        _amount(self.available_amount, "available_amount", optional=True)
        _currency(self.currency, optional=True)
        _text(self.amount_unit, "amount_unit", optional=True)
        if type(self.fee_included) is not bool:
            raise TypeError("fee_included must be an exact bool")
        _text(self.source_ref, "source_ref", optional=True)
        _text(self.account_balance_source_ref, "account_balance_source_ref", optional=True)
        _text(self.account_scope_ref, "account_scope_ref", optional=True)
        _text(self.session_generation, "session_generation", optional=True)
        _utc(self.observed_at_utc, "observed_at_utc", optional=True)
        _utc(self.expires_at_utc, "expires_at_utc", optional=True)
        _text(self.lease_ref, "lease_ref", optional=True)

        generation = self.request.rule_request.session_generation
        if self.instrument != self.request.instrument:
            raise ValueError("economics decision instrument does not match its request")
        if self.session_generation is not None and self.session_generation != generation:
            raise ValueError("economics decision session generation does not match its request")
        if (
            self.evaluated_quantity is not None
            and self.evaluated_quantity != self.request.rule_request.quantity
        ):
            raise ValueError("economics decision quantity does not match its request")
        if self.quantity_unit is not None and self.quantity_unit != self.request.quantity_unit:
            raise ValueError("economics decision quantity unit does not match its request")
        if (self.observed_at_utc is None) != (self.expires_at_utc is None):
            raise ValueError("economics evidence timestamps must be supplied together")
        if (
            self.observed_at_utc is not None
            and self.expires_at_utc is not None
            and self.expires_at_utc <= self.observed_at_utc
        ):
            raise ValueError("economics evidence expiry must follow its observation")

        if self.status == "accepted":
            if (
                self.reason_code is not None
                or self.requirement_kind is None
                or self.evaluated_quantity != self.request.rule_request.quantity
                or self.quantity_unit != self.request.quantity_unit
                or self.required_amount is None
                or self.available_amount is None
                or self.currency is None
                or self.amount_unit != _AMOUNT_UNIT
                or not self.fee_included
                or self.source_ref is None
                or self.account_balance_source_ref is None
                or self.account_scope_ref is None
                or generation is None
                or self.session_generation != generation
                or self.observed_at_utc is None
                or self.expires_at_utc is None
                or self.lease_ref is None
            ):
                raise ValueError(
                    "accepted economics decision lacks exact order and source evidence"
                )
            if self.request.rule_decision.status != "accepted":
                raise ValueError("accepted economics decision requires an accepted rule decision")
            rule_facts = self.request.rule_decision.facts
            if (
                rule_facts is None
                or rule_facts.observed_at_utc is None
                or rule_facts.expires_at_utc is None
                or self.observed_at_utc < rule_facts.observed_at_utc
                or self.expires_at_utc > rule_facts.expires_at_utc
            ):
                raise ValueError("economics evidence cannot outlive its bound rule facts")
            fee_amount = _amount(
                self.request.rule_decision.commission_estimate,
                "commission_estimate",
                optional=True,
            )
            fee_currency = self.request.rule_decision.commission_currency
            if (
                fee_amount is None
                or fee_currency != self.currency
                or self.required_amount is None
            ):
                raise ValueError("accepted economics must include a verified same-currency fee")
            required = _amount(self.required_amount, "required_amount")
            available = _amount(self.available_amount, "available_amount")
            if required is None or available is None or required < fee_amount:
                raise ValueError("required amount must include the verified fee estimate")
            if required > available:
                raise ValueError("insufficient available amount cannot be accepted")
        elif self.reason_code is None:
            raise ValueError("rejected and unavailable economics decisions require a reason code")


@runtime_checkable
class ExecutionEconomicsPort(Protocol):
    """SDK-owned route-bound economics evidence and freshness verifier.

    Structural validity of an ``ExecutionEconomicsDecision`` is not proof that
    its issuer produced it or that its balance snapshot is still current. The
    SDK implementation must resolve the exact request/decision and opaque
    lease/source references against its own issuer state.
    """

    def evaluate_order_economics(
        self, request: ExecutionEconomicsRequest
    ) -> ExecutionEconomicsDecision:
        """Evaluate affordability for one exact rule decision without reserving funds."""
        ...

    def revalidate_order_economics(
        self,
        request: ExecutionEconomicsRequest,
        decision: ExecutionEconomicsDecision,
        *,
        stage: EconomicsRevalidationStage,
    ) -> bool:
        """Revalidate the exact evidence lease immediately at a write boundary.

        The SDK owner must independently confirm that this exact immutable
        request and decision map to its issued evidence; that ``lease_ref``,
        ``source_ref``, ``account_balance_source_ref``, ``account_scope_ref``
        and session generation still resolve to the same selected route; and
        that the bound rule facts, position evidence, and exact balance
        snapshot are still authoritative, unexpired, same-generation,
        same-currency, and sufficient for the exact amount including the bound
        verified fee. It uses its own current clock and current provider
        source/session evidence; callers cannot provide or override either. A
        changed/superseded balance snapshot invalidates this decision; the SDK
        must require a fresh evaluation instead of silently substituting new
        amounts or source references. A stale, superseded, unavailable,
        ambiguous, or unresolvable reference must return the exact bool
        ``False``. Only exact ``True`` means this evidence was revalidated at
        the requested ``claim`` or ``dispatch`` boundary.

        This boolean is an observation, not a write capability or
        authorization. SDK claim and dispatch authorities must enforce their
        own revalidation at each boundary, using the same SDK-held evidence
        issuer; a caller-side check cannot replace that enforcement. An
        exception, a non-exact-bool result, or any state that the issuer cannot
        prove is failure and must not continue to dispatch. The check does not
        reserve cash, margin, or inventory and cannot promise affordability
        after the check. A provider that cannot revalidate the exact current
        evidence at a boundary must fail closed and must not dispatch.
        """
        ...


ExecutionEconomicsProviderFactory = Callable[
    [SelectedExecutionRoute], Optional[ExecutionEconomicsPort]
]


@runtime_checkable
class ExecutionEconomicsProviderRegistryPort(Protocol):
    """Provider-neutral exact-route registration contract.

    Registration makes a factory discoverable, not its output authoritative.
    A provider factory must return an owner only when its trusted runtime has
    supplied the exact evidence issuer/source binding required by the route.
    """

    def register(
        self,
        exchange_name: str,
        factory: ExecutionEconomicsProviderFactory,
    ) -> None: ...


__all__ = [
    "EconomicsStatus",
    "EconomicsRevalidationStage",
    "ExecutionEconomicsDecision",
    "ExecutionEconomicsPort",
    "ExecutionEconomicsProviderFactory",
    "ExecutionEconomicsProviderRegistryPort",
    "ExecutionEconomicsRequest",
    "RequirementKind",
]
