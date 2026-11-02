"""Neutral contracts for exact-route SDK managed runtime composition.

These values carry route selection and opaque SDK-owned runtime/authorization
objects across the parent SDK/provider boundary. They do not prove that a
runtime is ready, grant write permission, or identify any native provider
objects. Provider code must validate the exact runtime/session/feed and keep
provider-native state inside its own package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from typing import Callable, Literal, Optional, Protocol, runtime_checkable

from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.provider_configuration_protocol import ProviderConfiguration

ManagedRuntimeAccessMode = Literal["read_only", "managed_execution"]
RuntimeThreadAffinity = Literal["any_thread", "owner_thread"]

_ERROR_CODES = frozenset(
    {
        "MANAGED_RUNTIME_ROUTE_INVALID",
        "MANAGED_RUNTIME_CONFIGURATION_INVALID",
        "MANAGED_RUNTIME_BINDING_UNAVAILABLE",
        "MANAGED_RUNTIME_BINDING_ROUTE_MISMATCH",
        "MANAGED_RUNTIME_ACCESS_MODE_INVALID",
        "MANAGED_RUNTIME_AUTHORIZATION_SOURCE_UNAVAILABLE",
        "MANAGED_RUNTIME_OPERATOR_GRANT_INVALID",
        "MANAGED_RUNTIME_OPERATOR_GRANT_REJECTED",
        "MANAGED_RUNTIME_FACTORY_INVALID",
        "MANAGED_RUNTIME_WRITE_UNAVAILABLE",
        "MANAGED_RUNTIME_BINDING_UNVERIFIED",
        "MANAGED_RUNTIME_FACADE_INVALID",
        "MANAGED_RUNTIME_PROVIDER_REGISTRATION_FAILED",
        "MANAGED_RUNTIME_COMPOSITION_FAILED",
        "MANAGED_RUNTIME_CLOSE_FAILED",
        "MANAGED_RUNTIME_THREAD_CONSTRAINT_INVALID",
        "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED",
        "MANAGED_RUNTIME_WRONG_THREAD",
    }
)


class ManagedRuntimeContractError(ValueError):
    """Finite, non-sensitive error from neutral managed-runtime DTOs."""

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in _ERROR_CODES
            else "MANAGED_RUNTIME_FACTORY_INVALID"
        )
        super().__init__(self.code)


@dataclass(frozen=True, eq=False, repr=False)
class RuntimeThreadConstraint:
    """Provider-owned declaration and check for runtime thread affinity.

    ``any_thread`` may be selected only when the provider guarantees that all
    operations covered by its composition, including close, are safe from any
    calling thread. ``owner_thread`` requires a synchronous verifier that
    checks the *actual current thread* against the provider's captured owner.
    The verifier accepts no caller-supplied thread id or token, and a mailbox
    call marshalled to the owner thread must not be used to claim that the
    original caller was on that thread.

    Omitting this contract means unknown and must be treated as unavailable.
    """

    affinity: RuntimeThreadAffinity
    verify_current_thread: Optional[Callable[[], bool]] = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if type(self.affinity) is not str or self.affinity not in {
            "any_thread",
            "owner_thread",
        }:
            raise ManagedRuntimeContractError(
                "MANAGED_RUNTIME_THREAD_CONSTRAINT_INVALID"
            )
        if self.affinity == "any_thread":
            if self.verify_current_thread is not None:
                raise ManagedRuntimeContractError(
                    "MANAGED_RUNTIME_THREAD_CONSTRAINT_INVALID"
                )
        elif not callable(self.verify_current_thread):
            raise ManagedRuntimeContractError(
                "MANAGED_RUNTIME_THREAD_CONSTRAINT_INVALID"
            )

    def assert_current_thread(self) -> None:
        """Return only for an explicit any-thread contract or exact owner match."""

        if self.affinity == "any_thread":
            return
        verifier = self.verify_current_thread
        if not callable(verifier):
            raise ManagedRuntimeContractError(
                "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED"
            )
        try:
            result = verifier()
        except Exception:
            raise ManagedRuntimeContractError(
                "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED"
            ) from None
        if type(result) is not bool:
            raise ManagedRuntimeContractError(
                "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED"
            )
        if result is not True:
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_WRONG_THREAD")

    def __repr__(self) -> str:
        return "<runtime thread constraint {!r}>".format(self.affinity)


class ReadOnlyRouteOwnerCloseError(RuntimeError):
    """Finite signal that a route owner's one close attempt was unconfirmed.

    Provider factories raise this only when cleanup of an internally owned
    read-only route fails. The parent composer maps it to its public close
    failure code without importing a provider package or exposing exception
    details. It does not authorize a retry.
    """

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__("ROUTE_OWNER_CLOSE_UNCONFIRMED")


def _require_text(value: object, code: str) -> None:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.isprintable()
    ):
        raise ManagedRuntimeContractError(code)
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError:
        raise ManagedRuntimeContractError(code) from None
    if size > 256:
        raise ManagedRuntimeContractError(code)


@dataclass(frozen=True, eq=False, repr=False)
class ManagedRuntimeBinding:
    """Opaque carrier for an owner and exact neutral route.

    The value itself is not proof of readiness or route ownership. A selected
    provider must check route identity for a read-only route and check the live
    runtime/session/feed for managed execution. Route verification does not
    imply connection, account readiness, or write authority.
    """

    exchange_name: str
    environment: str
    runtime_owner: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_text(self.exchange_name, "MANAGED_RUNTIME_ROUTE_INVALID")
        _require_text(self.environment, "MANAGED_RUNTIME_ROUTE_INVALID")
        if self.runtime_owner is None:
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_BINDING_UNAVAILABLE")

    def __repr__(self) -> str:
        return (
            "ManagedRuntimeBinding(exchange_name={!r}, environment={!r}, "
            "runtime_owner=<opaque>)"
        ).format(self.exchange_name, self.environment)


@dataclass(frozen=True, repr=False)
class OperatorWriteGrant:
    """Neutral operator bounds, without issuer proof or SDK write authority.

    A provider must bind these exact run/route/symbol/time/count/notional
    bounds to its existing per-write gates and one-shot consumption path. This
    object cannot create Basic/Risk authorization or authorize dispatch.
    """

    run_id: str
    mode: Literal["paper", "live"]
    provider_ref: str
    environment: str
    symbols: tuple[str, ...]
    expires_at_utc: str
    max_order_count: int
    max_order_notional: float
    allow_live_write: bool = False

    def __post_init__(self) -> None:
        for name in ("run_id", "provider_ref", "environment"):
            _require_text(getattr(self, name), "MANAGED_RUNTIME_OPERATOR_GRANT_INVALID")
        if type(self.mode) is not str or self.mode not in {"paper", "live"}:
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_OPERATOR_GRANT_INVALID")
        if type(self.symbols) is not tuple or not self.symbols:
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_OPERATOR_GRANT_INVALID")
        for symbol in self.symbols:
            _require_text(symbol, "MANAGED_RUNTIME_OPERATOR_GRANT_INVALID")
        if len(set(self.symbols)) != len(self.symbols):
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_OPERATOR_GRANT_INVALID")
        _require_text(self.expires_at_utc, "MANAGED_RUNTIME_OPERATOR_GRANT_INVALID")
        if not self.expires_at_utc.endswith("Z"):
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_OPERATOR_GRANT_INVALID")
        try:
            expiry = datetime.fromisoformat(self.expires_at_utc[:-1] + "+00:00")
        except (ValueError, OverflowError):
            raise ManagedRuntimeContractError(
                "MANAGED_RUNTIME_OPERATOR_GRANT_INVALID"
            ) from None
        if expiry.tzinfo is None or expiry.utcoffset() != timezone.utc.utcoffset(expiry):
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_OPERATOR_GRANT_INVALID")
        if type(self.max_order_count) is not int or self.max_order_count <= 0:
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_OPERATOR_GRANT_INVALID")
        if (
            type(self.max_order_notional) not in (int, float)
            or isinstance(self.max_order_notional, bool)
            or self.max_order_notional <= 0
        ):
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_OPERATOR_GRANT_INVALID")
        try:
            finite_notional = isfinite(float(self.max_order_notional))
        except (OverflowError, ValueError):
            finite_notional = False
        if not finite_notional or type(self.allow_live_write) is not bool:
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_OPERATOR_GRANT_INVALID")

    def __repr__(self) -> str:
        return "<operator write grant bounds run_id={!r} mode={!r}>".format(
            self.run_id,
            self.mode,
        )


@dataclass(frozen=True, eq=False, repr=False)
class SelectedManagedRuntimeRoute:
    """Provider-only input for one exact configured runtime route."""

    exchange_name: str
    environment: str
    access_mode: ManagedRuntimeAccessMode
    configuration: ProviderConfiguration = field(repr=False, compare=False)
    runtime_binding: ManagedRuntimeBinding = field(repr=False, compare=False)
    operator_grant: Optional[OperatorWriteGrant] = field(repr=False, compare=False)
    authorization_source: Optional[object] = field(repr=False, compare=False)
    # Parent SDK supplies its exact class for provider-owned read-only binding.
    api_factory: Optional[Callable[..., object]] = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.api_factory is not None and type(self.api_factory) is not type:
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_FACTORY_INVALID")
        _require_text(self.exchange_name, "MANAGED_RUNTIME_ROUTE_INVALID")
        _require_text(self.environment, "MANAGED_RUNTIME_ROUTE_INVALID")
        if type(self.access_mode) is not str or self.access_mode not in {
            "read_only",
            "managed_execution",
        }:
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_ACCESS_MODE_INVALID")
        if type(self.configuration) is not ProviderConfiguration:
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_CONFIGURATION_INVALID")
        if type(self.runtime_binding) is not ManagedRuntimeBinding:
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_BINDING_UNAVAILABLE")
        if (
            self.configuration.exchange_name != self.exchange_name
            or self.configuration.environment != self.environment
            or self.runtime_binding.exchange_name != self.exchange_name
            or self.runtime_binding.environment != self.environment
        ):
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_BINDING_ROUTE_MISMATCH")
        if self.access_mode == "read_only":
            if self.operator_grant is not None or self.authorization_source is not None:
                raise ManagedRuntimeContractError("MANAGED_RUNTIME_ACCESS_MODE_INVALID")
            return
        if type(self.operator_grant) is not OperatorWriteGrant:
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_OPERATOR_GRANT_INVALID")
        source = self.authorization_source
        if (
            source is None
            or type(source) in (bool, str, bytes, int, float)
            or source is self.operator_grant
            or source is self.runtime_binding
        ):
            raise ManagedRuntimeContractError(
                "MANAGED_RUNTIME_AUTHORIZATION_SOURCE_UNAVAILABLE"
            )

    def __repr__(self) -> str:
        return "<selected managed runtime route {!r} mode={!r}>".format(
            self.exchange_name,
            self.access_mode,
        )


@dataclass(frozen=True, repr=False)
class ManagedRuntimeProviderProduct:
    """Provider result consumed by parent composition, never returned directly.

    ``runtime_binding_verified`` records that the provider checked exact live
    runtime/session/feed binding. ``route_binding_verified`` records only an
    exact provider route/config/feed binding and is sufficient for a stateless
    read-only provider route; it does not assert connection or account
    readiness. ``operator_grant_verified`` is relevant only to managed mode
    and requires the exact bounds to be installed in the provider's existing
    per-write gate. None of these flags is authorization.

    ``serve_route`` is an optional synchronous, single-step owner pump. The
    parent composition invokes it only when the host explicitly calls
    ``serve_once``; providers must enforce their exact owner-thread rule,
    perform one bounded maintenance step, and must not create a background
    polling thread or retry failed work. Exceptions report that pump attempt
    to the caller; close remains a separate one-shot lifecycle operation.

    ``thread_constraint`` is required before a Backtrader managed host can
    safely start. ``None`` means unknown. A provider may choose ``any_thread``
    only when serving and closing are safe from any thread; an owner-thread
    provider supplies a verifier that checks the actual current thread.
    """

    api: object = field(repr=False, compare=False)
    close_route: Callable[[], None] = field(repr=False, compare=False)
    runtime_binding_verified: bool = False
    operator_grant_verified: bool = False
    route_binding_verified: bool = False
    serve_route: Callable[[], object] | None = field(default=None, repr=False, compare=False)
    thread_constraint: Optional[RuntimeThreadConstraint] = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if (
            self.api is None
            or not callable(self.close_route)
            or type(self.runtime_binding_verified) is not bool
            or type(self.operator_grant_verified) is not bool
            or type(self.route_binding_verified) is not bool
            or (self.serve_route is not None and not callable(self.serve_route))
            or (
                self.thread_constraint is not None
                and type(self.thread_constraint) is not RuntimeThreadConstraint
            )
        ):
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_FACTORY_INVALID")


@dataclass(frozen=True, eq=False, repr=False)
class SelectedReadOnlyRoute:
    """Provider-only input for route-bound read-only owner construction.

    The parent SDK supplies the exact secret-free configuration and its own
    BtApi class. Providers consume their opaque configuration handle and keep
    all credential values and native objects inside the SDK/provider boundary.
    This input carries no runtime readiness or write authorization.
    """

    exchange_name: str
    configuration: ProviderConfiguration = field(repr=False, compare=False)
    api_factory: Callable[..., object] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_text(self.exchange_name, "MANAGED_RUNTIME_ROUTE_INVALID")
        if type(self.configuration) is not ProviderConfiguration:
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_CONFIGURATION_INVALID")
        if self.configuration.exchange_name != self.exchange_name:
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_BINDING_ROUTE_MISMATCH")
        if type(self.api_factory) is not type or not callable(self.api_factory):
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_FACTORY_INVALID")

    def __repr__(self) -> str:
        return "<selected read-only SDK route {!r}>".format(self.exchange_name)


@dataclass(frozen=True, repr=False)
class ReadOnlyRouteOwnerProduct:
    """Provider result for one stateless route; never returned to Backtrader.

    ``route_binding_verified`` means only that this provider checked its exact
    configuration, endpoint, and client route. It is not a connected-session,
    authenticated-account, readiness, or write-capability assertion.
    ``thread_constraint`` separately states whether the provider guarantees
    any-thread safety or requires a provider-verifiable owner thread. Omitting
    it leaves thread affinity unknown.
    """

    exchange_name: str
    api: object = field(repr=False, compare=False)
    close_route: Callable[[], None] = field(repr=False, compare=False)
    route_binding_verified: bool = False
    thread_constraint: Optional[RuntimeThreadConstraint] = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        _require_text(self.exchange_name, "MANAGED_RUNTIME_ROUTE_INVALID")
        if (
            self.api is None
            or not callable(self.close_route)
            or type(self.route_binding_verified) is not bool
            or (
                self.thread_constraint is not None
                and type(self.thread_constraint) is not RuntimeThreadConstraint
            )
        ):
            raise ManagedRuntimeContractError("MANAGED_RUNTIME_FACTORY_INVALID")


@runtime_checkable
class ManagedRuntimeFactory(Protocol):
    """Construct one provider-owned facade for an exact selected route."""

    def __call__(
        self,
        route: SelectedManagedRuntimeRoute,
        /,
    ) -> ManagedRuntimeProviderProduct:
        ...


@runtime_checkable
class ManagedRuntimeFactoryRegistryPort(Protocol):
    """Neutral registration port consumed by provider packages."""

    def register(self, exchange_name: str, factory: ManagedRuntimeFactory) -> None:
        ...


@runtime_checkable
class ReadOnlyRouteOwnerFactory(Protocol):
    """Construct one exact provider-owned stateless route owner."""

    def __call__(
        self,
        route: SelectedReadOnlyRoute,
        /,
    ) -> ReadOnlyRouteOwnerProduct:
        ...


@runtime_checkable
class ReadOnlyRouteOwnerRegistryPort(Protocol):
    """Registration port implemented by the parent SDK route composer."""

    def register(self, exchange_name: str, factory: ReadOnlyRouteOwnerFactory) -> None:
        ...


__all__ = [
    "ManagedRuntimeAccessMode",
    "ManagedRuntimeBinding",
    "ManagedRuntimeContractError",
    "ManagedRuntimeFactory",
    "ManagedRuntimeFactoryRegistryPort",
    "ManagedRuntimeProviderProduct",
    "OperatorWriteGrant",
    "RuntimeThreadAffinity",
    "RuntimeThreadConstraint",
    "ReadOnlyRouteOwnerFactory",
    "ReadOnlyRouteOwnerCloseError",
    "ReadOnlyRouteOwnerProduct",
    "ReadOnlyRouteOwnerRegistryPort",
    "SelectedReadOnlyRoute",
    "SelectedManagedRuntimeRoute",
]
