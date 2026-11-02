"""Provider-neutral reconciliation DTOs and authority protocol.

This module belongs to bt_api_base so provider plugins and the SDK facade can
share one neutral contract without a provider package importing its parent
composition package. DTO values describe evidence; they do not establish trust
or authorize execution by themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

from bt_api_base.execution_correlation_protocol import OrderCorrelation

_FAMILIES = frozenset({"orders", "fills", "positions"})
_ORDER_STATUSES = frozenset(
    {"open", "partially_filled", "completed", "canceled", "rejected", "expired", "unknown"}
)
_TERMINAL_ORDER_STATUSES = frozenset({"completed", "canceled", "rejected", "expired"})
_POSITION_SIDES = frozenset({"net", "long", "short"})
_FEE_RATE_UNITS = frozenset(
    {"quote_notional", "base_quantity", "contract", "per_order", "per_fill"}
)


def validate_reconciliation_order_status(status: object, terminal_confirmed: object) -> None:
    """Validate neutral status and terminal flag without establishing provenance."""
    if type(status) is not str or status not in _ORDER_STATUSES:
        raise ValueError("order status is not normalized")
    if type(terminal_confirmed) is not bool:
        raise TypeError("terminal_confirmed must be a bool")
    if terminal_confirmed != (status in _TERMINAL_ORDER_STATUSES):
        raise ValueError("terminal status confirmation does not match status")


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        raise ValueError(f"{field_name} must be non-empty, trimmed printable text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be valid UTF-8") from exc
    if len(encoded) > 256:
        raise ValueError(f"{field_name} exceeds the UTF-8 byte limit")
    return value


def _decimal(value: object, field_name: str, *, minimum: Decimal | None = None) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise TypeError(f"{field_name} must be a finite Decimal")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field_name} is below its minimum")
    return value


def _utc(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be a timezone-aware UTC datetime")
    return value


def _texts(values: object, field_name: str) -> tuple[str, ...]:
    if type(values) not in (tuple, list):
        raise TypeError(f"{field_name} must be a tuple or list")
    result = tuple(_text(value, field_name) for value in values)
    if len(set(result)) != len(result):
        raise ValueError(f"{field_name} must not contain duplicates")
    return result


@dataclass(frozen=True)
class ReconciliationRequest:
    """SDK-owned account and strategy scope to reconcile.

    References are opaque and contain no credential material. An empty
    ``instrument_refs`` or ``intent_refs`` means the complete corresponding
    scope is requested; it does not assert that the result is empty.
    """

    scope_ref: str
    account_ref: str
    venue_ref: str
    strategy_ref: str
    instrument_refs: tuple[str, ...] = ()
    intent_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("scope_ref", "account_ref", "venue_ref", "strategy_ref"):
            _text(getattr(self, name), name)
        object.__setattr__(self, "instrument_refs", _texts(self.instrument_refs, "instrument_refs"))
        object.__setattr__(self, "intent_refs", _texts(self.intent_refs, "intent_refs"))


@runtime_checkable
class ReconciliationRequestResolver(Protocol):
    """Trusted SDK-runtime issuer of scope-bound reconciliation requests.

    Implementations are selected for one exact SDK route. They resolve account,
    strategy, instrument, and intent scope from their own trusted runtime
    bindings. Backtrader must never supply those references. A missing request
    means that the requested operation cannot be reconciled by this route.
    ``issue_order_request`` must validate the exact correlation against the
    live SDK order-reservation issuer registry; constructing an
    ``OrderCorrelation`` DTO is not proof of an issued reservation. Returning
    a request is not itself provider evidence; the selected provider authority
    must still verify the evidence and its current lease.
    """

    def issue_order_request(
        self,
        correlation: OrderCorrelation,
    ) -> ReconciliationRequest | None: ...

    def issue_authorized_account_request(self) -> ReconciliationRequest | None: ...


@dataclass(frozen=True)
class CommissionAmount:
    """One realized commission amount in an explicit currency."""

    amount: Decimal
    currency: str
    unit: Literal["currency"] = "currency"

    def __post_init__(self) -> None:
        _decimal(self.amount, "amount")
        _text(self.currency, "currency")
        if type(self.unit) is not str or self.unit != "currency":
            raise ValueError("commission amount unit must be currency")


@dataclass(frozen=True)
class FeeRate:
    """A fee rate with its charged currency and mathematical basis."""

    rate: Decimal
    currency: str
    unit: str
    role: Literal["maker", "taker", "unknown"]

    def __post_init__(self) -> None:
        _decimal(self.rate, "rate")
        _text(self.currency, "currency")
        _text(self.unit, "unit")
        if self.unit not in _FEE_RATE_UNITS:
            raise ValueError("unsupported fee-rate unit")
        if type(self.role) is not str or self.role not in {"maker", "taker", "unknown"}:
            raise ValueError("unsupported fee-rate role")


@dataclass(frozen=True)
class TerminalOrderSnapshot:
    """Provider-neutral current or terminal order facts for one order key."""

    scope_ref: str
    instrument_ref: str
    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    status: str
    terminal_confirmed: bool
    quantity: Decimal
    filled_quantity: Decimal
    quantity_unit: str
    price: Decimal | None = None
    average_price: Decimal | None = None
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("scope_ref", "instrument_ref", "order_id", "symbol", "quantity_unit"):
            _text(getattr(self, name), name)
        if type(self.side) is not str or self.side not in {"buy", "sell"}:
            raise ValueError("order side must be buy or sell")
        validate_reconciliation_order_status(self.status, self.terminal_confirmed)
        _decimal(self.quantity, "quantity", minimum=Decimal("0"))
        _decimal(self.filled_quantity, "filled_quantity", minimum=Decimal("0"))
        if self.quantity <= 0 or self.filled_quantity > self.quantity:
            raise ValueError("order quantities are inconsistent")
        for name in ("price", "average_price"):
            value = getattr(self, name)
            if value is not None:
                _decimal(value, name, minimum=Decimal("0"))
        if self.observed_at is not None:
            _utc(self.observed_at, "observed_at")


@dataclass(frozen=True)
class ReconciledOrder:
    """Order receipt bound to intent, scope, key, lease, source, and generation."""

    scope_ref: str
    account_ref: str
    strategy_ref: str
    source_ref: str
    generation: str
    snapshot_ref: str
    lease_ref: str
    intent_ref: str
    client_order_id: str
    order: TerminalOrderSnapshot

    def __post_init__(self) -> None:
        for name in (
            "scope_ref",
            "account_ref",
            "strategy_ref",
            "source_ref",
            "generation",
            "snapshot_ref",
            "lease_ref",
            "intent_ref",
            "client_order_id",
        ):
            _text(getattr(self, name), name)
        if type(self.order) is not TerminalOrderSnapshot:
            raise TypeError("order must be an exact TerminalOrderSnapshot")
        if self.order.scope_ref != self.scope_ref:
            raise ValueError("order scope does not match its reconciliation row")


# The longer spelling emphasizes that this wrapper is provider evidence, not
# the ordinary order DTO consumed by a Broker.
TerminalOrderReconciliationReceipt = ReconciledOrder


@dataclass(frozen=True)
class ReconciliationFill:
    """One normalized account fill linked to an order and intent."""

    scope_ref: str
    intent_ref: str
    client_order_id: str
    fill_id: str
    order_id: str
    instrument_ref: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    quantity_unit: str
    price: Decimal
    commission: CommissionAmount | None
    timestamp: datetime

    def __post_init__(self) -> None:
        for name in (
            "scope_ref",
            "intent_ref",
            "client_order_id",
            "fill_id",
            "order_id",
            "instrument_ref",
            "symbol",
            "quantity_unit",
        ):
            _text(getattr(self, name), name)
        if type(self.side) is not str or self.side not in {"buy", "sell"}:
            raise ValueError("fill side must be buy or sell")
        _decimal(self.quantity, "quantity", minimum=Decimal("0"))
        _decimal(self.price, "price", minimum=Decimal("0"))
        if self.quantity <= 0 or self.price <= 0:
            raise ValueError("fill quantity and price must be positive")
        if self.commission is not None and type(self.commission) is not CommissionAmount:
            raise TypeError("commission must be an exact CommissionAmount or None")
        _utc(self.timestamp, "timestamp")


@dataclass(frozen=True)
class UnresolvedFillObservation:
    """Neutral provider fill facts without a trusted intent/client-order join."""

    scope_ref: str
    fill_id: str
    order_id: str
    instrument_ref: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    quantity_unit: str
    price: Decimal
    timestamp: datetime
    commission: CommissionAmount | None = None

    def __post_init__(self) -> None:
        for name in (
            "scope_ref",
            "fill_id",
            "order_id",
            "instrument_ref",
            "symbol",
            "quantity_unit",
        ):
            _text(getattr(self, name), name)
        if type(self.side) is not str or self.side not in {"buy", "sell"}:
            raise ValueError("fill side must be buy or sell")
        _decimal(self.quantity, "quantity", minimum=Decimal("0"))
        _decimal(self.price, "price", minimum=Decimal("0"))
        if self.quantity <= 0 or self.price <= 0:
            raise ValueError("fill quantity and price must be positive")
        _utc(self.timestamp, "timestamp")
        if self.commission is not None and type(self.commission) is not CommissionAmount:
            raise TypeError("commission must be an exact CommissionAmount or None")


@dataclass(frozen=True)
class ReconciliationPosition:
    """One position row with an explicit instrument key, side, and unit."""

    scope_ref: str
    instrument_ref: str
    symbol: str
    position_side: Literal["net", "long", "short"]
    quantity: Decimal
    quantity_unit: str
    average_price: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("scope_ref", "instrument_ref", "symbol", "quantity_unit"):
            _text(getattr(self, name), name)
        if type(self.position_side) is not str or self.position_side not in _POSITION_SIDES:
            raise ValueError("position_side must be net, long, or short")
        _decimal(self.quantity, "quantity")
        if self.position_side != "net" and self.quantity < 0:
            raise ValueError("directional position quantity must be nonnegative")
        if self.average_price is not None:
            _decimal(self.average_price, "average_price", minimum=Decimal("0"))


@dataclass(frozen=True)
class UnresolvedPositionObservation:
    """Neutral provider position magnitude without a strategy attribution proof.

    For a provider's ``net`` bucket, quantity is the reported nonnegative
    magnitude; its sign is not implied. Use ``ReconciliationPosition`` only
    when a trusted projection establishes signed net exposure.
    """

    scope_ref: str
    instrument_ref: str
    symbol: str
    reported_position_side: Literal["net", "long", "short"]
    quantity: Decimal
    quantity_unit: str
    observed_at: datetime
    average_price: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("scope_ref", "instrument_ref", "symbol", "quantity_unit"):
            _text(getattr(self, name), name)
        if type(self.reported_position_side) is not str or self.reported_position_side not in _POSITION_SIDES:
            raise ValueError("reported_position_side must be net, long, or short")
        _decimal(self.quantity, "quantity", minimum=Decimal("0"))
        _utc(self.observed_at, "observed_at")
        if self.average_price is not None:
            _decimal(self.average_price, "average_price", minimum=Decimal("0"))


@dataclass(frozen=True)
class ReconciliationCoverage:
    """Provider completeness for one domain in one coherent query snapshot.

    ``empty_result_proven=True`` asserts that this family returned no rows.
    The SDK facade checks that assertion against the corresponding evidence
    collection and rejects a proof that marks a non-empty family as empty.
    """

    family: str
    scope_ref: str
    source_ref: str
    generation: str
    snapshot_ref: str
    consistency_ref: str
    complete: bool
    scope_complete: bool
    history_complete: bool
    empty_result_proven: bool
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.family) is not str or self.family not in _FAMILIES:
            raise ValueError("unsupported reconciliation family")
        for name in (
            "scope_ref",
            "source_ref",
            "generation",
            "snapshot_ref",
            "consistency_ref",
        ):
            _text(getattr(self, name), name)
        for name in ("complete", "scope_complete", "history_complete", "empty_result_proven"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a bool")
        object.__setattr__(self, "blockers", _texts(self.blockers, "blockers"))


@dataclass(frozen=True)
class ReconciliationLease:
    """Provider-issued lease binding one exact scope and receipt digest."""

    lease_ref: str
    scope_ref: str
    source_ref: str
    generation: str
    snapshot_ref: str
    request_digest: str
    evidence_digest: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "lease_ref",
            "scope_ref",
            "source_ref",
            "generation",
            "snapshot_ref",
            "request_digest",
            "evidence_digest",
        ):
            _text(getattr(self, name), name)
        _utc(self.issued_at, "issued_at")
        _utc(self.expires_at, "expires_at")
        if self.issued_at >= self.expires_at:
            raise ValueError("lease must expire after it is issued")


@dataclass(frozen=True)
class PositionReconciliationReceipt:
    """Provider evidence tying positions to this exact order/fill query set."""

    receipt_ref: str
    scope_ref: str
    account_ref: str
    strategy_ref: str
    source_ref: str
    generation: str
    snapshot_ref: str
    lease_ref: str
    orders_digest: str
    fills_digest: str
    positions_digest: str
    quantity_units: tuple[tuple[str, str, str], ...]
    consistent: bool

    def __post_init__(self) -> None:
        for name in (
            "receipt_ref",
            "scope_ref",
            "account_ref",
            "strategy_ref",
            "source_ref",
            "generation",
            "snapshot_ref",
            "lease_ref",
            "orders_digest",
            "fills_digest",
            "positions_digest",
        ):
            _text(getattr(self, name), name)
        if type(self.consistent) is not bool:
            raise TypeError("consistent must be a bool")
        rows = []
        if type(self.quantity_units) not in (tuple, list):
            raise TypeError("quantity_units must be a tuple or list")
        for row in self.quantity_units:
            if type(row) not in (tuple, list) or len(row) != 3:
                raise TypeError("each quantity unit binding must have three fields")
            rows.append(tuple(_text(part, "quantity unit binding") for part in row))
        if len(set(rows)) != len(rows):
            raise ValueError("quantity unit bindings must be unique")
        object.__setattr__(self, "quantity_units", tuple(rows))


@dataclass(frozen=True)
class ReconciliationEvidence:
    """One provider-issued reconciliation result, possibly incomplete.

    ``None`` row collections mean unobserved/unavailable. Empty tuples are
    accepted only with explicit per-family ``empty_result_proven=True``.
    ``safe_to_resume`` is intentionally absent from this provider DTO.
    """

    request: ReconciliationRequest
    issuer_ref: str | None = None
    source_ref: str | None = None
    generation: str | None = None
    snapshot_ref: str | None = None
    consistency_ref: str | None = None
    observed_at: datetime | None = None
    coverage: tuple[ReconciliationCoverage, ...] | None = None
    orders: tuple[ReconciledOrder, ...] | None = None
    fills: tuple[ReconciliationFill, ...] | None = None
    positions: tuple[ReconciliationPosition, ...] | None = None
    unresolved_orders: tuple[TerminalOrderSnapshot, ...] | None = None
    unresolved_fills: tuple[UnresolvedFillObservation, ...] | None = None
    unresolved_positions: tuple[UnresolvedPositionObservation, ...] | None = None
    lease: ReconciliationLease | None = None
    position_receipt: PositionReconciliationReceipt | None = None
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.request) is not ReconciliationRequest:
            raise TypeError("request must be an exact ReconciliationRequest")
        for name in ("issuer_ref", "source_ref", "generation", "snapshot_ref", "consistency_ref"):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)
        if self.observed_at is not None:
            _utc(self.observed_at, "observed_at")
        for name, expected in (
            ("coverage", ReconciliationCoverage),
            ("orders", ReconciledOrder),
            ("fills", ReconciliationFill),
            ("positions", ReconciliationPosition),
            ("unresolved_orders", TerminalOrderSnapshot),
            ("unresolved_fills", UnresolvedFillObservation),
            ("unresolved_positions", UnresolvedPositionObservation),
        ):
            values = getattr(self, name)
            if values is None:
                continue
            if type(values) not in (tuple, list) or any(
                type(item) is not expected for item in values
            ):
                raise TypeError(f"{name} must contain exact {expected.__name__} values")
            object.__setattr__(self, name, tuple(values))
        if self.lease is not None and type(self.lease) is not ReconciliationLease:
            raise TypeError("lease must be an exact ReconciliationLease or None")
        if self.position_receipt is not None and type(
            self.position_receipt
        ) is not PositionReconciliationReceipt:
            raise TypeError(
                "position_receipt must be an exact PositionReconciliationReceipt or None"
            )
        object.__setattr__(self, "blockers", _texts(self.blockers, "blockers"))


@runtime_checkable
class ProviderReconciliationAuthority(Protocol):
    """Trusted SDK provider capability for complete reconciliation evidence.

    Implementations are selected by SDK composition, not by Backtrader. The
    verifier methods must check issuer registration, exact account/strategy
    scope, source and generation, snapshot completeness, lease currentness, and
    the provider's position/order/fill consistency receipt. Merely returning a
    populated DTO or exposing these methods is not proof.
    """

    issuer_ref: str

    def query_reconciliation(
        self,
        request: ReconciliationRequest,
        *,
        deadline: datetime,
    ) -> ReconciliationEvidence: ...

    def verify_reconciliation_evidence(
        self,
        evidence: ReconciliationEvidence,
        request: ReconciliationRequest,
    ) -> bool: ...

    def validate_reconciliation_lease(
        self,
        evidence: ReconciliationEvidence,
        *,
        now: datetime,
    ) -> bool: ...

    def verify_position_consistency(self, evidence: ReconciliationEvidence) -> bool: ...




__all__ = [
    "CommissionAmount",
    "FeeRate",
    "PositionReconciliationReceipt",
    "ProviderReconciliationAuthority",
    "ReconciledOrder",
    "ReconciliationCoverage",
    "ReconciliationEvidence",
    "ReconciliationFill",
    "ReconciliationLease",
    "ReconciliationPosition",
    "ReconciliationRequest",
    "ReconciliationRequestResolver",
    "TerminalOrderReconciliationReceipt",
    "TerminalOrderSnapshot",
    "UnresolvedFillObservation",
    "UnresolvedPositionObservation",
    "validate_reconciliation_order_status",
]
