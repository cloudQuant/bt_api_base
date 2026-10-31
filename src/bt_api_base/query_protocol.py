"""Provider-neutral query request, snapshot, batch, and freshness contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, Optional, Protocol, Union

from bt_api_base.account_protocol import AccountBalance, AccountOpenOrder, AccountPosition
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import MAX_REFERENCE_BYTES

JsonValue = Union[
    None,
    bool,
    int,
    float,
    str,
    Sequence["JsonValue"],
    Mapping[str, "JsonValue"],
]

QUERY_CONTRACT_VERSION = 1
MAX_QUERY_BATCH_REQUESTS = 256
MAX_QUERY_RECORDS = 100_000
MAX_QUERY_JSON_BYTES = 64 * 1024 * 1024
MAX_QUERY_JSON_DEPTH = 32

# These names describe neutral resource families. Providers may support only a
# subset and may add future neutral families; native method names are not family
# names. Unsupported requests must be reported as unavailable, never remapped.
STANDARD_QUERY_FAMILIES = frozenset(
    {
        "account",
        "instruments",
        "open_orders",
        "positions",
    }
)

# A known interoperable subset. QueryRequest accepts future filter keys as
# bounded data, but implementations must reject or report unsupported filters
# rather than silently dropping them.
STANDARD_QUERY_FILTER_KEYS = frozenset(
    {
        "currency",
        "end_time",
        "exchange",
        "instrument_id",
        "margin_pool",
        "product_id",
        "product_type",
        "provider_order_id",
        "side",
        "start_time",
        "status",
        "symbol",
    }
)

_FAMILY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class QueryCompleteness(str, Enum):
    """Provider-neutral outcome for one requested query."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


def _check_text(value: Any, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be valid UTF-8") from exc
    if (
        not encoded
        or len(encoded) > MAX_REFERENCE_BYTES
        or value != value.strip()
        or not value.isprintable()
    ):
        raise ValueError(f"{field_name} must be non-empty printable UTF-8 within the byte limit")
    return value


def _check_optional_text(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    return _check_text(value, field_name)


def _check_utc_datetime(value: Any, field_name: str) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _check_optional_utc_datetime(value: Any, field_name: str) -> Optional[datetime]:
    if value is None:
        return None
    return _check_utc_datetime(value, field_name)


def _check_json_string(value: str, field_name: str) -> str:
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be valid UTF-8") from exc
    if len(encoded) > MAX_QUERY_JSON_BYTES:
        raise ValueError(f"{field_name} exceeds the query JSON byte limit")
    return value


def _freeze_json(
    value: Any,
    *,
    field_name: str,
    active: Optional[set[int]] = None,
    depth: int = 0,
) -> Any:
    if depth > MAX_QUERY_JSON_DEPTH:
        raise ValueError(f"{field_name} exceeds the maximum JSON nesting depth")
    if value is None or type(value) in (bool, int):
        if type(value) is int and value.bit_length() > 4096:
            raise ValueError(f"{field_name} contains an oversized integer")
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ValueError(f"{field_name} must not contain NaN or infinity")
        return value
    if type(value) is str:
        return _check_json_string(value, field_name)
    if active is None:
        active = set()
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise ValueError(f"{field_name} must not contain reference cycles")
        active.add(identity)
        try:
            frozen: dict[str, Any] = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise TypeError(f"{field_name} mapping keys must be exact strings")
                _check_json_string(key, field_name)
                if not key or key != key.strip():
                    raise ValueError(f"{field_name} mapping keys must be non-empty and trimmed")
                frozen[key] = _freeze_json(
                    item,
                    field_name=field_name,
                    active=active,
                    depth=depth + 1,
                )
            return MappingProxyType(frozen)
        finally:
            active.remove(identity)
    if isinstance(value, (tuple, list)):
        identity = id(value)
        if identity in active:
            raise ValueError(f"{field_name} must not contain reference cycles")
        active.add(identity)
        try:
            return tuple(
                _freeze_json(item, field_name=field_name, active=active, depth=depth + 1)
                for item in value
            )
        finally:
            active.remove(identity)
    raise TypeError(f"{field_name} contains a non-JSON value")


def _freeze_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    frozen = _freeze_json(value, field_name=field_name)
    if not isinstance(frozen, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return frozen


def _json_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _json_plain(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return [_json_plain(item) for item in value]
    return value


def _canonical_json_bytes(value: Any, field_name: str) -> bytes:
    try:
        encoded = json.dumps(
            _json_plain(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError(f"{field_name} cannot be canonically encoded as JSON") from exc
    if len(encoded) > MAX_QUERY_JSON_BYTES:
        raise ValueError(f"{field_name} exceeds the query JSON byte limit")
    return encoded


def _sha256(value: Any, field_name: str) -> str:
    return hashlib.sha256(_canonical_json_bytes(value, field_name)).hexdigest()


def _check_string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if type(value) not in (tuple, list):
        raise TypeError(f"{field_name} must be a tuple or list of strings")
    checked = tuple(_check_text(item, field_name) for item in value)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{field_name} must not contain duplicates")
    return checked


def _validate_family_records(
    family: str,
    records: tuple[Mapping[str, Any], ...],
) -> None:
    """Validate records against the currently published neutral family schemas."""
    validators = {
        "account": AccountBalance.from_dict,
        "positions": AccountPosition.from_dict,
        "open_orders": AccountOpenOrder.from_dict,
        "instruments": MarketInstrumentKey.from_dict,
    }
    validator = validators.get(family)
    if validator is None:
        if records:
            raise ValueError(
                "records require a published neutral schema for the requested family"
            )
        return
    for index, record in enumerate(records):
        try:
            projected = validator(record)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"records[{index}] does not match the neutral {family} schema"
            ) from exc
        if projected.to_dict() != record:
            raise ValueError(
                f"records[{index}] is not in canonical neutral {family} form"
            )


def _request_data(request: QueryRequest) -> dict[str, Any]:
    return {
        "request_ref": request.request_ref,
        "family": request.family,
        "filters": _json_plain(request.filters),
        "required": request.required,
        "require_complete_scope": request.require_complete_scope,
    }


def _snapshot_data(snapshot: QuerySnapshot) -> dict[str, Any]:
    return {
        "request": _request_data(snapshot.request),
        "source_ref": snapshot.source_ref,
        "generation": snapshot.generation,
        "snapshot_ref": snapshot.snapshot_ref,
        "completeness": snapshot.completeness.value,
        "started_at": snapshot.started_at.isoformat() if snapshot.started_at else None,
        "completed_at": snapshot.completed_at.isoformat() if snapshot.completed_at else None,
        "observed_at": snapshot.observed_at.isoformat() if snapshot.observed_at else None,
        "scope_complete": snapshot.scope_complete,
        "record_count": snapshot.record_count,
        "records_digest": snapshot.records_digest,
        "blockers": list(snapshot.blockers),
        "continuation_ref": snapshot.continuation_ref,
    }


@dataclass(frozen=True)
class QueryRequest:
    """One neutral resource-family query with immutable JSON filters."""

    request_ref: str
    family: str
    filters: Mapping[str, JsonValue] = field(default_factory=dict)
    required: bool = True
    require_complete_scope: bool = False

    def __post_init__(self) -> None:
        _check_text(self.request_ref, "request_ref")
        _check_text(self.family, "family")
        if not _FAMILY_PATTERN.fullmatch(self.family):
            raise ValueError("family must be a lower-case neutral identifier")
        if type(self.required) is not bool:
            raise TypeError("required must be a bool")
        if type(self.require_complete_scope) is not bool:
            raise TypeError("require_complete_scope must be a bool")
        frozen_filters = _freeze_mapping(self.filters, "filters")
        _canonical_json_bytes(frozen_filters, "filters")
        object.__setattr__(self, "filters", frozen_filters)


@dataclass(frozen=True)
class QuerySnapshot:
    """Immutable semantic projection of one query result.

    Records use the published neutral family schema and contain JSON only.
    The current schemas are AccountBalance for account, AccountPosition for
    positions, AccountOpenOrder for open_orders, and MarketInstrumentKey for
    instruments. Extension families have no shared row schema yet, so they
    cannot carry records or claim COMPLETE. Provider-native diagnostics and
    mutable SDK objects remain provider-owned and may be associated privately
    with snapshot_ref. A complete native response does not by itself prove that
    the requested account or resource scope is complete.
    """

    request: QueryRequest
    source_ref: Optional[str]
    generation: Optional[str]
    snapshot_ref: Optional[str]
    completeness: QueryCompleteness
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    observed_at: Optional[datetime]
    scope_complete: Optional[bool]
    records: tuple[Mapping[str, JsonValue], ...] = ()
    blockers: tuple[str, ...] = ()
    continuation_ref: Optional[str] = None
    _records_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.request) is not QueryRequest:
            raise TypeError("request must be a QueryRequest")
        for name in ("source_ref", "generation", "snapshot_ref", "continuation_ref"):
            _check_optional_text(getattr(self, name), name)
        if type(self.completeness) is not QueryCompleteness:
            raise TypeError("completeness must be a QueryCompleteness")
        if self.scope_complete is not None and type(self.scope_complete) is not bool:
            raise TypeError("scope_complete must be a bool or None")

        started_at = _check_optional_utc_datetime(self.started_at, "started_at")
        completed_at = _check_optional_utc_datetime(self.completed_at, "completed_at")
        observed_at = _check_optional_utc_datetime(self.observed_at, "observed_at")
        if started_at is not None and completed_at is not None and started_at > completed_at:
            raise ValueError("started_at must not be after completed_at")
        if completed_at is not None and observed_at is not None and observed_at < completed_at:
            raise ValueError("observed_at must not be before completed_at")

        blockers = _check_string_tuple(self.blockers, "blockers")
        if type(self.records) not in (tuple, list):
            raise TypeError("records must be a tuple or list")
        if len(self.records) > MAX_QUERY_RECORDS:
            raise ValueError("records exceeds the maximum query row count")
        rows: list[Mapping[str, Any]] = []
        for row in self.records:
            frozen_row = _freeze_mapping(row, "record")
            rows.append(frozen_row)
        frozen_records = tuple(rows)
        _validate_family_records(self.request.family, frozen_records)
        digest = _sha256(frozen_records, "records")

        if self.completeness is QueryCompleteness.COMPLETE:
            if self.request.family not in STANDARD_QUERY_FAMILIES:
                raise ValueError("a complete snapshot requires a published neutral family schema")
            if (
                self.source_ref is None
                or self.generation is None
                or self.snapshot_ref is None
                or started_at is None
                or completed_at is None
                or observed_at is None
            ):
                raise ValueError(
                    "a complete snapshot requires source, generation, identity, and times"
                )
            if blockers or self.continuation_ref is not None:
                raise ValueError("a complete snapshot cannot have blockers or a continuation")
        elif self.completeness in (QueryCompleteness.UNAVAILABLE, QueryCompleteness.UNKNOWN):
            if frozen_records:
                raise ValueError("unavailable or unknown snapshots cannot contain records")
            if self.completeness is QueryCompleteness.UNAVAILABLE and not blockers:
                raise ValueError("an unavailable snapshot requires a blocker code")

        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "records", frozen_records)
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "_records_digest", digest)

    @property
    def record_count(self) -> int:
        """Number of normalized immutable records."""
        return len(self.records)

    @property
    def records_digest(self) -> str:
        """SHA-256 over canonical JSON for the exact ordered record sequence."""
        return self._records_digest

    @property
    def is_complete(self) -> bool:
        """Whether this result satisfies its request-level completeness policy."""
        if (
            self.completeness is not QueryCompleteness.COMPLETE
            or self.blockers
            or self.continuation_ref is not None
        ):
            return False
        if self.request.require_complete_scope and self.scope_complete is not True:
            return False
        return True


@dataclass(frozen=True)
class QueryBatchReceipt:
    """Immutable result of one provider query batch."""

    batch_ref: str
    source_ref: Optional[str]
    generation: Optional[str]
    started_at: datetime
    completed_at: datetime
    requests: tuple[QueryRequest, ...]
    snapshots: tuple[QuerySnapshot, ...]
    blockers: tuple[str, ...] = ()
    _receipt_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _check_text(self.batch_ref, "batch_ref")
        _check_optional_text(self.source_ref, "source_ref")
        _check_optional_text(self.generation, "generation")
        started_at = _check_utc_datetime(self.started_at, "started_at")
        completed_at = _check_utc_datetime(self.completed_at, "completed_at")
        if started_at > completed_at:
            raise ValueError("started_at must not be after completed_at")
        if type(self.requests) not in (tuple, list):
            raise TypeError("requests must be a tuple or list")
        if not 1 <= len(self.requests) <= MAX_QUERY_BATCH_REQUESTS:
            raise ValueError("requests must contain between 1 and the batch limit")
        requests = tuple(self.requests)
        if any(type(request) is not QueryRequest for request in requests):
            raise TypeError("requests must contain QueryRequest values")
        request_by_ref = {request.request_ref: request for request in requests}
        if len(request_by_ref) != len(requests):
            raise ValueError("request_ref values must be unique within a receipt")

        if type(self.snapshots) not in (tuple, list):
            raise TypeError("snapshots must be a tuple or list")
        snapshots = tuple(self.snapshots)
        if any(type(snapshot) is not QuerySnapshot for snapshot in snapshots):
            raise TypeError("snapshots must contain QuerySnapshot values")
        snapshot_refs: set[str] = set()
        seen_snapshots: set[str] = set()
        seen_sources: set[str] = set()
        seen_generations: set[str] = set()
        for snapshot in snapshots:
            request_ref = snapshot.request.request_ref
            expected = request_by_ref.get(request_ref)
            if expected is None or snapshot.request != expected:
                raise ValueError("every snapshot must match a request in the receipt")
            if request_ref in seen_snapshots:
                raise ValueError("a receipt cannot contain multiple snapshots for one request")
            seen_snapshots.add(request_ref)
            if snapshot.source_ref is not None:
                seen_sources.add(snapshot.source_ref)
                if self.source_ref is not None and snapshot.source_ref != self.source_ref:
                    raise ValueError("snapshot source_ref does not match the receipt")
            if snapshot.generation is not None:
                seen_generations.add(snapshot.generation)
                if self.generation is not None and snapshot.generation != self.generation:
                    raise ValueError("snapshot generation does not match the receipt")
            if snapshot.completeness is QueryCompleteness.COMPLETE:
                if snapshot.source_ref != self.source_ref or snapshot.generation != self.generation:
                    raise ValueError("complete snapshots must match receipt source and generation")
                if snapshot.snapshot_ref in snapshot_refs:
                    raise ValueError("snapshot_ref values must be unique within a receipt")
                snapshot_refs.add(snapshot.snapshot_ref)
        if len(seen_sources) > 1:
            raise ValueError("a receipt cannot mix source identities")
        if len(seen_generations) > 1:
            raise ValueError("a receipt cannot mix generations")

        blockers = _check_string_tuple(self.blockers, "blockers")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        object.__setattr__(self, "requests", requests)
        object.__setattr__(self, "snapshots", snapshots)
        object.__setattr__(self, "blockers", blockers)
        payload = {
            "contract_version": QUERY_CONTRACT_VERSION,
            "batch_ref": self.batch_ref,
            "source_ref": self.source_ref,
            "generation": self.generation,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "requests": [_request_data(request) for request in requests],
            "snapshots": [_snapshot_data(snapshot) for snapshot in snapshots],
            "blockers": list(blockers),
        }
        object.__setattr__(self, "_receipt_digest", _sha256(payload, "receipt"))

    @property
    def complete(self) -> bool:
        """Whether all required requests have sufficient complete snapshots."""
        if self.blockers:
            return False
        by_ref = {snapshot.request.request_ref: snapshot for snapshot in self.snapshots}
        for request in self.requests:
            if not request.required:
                continue
            snapshot = by_ref.get(request.request_ref)
            if snapshot is None or not snapshot.is_complete:
                return False
        return True

    @property
    def receipt_digest(self) -> str:
        """SHA-256 binding the request set, snapshot digests, source, and times."""
        return self._receipt_digest

    @property
    def complete_snapshot_refs(self) -> tuple[str, ...]:
        """Snapshot identities eligible for a lease over this receipt."""
        by_ref = {snapshot.request.request_ref: snapshot for snapshot in self.snapshots}
        refs: list[str] = []
        for request in self.requests:
            snapshot = by_ref.get(request.request_ref)
            if snapshot is not None and snapshot.is_complete and snapshot.snapshot_ref is not None:
                refs.append(snapshot.snapshot_ref)
        return tuple(refs)


@dataclass(frozen=True)
class QuerySnapshotLease:
    """Opaque provider-issued lease descriptor for a specific receipt snapshot set.

    Constructing this DTO does not confer authority. The provider port is the
    authority for issuing and validating leases; its opaque lease_ref must not
    expose a native handle or credential.
    """

    lease_ref: str
    receipt_digest: str
    source_ref: str
    generation: str
    snapshot_refs: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    purpose: str

    def __post_init__(self) -> None:
        _check_text(self.lease_ref, "lease_ref")
        if type(self.receipt_digest) is not str or not _SHA256_PATTERN.fullmatch(
            self.receipt_digest
        ):
            raise ValueError("receipt_digest must be a lower-case SHA-256 hex digest")
        _check_text(self.source_ref, "source_ref")
        _check_text(self.generation, "generation")
        refs = _check_string_tuple(self.snapshot_refs, "snapshot_refs")
        if not refs:
            raise ValueError("snapshot_refs must not be empty")
        issued_at = _check_utc_datetime(self.issued_at, "issued_at")
        expires_at = _check_utc_datetime(self.expires_at, "expires_at")
        if issued_at >= expires_at:
            raise ValueError("issued_at must be before expires_at")
        _check_text(self.purpose, "purpose")
        object.__setattr__(self, "snapshot_refs", refs)
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)


class ProviderQueryPort(Protocol):
    """Provider-neutral boundary for querying and revalidating snapshots.

    Implementations return a receipt whose requests exactly match the input
    sequence. Unsupported families or filters must fail closed. The absolute
    deadline and all lease times are timezone-aware UTC datetimes.
    """

    def query_batch(
        self,
        requests: Sequence[QueryRequest],
        *,
        deadline: datetime,
    ) -> QueryBatchReceipt:
        """Execute a bounded query batch before the supplied UTC deadline."""
        ...

    def acquire_snapshot_lease(
        self,
        receipt: QueryBatchReceipt,
        *,
        purpose: str,
        expires_at: datetime,
    ) -> QuerySnapshotLease:
        """Issue a provider-owned lease for a complete receipt.

        The returned lease must bind receipt_digest, source_ref, generation,
        and exactly receipt.complete_snapshot_refs. Incomplete receipts must
        not be promoted into leases.
        """
        ...

    def validate_lease(
        self,
        lease: QuerySnapshotLease,
        receipt: QueryBatchReceipt,
        *,
        now: datetime,
    ) -> bool:
        """Return true only if the same receipt snapshot set remains current.

        Expiry, source/generation change, snapshot change, or inability to
        confirm currentness returns false. Invalid argument types may raise
        TypeError or ValueError.
        """
        ...


__all__ = [
    "MAX_QUERY_BATCH_REQUESTS",
    "MAX_QUERY_JSON_BYTES",
    "MAX_QUERY_RECORDS",
    "MAX_QUERY_JSON_DEPTH",
    "ProviderQueryPort",
    "QUERY_CONTRACT_VERSION",
    "QueryBatchReceipt",
    "QueryCompleteness",
    "QueryRequest",
    "QuerySnapshot",
    "QuerySnapshotLease",
    "STANDARD_QUERY_FAMILIES",
    "STANDARD_QUERY_FILTER_KEYS",
]
