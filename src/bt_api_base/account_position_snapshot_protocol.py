"""Provider-neutral, full-scope account position snapshots.

The snapshot keeps provider-neutral position rows attached to the exact
``positions`` query receipt, provider-issued lease, and authenticated account
session identity. It does not attribute rows to a strategy or virtual book and
does not infer provider-specific instrument identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from bt_api_base.account_protocol import AccountPosition, MAX_ACCOUNT_ROWS
from bt_api_base.account_session_protocol import AccountSessionSnapshot
from bt_api_base.query_protocol import (
    QueryBatchReceipt,
    QueryCompleteness,
    QueryRequest,
    QuerySnapshot,
    QuerySnapshotLease,
)


ACCOUNT_POSITION_QUERY_FAMILY = "positions"
ACCOUNT_POSITION_LEASE_PURPOSE = "account_position_snapshot"


class AccountPositionSnapshotFailureCode(str, Enum):
    """Finite failure categories for the SDK position snapshot adapter."""

    ROUTE_UNAVAILABLE = "account_position_route_unavailable"
    SESSION_UNAVAILABLE = "account_position_session_unavailable"
    SESSION_MISMATCH = "account_position_session_mismatch"
    QUERY_FAILED = "account_position_query_failed"
    RECEIPT_INVALID = "account_position_receipt_invalid"
    SNAPSHOT_MISSING = "account_position_snapshot_missing"
    POSITION_RECORD_INVALID = "account_position_record_invalid"
    LEASE_UNAVAILABLE = "account_position_lease_unavailable"


@dataclass(frozen=True)
class AccountPositionSnapshot:
    """One unfiltered, complete account-wide positions query.

    ``complete`` only describes the provider's declared full query scope.
    ``usable`` additionally requires matching ready account-session evidence
    and a current provider-issued lease. Consumers must call the exact port's
    ``validate_snapshot`` immediately before relying on the result.
    """

    exchange_name: str
    request: QueryRequest
    receipt: QueryBatchReceipt | None
    query_snapshot: QuerySnapshot | None
    lease: QuerySnapshotLease | None
    session_snapshot: AccountSessionSnapshot | None
    failure_code: AccountPositionSnapshotFailureCode | None = None
    positions: tuple[AccountPosition, ...] = field(init=False)
    coverage_blockers: tuple[str, ...] = field(init=False)
    session_blockers: tuple[str, ...] = field(init=False)
    validation_blockers: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        self._validate_request()
        self._validate_receipt_and_snapshot()
        self._validate_lease()
        self._validate_failure_shape()

        coverage: list[str] = []
        session_blockers: list[str] = []
        other: list[str] = []
        positions: tuple[AccountPosition, ...] = ()

        if self.receipt is not None:
            coverage.extend(self.receipt.blockers)
        if self.query_snapshot is not None:
            coverage.extend(self.query_snapshot.blockers)
            if (
                self.receipt is not None
                and (
                    self.query_snapshot.source_ref != self.receipt.source_ref
                    or self.query_snapshot.generation != self.receipt.generation
                )
            ):
                coverage.append("account_position_receipt_source_generation_mismatch")
            if self.query_snapshot.record_count > MAX_ACCOUNT_ROWS:
                coverage.append("account_position_row_limit_exceeded")
            else:
                try:
                    parsed = tuple(
                        AccountPosition.from_dict(row)
                        for row in self.query_snapshot.records
                    )
                except Exception:
                    coverage.append("account_position_record_invalid")
                else:
                    identities = tuple(
                        (row.resource, row.instrument, row.side) for row in parsed
                    )
                    if len(set(identities)) != len(identities):
                        coverage.append("duplicate_account_position_resource_instrument_side")
                    completed = self.query_snapshot.completed_at
                    if completed is not None and any(
                        _parse_utc(row.observed_at_utc) > completed for row in parsed
                    ):
                        coverage.append("account_position_observed_after_completion")
                    positions = parsed

        session_blockers.extend(self._session_blockers())
        code = self.failure_code
        if code in {
            AccountPositionSnapshotFailureCode.ROUTE_UNAVAILABLE,
            AccountPositionSnapshotFailureCode.QUERY_FAILED,
            AccountPositionSnapshotFailureCode.RECEIPT_INVALID,
            AccountPositionSnapshotFailureCode.SNAPSHOT_MISSING,
            AccountPositionSnapshotFailureCode.POSITION_RECORD_INVALID,
        }:
            coverage.append(code.value)
        elif code in {
            AccountPositionSnapshotFailureCode.SESSION_UNAVAILABLE,
            AccountPositionSnapshotFailureCode.SESSION_MISMATCH,
        }:
            session_blockers.append(code.value)
        elif code is AccountPositionSnapshotFailureCode.LEASE_UNAVAILABLE:
            other.append(code.value)

        object.__setattr__(self, "positions", positions)
        object.__setattr__(self, "coverage_blockers", tuple(sorted(set(coverage))))
        object.__setattr__(self, "session_blockers", tuple(sorted(set(session_blockers))))
        object.__setattr__(
            self,
            "validation_blockers",
            tuple(sorted(set(coverage + session_blockers + other))),
        )

    def _validate_request(self) -> None:
        if (
            type(self.exchange_name) is not str
            or not self.exchange_name
            or self.exchange_name != self.exchange_name.strip()
        ):
            raise ValueError("exchange_name must be a non-empty exact SDK route")
        if type(self.request) is not QueryRequest:
            raise TypeError("request must be a QueryRequest")
        if (
            self.request.family != ACCOUNT_POSITION_QUERY_FAMILY
            or self.request.filters
            or self.request.required is not True
            or self.request.require_complete_scope is not True
        ):
            raise ValueError("request must cover the full unfiltered positions family")
        if (
            self.failure_code is not None
            and type(self.failure_code) is not AccountPositionSnapshotFailureCode
        ):
            raise TypeError(
                "failure_code must be an AccountPositionSnapshotFailureCode or None"
            )
        if (
            self.session_snapshot is not None
            and type(self.session_snapshot) is not AccountSessionSnapshot
        ):
            raise TypeError("session_snapshot must be an AccountSessionSnapshot or None")
        if (
            self.session_snapshot is not None
            and self.session_snapshot.exchange_name != self.exchange_name
        ):
            raise ValueError("session snapshot must match the exact SDK route")

    def _validate_receipt_and_snapshot(self) -> None:
        if self.receipt is None:
            if self.query_snapshot is not None or self.lease is not None:
                raise ValueError("query evidence cannot exist without its receipt")
            return
        if type(self.receipt) is not QueryBatchReceipt:
            raise TypeError("receipt must be a QueryBatchReceipt or None")
        if self.receipt.requests != (self.request,):
            raise ValueError("receipt must bind exactly the full positions request")
        if self.query_snapshot is not None:
            if type(self.query_snapshot) is not QuerySnapshot:
                raise TypeError("query_snapshot must be a QuerySnapshot or None")
            if self.query_snapshot.request != self.request or not any(
                item is self.query_snapshot for item in self.receipt.snapshots
            ):
                raise ValueError("positions snapshot must be retained by its exact receipt")

    def _validate_lease(self) -> None:
        if self.lease is None:
            return
        if type(self.lease) is not QuerySnapshotLease:
            raise TypeError("lease must be a QuerySnapshotLease or None")
        snapshot = self.query_snapshot
        if (
            self.receipt is None
            or snapshot is None
            or not self.receipt.complete
            or not snapshot.is_complete
            or snapshot.scope_complete is not True
            or snapshot.snapshot_ref not in self.receipt.complete_snapshot_refs
            or self.receipt.complete_snapshot_refs != (snapshot.snapshot_ref,)
            or self.lease.purpose != ACCOUNT_POSITION_LEASE_PURPOSE
            or self.lease.receipt_digest != self.receipt.receipt_digest
            or self.lease.source_ref != self.receipt.source_ref
            or self.lease.generation != self.receipt.generation
            or self.lease.snapshot_refs != (snapshot.snapshot_ref,)
        ):
            raise ValueError("lease must bind the exact complete positions receipt")

    def _validate_failure_shape(self) -> None:
        code = self.failure_code
        if self.receipt is None and code is None:
            raise ValueError("missing receipt requires an explicit failure code")
        if self.receipt is not None and self.query_snapshot is None and code not in {
            AccountPositionSnapshotFailureCode.RECEIPT_INVALID,
            AccountPositionSnapshotFailureCode.SNAPSHOT_MISSING,
        }:
            raise ValueError("receipt without positions snapshot requires an explicit failure")
        if code in {
            AccountPositionSnapshotFailureCode.ROUTE_UNAVAILABLE,
            AccountPositionSnapshotFailureCode.QUERY_FAILED,
        } and (
            self.receipt is not None
            or self.query_snapshot is not None
            or self.lease is not None
        ):
            raise ValueError("route/query failure cannot carry query evidence")
        if code is AccountPositionSnapshotFailureCode.SNAPSHOT_MISSING and (
            self.receipt is None or self.query_snapshot is not None or self.lease is not None
        ):
            raise ValueError("snapshot-missing failure has an invalid evidence shape")
        if code is AccountPositionSnapshotFailureCode.LEASE_UNAVAILABLE and (
            self.receipt is None
            or self.query_snapshot is None
            or self.lease is not None
            or not self.receipt.complete
            or not self.query_snapshot.is_complete
        ):
            raise ValueError("lease-unavailable requires a complete positions result")
        if code in {
            AccountPositionSnapshotFailureCode.SESSION_UNAVAILABLE,
            AccountPositionSnapshotFailureCode.SESSION_MISMATCH,
        } and self.lease is not None:
            raise ValueError("session failure cannot carry a usable positions lease")

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
        if session.exchange_name != self.exchange_name:
            blockers.append("account_session_route_mismatch")
        if (
            self.completed_at is not None
            and session.observed_at is not None
            and session.observed_at < self.completed_at
        ):
            blockers.append("account_session_observed_before_query")
        if self.source_ref is not None and session.source_ref != self.source_ref:
            blockers.append("account_session_source_mismatch")
        if self.generation is not None and session.generation != self.generation:
            blockers.append("account_session_generation_mismatch")
        if (self.source_ref is None) != (session.source_ref is None):
            blockers.append("account_session_source_unavailable")
        if (self.generation is None) != (session.generation is None):
            blockers.append("account_session_generation_unavailable")
        return tuple(sorted(set(blockers)))

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
    def observed_at(self) -> datetime | None:
        return None if self.query_snapshot is None else self.query_snapshot.observed_at

    @property
    def complete(self) -> bool:
        return bool(
            self.receipt is not None
            and self.query_snapshot is not None
            and self.receipt.complete
            and self.query_snapshot.is_complete
            and self.query_snapshot.scope_complete is True
            and self.source_ref == self.receipt.source_ref
            and self.generation == self.receipt.generation
            and self.query_snapshot.snapshot_ref in self.receipt.complete_snapshot_refs
            and not self.coverage_blockers
            and self.failure_code
            in (
                None,
                AccountPositionSnapshotFailureCode.LEASE_UNAVAILABLE,
                AccountPositionSnapshotFailureCode.SESSION_UNAVAILABLE,
                AccountPositionSnapshotFailureCode.SESSION_MISMATCH,
            )
        )

    @property
    def session_bound(self) -> bool:
        session = self.session_snapshot
        return bool(
            type(session) is AccountSessionSnapshot
            and session.exchange_name == self.exchange_name
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
        """Whether full-scope rows have a matching session and current lease."""
        return (
            self.complete
            and self.session_bound
            and self.lease is not None
            and self.failure_code is None
        )

    @property
    def empty_result_proven(self) -> bool:
        """Whether the leased complete account-wide query proves no positions."""
        return bool(self.usable and self.query_snapshot is not None and not self.positions)

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.validation_blockers

    @property
    def completed_at(self) -> datetime | None:
        return None if self.query_snapshot is None else self.query_snapshot.completed_at


@runtime_checkable
class AccountPositionSnapshotPort(Protocol):
    """Read and revalidate full-scope provider-neutral account positions."""

    def refresh(self, *, deadline: datetime) -> AccountPositionSnapshot:
        """Query full positions before an aware UTC deadline."""
        ...

    def validate_snapshot(self, snapshot: AccountPositionSnapshot) -> bool:
        """Return exact bool true only for this port's current issued evidence."""
        ...


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")


__all__ = [
    "ACCOUNT_POSITION_LEASE_PURPOSE",
    "ACCOUNT_POSITION_QUERY_FAMILY",
    "AccountPositionSnapshot",
    "AccountPositionSnapshotFailureCode",
    "AccountPositionSnapshotPort",
]
