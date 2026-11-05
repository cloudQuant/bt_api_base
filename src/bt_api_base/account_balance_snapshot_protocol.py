"""Provider-neutral, source-bound account balance and valuation snapshots.

Balance rows retain their explicit currencies and provider-neutral amount
labels. This contract does not combine currencies or reinterpret balances as
cash, equity, margin, or buying power. Optional valuation is separately
source-bound and its ``available_cash`` field does not claim settled or
withdrawable funds. Query generation is not promoted into session readiness;
the exact account session snapshot and query lease must both be revalidated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from bt_api_base.account_protocol import (
    AccountBalance,
    AccountValuation,
    MAX_ACCOUNT_ROWS,
)
from bt_api_base.account_session_protocol import AccountSessionSnapshot
from bt_api_base.query_protocol import (
    QueryBatchReceipt,
    QueryCompleteness,
    QueryRequest,
    QuerySnapshot,
    QuerySnapshotLease,
)


ACCOUNT_BALANCE_QUERY_FAMILY = "account"
ACCOUNT_VALUATION_QUERY_FAMILY = "account_valuation"
ACCOUNT_BALANCE_LEASE_PURPOSE = "account_balance_snapshot"


class AccountBalanceSnapshotFailureCode(str, Enum):
    """Finite failure categories for the SDK balance snapshot adapter."""

    ROUTE_UNAVAILABLE = "account_balance_route_unavailable"
    SESSION_UNAVAILABLE = "account_balance_session_unavailable"
    SESSION_MISMATCH = "account_balance_session_mismatch"
    QUERY_FAILED = "account_balance_query_failed"
    RECEIPT_INVALID = "account_balance_receipt_invalid"
    SNAPSHOT_MISSING = "account_balance_snapshot_missing"
    LEASE_UNAVAILABLE = "account_balance_lease_unavailable"


@dataclass(frozen=True)
class AccountBalanceSnapshot:
    """One full account query with optional same-batch valuation evidence.

    ``complete`` describes the provider's full account-balance family
    coverage. ``usable`` additionally requires matching authenticated session
    evidence and a provider-issued currentness lease; consumers must call their
    exact ``AccountBalanceSnapshotPort`` to validate both immediately before
    use. The optional valuation has its own family completeness and may remain
    unavailable while balance rows are complete.
    """

    request: QueryRequest
    valuation_request: QueryRequest
    receipt: QueryBatchReceipt | None
    query_snapshot: QuerySnapshot | None
    valuation_snapshot: QuerySnapshot | None
    lease: QuerySnapshotLease | None
    session_snapshot: AccountSessionSnapshot | None
    failure_code: AccountBalanceSnapshotFailureCode | None = None
    balances: tuple[AccountBalance, ...] = field(init=False)
    currencies: tuple[str, ...] = field(init=False)
    valuation: AccountValuation | None = field(init=False)
    coverage_blockers: tuple[str, ...] = field(init=False)
    session_blockers: tuple[str, ...] = field(init=False)
    valuation_blockers: tuple[str, ...] = field(init=False)
    validation_blockers: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        self._validate_requests()
        self._validate_receipt_and_snapshots()
        self._validate_lease()
        self._validate_failure_shape()

        coverage_blockers: list[str] = []
        session_blockers: list[str] = []
        valuation_blockers: list[str] = []
        other_blockers: list[str] = []
        balances: tuple[AccountBalance, ...] = ()

        if self.receipt is not None:
            coverage_blockers.extend(self.receipt.blockers)
        if self.query_snapshot is not None:
            coverage_blockers.extend(self.query_snapshot.blockers)
            if self.query_snapshot.record_count > MAX_ACCOUNT_ROWS:
                coverage_blockers.append("account_balance_row_limit_exceeded")
            else:
                parsed = tuple(
                    AccountBalance.from_dict(row) for row in self.query_snapshot.records
                )
                balances = parsed
                identities = tuple((row.resource, row.currency) for row in parsed)
                if len(set(identities)) != len(identities):
                    coverage_blockers.append(
                        "duplicate_account_balance_resource_currency"
                    )
                completed = self.query_snapshot.completed_at
                if completed is not None and any(
                    _parse_utc(row.observed_at_utc) > completed for row in parsed
                ):
                    coverage_blockers.append("account_balance_observed_after_completion")

        session_blockers.extend(self._session_blockers())
        valuation, valuation_rows_blockers = self._project_valuation(
            balances, tuple(coverage_blockers)
        )
        valuation_blockers.extend(valuation_rows_blockers)
        if self.failure_code is not None:
            if self.failure_code in {
                AccountBalanceSnapshotFailureCode.ROUTE_UNAVAILABLE,
                AccountBalanceSnapshotFailureCode.QUERY_FAILED,
                AccountBalanceSnapshotFailureCode.RECEIPT_INVALID,
                AccountBalanceSnapshotFailureCode.SNAPSHOT_MISSING,
            }:
                coverage_blockers.append(self.failure_code.value)
            elif self.failure_code in {
                AccountBalanceSnapshotFailureCode.SESSION_UNAVAILABLE,
                AccountBalanceSnapshotFailureCode.SESSION_MISMATCH,
            }:
                session_blockers.append(self.failure_code.value)
            elif self.failure_code is AccountBalanceSnapshotFailureCode.LEASE_UNAVAILABLE:
                other_blockers.append(self.failure_code.value)

        object.__setattr__(self, "balances", balances)
        object.__setattr__(self, "currencies", tuple(sorted({row.currency for row in balances})))
        object.__setattr__(self, "valuation", valuation)
        object.__setattr__(self, "coverage_blockers", tuple(sorted(set(coverage_blockers))))
        object.__setattr__(self, "session_blockers", tuple(sorted(set(session_blockers))))
        object.__setattr__(self, "valuation_blockers", tuple(sorted(set(valuation_blockers))))
        # Valuation is optional. Its blockers must not make a complete balance
        # snapshot look unusable; consumers can inspect valuation_blockers.
        required_blockers = coverage_blockers + session_blockers + other_blockers
        object.__setattr__(self, "validation_blockers", tuple(sorted(set(required_blockers))))

    def _validate_requests(self) -> None:
        if type(self.request) is not QueryRequest:
            raise TypeError("request must be a QueryRequest")
        if (
            self.request.family != ACCOUNT_BALANCE_QUERY_FAMILY
            or self.request.filters
            or self.request.required is not True
            or self.request.require_complete_scope is not True
        ):
            raise ValueError("request must cover the full account balance family")
        if type(self.valuation_request) is not QueryRequest:
            raise TypeError("valuation_request must be a QueryRequest")
        if (
            self.valuation_request.family != ACCOUNT_VALUATION_QUERY_FAMILY
            or self.valuation_request.filters
            or self.valuation_request.required is not False
            or self.valuation_request.require_complete_scope is not True
            or self.valuation_request.request_ref == self.request.request_ref
        ):
            raise ValueError("valuation_request must be an optional full-scope query")
        if (
            self.failure_code is not None
            and type(self.failure_code) is not AccountBalanceSnapshotFailureCode
        ):
            raise TypeError(
                "failure_code must be an AccountBalanceSnapshotFailureCode or None"
            )
        if (
            self.session_snapshot is not None
            and type(self.session_snapshot) is not AccountSessionSnapshot
        ):
            raise TypeError("session_snapshot must be an AccountSessionSnapshot or None")

    def _validate_receipt_and_snapshots(self) -> None:
        if self.receipt is None:
            if self.query_snapshot is not None or self.valuation_snapshot is not None:
                raise ValueError("query snapshots cannot exist without their batch receipt")
            return
        if type(self.receipt) is not QueryBatchReceipt:
            raise TypeError("receipt must be a QueryBatchReceipt or None")
        if self.receipt.requests != (self.request, self.valuation_request):
            raise ValueError("receipt must bind the exact balance and valuation requests")
        if self.query_snapshot is not None:
            if type(self.query_snapshot) is not QuerySnapshot:
                raise TypeError("query_snapshot must be a QuerySnapshot or None")
            if self.query_snapshot.request != self.request or not any(
                item == self.query_snapshot for item in self.receipt.snapshots
            ):
                raise ValueError("balance snapshot must be retained by its exact receipt")
        if self.valuation_snapshot is not None:
            if type(self.valuation_snapshot) is not QuerySnapshot:
                raise TypeError("valuation_snapshot must be a QuerySnapshot or None")
            if self.valuation_snapshot.request != self.valuation_request or not any(
                item == self.valuation_snapshot for item in self.receipt.snapshots
            ):
                raise ValueError("valuation snapshot must be retained by its exact receipt")

    def _validate_lease(self) -> None:
        if self.lease is None:
            return
        if type(self.lease) is not QuerySnapshotLease:
            raise TypeError("lease must be a QuerySnapshotLease or None")
        if (
            self.receipt is None
            or self.query_snapshot is None
            or not self.receipt.complete
            or not self.query_snapshot.is_complete
            or self.query_snapshot.snapshot_ref not in self.receipt.complete_snapshot_refs
            or self.lease.purpose != ACCOUNT_BALANCE_LEASE_PURPOSE
            or self.lease.receipt_digest != self.receipt.receipt_digest
            or self.lease.source_ref != self.receipt.source_ref
            or self.lease.generation != self.receipt.generation
            or self.lease.snapshot_refs != self.receipt.complete_snapshot_refs
        ):
            raise ValueError("lease must bind the exact complete account balance receipt")

    def _validate_failure_shape(self) -> None:
        code = self.failure_code
        if self.receipt is None and code is None:
            raise ValueError("a snapshot without a receipt must state why evidence is unavailable")
        if self.receipt is not None and self.query_snapshot is None and code not in {
            AccountBalanceSnapshotFailureCode.RECEIPT_INVALID,
            AccountBalanceSnapshotFailureCode.SNAPSHOT_MISSING,
        }:
            raise ValueError("a receipt without its balance result requires an explicit failure")
        if code in {
            AccountBalanceSnapshotFailureCode.ROUTE_UNAVAILABLE,
            AccountBalanceSnapshotFailureCode.QUERY_FAILED,
        } and (
            self.receipt is not None
            or self.query_snapshot is not None
            or self.valuation_snapshot is not None
            or self.lease is not None
        ):
            raise ValueError("route/query failure cannot carry query evidence")
        if code is AccountBalanceSnapshotFailureCode.SNAPSHOT_MISSING and (
            self.receipt is None or self.query_snapshot is not None or self.lease is not None
        ):
            raise ValueError("snapshot-missing failure cannot retain a balance result or lease")
        if code is AccountBalanceSnapshotFailureCode.LEASE_UNAVAILABLE and (
            self.receipt is None
            or self.query_snapshot is None
            or self.lease is not None
            or not self.receipt.complete
            or not self.query_snapshot.is_complete
        ):
            raise ValueError("lease-unavailable failure must retain complete balance data")
        if code in {
            AccountBalanceSnapshotFailureCode.SESSION_UNAVAILABLE,
            AccountBalanceSnapshotFailureCode.SESSION_MISMATCH,
        } and self.lease is not None:
            raise ValueError("session failure cannot carry a usable balance lease")
        if code is AccountBalanceSnapshotFailureCode.SESSION_MISMATCH and (
            self.receipt is None or self.query_snapshot is None
        ):
            raise ValueError("session mismatch requires query evidence to compare")

    def _session_blockers(self) -> tuple[str, ...]:
        session = self.session_snapshot
        if session is None:
            return ("account_session_evidence_unavailable",)
        blockers: list[str] = []
        if session.available is not True:
            blockers.append("account_session_unavailable")
            blockers.extend(session.blockers)
        if session.connected is not True:
            blockers.append("account_session_not_connected")
        if session.authenticated is not True:
            blockers.append("account_session_not_authenticated")
        if not session.session_ref:
            blockers.append("account_session_reference_unavailable")
        if (
            self.completed_at is not None
            and session.observed_at is not None
            and session.observed_at < self.completed_at
        ):
            blockers.append("account_session_observed_before_query")
        source_ref = self.source_ref
        generation = self.generation
        if source_ref is not None and session.source_ref != source_ref:
            blockers.append("account_session_source_mismatch")
        if generation is not None and session.generation != generation:
            blockers.append("account_session_generation_mismatch")
        if (source_ref is None) != (session.source_ref is None):
            blockers.append("account_session_source_unavailable")
        if (generation is None) != (session.generation is None):
            blockers.append("account_session_generation_unavailable")
        return tuple(sorted(set(blockers)))

    def _project_valuation(
        self,
        balances: tuple[AccountBalance, ...],
        coverage_blockers: tuple[str, ...] = (),
    ) -> tuple[AccountValuation | None, tuple[str, ...]]:
        # ``coverage_blockers`` is passed in: this runs inside __post_init__
        # before the frozen field is assigned.
        snapshot = self.valuation_snapshot
        if snapshot is None:
            return None, ("account_valuation_snapshot_unavailable",)
        blockers: list[str] = list(snapshot.blockers)
        if not snapshot.is_complete or snapshot.scope_complete is not True:
            if not blockers:
                blockers.append("account_valuation_scope_incomplete")
            return None, tuple(sorted(set(blockers)))
        if (
            self.query_snapshot is None
            or not self.query_snapshot.is_complete
            or self.query_snapshot.scope_complete is not True
            or coverage_blockers
            or snapshot.source_ref != self.query_snapshot.source_ref
            or snapshot.generation != self.query_snapshot.generation
        ):
            return None, ("account_valuation_balance_scope_unavailable",)
        if len(snapshot.records) != 1:
            return None, ("account_valuation_single_currency_required",)
        if len(balances) != 1 or len({item.currency for item in balances}) != 1:
            return None, ("account_valuation_balance_currency_scope_mismatch",)
        try:
            valuation = AccountValuation.from_dict(snapshot.records[0])
        except Exception:
            return None, ("account_valuation_record_invalid",)
        if valuation.currency != balances[0].currency:
            return None, ("account_valuation_currency_mismatch",)
        if snapshot.completed_at is not None and (
            _parse_utc(valuation.observed_at_utc) > snapshot.completed_at
        ):
            return None, ("account_valuation_observed_after_completion",)
        return valuation, ()

    @property
    def request_ref(self) -> str:
        """Exact SDK-generated account-balance request identity."""
        return self.request.request_ref

    @property
    def valuation_request_ref(self) -> str:
        """Exact SDK-generated optional valuation request identity."""
        return self.valuation_request.request_ref

    @property
    def completeness(self) -> QueryCompleteness:
        if self.query_snapshot is None:
            return QueryCompleteness.UNAVAILABLE
        return self.query_snapshot.completeness

    @property
    def scope_complete(self) -> bool | None:
        return None if self.query_snapshot is None else self.query_snapshot.scope_complete

    @property
    def source_ref(self) -> str | None:
        if self.query_snapshot is not None:
            return self.query_snapshot.source_ref
        return None if self.receipt is None else self.receipt.source_ref

    @property
    def generation(self) -> str | None:
        if self.query_snapshot is not None:
            return self.query_snapshot.generation
        return None if self.receipt is None else self.receipt.generation

    @property
    def session_ref(self) -> str | None:
        return None if self.session_snapshot is None else self.session_snapshot.session_ref

    @property
    def snapshot_ref(self) -> str | None:
        return None if self.query_snapshot is None else self.query_snapshot.snapshot_ref

    @property
    def records_digest(self) -> str | None:
        return None if self.query_snapshot is None else self.query_snapshot.records_digest

    @property
    def started_at(self) -> datetime | None:
        if self.query_snapshot is not None:
            return self.query_snapshot.started_at
        return None if self.receipt is None else self.receipt.started_at

    @property
    def completed_at(self) -> datetime | None:
        if self.query_snapshot is not None:
            return self.query_snapshot.completed_at
        return None if self.receipt is None else self.receipt.completed_at

    @property
    def observed_at(self) -> datetime | None:
        return None if self.query_snapshot is None else self.query_snapshot.observed_at

    @property
    def valuation_completeness(self) -> QueryCompleteness:
        if self.valuation_snapshot is None:
            return QueryCompleteness.UNAVAILABLE
        return self.valuation_snapshot.completeness

    @property
    def valuation_scope_complete(self) -> bool | None:
        return (
            None
            if self.valuation_snapshot is None
            else self.valuation_snapshot.scope_complete
        )

    @property
    def valuation_source_ref(self) -> str | None:
        return None if self.valuation_snapshot is None else self.valuation_snapshot.source_ref

    @property
    def valuation_generation(self) -> str | None:
        return None if self.valuation_snapshot is None else self.valuation_snapshot.generation

    @property
    def valuation_snapshot_ref(self) -> str | None:
        return None if self.valuation_snapshot is None else self.valuation_snapshot.snapshot_ref

    @property
    def valuation_started_at(self) -> datetime | None:
        return None if self.valuation_snapshot is None else self.valuation_snapshot.started_at

    @property
    def valuation_completed_at(self) -> datetime | None:
        return None if self.valuation_snapshot is None else self.valuation_snapshot.completed_at

    @property
    def valuation_records_digest(self) -> str | None:
        return None if self.valuation_snapshot is None else self.valuation_snapshot.records_digest

    @property
    def valuation_observed_at(self) -> datetime | None:
        return None if self.valuation_snapshot is None else self.valuation_snapshot.observed_at

    @property
    def valuation_available(self) -> bool:
        """Whether same-session complete balances and valuation have a lease."""
        return self.usable and self.valuation is not None and not self.valuation_blockers

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.validation_blockers

    @property
    def complete(self) -> bool:
        """Whether the account-balance query proves its exact full scope."""
        return bool(
            self.receipt is not None
            and self.query_snapshot is not None
            and self.receipt.complete
            and self.query_snapshot.is_complete
            and self.query_snapshot.scope_complete is True
            and self.query_snapshot.source_ref == self.receipt.source_ref
            and self.query_snapshot.generation == self.receipt.generation
            and self.query_snapshot.snapshot_ref in self.receipt.complete_snapshot_refs
            and not self.coverage_blockers
            and self.failure_code
            in (
                None,
                AccountBalanceSnapshotFailureCode.LEASE_UNAVAILABLE,
                AccountBalanceSnapshotFailureCode.SESSION_UNAVAILABLE,
                AccountBalanceSnapshotFailureCode.SESSION_MISMATCH,
            )
        )

    @property
    def session_bound(self) -> bool:
        session = self.session_snapshot
        return bool(
            session is not None
            and session.available is True
            and session.connected is True
            and session.authenticated is True
            and session.session_ref
            and self.source_ref is not None
            and session.source_ref == self.source_ref
            and self.generation is not None
            and session.generation == self.generation
            and not self.session_blockers
        )

    @property
    def usable(self) -> bool:
        """Whether complete balances have same-session evidence and a lease."""
        return (
            self.complete
            and self.session_bound
            and self.lease is not None
            and self.failure_code is None
        )


@runtime_checkable
class AccountBalanceSnapshotPort(Protocol):
    """Read and revalidate full-scope neutral account balance evidence."""

    def refresh(self, *, deadline: datetime) -> AccountBalanceSnapshot:
        """Query balances and optional valuation before an aware UTC deadline."""
        ...

    def validate_snapshot(self, snapshot: AccountBalanceSnapshot) -> bool:
        """Return exact bool true only for this port's current issued evidence."""
        ...


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")


__all__ = [
    "ACCOUNT_BALANCE_LEASE_PURPOSE",
    "ACCOUNT_BALANCE_QUERY_FAMILY",
    "ACCOUNT_VALUATION_QUERY_FAMILY",
    "AccountBalanceSnapshot",
    "AccountBalanceSnapshotFailureCode",
    "AccountBalanceSnapshotPort",
]
