"""Provider-neutral order identity and correlated-dispatch contracts.

This module is intentionally independent of ``bt_api_py``, venue packages,
and framework types.  It defines the neutral identity exchanged by the SDK
composer and provider packages.  Constructing one of these DTOs does not create
an issuer reservation, provider binding, authorization, claim, or dispatch
permission; only the injected SDK-owned issuer/provider authorities can prove
those separate facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Literal, Optional, Protocol, runtime_checkable

from bt_api_base.market_protocol import MarketInstrumentKey

__all__ = (
    "CancelOrderRequestProtocol",
    "OrderCorrelation",
    "OrderRequestProtocol",
    "SelectedExecutionRoute",
    "TypedOrderProviderFactory",
    "TypedOrderProviderRegistryPort",
    "OrderCorrelationIssuer",
    "TypedOrderProvider",
    "VerifiedOrderAcknowledgement",
)


def _require_text(value: object, field_name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        raise ValueError(f"{field_name} must be non-empty trimmed printable text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be valid UTF-8") from exc
    if len(encoded) > 256:
        raise ValueError(f"{field_name} exceeds the UTF-8 byte limit")
    return value


@dataclass(frozen=True)
class SelectedExecutionRoute:
    """Opaque exact route binding supplied by trusted SDK composition.

    Provider-neutral factories receive the already selected SDK client and an
    optional opaque execution context. This DTO carries route selection only;
    it does not prove endpoint, account, session, authorization, provider
    capability, or write permission. The context is never represented or
    compared by value.
    """

    exchange_name: str
    client: object = field(repr=False, compare=False)
    environment: str | None = None
    execution_context: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_text(self.exchange_name, "exchange_name")
        if self.client is None:
            raise ValueError("selected route client is required")
        if self.environment is not None:
            _require_text(self.environment, "environment")


@dataclass(frozen=True)
class OrderCorrelation:
    """Neutral SDK-issued identity for exactly one route and symbol.

    The opaque references are not provider-native IDs and do not prove that a
    provider has reserved or dispatched an order.
    """

    exchange_name: str
    symbol: str
    client_order_id: str
    reservation_ref: str

    def __post_init__(self) -> None:
        for name in ("exchange_name", "symbol", "client_order_id", "reservation_ref"):
            _require_text(getattr(self, name), name)


@dataclass(frozen=True)
class VerifiedOrderAcknowledgement:
    """Sanitized provider acknowledgement with no provider-native order ID.

    This value is evidence only when returned by the selected SDK provider's
    trusted verifier for the exact correlation and operation. Constructing the
    DTO does not verify a response. The two dispositions represent a verified
    provider acknowledgement; an absent/unverifiable acknowledgement is
    represented by ``None`` from the verifier and remains UNKNOWN.
    """

    correlation: OrderCorrelation
    operation: Literal["submit", "cancel"]
    disposition: Literal["accepted", "rejected"]
    observed_at: datetime
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.correlation) is not OrderCorrelation:
            raise TypeError("correlation must be an exact OrderCorrelation")
        if type(self.operation) is not str or self.operation not in {"submit", "cancel"}:
            raise ValueError("operation must be submit or cancel")
        if type(self.disposition) is not str or self.disposition not in {"accepted", "rejected"}:
            raise ValueError("disposition must be accepted or rejected")
        if type(self.observed_at) is not datetime:
            raise TypeError("observed_at must be a datetime")
        if (
            self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
            or self.observed_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("observed_at must be timezone-aware UTC")
        if self.reason_code is not None:
            _require_text(self.reason_code, "reason_code")


@runtime_checkable
class OrderRequestProtocol(Protocol):
    """Neutral typed fields consumed by a provider's order mapper.

    Provider authorization labels and raw venue request fields are deliberately
    absent. The optional canonical ``MarketInstrumentKey`` may contain the
    provider's native symbol spelling, but it is only a key: a provider must
    validate it against its selected catalog before deriving venue fields.
    Concrete SDK request objects may carry additional internal fields, but a
    provider must validate and consume only this common typed surface.
    ``hedge_class`` is provider-neutral strategy intent. ``None`` means the
    caller supplied no hedge intent; a provider that requires one must reject
    the request instead of selecting a default. Supported common values are
    ``speculation``, ``arbitrage``, and ``hedge``.
    ``instrument`` is an optional canonical market identity. A provider that
    needs a venue-specific exchange code must validate this key against its
    own selected catalog; it must not trust a caller-supplied exchange string.
    """

    @property
    def symbol(self) -> str: ...

    @property
    def instrument(self) -> MarketInstrumentKey | None: ...

    @property
    def side(self) -> str: ...

    @property
    def order_type(self) -> str: ...

    @property
    def quantity(self) -> Decimal: ...

    @property
    def account_id(self) -> str: ...

    @property
    def client_order_id(self) -> str: ...

    @property
    def price(self) -> Decimal | None: ...

    @property
    def time_in_force(self) -> str: ...

    @property
    def reduce_only(self) -> bool: ...

    @property
    def idempotency_key(self) -> str: ...

    @property
    def quantity_unit(self) -> str: ...

    @property
    def position_side(self) -> str | None: ...

    @property
    def offset(self) -> str | None: ...

    @property
    def position_mode(self) -> str | None: ...

    @property
    def hedge_class(self) -> str | None: ...


@runtime_checkable
class CancelOrderRequestProtocol(Protocol):
    """Neutral fields for a correlated cancellation request.

    The correlated dispatch path requires a non-empty ``client_order_id``
    equal to the SDK-issued correlation's client ID. A generic cancel request
    that identifies an order only by another identifier is not sufficient for
    this capability and must fail before provider dispatch.
    """

    @property
    def symbol(self) -> str: ...

    @property
    def account_id(self) -> str: ...

    @property
    def client_order_id(self) -> str: ...

    @property
    def order_id(self) -> str | None: ...

    @property
    def idempotency_key(self) -> str: ...


class OrderCorrelationIssuer(Protocol):
    """SDK-owned durable issuer for provider-neutral client order identity."""

    def issue_order_correlation(
        self,
        exchange_name: str,
        symbol: str,
    ) -> tuple[OrderCorrelation, object]: ...

    def resolve_order_correlation(
        self,
        correlation: OrderCorrelation,
    ) -> object | None: ...

    def validate_order_correlation(
        self,
        correlation: OrderCorrelation,
        *,
        issuer_reservation: object,
    ) -> bool: ...


class TypedOrderProvider(Protocol):
    """Provider-internal route-bound reservation and correlated dispatch port.

    All reservation and authorization arguments are opaque.  The provider
    binding, one-shot claim, dispatch, and acknowledgement evidence remain in
    the selected provider package.  A claim implementation is pre-dispatch;
    an implementation must never issue the native write from ``claim``. A
    claim is not a provider acknowledgement and does not itself authorize a
    second dispatch attempt.

    Once either dispatch method below has been entered, an exception,
    cancellation, timeout, malformed result, or missing verifiable
    acknowledgement is UNKNOWN unless the SDK receives separate typed proof
    that the provider write definitely did not occur. The SDK/provider must not
    automatically retry that submit or cancel. ``None`` from a response
    verifier means UNKNOWN; it does not mean rejected, not-dispatched, or safe
    to retry. Resolve uncertainty only through an independently authorized
    reconciliation path.
    """

    def bind_order_reservation(
        self,
        correlation: OrderCorrelation,
        *,
        issuer_reservation: object,
    ) -> object: ...

    def resolve_order_reservation(
        self,
        correlation: OrderCorrelation,
        *,
        issuer_reservation: object,
    ) -> object | None: ...

    def claim_correlated_order(
        self,
        operation: Literal["submit", "cancel"],
        correlation: OrderCorrelation,
        request: OrderRequestProtocol | CancelOrderRequestProtocol,
        *,
        issuer_reservation: object,
        provider_reservation: object,
        authorization: object,
    ) -> object: ...

    async def submit_correlated_order(
        self,
        correlation: OrderCorrelation,
        request: OrderRequestProtocol,
        *,
        issuer_reservation: object,
        provider_reservation: object,
        claim: object,
        authorization: object,
    ) -> object:
        """Issue the claimed submit once; ambiguous outcomes remain UNKNOWN."""
        ...

    async def cancel_correlated_order(
        self,
        correlation: OrderCorrelation,
        request: CancelOrderRequestProtocol,
        *,
        issuer_reservation: object,
        provider_reservation: object,
        claim: object,
        authorization: object,
    ) -> object:
        """Issue the claimed cancel once; ambiguous outcomes remain UNKNOWN."""
        ...

    def verify_order_response(
        self,
        correlation: OrderCorrelation,
        response: object,
        *,
        issuer_reservation: object,
        provider_reservation: object,
    ) -> VerifiedOrderAcknowledgement | None:
        """Return ``None`` when acknowledgement is unproven (UNKNOWN)."""
        ...

    def verify_cancel_response(
        self,
        correlation: OrderCorrelation,
        response: object,
        *,
        issuer_reservation: object,
        provider_reservation: object,
    ) -> VerifiedOrderAcknowledgement | None:
        """Return ``None`` when acknowledgement is unproven (UNKNOWN)."""
        ...


TypedOrderProviderFactory = Callable[
    [SelectedExecutionRoute, Optional[OrderCorrelationIssuer]], TypedOrderProvider
]


@runtime_checkable
class TypedOrderProviderRegistryPort(Protocol):
    """Provider-neutral registrar contract for one exact route factory."""

    def register(
        self,
        exchange_name: str,
        factory: TypedOrderProviderFactory,
    ) -> None: ...
