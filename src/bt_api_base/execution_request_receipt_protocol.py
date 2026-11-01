"""Provider-neutral contracts for exact authenticated request observations.

Constructing either DTO does not prove dispatch, remote response, credential
acceptance, or account identity. The provider's physical transport must retain
the exact observation object for one completed request/response and pass that
object directly to its trusted receipt issuer. The issuer returns the receipt
to that same caller, binds expiry using its own provider/runtime policy, and
retains the exact observation/receipt identities. Copying or recreating either
DTO is not evidence.

The SDK execution-session owner must independently validate the selected route,
credential lineage, owner generation, active lease, session generation, and
fencing epoch. The marker objects contain no payload and are not credentials,
hashes, wire identifiers, signatures, or serialized proof. REST and WSS
observations have separate transport labels and cannot substitute for one
another. This protocol does not grant execution authority or prove a remote
account ID.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import ClassVar, Protocol, runtime_checkable


class ExecutionCredentialRequestTransport(str, Enum):
    """Transport on which the provider-owned request was observed."""

    REST = "rest"
    WSS = "wss"


class ExecutionCredentialRequestSuccessCategory(str, Enum):
    """Finite successful outcome supported by this request-receipt contract."""

    AUTHENTICATED_RESPONSE_ACCEPTED = "authenticated_response_accepted"


_UNAVAILABLE_CODES = frozenset(
    {
        "execution_credential_request_receipt_unavailable",
        "execution_credential_request_transport_observation_invalid",
        "execution_credential_request_receipt_policy_unavailable",
        "execution_credential_request_receipt_issuer_unavailable",
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


class ExecutionCredentialRequestOpaqueRef:
    """Empty identity marker; trusted owners retain its meaning out of band."""

    __slots__ = ()

    def __reduce__(self):
        raise TypeError("execution credential request references cannot be serialized")

    def __repr__(self) -> str:
        return "<ExecutionCredentialRequestOpaqueRef>"


def _require_opaque_reference(value: object, field_name: str) -> None:
    """Require an empty marker; issuer provenance still needs validation."""

    if type(value) is not ExecutionCredentialRequestOpaqueRef:
        raise TypeError(f"{field_name} must be an exact opaque reference marker")


class ExecutionCredentialRequestReceiptUnavailable(RuntimeError):
    """Finite failure to issue a trusted request receipt."""

    _CODES = _UNAVAILABLE_CODES

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in self._CODES
            else "execution_credential_request_receipt_unavailable"
        )
        super().__init__(self.code)


@dataclass(frozen=True, eq=False, repr=False)
class ExecutionCredentialRequestTransportObservation:
    """Provider transport's metadata for one completed physical exchange.

    The provider transport must create this exact object only after observing
    the response for the physical request identified by ``request_ref``. The
    request and response markers are local empty references, not remote wire
    identifiers. An issuer must accept only the exact observation object it
    registered from that transport callback; structural copies and caller-
    constructed observations are not evidence.

    The observation contains no raw response, status headers, signatures,
    credentials, hashes, or account identity. The success category is a
    provider classification of the exact response for the declared operation.
    """

    exchange_name: str
    provider: str
    environment: str
    transport: ExecutionCredentialRequestTransport
    operation: str
    request_ref: str
    physical_request_ref: ExecutionCredentialRequestOpaqueRef = field(
        repr=False, compare=False
    )
    physical_response_ref: ExecutionCredentialRequestOpaqueRef = field(
        repr=False, compare=False
    )
    credential_lineage_ref: ExecutionCredentialRequestOpaqueRef = field(
        repr=False, compare=False
    )
    selected_route_ref: ExecutionCredentialRequestOpaqueRef = field(
        repr=False, compare=False
    )
    owner_generation_ref: ExecutionCredentialRequestOpaqueRef = field(
        repr=False, compare=False
    )
    owner_lease_ref: ExecutionCredentialRequestOpaqueRef = field(
        repr=False, compare=False
    )
    session_generation: str = field(repr=False, compare=False)
    fencing_epoch: int = field(repr=False, compare=False)
    success_category: ExecutionCredentialRequestSuccessCategory
    schema: ClassVar[str] = "bt_api.execution_credential_request_observation.v1"

    def __post_init__(self) -> None:
        _require_text(self.exchange_name, "exchange_name")
        _require_text(self.provider, "provider", maximum=64)
        if self.provider != self.provider.casefold():
            raise ValueError("provider must use canonical lowercase text")
        _require_text(self.environment, "environment", maximum=128)
        if type(self.transport) is not ExecutionCredentialRequestTransport:
            raise TypeError("transport must be an exact ExecutionCredentialRequestTransport")
        _require_text(self.operation, "operation", maximum=128)
        _require_text(self.request_ref, "request_ref", maximum=128)
        _require_opaque_reference(self.physical_request_ref, "physical_request_ref")
        _require_opaque_reference(self.physical_response_ref, "physical_response_ref")
        _require_opaque_reference(self.credential_lineage_ref, "credential_lineage_ref")
        _require_opaque_reference(self.selected_route_ref, "selected_route_ref")
        _require_opaque_reference(self.owner_generation_ref, "owner_generation_ref")
        _require_opaque_reference(self.owner_lease_ref, "owner_lease_ref")
        opaque_refs = (
            self.physical_request_ref,
            self.physical_response_ref,
            self.credential_lineage_ref,
            self.selected_route_ref,
            self.owner_generation_ref,
            self.owner_lease_ref,
        )
        if any(
            left is right
            for index, left in enumerate(opaque_refs)
            for right in opaque_refs[index + 1 :]
        ):
            raise ValueError("opaque receipt references must have distinct owner identities")
        _require_text(self.session_generation, "session_generation", maximum=128)
        if type(self.fencing_epoch) is not int or self.fencing_epoch <= 0:
            raise ValueError("fencing_epoch must be a positive exact int")
        if (
            type(self.success_category) is not ExecutionCredentialRequestSuccessCategory
            or self.success_category
            is not ExecutionCredentialRequestSuccessCategory.AUTHENTICATED_RESPONSE_ACCEPTED
        ):
            raise ValueError("success_category is unsupported")

    def __reduce__(self):
        """Observations are live transport references, not portable evidence."""

        raise TypeError("execution credential transport observations cannot be serialized")

    def __repr__(self) -> str:
        return (
            "<ExecutionCredentialRequestTransportObservation(provider transport; "
            "validation required)>"
        )


@dataclass(frozen=True, eq=False, repr=False)
class ExecutionCredentialRequestReceipt:
    """Provider-issued, policy-bounded receipt for one exact observation.

    ``issued_at_utc`` and ``expires_at_utc`` are assigned by the trusted
    provider/runtime issuer. This base contract requires a finite expiry after
    issuance but does not select a maximum lifetime. The provider/runtime
    policy must supply an acceptable finite lifetime, and the issuer must fail
    closed if its policy or trusted clock is unavailable.

    ``observation`` is retained by exact object identity, not reconstructed
    from caller-provided fields. A valid issuer registry must prove that it is
    the same observation returned by the physical transport callback.
    """

    observation: ExecutionCredentialRequestTransportObservation = field(
        repr=False, compare=False
    )
    receipt_ref: ExecutionCredentialRequestOpaqueRef = field(repr=False, compare=False)
    provider_issuer_ref: ExecutionCredentialRequestOpaqueRef = field(
        repr=False, compare=False
    )
    expiry_policy_ref: ExecutionCredentialRequestOpaqueRef = field(
        repr=False, compare=False
    )
    issued_at_utc: datetime
    expires_at_utc: datetime

    schema: ClassVar[str] = "bt_api.execution_credential_request_receipt.v1"

    def __post_init__(self) -> None:
        if type(self.observation) is not ExecutionCredentialRequestTransportObservation:
            raise TypeError("observation must be an exact provider transport observation")
        _require_opaque_reference(self.receipt_ref, "receipt_ref")
        _require_opaque_reference(self.provider_issuer_ref, "provider_issuer_ref")
        _require_opaque_reference(self.expiry_policy_ref, "expiry_policy_ref")
        receipt_refs = (
            self.receipt_ref,
            self.provider_issuer_ref,
            self.expiry_policy_ref,
        )
        observation_refs = (
            self.observation.physical_request_ref,
            self.observation.physical_response_ref,
            self.observation.credential_lineage_ref,
            self.observation.selected_route_ref,
            self.observation.owner_generation_ref,
            self.observation.owner_lease_ref,
        )
        all_refs = receipt_refs + observation_refs
        if any(
            left is right
            for index, left in enumerate(all_refs)
            for right in all_refs[index + 1 :]
        ):
            raise ValueError("receipt references must have distinct owner identities")
        issued = _require_utc(self.issued_at_utc, "issued_at_utc")
        expires = _require_utc(self.expires_at_utc, "expires_at_utc")
        if expires <= issued:
            raise ValueError("expires_at_utc must follow issuer time")

    def __reduce__(self):
        """Receipts are live issuer/session references, not portable evidence."""

        raise TypeError("execution credential request receipts cannot be serialized")

    def __repr__(self) -> str:
        return "<ExecutionCredentialRequestReceipt(provider-owned; validation required)>"


@runtime_checkable
class ExecutionCredentialRequestReceiptIssuerPort(Protocol):
    """Provider-owned issue-and-validate seam for one physical exchange.

    The transport adapter returns its provider response together with the
    exact :class:`ExecutionCredentialRequestTransportObservation` created in
    that physical request/response callback. The adapter passes that object to
    ``issue_execution_credential_request_receipt`` and returns the resulting
    receipt directly alongside the same provider response to its caller. There
    is no global/latest-receipt lookup or later reconstruction.

    The issuer accepts only the exact observation object registered by its
    trusted provider transport, issues it once, and uses its own trusted clock
    and configured provider/runtime expiry policy. If the transport observation,
    clock, selected route, owner lease, or finite expiry policy cannot be
    verified, issuance raises
    :class:`ExecutionCredentialRequestReceiptUnavailable`.

    Validation uses the issuer's own trusted clock; callers cannot provide a
    stale ``now`` value. The provider validator must still compare the exact
    observation and all expected bindings. The SDK execution-session owner
    separately revalidates the current route/owner lease/fence.
    """

    def issue_execution_credential_request_receipt(
        self,
        observation: ExecutionCredentialRequestTransportObservation,
        /,
    ) -> ExecutionCredentialRequestReceipt:
        """Issue one receipt for the exact registered transport observation.

        The method must return the exact receipt to the same provider caller
        that holds the response for this attempt. It must not accept caller
        timestamps, expiry values, response bodies, credentials, or hashes.
        """

        ...

    def validate_execution_credential_request_receipt(
        self,
        receipt: ExecutionCredentialRequestReceipt,
        *,
        expected_observation: ExecutionCredentialRequestTransportObservation,
        expected_exchange_name: str,
        expected_provider: str,
        expected_environment: str,
        expected_transport: ExecutionCredentialRequestTransport,
        expected_operation: str,
        expected_credential_lineage_ref: ExecutionCredentialRequestOpaqueRef,
        expected_selected_route_ref: ExecutionCredentialRequestOpaqueRef,
        expected_owner_generation_ref: ExecutionCredentialRequestOpaqueRef,
        expected_owner_lease_ref: ExecutionCredentialRequestOpaqueRef,
        expected_session_generation: str,
        expected_fencing_epoch: int,
    ) -> bool:
        """Return exact ``True`` only if this issuer's trusted clock says current."""

        ...


__all__ = [
    "ExecutionCredentialRequestReceipt",
    "ExecutionCredentialRequestOpaqueRef",
    "ExecutionCredentialRequestReceiptIssuerPort",
    "ExecutionCredentialRequestSuccessCategory",
    "ExecutionCredentialRequestReceiptUnavailable",
    "ExecutionCredentialRequestTransportObservation",
    "ExecutionCredentialRequestTransport",
]
