"""Provider-neutral assurance for the active execution account identity.

This contract carries only an SDK-normalized account reference and the source
receipt needed to revalidate it. A configured alias or locally derived label
is not provider evidence. ``authenticated_credential`` means that the exact
credential was accepted by a provider-authenticated read; it does not claim a
physical account identifier. ``provider_account_id`` means the provider's
returned account identity was checked against the selected SDK session.
Neither binding type grants order authorization or dispatch permission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .execution_request_receipt_protocol import (
        ExecutionCredentialRequestAttemptContext,
        ExecutionCredentialRequestOpaqueRef,
        ExecutionCredentialRequestTransport,
    )

_IDENTITY_BINDINGS = frozenset({"provider_account_id", "authenticated_credential"})
_UNAVAILABLE_CODES = frozenset(
    {
        "execution_identity_assurance_unavailable",
        "execution_identity_assurance_route_unavailable",
        "execution_identity_assurance_route_changed",
        "execution_identity_assurance_provider_unavailable",
        "execution_identity_assurance_discovery_failed",
        "execution_identity_assurance_projection_invalid",
        "execution_identity_assurance_not_current",
        "execution_identity_assurance_identity_mismatch",
    }
)
_SNAPSHOT_UNAVAILABLE_CODES = frozenset(
    {
        "execution_identity_snapshot_unavailable",
        "execution_identity_snapshot_route_unavailable",
        "execution_identity_snapshot_route_changed",
        "execution_identity_snapshot_config_mismatch",
        "execution_identity_snapshot_projection_invalid",
        "execution_identity_snapshot_not_current",
        "execution_identity_vector_invalid",
        "execution_identity_vector_assurance_unavailable",
        "execution_identity_vector_not_current",
    }
)
_EVIDENCE_UNAVAILABLE_CODES = frozenset(
    {
        "execution_identity_evidence_unavailable",
        "execution_identity_evidence_contract_unavailable",
        "execution_identity_evidence_route_unavailable",
        "execution_identity_evidence_route_changed",
        "execution_identity_evidence_config_mismatch",
        "execution_identity_evidence_provider_unavailable",
        "execution_identity_evidence_not_current",
        "execution_identity_evidence_vector_unavailable",
        "execution_identity_evidence_vector_invalid",
    }
)


def _require_text(value: object, field_name: str, *, maximum: int = 256) -> None:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.isprintable()
    ):
        raise ValueError(f"{field_name} must be non-empty printable text")
    try:
        if len(value.encode("utf-8", errors="strict")) > maximum:
            raise ValueError(f"{field_name} exceeds its UTF-8 byte limit")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be valid UTF-8") from exc


def _require_utc(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise TypeError(f"{field_name} must be an aware UTC datetime")
    try:
        if value.utcoffset() != timedelta(0):
            raise ValueError(f"{field_name} must be UTC")
    except Exception as exc:
        raise ValueError(f"{field_name} must be UTC") from exc
    return value


@dataclass(frozen=True)
class ExecutionIdentityAssurance:
    """One provider-issued, route-bound proof of an execution identity.

    ``account_ref`` is a non-secret, stable SDK reference that must match the
    identity's account reference already held by the SDK execution ledger.
    It must never be derived from an unverified account alias. The exact DTO
    object remains subject to provider-side receipt, session, and freshness
    validation through :class:`ExecutionIdentityAssurancePort`.
    """

    exchange_name: str
    provider: str
    environment: str
    account_ref: str = field(repr=False)
    identity_binding: Literal["provider_account_id", "authenticated_credential"]
    source_ref: str = field(repr=False)
    session_generation: str = field(repr=False)
    observed_at_utc: datetime
    expires_at_utc: datetime
    receipt_ref: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_text(self.exchange_name, "exchange_name")
        _require_text(self.provider, "provider", maximum=64)
        _require_text(self.environment, "environment", maximum=128)
        _require_text(self.account_ref, "account_ref")
        if type(self.identity_binding) is not str or self.identity_binding not in _IDENTITY_BINDINGS:
            raise ValueError("identity_binding is unsupported")
        _require_text(self.source_ref, "source_ref")
        _require_text(self.session_generation, "session_generation")
        observed = _require_utc(self.observed_at_utc, "observed_at_utc")
        expires = _require_utc(self.expires_at_utc, "expires_at_utc")
        if expires <= observed:
            raise ValueError("expires_at_utc must follow observed_at_utc")
        _require_text(self.receipt_ref, "receipt_ref")


class ExecutionIdentityAssuranceUnavailable(RuntimeError):
    """Finite failure to obtain or validate provider identity assurance."""

    _CODES = _UNAVAILABLE_CODES

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in self._CODES
            else "execution_identity_assurance_unavailable"
        )
        super().__init__(self.code)


class ExecutionIdentitySnapshotRef:
    """Opaque SDK identity-configuration reference.

    This marker is useful only by exact object identity inside the SDK-owned
    currentness validator. It is not an account proof or execution authority.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<opaque SDK execution-identity snapshot reference>"

    def __reduce__(self):
        raise TypeError("execution identity snapshot references cannot be serialized")


class ExecutionIdentityScopeRef:
    """Opaque SDK identity-scope key for local cross-generation fencing.

    This marker is stable for the same configured route/provider/environment/
    account/strategy identity inside one SDK process, including when an
    execution-session owner is reconstructed. It contains no public identity
    fields, cannot be serialized, and is not provider evidence or execution
    authority. SDK vector validators still establish whether a marker belongs
    to the exact current snapshot and assurance set.
    """

    __slots__ = ("__weakref__",)

    def __repr__(self) -> str:
        return "<opaque SDK execution-identity scope>"

    def __reduce__(self):
        raise TypeError("execution identity scope references cannot be serialized")


@dataclass(frozen=True)
class ExecutionIdentityRouteExpectation:
    """Caller configuration declarations required for SDK identity capture.

    These values are supplied only so the SDK can compare its selected route
    and ledger configuration with the caller's explicit configuration. They
    do not establish provider identity, credential validity, or write
    authority. The strategy and account-alias labels are hidden from repr and
    are never copied into the issued identity snapshot.
    """

    exchange_name: str
    expected_provider: str
    expected_environment: str | None
    expected_strategy_id: str = field(repr=False)
    expected_account_alias: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_text(self.exchange_name, "exchange_name")
        _require_text(self.expected_provider, "expected_provider", maximum=64)
        if self.expected_provider != self.expected_provider.casefold():
            raise ValueError("expected_provider must use canonical lowercase text")
        # None means that the caller has no local environment declaration.
        # The SDK still binds the selected route, snapshot, and assurance to
        # their exact current environment.
        if self.expected_environment is not None:
            _require_text(self.expected_environment, "expected_environment", maximum=128)
        _require_text(self.expected_strategy_id, "expected_strategy_id")
        if self.expected_account_alias is not None:
            _require_text(self.expected_account_alias, "expected_account_alias")


@dataclass(frozen=True)
class ExecutionIdentitySnapshot:
    """Immutable SDK ledger/config declaration for one exact active route.

    ``account_ref`` is the canonical non-secret account reference already
    owned by the SDK ledger. ``strategy_ref`` is an opaque SDK marker bound to
    the configured strategy declaration. The configured alias and strategy
    text, credential fingerprint, and credential lineage are never rendered
    by this DTO. None of these values is provider evidence or write authority;
    provider-issued :class:`ExecutionIdentityAssurance` remains independent.

    The SDK accepts caller-supplied route declarations only to compare them
    with its own current configuration before issuing this exact object. A
    currentness check must validate the exact object with its issuing SDK
    session; constructing this DTO in application code proves nothing.
    """

    exchange_name: str
    provider: str
    environment: str
    account_ref: str = field(repr=False)
    strategy_ref: ExecutionIdentitySnapshotRef = field(repr=False, compare=False)
    credential_lineage_ref: object | None = field(repr=False, compare=False)
    fencing_epoch: int
    session_generation: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_text(self.exchange_name, "exchange_name")
        _require_text(self.provider, "provider", maximum=64)
        if self.provider != self.provider.casefold():
            raise ValueError("provider must use canonical lowercase text")
        _require_text(self.environment, "environment", maximum=128)
        _require_text(self.account_ref, "account_ref")
        if type(self.strategy_ref) is not ExecutionIdentitySnapshotRef:
            raise TypeError("strategy_ref must be an exact SDK opaque reference")
        if self.credential_lineage_ref is not None and self.credential_lineage_ref is self.strategy_ref:
            raise ValueError("credential_lineage_ref must be independently bound")
        if type(self.fencing_epoch) is not int or self.fencing_epoch <= 0:
            raise ValueError("fencing_epoch must be a positive exact int")
        _require_text(self.session_generation, "session_generation")


class ExecutionIdentitySnapshotUnavailable(RuntimeError):
    """Finite failure to issue, validate, or summarize a current SDK snapshot."""

    _CODES = _SNAPSHOT_UNAVAILABLE_CODES

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in self._CODES
            else "execution_identity_snapshot_unavailable"
        )
        super().__init__(self.code)


class ExecutionIdentityEvidenceUnavailable(RuntimeError):
    """Finite failure to capture or validate exact SDK-bound identity evidence."""

    _CODES = _EVIDENCE_UNAVAILABLE_CODES

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in self._CODES
            else "execution_identity_evidence_unavailable"
        )
        super().__init__(self.code)


@runtime_checkable
class ExecutionCredentialRequestContextPort(Protocol):
    """Session-owned request context exposed only through a selected route.

    ``credential_lineage_ref`` must be the exact marker pinned from the
    selected provider feed when that feed is bound to the SDK execution
    session. The provider separately checks that its current immutable signer
    binding was created with that marker and is the binding used for the
    physical request. The context never receives credential values.
    """

    def begin_request(
        self,
        route: "SelectedExecutionIdentityRoute",
        *,
        selected_client: object,
        credential_lineage_ref: ExecutionCredentialRequestOpaqueRef,
        transport: ExecutionCredentialRequestTransport,
        operation: str,
    ) -> ExecutionCredentialRequestAttemptContext | None:
        """Issue an attempt only for the exact currently selected route."""
        ...

    def validate_current(
        self,
        route: "SelectedExecutionIdentityRoute",
        *,
        selected_client: object,
        credential_lineage_ref: ExecutionCredentialRequestOpaqueRef,
        context: ExecutionCredentialRequestAttemptContext,
    ) -> bool:
        """Recheck current feed, session, credential lineage, lease and fence."""
        ...


@dataclass(frozen=True)
class SelectedExecutionIdentityRoute:
    """SDK-internal provider route bound to a current durable identity ledger.

    The opaque ``ledger_binding`` is issued and retained by the trusted SDK
    execution-session owner. It binds this exact selected client, canonical
    ledger account reference, configured credential identity, owner generation,
    and fence.
    The binding is not an authentication result or order authorization. The
    optional ``request_receipt_context`` is an internal session-owned port.
    It exists only when trusted assembly pinned the selected feed's
    construction-time credential-lineage marker before any request. The
    provider must bind that marker to the exact immutable signer binding on
    ``client``; the SDK does not derive it from ``account_ref`` or a public
    fingerprint. Its attempt object contains distinct opaque route, owner,
    lease, and lineage refs. These markers are correlation handles, not
    authentication evidence. A provider must still use the selected client to
    perform and verify its own authenticated identity read. This route is passed
    only to a registered SDK provider factory; it is not a BT-facing DTO.
    """

    exchange_name: str
    provider: str
    environment: str
    client: object = field(repr=False, compare=False)
    account_ref: str = field(repr=False, compare=False)
    identity_binding: Literal["provider_account_id", "authenticated_credential"]
    session_generation: str = field(repr=False, compare=False)
    fencing_epoch: int = field(repr=False, compare=False)
    ledger_binding: object = field(repr=False, compare=False)
    request_receipt_context: ExecutionCredentialRequestContextPort | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        _require_text(self.exchange_name, "exchange_name")
        _require_text(self.provider, "provider", maximum=64)
        if self.provider != self.provider.casefold():
            raise ValueError("provider must use canonical lowercase text")
        _require_text(self.environment, "environment", maximum=128)
        if self.client is None:
            raise ValueError("client must be the selected SDK feed")
        _require_text(self.account_ref, "account_ref")
        if type(self.identity_binding) is not str or self.identity_binding not in _IDENTITY_BINDINGS:
            raise ValueError("identity_binding is unsupported")
        _require_text(self.session_generation, "session_generation")
        if type(self.fencing_epoch) is not int or self.fencing_epoch <= 0:
            raise ValueError("fencing_epoch must be a positive exact int")
        if self.ledger_binding is None:
            raise ValueError("ledger_binding must be an SDK-issued opaque token")
        if self.request_receipt_context is not None and not isinstance(
            self.request_receipt_context, ExecutionCredentialRequestContextPort
        ):
            raise TypeError("request_receipt_context must implement its exact SDK port")


@runtime_checkable
class ExecutionIdentityAssurancePort(Protocol):
    """Route-bound provider identity proof and exact currentness validation."""

    def assure_execution_identity(self) -> ExecutionIdentityAssurance:
        """Return a freshly provider-verified identity or raise unavailable."""
        ...

    def validate_execution_identity(
        self,
        assurance: ExecutionIdentityAssurance,
        *,
        now_utc: datetime,
    ) -> bool:
        """Return exact ``True`` only for this port's exact current proof."""
        ...


@runtime_checkable
class ExecutionIdentityAssuranceProviderFactory(Protocol):
    """Build an identity assurance port for an exact ledger-bound SDK route."""

    def __call__(
        self,
        route: SelectedExecutionIdentityRoute,
        /,
    ) -> ExecutionIdentityAssurancePort | None:
        ...


@runtime_checkable
class ExecutionIdentityAssuranceProviderRegistryPort(Protocol):
    """Exact-route registration surface provided to an SDK plugin registrar."""

    def register(
        self,
        exchange_name: str,
        factory: ExecutionIdentityAssuranceProviderFactory,
        /,
    ) -> None:
        ...


__all__ = [
    "ExecutionIdentityAssurance",
    "ExecutionIdentityAssurancePort",
    "ExecutionCredentialRequestContextPort",
    "ExecutionIdentityEvidenceUnavailable",
    "ExecutionIdentityAssuranceProviderFactory",
    "ExecutionIdentityAssuranceProviderRegistryPort",
    "ExecutionIdentityAssuranceUnavailable",
    "ExecutionIdentitySnapshot",
    "ExecutionIdentitySnapshotRef",
    "ExecutionIdentityScopeRef",
    "ExecutionIdentitySnapshotUnavailable",
    "ExecutionIdentityRouteExpectation",
    "SelectedExecutionIdentityRoute",
]
