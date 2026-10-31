"""Provider-neutral account session, preflight, and settlement contracts.

These values carry bounded evidence across the unified SDK facade. They do
not expose provider rows, credentials, native request identifiers, or write
authority. Settlement confirmation is a separate optional capability and
must validate SDK-issued one-shot authorization and claim objects internally.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol, runtime_checkable

from bt_api_base.query_protocol import QueryBatchReceipt, QuerySnapshotLease

_SETTLEMENT_STATES = frozenset(
    {"required", "confirmed", "not_required", "unknown", "unavailable"}
)
_SETTLEMENT_DISPOSITIONS = frozenset({"accepted", "rejected", "unknown"})


def _require_text(value: object, field_name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty trimmed text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be valid UTF-8") from exc
    if len(encoded) > 256 or not value.isprintable():
        raise ValueError(f"{field_name} must be printable UTF-8 within the byte limit")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    return None if value is None else _require_text(value, field_name)


def _require_utc(value: object, field_name: str, *, optional: bool = False) -> datetime | None:
    if value is None and optional:
        return None
    if type(value) is not datetime:
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _check_blockers(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) not in (tuple, list):
        raise TypeError(f"{field_name} must be a tuple or list")
    result = tuple(_require_text(item, field_name) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{field_name} must not contain duplicates")
    return result


@dataclass(frozen=True)
class AccountSessionSnapshot:
    """Sanitized observation of one SDK-selected account session.

    ``source_ref``, ``generation``, and ``session_ref`` are opaque SDK values.
    Authentication, session readiness, and settlement status remain
    observations only; none of them grants permission to submit, cancel, or
    confirm settlement. Unknown values use ``None`` or the explicit
    ``unknown``/``unavailable`` settlement state rather than being inferred.
    """

    exchange_name: str
    source_ref: str | None
    generation: str | None
    session_ref: str | None
    connected: bool | None
    authenticated: bool | None
    trading_enabled: bool | None
    business_day: str | None
    settlement_status: Literal[
        "required", "confirmed", "not_required", "unknown", "unavailable"
    ]
    observed_at: datetime | None
    available: bool
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.exchange_name, "exchange_name")
        _optional_text(self.source_ref, "source_ref")
        _optional_text(self.generation, "generation")
        _optional_text(self.session_ref, "session_ref")
        for name in ("connected", "authenticated", "trading_enabled"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise TypeError(f"{name} must be bool or None")
        _optional_text(self.business_day, "business_day")
        if type(self.settlement_status) is not str or self.settlement_status not in _SETTLEMENT_STATES:
            raise ValueError("settlement_status is invalid")
        _require_utc(self.observed_at, "observed_at", optional=True)
        if type(self.available) is not bool:
            raise TypeError("available must be a bool")
        blockers = _check_blockers(self.blockers, "blockers")
        if not self.available and not blockers:
            raise ValueError("an unavailable session snapshot requires a blocker")
        object.__setattr__(self, "blockers", blockers)


@dataclass(frozen=True)
class AccountPreflightRequest:
    """Neutral, bounded request for account/order readiness evidence."""

    exchange_name: str
    symbol: str
    operation: Literal["submit", "cancel"]
    deadline: datetime

    def __post_init__(self) -> None:
        _require_text(self.exchange_name, "exchange_name")
        _require_text(self.symbol, "symbol")
        if type(self.operation) is not str or self.operation not in {"submit", "cancel"}:
            raise ValueError("operation must be submit or cancel")
        _require_utc(self.deadline, "deadline")


@dataclass(frozen=True)
class AccountPreflightSnapshot:
    """Preflight outcome bound to one neutral query receipt and freshness lease.

    The receipt and lease carry normalized query evidence. This projection
    intentionally omits provider-native rows and does not represent a write
    claim or authorization.
    """

    request: AccountPreflightRequest
    source_ref: str | None
    generation: str | None
    observed_at: datetime | None
    ready: bool | None
    available: bool
    blockers: tuple[str, ...] = ()
    query_receipt: QueryBatchReceipt | None = None
    query_lease: QuerySnapshotLease | None = None

    def __post_init__(self) -> None:
        if type(self.request) is not AccountPreflightRequest:
            raise TypeError("request must be an AccountPreflightRequest")
        _optional_text(self.source_ref, "source_ref")
        _optional_text(self.generation, "generation")
        _require_utc(self.observed_at, "observed_at", optional=True)
        if self.ready is not None and type(self.ready) is not bool:
            raise TypeError("ready must be bool or None")
        if type(self.available) is not bool:
            raise TypeError("available must be a bool")
        if self.observed_at is not None and self.observed_at > self.request.deadline:
            raise ValueError("preflight observation completed outside the request deadline")
        blockers = _check_blockers(self.blockers, "blockers")
        receipt = self.query_receipt
        lease = self.query_lease
        if receipt is not None and type(receipt) is not QueryBatchReceipt:
            raise TypeError("query_receipt must be a QueryBatchReceipt or None")
        if lease is not None and type(lease) is not QuerySnapshotLease:
            raise TypeError("query_lease must be a QuerySnapshotLease or None")
        if lease is not None:
            if receipt is None:
                raise ValueError("query_lease requires its query_receipt")
            if (
                lease.receipt_digest != receipt.receipt_digest
                or lease.source_ref != receipt.source_ref
                or lease.generation != receipt.generation
                or lease.snapshot_refs != receipt.complete_snapshot_refs
                or lease.purpose != "account_preflight"
            ):
                raise ValueError("query_lease does not bind this account preflight")
            if self.observed_at is not None and not (
                lease.issued_at <= self.observed_at < lease.expires_at
            ):
                raise ValueError("observed_at must fall within the query lease")
            if lease.issued_at > self.request.deadline:
                raise ValueError("query lease was issued after the request deadline")
        if receipt is not None and (
            self.source_ref != receipt.source_ref or self.generation != receipt.generation
        ):
            raise ValueError("snapshot source and generation must match its query_receipt")
        if receipt is not None:
            if not _account_preflight_query_scope_matches(self.request, receipt):
                raise ValueError("query receipt does not cover this preflight request")
            if receipt.started_at > self.request.deadline or receipt.completed_at > self.request.deadline:
                raise ValueError("query receipt completed outside the request deadline")
            if self.observed_at is not None and self.observed_at < receipt.completed_at:
                raise ValueError("preflight observation predates its query receipt")
            if any(
                (snapshot.started_at is not None and snapshot.started_at > self.request.deadline)
                or (
                    snapshot.completed_at is not None
                    and snapshot.completed_at > self.request.deadline
                )
                or (
                    snapshot.observed_at is not None
                    and snapshot.observed_at > self.request.deadline
                )
                for snapshot in receipt.snapshots
            ):
                raise ValueError("query snapshot was observed outside the request deadline")
        if self.request.operation == "cancel":
            if self.available or self.query_receipt is not None or self.query_lease is not None:
                raise ValueError(
                    "cancel preflight is unavailable without a neutral target order identity"
                )
        if not self.available and not blockers:
            raise ValueError("an unavailable preflight snapshot requires a blocker")
        if self.ready is True:
            raise ValueError(
                "preflight cannot be ready until neutral execution/trade query evidence is published"
            )
        if self.ready is None and not blockers:
            raise ValueError("an unknown preflight result requires a blocker")
        if self.ready is False and not blockers:
            raise ValueError("a non-ready preflight snapshot requires a blocker")
        object.__setattr__(self, "blockers", blockers)


def _account_preflight_query_scope_matches(
    request: AccountPreflightRequest,
    receipt: QueryBatchReceipt,
) -> bool:
    """Bind any attached receipt to the exact published submit-preflight scope."""

    if request.operation != "submit" or type(receipt) is not QueryBatchReceipt:
        return False
    expected = (
        ("account", {}),
        ("positions", {}),
        ("open_orders", {"symbol": request.symbol}),
        ("instruments", {"symbol": request.symbol}),
    )
    if len(receipt.requests) != len(expected):
        return False
    unmatched = list(expected)
    for query_request in receipt.requests:
        match_index = next(
            (
                index
                for index, (family, filters) in enumerate(unmatched)
                if query_request.family == family
                and dict(query_request.filters) == filters
                and query_request.required is True
                and query_request.require_complete_scope is True
            ),
            None,
        )
        if match_index is None:
            return False
        unmatched.pop(match_index)
    return not unmatched


@dataclass(frozen=True)
class SettlementVerificationReceipt:
    """Read-only server readback bound to one current account session."""

    exchange_name: str
    source_ref: str | None
    generation: str | None
    business_day: str | None
    status: Literal["confirmed", "required", "unknown", "unavailable"]
    observed_at: datetime | None
    complete: bool
    read_only_safe: bool
    receipt_ref: str | None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.exchange_name, "exchange_name")
        _optional_text(self.source_ref, "source_ref")
        _optional_text(self.generation, "generation")
        _optional_text(self.business_day, "business_day")
        if type(self.status) is not str or self.status not in {
            "confirmed",
            "required",
            "unknown",
            "unavailable",
        }:
            raise ValueError("status is invalid")
        _require_utc(self.observed_at, "observed_at", optional=True)
        if type(self.complete) is not bool or type(self.read_only_safe) is not bool:
            raise TypeError("complete and read_only_safe must be bool values")
        _optional_text(self.receipt_ref, "receipt_ref")
        _optional_text(self.reason_code, "reason_code")
        if self.complete:
            if (
                self.source_ref is None
                or self.generation is None
                or self.business_day is None
                or self.observed_at is None
                or self.receipt_ref is None
                or not self.read_only_safe
                or self.status in {"unknown", "unavailable"}
            ):
                raise ValueError("a complete settlement readback requires current read-only proof")
        elif self.reason_code is None:
            raise ValueError("an incomplete settlement readback requires a reason_code")


@dataclass(frozen=True)
class SettlementConfirmationRequest:
    """Request for a separately authorized settlement confirmation write."""

    exchange_name: str
    business_day: str
    expected_generation: str
    deadline: datetime

    def __post_init__(self) -> None:
        _require_text(self.exchange_name, "exchange_name")
        _require_text(self.business_day, "business_day")
        _require_text(self.expected_generation, "expected_generation")
        _require_utc(self.deadline, "deadline")


@dataclass(frozen=True)
class SettlementConfirmationReceipt:
    """Sanitized response to an authorized settlement confirmation command."""

    request: SettlementConfirmationRequest
    disposition: Literal["accepted", "rejected", "unknown"]
    observed_at: datetime | None
    receipt_ref: str | None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.request) is not SettlementConfirmationRequest:
            raise TypeError("request must be a SettlementConfirmationRequest")
        if type(self.disposition) is not str or self.disposition not in _SETTLEMENT_DISPOSITIONS:
            raise ValueError("disposition is invalid")
        _require_utc(self.observed_at, "observed_at", optional=True)
        _optional_text(self.receipt_ref, "receipt_ref")
        _optional_text(self.reason_code, "reason_code")
        if self.disposition == "accepted" and (
            self.receipt_ref is None or self.observed_at is None
        ):
            raise ValueError("an accepted settlement receipt requires time and receipt_ref")
        if self.disposition in {"rejected", "unknown"} and self.reason_code is None:
            raise ValueError("a rejected or unknown settlement receipt requires reason_code")


@dataclass(frozen=True)
class SettlementConfirmationOutcome:
    """Store-side aggregate of the SDK receipt and its exact verification.

    Providers return ``SettlementConfirmationReceipt`` from the write call
    and verify that exact object separately through the SDK port. A Store may
    assemble this neutral value only after consuming that verifier result;
    receipt disposition alone never sets ``verified``.
    """

    receipt: SettlementConfirmationReceipt
    verified: bool
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.receipt) is not SettlementConfirmationReceipt:
            raise TypeError("receipt must be a SettlementConfirmationReceipt")
        if type(self.verified) is not bool:
            raise TypeError("verified must be a bool")
        blockers = _check_blockers(self.blockers, "blockers")
        if self.verified and (
            self.receipt.disposition != "accepted" or blockers
        ):
            raise ValueError("verified requires an accepted receipt and no blockers")
        if not self.verified and not blockers:
            raise ValueError("an unverified settlement outcome requires a blocker")
        object.__setattr__(self, "blockers", blockers)


@runtime_checkable
class AccountSessionPort(Protocol):
    """Optional neutral capability for account session/preflight/readback facts."""

    def session_snapshot(self) -> AccountSessionSnapshot:
        """Return a bounded observation without starting or authorizing writes."""
        ...

    def preflight(self, request: AccountPreflightRequest) -> AccountPreflightSnapshot:
        """Return query-backed readiness evidence for one neutral operation."""
        ...

    def verify_settlement(self, *, deadline: datetime) -> SettlementVerificationReceipt:
        """Perform an active read-only server readback with no write requests."""
        ...

    def validate_preflight(
        self,
        snapshot: AccountPreflightSnapshot,
        *,
        now: datetime,
    ) -> bool:
        """Revalidate the exact receipt/lease against the live SDK session."""
        ...


@runtime_checkable
class AccountSessionFacade(Protocol):
    """Optional unified-facade selector for one account session capability."""

    def account_session(self, exchange_name: str) -> AccountSessionPort:
        """Select a registered account-session port by neutral route name."""
        ...


@runtime_checkable
class SettlementConfirmationPort(Protocol):
    """Separate optional write capability; never inferred from read readiness.

    ``authorization`` is opaque and must be an SDK-issued, one-shot value.
    ``claim`` is a provider-issued one-shot value bound to the exact request
    and authorization. Implementations must validate both objects, the live
    session generation/day, and the deadline on every call. Callers must pass
    the same objects unchanged and must treat an uncertain result as unknown.
    """

    def claim_settlement_confirmation(
        self,
        request: SettlementConfirmationRequest,
        *,
        authorization: object,
    ) -> object:
        """Claim one authorized settlement attempt for the exact session."""
        ...

    def confirm_settlement(
        self,
        request: SettlementConfirmationRequest,
        *,
        claim: object,
        authorization: object,
    ) -> SettlementConfirmationReceipt:
        """Consume the matching one-shot claim and return finite evidence."""
        ...

    def verify_confirmation(
        self,
        receipt: SettlementConfirmationReceipt,
        *,
        now: datetime,
    ) -> bool:
        """Return true only after current server readback for the exact request."""
        ...


@runtime_checkable
class SettlementConfirmationFacade(Protocol):
    """Optional facade selector for a separately authorized write port."""

    def settlement_confirmation(self, exchange_name: str) -> SettlementConfirmationPort:
        """Select a confirmation capability by neutral route name."""
        ...


__all__ = [
    "AccountPreflightRequest",
    "AccountPreflightSnapshot",
    "AccountSessionFacade",
    "AccountSessionPort",
    "AccountSessionSnapshot",
    "SettlementConfirmationFacade",
    "SettlementConfirmationOutcome",
    "SettlementConfirmationPort",
    "SettlementConfirmationReceipt",
    "SettlementConfirmationRequest",
    "SettlementVerificationReceipt",
]
