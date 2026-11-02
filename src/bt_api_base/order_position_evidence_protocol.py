"""Neutral, source-bound position evidence contracts for order preflight.

The DTO describes quantities, not authority. Constructing an
``OrderPositionEvidence`` does not prove that its issuer queried the selected
account, that the result covered the requested scope, or that its lease is
still current. Consumers must obtain the exact DTO from a route-bound SDK
facade and keep the provider validator in the decision path. Provider-native
fields, account identifiers, Backtrader identifiers, and mutable query rows do
not belong in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional, Protocol, Sequence, runtime_checkable

from bt_api_base.execution_correlation_protocol import SelectedExecutionRoute
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.query_protocol import (
    QueryBatchReceipt,
    QueryRequest,
    QuerySnapshot,
    QuerySnapshotLease,
)
from bt_api_base.service_protocol import MAX_REFERENCE_BYTES

_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z", re.ASCII)
_MAX_DECIMAL_BYTES = 128
_MAX_POSITION_ROWS = 100_000
_MAX_TIMEOUT_SECONDS = 30.0


def _check_text(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be valid UTF-8") from exc
    if (
        not value
        or value != value.strip()
        or not value.isprintable()
        or size > MAX_REFERENCE_BYTES
    ):
        raise ValueError(f"{field_name} must be non-empty trimmed printable UTF-8")
    return value


def _check_decimal(value: object, field_name: str, *, signed: bool) -> Decimal:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a decimal string")
    if (
        not value
        or len(value.encode("utf-8", errors="strict")) > _MAX_DECIMAL_BYTES
        or value != value.strip()
        or _DECIMAL_PATTERN.fullmatch(value) is None
    ):
        raise ValueError(f"{field_name} must be a bounded decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be a bounded decimal string") from exc
    if not number.is_finite() or (not signed and number < 0):
        raise ValueError(f"{field_name} must be finite and within its sign domain")
    return number


def _check_optional_decimal(value: object, field_name: str) -> Optional[Decimal]:
    if value is None:
        return None
    return _check_decimal(value, field_name, signed=False)


def _check_utc(value: object, field_name: str) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _check_timeout(value: object) -> float:
    if type(value) not in (int, float) or isinstance(value, bool):
        raise TypeError("timeout must be an exact int or float")
    timeout = float(value)
    if not 0.01 <= timeout <= _MAX_TIMEOUT_SECONDS:
        raise ValueError("timeout must be between 0.01 and 30 seconds")
    return timeout


@dataclass(frozen=True)
class OrderPositionQuantities:
    """Neutral quantities for one instrument and one provider observation.

    ``net_position_size`` is signed (long minus short). Long and short totals
    are nonnegative. Day-bucket fields are optional because a provider-neutral
    query family may not preserve the provider's close-today/close-yesterday
    distinction; an absent bucket must remain unavailable to the evaluator.
    """

    instrument: MarketInstrumentKey
    qty_unit: str
    net_position_size: str
    long_position_size: str
    short_position_size: str
    long_close_today_size: Optional[str] = None
    long_close_yesterday_size: Optional[str] = None
    short_close_today_size: Optional[str] = None
    short_close_yesterday_size: Optional[str] = None

    def __post_init__(self) -> None:
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be an exact MarketInstrumentKey")
        _check_text(self.qty_unit, "qty_unit")
        net = _check_decimal(self.net_position_size, "net_position_size", signed=True)
        long = _check_decimal(self.long_position_size, "long_position_size", signed=False)
        short = _check_decimal(self.short_position_size, "short_position_size", signed=False)
        if net != long - short:
            raise ValueError("net position must equal long minus short")
        for name in (
            "long_close_today_size",
            "long_close_yesterday_size",
            "short_close_today_size",
            "short_close_yesterday_size",
        ):
            selected = _check_optional_decimal(getattr(self, name), name)
            if selected is not None:
                parent = long if name.startswith("long_") else short
                if selected > parent:
                    raise ValueError(f"{name} must not exceed its side total")


@dataclass(frozen=True)
class OrderPositionEvidence:
    """Complete neutral position projection plus opaque source receipt refs.

    All reference fields are opaque identifiers. The actual query receipt,
    source/session bindings, lease object, and provider result stay inside the
    SDK/provider. ``complete`` and ``scope_complete`` are required true; a
    caller-created DTO is never authoritative without exact-identity issuer
    validation.
    """

    quantities: OrderPositionQuantities
    evidence_ref: str
    issuer_ref: str
    source_ref: str
    session_generation: str
    receipt_ref: str
    snapshot_ref: str
    lease_ref: str
    records_digest: str
    observed_at_utc: datetime
    expires_at_utc: datetime
    snapshot_record_count: int
    instrument_record_count: int
    complete: bool = True
    scope_complete: bool = True
    empty_result_proven: bool = False

    def __post_init__(self) -> None:
        if type(self.quantities) is not OrderPositionQuantities:
            raise TypeError("quantities must be an exact OrderPositionQuantities")
        for name in (
            "evidence_ref",
            "issuer_ref",
            "source_ref",
            "session_generation",
            "receipt_ref",
            "snapshot_ref",
            "lease_ref",
            "records_digest",
        ):
            _check_text(getattr(self, name), name)
        observed = _check_utc(self.observed_at_utc, "observed_at_utc")
        expires = _check_utc(self.expires_at_utc, "expires_at_utc")
        if expires <= observed:
            raise ValueError("expires_at_utc must be after observed_at_utc")
        if type(self.snapshot_record_count) is not int or not (
            0 <= self.snapshot_record_count <= _MAX_POSITION_ROWS
        ):
            raise ValueError("snapshot_record_count is outside the published bound")
        if type(self.instrument_record_count) is not int or not (
            0 <= self.instrument_record_count <= self.snapshot_record_count
        ):
            raise ValueError("instrument_record_count is outside the published bound")
        if type(self.complete) is not bool or self.complete is not True:
            raise ValueError("position evidence must be complete")
        if type(self.scope_complete) is not bool or self.scope_complete is not True:
            raise ValueError("position evidence must prove complete scope")
        # The provider query may contain rows for other instruments. This
        # flag proves an empty result for the requested instrument inside the
        # complete, scope-complete position snapshot, not an empty account.
        expected_empty = self.instrument_record_count == 0
        if (
            type(self.empty_result_proven) is not bool
            or self.empty_result_proven is not expected_empty
        ):
            raise ValueError("empty_result_proven must exactly match the complete instrument result")
        if expected_empty and any(
            _check_decimal(value, "empty_position_quantity", signed=True) != 0
            for value in (
                self.quantities.net_position_size,
                self.quantities.long_position_size,
                self.quantities.short_position_size,
            )
        ):
            raise ValueError("an explicitly empty result must have zero position quantities")


class OrderPositionEvidenceUnavailable(RuntimeError):
    """Finite, value-free failure to obtain or validate current position proof."""

    _CODES = frozenset(
        {
            "POSITION_EVIDENCE_ROUTE_UNAVAILABLE",
            "POSITION_EVIDENCE_PROVIDER_UNAVAILABLE",
            "POSITION_EVIDENCE_SOURCE_UNAVAILABLE",
            "POSITION_EVIDENCE_SCOPE_UNAVAILABLE",
            "POSITION_EVIDENCE_LEASE_NOT_CURRENT",
            "POSITION_EVIDENCE_TIMEOUT",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in self._CODES
            else "POSITION_EVIDENCE_PROVIDER_UNAVAILABLE"
        )
        super().__init__(self.code)


@runtime_checkable
class OrderPositionEvidencePort(Protocol):
    """Route-bound SDK port for issuing and revalidating position evidence."""

    def snapshot(
        self,
        instrument: MarketInstrumentKey,
        *,
        timeout: float = 5.0,
    ) -> OrderPositionEvidence:
        """Return complete evidence or raise ``OrderPositionEvidenceUnavailable``."""
        ...

    def validate(
        self,
        evidence: OrderPositionEvidence,
        *,
        now: datetime,
    ) -> bool:
        """Revalidate exact issuer identity and current provider lease."""
        ...


class OrderPositionEvidenceProviderPort(OrderPositionEvidencePort, Protocol):
    """Provider-internal implementation contract for one selected route."""


class OrderPositionEvidenceFacadePort(OrderPositionEvidencePort, Protocol):
    """BT-facing exact-route facade; implementations must not expose providers."""


@runtime_checkable
class ProviderQueryFacadePort(Protocol):
    """Neutral query facade injected by SDK composition for one exact route.

    This protocol intentionally mirrors ``bt_api_py.QueryFacade`` using only
    base DTOs. Provider packages can reuse the selected route's query service
    without importing the parent SDK package or creating a second client.
    """

    def refresh(
        self,
        requests: Sequence[QueryRequest],
        *,
        deadline: datetime,
    ) -> QueryBatchReceipt:
        ...

    def snapshot(self, receipt: QueryBatchReceipt, request_ref: str) -> QuerySnapshot | None:
        ...

    def acquire_snapshot_lease(
        self,
        receipt: QueryBatchReceipt,
        *,
        purpose: str,
        expires_at: datetime,
    ) -> QuerySnapshotLease:
        ...

    def validate_lease(
        self,
        lease: QuerySnapshotLease,
        receipt: QueryBatchReceipt,
        *,
        now: datetime,
    ) -> bool:
        ...


class OrderPositionEvidenceProviderFactory(Protocol):
    """Create a provider from one exact route and its matching query facade."""

    def __call__(
        self,
        route: SelectedExecutionRoute,
        query_facade: ProviderQueryFacadePort,
        /,
    ) -> OrderPositionEvidenceProviderPort:
        ...


@runtime_checkable
class OrderPositionEvidenceProviderRegistryPort(Protocol):
    """Minimal registration contract consumed by provider packages."""

    def register(
        self,
        exchange_name: str,
        factory: OrderPositionEvidenceProviderFactory,
        /,
    ) -> None:
        ...


__all__ = [
    "OrderPositionEvidence",
    "OrderPositionEvidenceFacadePort",
    "OrderPositionEvidencePort",
    "OrderPositionEvidenceProviderFactory",
    "OrderPositionEvidenceProviderPort",
    "OrderPositionEvidenceProviderRegistryPort",
    "OrderPositionEvidenceUnavailable",
    "OrderPositionQuantities",
    "ProviderQueryFacadePort",
]
