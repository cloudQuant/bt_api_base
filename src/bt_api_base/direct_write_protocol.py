"""Provider-neutral contracts for direct (no execution session) venue writes.

Iteration 62 layering:

* The SDK (``bt_api_py``) owns write admission.  It issues a one-shot
  :class:`WriteGrant` for every account-mutating call and hands providers a
  :class:`WriteGrantVerifier` that consumes the grant exactly once.
* A provider owns venue facts and the native call.  It reserves the native
  order identity (:class:`DirectOrderReservation`) *before* any send, so the
  host can persist it, and it converts native order/trade returns into
  :class:`DirectExecutionEvent` rows.  It never decides admission on its own.
* The host (for example Backtrader) supplies a :class:`PreDispatchCommitPort`
  that durably records the reservation before the SDK lets the provider send.

Constructing any DTO here proves nothing about an account, an authorization or
a venue acceptance; those facts come only from the SDK and the venue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bt_api_base.direct_cancel_protocol import PreparedCancelRequest
    from bt_api_base.direct_place_protocol import PreparedPlaceRequest

__all__ = (
    "DirectExecutionEvent",
    "DirectExecutionEventKind",
    "DirectOrderReservation",
    "DirectOrderStatus",
    "DirectSubmitResult",
    "DirectWriteError",
    "DirectWriteErrorPolicy",
    "DirectWriteProvider",
    "NativeOrderIdentity",
    "PreDispatchCommitPort",
    "PreDispatchRecord",
    "SettlementStatus",
    "SettlementObservation",
    "SettlementRequiredProvider",
    "SettlementWriteBinding",
    "WriteAdmissionDenied",
    "WriteGrant",
    "WriteGrantVerifier",
    "WriteOperation",
    "DirectAccountFacts",
    "DirectBalanceFact",
    "DirectPositionFact",
)


class WriteOperation(str, Enum):
    """Account-mutating operations covered by SDK write admission."""

    PLACE = "place"
    CANCEL = "cancel"
    SETTLEMENT_CONFIRM = "settlement_confirm"


class SettlementStatus(str, Enum):
    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SettlementObservation:
    """Provider observation bound to one account, trading day and session."""

    exchange_name: str
    account_binding: str
    trading_day: str
    session_generation: int
    status: SettlementStatus
    observation_id: str

    def __post_init__(self) -> None:
        for value in (self.exchange_name, self.account_binding, self.observation_id):
            if type(value) is not str or not value or value != value.strip() or len(value) > 256:
                raise ValueError("invalid settlement observation reference")
        if (type(self.trading_day) is not str or len(self.trading_day) != 8
                or not self.trading_day.isascii() or not self.trading_day.isdigit()):
            raise ValueError("invalid trading day")
        try:
            datetime.strptime(self.trading_day, "%Y%m%d")
        except ValueError:
            raise ValueError("invalid trading day") from None
        if type(self.session_generation) is not int or self.session_generation <= 0:
            raise ValueError("invalid settlement session generation")
        if type(self.status) is not SettlementStatus:
            raise ValueError("invalid settlement status")


@dataclass(frozen=True)
class SettlementWriteBinding:
    """An unconfirmed observation and its pre-dispatch host marker."""

    observation: SettlementObservation
    marker_id: str

    def __post_init__(self) -> None:
        if (
            type(self.observation) is not SettlementObservation
            or self.observation.status is not SettlementStatus.UNCONFIRMED
        ):
            raise ValueError("unconfirmed settlement observation required")
        if (
            type(self.marker_id) is not str or not self.marker_id
            or self.marker_id != self.marker_id.strip() or len(self.marker_id) > 256
        ):
            raise ValueError("invalid settlement marker")


@runtime_checkable
class SettlementRequiredProvider(Protocol):
    """Additional methods required only when settlement_required is True."""

    def observe_settlement(self) -> Optional[SettlementObservation]:
        """Read a session-bound settlement observation."""

    def validate_settlement_observation(self, observation: SettlementObservation) -> bool:
        """Return literal True only while the observation is current."""

    def confirm_settlement(
        self, grant: WriteGrant, verifier: WriteGrantVerifier, *, observation: SettlementObservation
    ) -> SettlementStatus:
        """Confirm exactly the observed statement under the supplied grant."""


class DirectWriteError(RuntimeError):
    """A direct write could not be prepared or sent; ``code`` is stable."""

    def __init__(self, code: str, detail: str = "") -> None:
        if type(code) is not str or not code:
            code = "direct_write_failed"
        self.code = code
        self.detail = detail if type(detail) is str else ""
        super().__init__(code if not self.detail else f"{code}: {self.detail}")


class WriteAdmissionDenied(DirectWriteError, PermissionError):
    """SDK write admission refused the operation; no native call happened."""


@dataclass(frozen=True)
class DirectWriteErrorPolicy:
    """Provider-declared codes whose PLACE or CANCEL outcome is unknown.

    Each field is an exact frozenset with at most 128 codes. Each code is an
    exact nonempty trimmed string of at most 128 characters. Empty sets are
    explicit declarations that no DirectWriteError code is classified unknown.
    """

    place_unknown_codes: frozenset[str]
    cancel_unknown_codes: frozenset[str]

    def __post_init__(self) -> None:
        for name in ("place_unknown_codes", "cancel_unknown_codes"):
            codes = getattr(self, name)
            if type(codes) is not frozenset or len(codes) > 128:
                raise ValueError(f"{name} must be a frozenset of at most 128 codes")
            if any(
                type(code) is not str or not code or len(code) > 128 or code != code.strip()
                for code in codes
            ):
                raise ValueError(f"{name} contains an invalid code")


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty trimmed string")
    return value


def _frozen_fields(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    plain: dict[str, Any] = {}
    for key, item in value.items():
        if type(key) is not str or not key:
            raise ValueError(f"{name} keys must be non-empty strings")
        if item is not None and type(item) not in (str, int, float, bool):
            raise ValueError(f"{name}[{key!r}] must be a scalar")
        plain[key] = item
    return MappingProxyType(plain)


@dataclass(frozen=True)
class WriteGrant:
    """One-shot SDK authorization for exactly one native write call."""

    exchange_name: str
    operation: WriteOperation
    session_generation: Optional[int]
    grant_id: str
    issued_monotonic_ns: int
    settlement_binding: Optional[SettlementWriteBinding] = None

    def __post_init__(self) -> None:
        _text(self.exchange_name, "exchange_name")
        if type(self.operation) is not WriteOperation:
            raise ValueError("operation must be a WriteOperation")
        if self.session_generation is not None and (
            type(self.session_generation) is not int or self.session_generation < 0
        ):
            raise ValueError("session_generation must be a non-negative int or None")
        _text(self.grant_id, "grant_id")
        if type(self.issued_monotonic_ns) is not int or self.issued_monotonic_ns <= 0:
            raise ValueError("issued_monotonic_ns must be a positive int")
        if (
            self.settlement_binding is not None
            and type(self.settlement_binding) is not SettlementWriteBinding
        ):
            raise ValueError("invalid settlement binding")


@runtime_checkable
class WriteGrantVerifier(Protocol):
    """SDK-owned verifier a provider calls immediately before the native call."""

    def consume(
        self,
        grant: WriteGrant,
        *,
        exchange_name: str,
        operation: WriteOperation,
        session_generation: Optional[int],
        settlement_binding: Optional[SettlementWriteBinding] = None,
    ) -> None:
        """Consume ``grant`` once or raise :class:`WriteAdmissionDenied`."""


@dataclass(frozen=True)
class NativeOrderIdentity:
    """Venue identity of one order as known at a point in time.

    ``client_order_id`` is the venue client id the provider sends (CTP
    ``OrderRef``).  ``fields`` holds the remaining venue-scoped keys needed to
    query or cancel the order later (for CTP ``front_id``, ``session_id``,
    ``trading_day``, ``exchange_id`` and, once known, ``order_sys_id``).
    """

    exchange_name: str
    client_order_id: Optional[str]
    fields: Mapping[str, Any] = field(default_factory=dict)
    session_generation: Optional[int] = None

    def __post_init__(self) -> None:
        _text(self.exchange_name, "exchange_name")
        if self.client_order_id is not None:
            _text(self.client_order_id, "client_order_id")
        object.__setattr__(self, "fields", _frozen_fields(self.fields, "fields"))
        if self.session_generation is not None and (
            type(self.session_generation) is not int or self.session_generation < 0
        ):
            raise ValueError("session_generation must be a non-negative int or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "exchange_name": self.exchange_name,
            "client_order_id": self.client_order_id,
            "fields": dict(self.fields),
            "session_generation": self.session_generation,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "NativeOrderIdentity":
        return cls(
            exchange_name=raw["exchange_name"],
            client_order_id=raw.get("client_order_id"),
            fields=raw.get("fields") or {},
            session_generation=raw.get("session_generation"),
        )


@dataclass(frozen=True)
class DirectOrderReservation:
    """Native identity reserved by a provider before any send."""

    identity: NativeOrderIdentity
    symbol: str
    reservation_id: str

    def __post_init__(self) -> None:
        if type(self.identity) is not NativeOrderIdentity:
            raise ValueError("identity must be a NativeOrderIdentity")
        _text(self.symbol, "symbol")
        _text(self.reservation_id, "reservation_id")


@dataclass(frozen=True)
class PreDispatchRecord:
    """What the host must persist durably before the SDK sends a write."""

    operation: WriteOperation
    host_scope: str
    exchange_name: str
    symbol: Optional[str]
    identity: Optional[NativeOrderIdentity]
    target_identity: Optional[NativeOrderIdentity]
    request_summary: Mapping[str, Any]
    trading_day: Optional[str]
    session_generation: Optional[int]
    created_at_utc: str
    prepared_cancel: Optional["PreparedCancelRequest"] = None
    prepared_place: Optional["PreparedPlaceRequest"] = None

    def __post_init__(self) -> None:
        if type(self.operation) is not WriteOperation:
            raise ValueError("operation must be a WriteOperation")
        _text(self.host_scope, "host_scope")
        _text(self.exchange_name, "exchange_name")
        object.__setattr__(
            self, "request_summary", _frozen_fields(self.request_summary, "request_summary")
        )
        _text(self.created_at_utc, "created_at_utc")
        self._validate_prepared_cancel()
        self._validate_prepared_place()

    def _validate_prepared_place(self) -> None:
        if self.prepared_place is None:
            return
        from bt_api_base.direct_place_protocol import PreparedPlaceRequest
        from bt_api_base.gateway_direct_protocol import canonical_gateway_payload

        prepared = self.prepared_place
        if type(prepared) is not PreparedPlaceRequest:
            raise ValueError("invalid prepared place")
        prepared.to_mapping()
        if (
            self.operation is not WriteOperation.PLACE
            or self.prepared_cancel is not None
            or self.target_identity is not None
            or type(self.identity) is not NativeOrderIdentity
            or canonical_gateway_payload(self.identity.to_dict())
            != canonical_gateway_payload(prepared.identity.to_dict())
            or self.exchange_name != prepared.identity.exchange_name
            or self.symbol != prepared.symbol
            or self.trading_day != prepared.trading_day
            or type(self.session_generation) is not int
            or self.session_generation != prepared.session_generation
        ):
            raise ValueError("prepared place binding mismatch")

    def _validate_prepared_cancel(self) -> None:
        if self.prepared_cancel is None:
            return
        from bt_api_base.direct_cancel_protocol import PreparedCancelRequest
        from bt_api_base.gateway_direct_protocol import canonical_gateway_payload

        prepared = self.prepared_cancel
        if type(prepared) is not PreparedCancelRequest:
            raise ValueError("invalid prepared cancel")
        prepared.to_mapping()
        if (self.operation is not WriteOperation.CANCEL or self.identity is not None
                or type(self.target_identity) is not NativeOrderIdentity
                or canonical_gateway_payload(self.target_identity.to_dict())
                    != canonical_gateway_payload(prepared.target_identity.to_dict())
                or self.exchange_name != prepared.target_identity.exchange_name
                or self.symbol != prepared.symbol or self.trading_day != prepared.trading_day
                or type(self.session_generation) is not int
                or self.session_generation != prepared.session_generation):
            raise ValueError("prepared cancel binding mismatch")

    def to_dict(self) -> dict[str, Any]:
        self._validate_prepared_cancel()
        self._validate_prepared_place()
        result = {
            "operation": self.operation.value,
            "host_scope": self.host_scope,
            "exchange_name": self.exchange_name,
            "symbol": self.symbol,
            "identity": None if self.identity is None else self.identity.to_dict(),
            "target_identity": (
                None if self.target_identity is None else self.target_identity.to_dict()
            ),
            "request_summary": dict(self.request_summary),
            "trading_day": self.trading_day,
            "session_generation": self.session_generation,
            "created_at_utc": self.created_at_utc,
        }
        if self.prepared_cancel is not None:
            result["prepared_cancel"] = self.prepared_cancel.to_mapping()
        if self.prepared_place is not None:
            result["prepared_place"] = self.prepared_place.to_mapping()
        return result


@runtime_checkable
class PreDispatchCommitPort(Protocol):
    """Host-owned durable store for pre-dispatch markers.

    ``commit`` returns a non-empty marker id only after the record is durably
    stored; any other return value (``None``, ``""``) or an exception means the
    SDK must not send.
    """

    def commit(self, record: PreDispatchRecord) -> Optional[str]:
        """Persist ``record`` durably and return its marker id."""


class DirectOrderStatus(str, Enum):
    """Neutral order status projected from venue returns."""

    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class DirectExecutionEventKind(str, Enum):
    ORDER = "order"
    TRADE = "trade"
    ORDER_ERROR = "order_error"
    CANCEL_ERROR = "cancel_error"


@dataclass(frozen=True)
class DirectSubmitResult:
    """Synchronous outcome of handing one request to the native API."""

    sent: Optional[bool]
    identity: Optional[NativeOrderIdentity]
    error_code: Optional[str] = None
    detail: Optional[str] = None


@dataclass(frozen=True)
class DirectExecutionEvent:
    """One provider-normalized order or trade return.

    The provider fills what the venue reported.  Correlation to a host order
    and any evidence label are added by the SDK, never by the provider.
    """

    kind: DirectExecutionEventKind
    exchange_name: str
    symbol: str
    identity: Optional[NativeOrderIdentity]
    exchange_order_id: Optional[str] = None
    status: Optional[DirectOrderStatus] = None
    side: Optional[str] = None
    offset: Optional[str] = None
    order_qty: Optional[float] = None
    filled_qty: Optional[float] = None
    remaining_qty: Optional[float] = None
    limit_price: Optional[float] = None
    trade_id: Optional[str] = None
    trade_price: Optional[float] = None
    trade_qty: Optional[float] = None
    trade_time: Optional[str] = None
    trading_day: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    raw_status: Optional[str] = None
    session_generation: Optional[int] = None
    sequence: int = 0

    def __post_init__(self) -> None:
        if type(self.kind) is not DirectExecutionEventKind:
            raise ValueError("kind must be a DirectExecutionEventKind")
        _text(self.exchange_name, "exchange_name")
        _text(self.symbol, "symbol")
        if self.identity is not None and type(self.identity) is not NativeOrderIdentity:
            raise ValueError("identity must be a NativeOrderIdentity or None")
        if self.status is not None and type(self.status) is not DirectOrderStatus:
            raise ValueError("status must be a DirectOrderStatus or None")

    def dedup_key(self) -> tuple[Any, ...]:
        """Stable de-duplication key across replays of the same venue return."""

        ident = self.identity
        client = None if ident is None else ident.client_order_id
        fields = {} if ident is None else ident.fields
        if self.kind is DirectExecutionEventKind.TRADE:
            return (
                "trade",
                self.exchange_name,
                fields.get("exchange_id"),
                self.trade_id,
                self.side,
                self.exchange_order_id,
            )
        return (
            self.kind.value,
            self.exchange_name,
            fields.get("front_id"),
            fields.get("session_id"),
            client,
            self.exchange_order_id,
            None if self.status is None else self.status.value,
            self.filled_qty,
            self.raw_status,
            self.error_code,
        )


@dataclass(frozen=True)
class DirectPositionFact:
    """Venue-reported position for one instrument and side (no attribution).

    ``side`` is ``long``/``short`` for two-sided venues, ``net`` otherwise.
    ``today``/``yesterday`` split ``total`` when the venue reports it; ``None``
    means unknown (never zero).  ``frozen_close`` is the venue-reported volume
    already reserved by working close orders when the venue reports it.
    """

    symbol: str
    venue: Optional[str]
    side: str
    total: float
    today: Optional[float] = None
    yesterday: Optional[float] = None
    frozen_close: Optional[float] = None

    def __post_init__(self) -> None:
        _text(self.symbol, "symbol")
        if self.side not in ("long", "short", "net"):
            raise ValueError("side must be long, short or net")


@dataclass(frozen=True)
class DirectBalanceFact:
    """Venue-reported account funds in the account currency."""

    currency: Optional[str]
    balance: Optional[float]
    available: Optional[float]
    margin: Optional[float] = None
    frozen: Optional[float] = None
    close_profit: Optional[float] = None
    position_profit: Optional[float] = None
    commission: Optional[float] = None


@dataclass(frozen=True)
class DirectAccountFacts:
    """One read-only account observation for direct-mode reconciliation.

    ``complete`` is True only when every requested section was read in full
    for the current session; ``blockers`` names what is missing.  A section
    that was not requested is ``None``.  Active orders and trades are
    normalized :class:`DirectExecutionEvent` records carrying the native
    identity needed to restore or cancel them.
    """

    exchange_name: str
    trading_day: Optional[str]
    session_generation: Optional[int]
    observed_at_utc: str
    positions: Optional[tuple[DirectPositionFact, ...]]
    active_orders: Optional[tuple[DirectExecutionEvent, ...]]
    trades: Optional[tuple[DirectExecutionEvent, ...]]
    balance: Optional[DirectBalanceFact]
    complete: bool
    blockers: tuple[str, ...] = ()
    # Every order of the current trading day (working and terminal) when
    # requested; used to verify pending identities after a restart.
    orders: Optional[tuple[DirectExecutionEvent, ...]] = None


@runtime_checkable
class DirectWriteProvider(Protocol):
    """Provider-side direct write port for one selected route.

    Every method that mutates the account receives a :class:`WriteGrant` and the
    SDK :class:`WriteGrantVerifier`; the provider must call
    ``verifier.consume(...)`` immediately before the native call and must not
    call the venue when consumption fails.
    """

    direct_write_error_policy: DirectWriteErrorPolicy
    settlement_required: bool

    def session_generation(self) -> Optional[int]:
        """Current native trading-session generation, or ``None`` if not logged in."""

    def trading_day(self) -> Optional[str]:
        """Venue trading day of the current session (``YYYYMMDD``) if known."""

    def reserve_order(self, request: Any) -> DirectOrderReservation:
        """Reserve the native identity for ``request`` without sending."""

    def release_reservation(self, reservation: DirectOrderReservation) -> None:
        """Forget a reservation that will not be sent."""

    def submit_order(
        self,
        reservation: DirectOrderReservation,
        request: Any,
        grant: WriteGrant,
        verifier: WriteGrantVerifier,
    ) -> DirectSubmitResult:
        """Send the reserved order once."""

    def cancel_order(
        self,
        target: NativeOrderIdentity,
        symbol: str,
        grant: WriteGrant,
        verifier: WriteGrantVerifier,
    ) -> DirectSubmitResult:
        """Send one cancel for ``target`` using its original venue identity."""

    def drain_execution_events(self, max_events: int) -> tuple[DirectExecutionEvent, ...]:
        """Return pending normalized returns in arrival order (non-blocking)."""

    def account_facts(
        self,
        *,
        positions: bool = True,
        active_orders: bool = True,
        trades: bool = False,
        balance: bool = True,
        all_orders: bool = False,
    ) -> DirectAccountFacts:
        """Read-only account observation for host reconciliation (optional)."""

    def account_reference(self) -> Optional[str]:
        """Stable, secret-free reference of the logged-in account (optional)."""
