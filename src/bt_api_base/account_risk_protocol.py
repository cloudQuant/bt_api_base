"""Typed identity binding for SDK-owned account-risk snapshots.

The snapshot object carries normalized risk facts without ledger identity rows.
Its identity-vector binding is only an SDK-issued currentness link; it is not
provider authentication, execution authorization, or proof by construction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any

from .execution_identity_protocol import ExecutionIdentityScopeRef

_RISK_FACT_KEYS = frozenset(
    {
        "schema_version",
        "baseline_equity",
        "baseline_equity_by_venue",
        "blocked_reasons",
        "clock_domain_id",
        "currency",
        "current_equity",
        "current_equity_by_venue",
        "configured_venues",
        "evidence_errors",
        "generation",
        "fencing_epoch",
        "as_of_monotonic_ns",
        "owner_pid",
        "durable",
        "trading_blocked",
        "evidence_complete",
        "loss_limit_bps",
        "loss_limit_breached",
        "loss_breached_at",
        "loss_amount",
        "loss_limit_amount",
        "loss_bps_observed",
        "peak_loss_bps",
    }
)
ACCOUNT_RISK_FACT_FIELDS = tuple(sorted(_RISK_FACT_KEYS))
_BINDING_CODES = frozenset(
    {
        "execution_identity_vector_binding_unavailable",
        "execution_identity_vector_binding_invalid",
        "execution_identity_vector_binding_not_current",
        "account_risk_source_binding_unavailable",
        "account_risk_snapshot_unavailable",
        "account_risk_snapshot_identity_mismatch",
        "account_risk_snapshot_not_current",
        "account_risk_snapshot_projection_invalid",
    }
)


def _require_text(value: object, name: str, *, maximum: int = 256) -> None:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.isprintable()
    ):
        raise ValueError(f"{name} must be non-empty printable text")
    try:
        if len(value.encode("utf-8", errors="strict")) > maximum:
            raise ValueError(f"{name} exceeds its UTF-8 byte limit")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} must be valid UTF-8") from exc


def _require_code(value: object, name: str, *, maximum: int = 160) -> None:
    _require_text(value, name, maximum=maximum)
    if any(
        not (character.isascii() and (character.isalnum() or character in "_.:-"))
        for character in value
    ):
        raise ValueError(f"{name} must be a finite public code")


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("account-risk mapping keys must be text")
            frozen[key] = _freeze_value(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise TypeError("account-risk facts must contain only immutable JSON values")


class ExecutionIdentityVectorBindingRef:
    """Opaque marker used only for exact SDK-issued binding identity checks."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<opaque SDK execution-identity vector binding>"

    def __reduce__(self):
        raise TypeError("execution identity vector bindings cannot be serialized")


@dataclass(frozen=True)
class ExecutionIdentityVectorBinding:
    """SDK-issued stable digest of exact current snapshots and assurances.

    ``identity_binding_sha256`` preserves the established SDK/Store canonical
    vector digest. ``identity_scope_refs`` are exact opaque ledger-state
    markers aligned with ``exchange_names``; they preserve Store-local
    same-identity fencing without exposing account or strategy labels. Route
    names and SDK session generations identify the vector scope. The binding
    ref is checked by exact object identity at the issuer. None of these fields
    grants write permission or substitutes for provider proof.
    """

    identity_binding_sha256: str = field(repr=False)
    exchange_names: tuple[str, ...]
    identity_scope_refs: tuple[ExecutionIdentityScopeRef, ...] = field(
        repr=False,
        compare=False,
    )
    session_generations: tuple[str, ...] = field(repr=False)
    fencing_epoch: int
    binding_ref: ExecutionIdentityVectorBindingRef = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_text(self.identity_binding_sha256, "identity_binding_sha256", maximum=64)
        if (
            len(self.identity_binding_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.identity_binding_sha256)
        ):
            raise ValueError("identity_binding_sha256 must be lowercase SHA-256 text")
        if type(self.exchange_names) is not tuple or not self.exchange_names:
            raise TypeError("exchange_names must be a non-empty exact tuple")
        if tuple(sorted(self.exchange_names)) != self.exchange_names:
            raise ValueError("exchange_names must be sorted")
        if len(set(self.exchange_names)) != len(self.exchange_names):
            raise ValueError("exchange_names must be unique")
        for name in self.exchange_names:
            _require_text(name, "exchange_name")
        if type(self.identity_scope_refs) is not tuple or len(
            self.identity_scope_refs
        ) != len(self.exchange_names):
            raise TypeError("identity_scope_refs must match exchange_names")
        if any(type(ref) is not ExecutionIdentityScopeRef for ref in self.identity_scope_refs):
            raise TypeError("identity_scope_refs must be exact SDK opaque references")
        if len({id(ref) for ref in self.identity_scope_refs}) != len(
            self.identity_scope_refs
        ):
            raise ValueError("identity_scope_refs must be unique per route")
        if type(self.session_generations) is not tuple or len(
            self.session_generations
        ) != len(self.exchange_names):
            raise TypeError("session_generations must match exchange_names")
        for generation in self.session_generations:
            _require_text(generation, "session_generation")
        if type(self.fencing_epoch) is not int or self.fencing_epoch <= 0:
            raise ValueError("fencing_epoch must be a positive exact int")
        if type(self.binding_ref) is not ExecutionIdentityVectorBindingRef:
            raise TypeError("binding_ref must be an exact opaque SDK reference")


@dataclass(frozen=True)
class AccountRiskSnapshot:
    """Exact immutable risk-facts projection bound to one SDK identity vector.

    ``facts`` contains only the fixed non-identity risk fields. Provider or
    credential ledger rows, journal paths, and owner tokens are rejected and
    are never projected to Backtrader. The issuing SDK must separately validate
    the exact snapshot object and its ``identity_binding`` against the active
    execution session and provider assurance sources.
    """

    facts: Mapping[str, Any] = field(repr=False)
    identity_binding: ExecutionIdentityVectorBinding = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.identity_binding) is not ExecutionIdentityVectorBinding:
            raise TypeError("identity_binding must be an exact SDK vector binding")
        if not isinstance(self.facts, Mapping):
            raise TypeError("facts must be a mapping of non-identity risk fields")
        keys = set(self.facts)
        if keys != _RISK_FACT_KEYS:
            raise ValueError("account-risk facts do not match the exact public schema")
        if type(self.facts["schema_version"]) is not int or self.facts["schema_version"] != 1:
            raise ValueError("unsupported account-risk facts schema")
        for key in ("generation", "fencing_epoch", "as_of_monotonic_ns", "owner_pid"):
            value = self.facts[key]
            if type(value) is not int or value <= 0:
                raise ValueError(f"{key} must be a positive exact int")
        if type(self.facts["clock_domain_id"]) is not str:
            raise TypeError("clock_domain_id must be text")
        _require_text(self.facts["clock_domain_id"], "clock_domain_id")
        for key in ("durable", "trading_blocked", "evidence_complete", "loss_limit_breached"):
            if type(self.facts[key]) is not bool:
                raise TypeError(f"{key} must be an exact bool")
        venues = self.facts["configured_venues"]
        if (
            not isinstance(venues, (list, tuple))
            or any(type(item) is not str for item in venues)
            or any(not item or item != item.strip() or not item.isprintable() for item in venues)
        ):
            raise TypeError("configured_venues must contain exact route strings")
        if tuple(sorted(venues)) != self.identity_binding.exchange_names:
            raise ValueError("risk facts routes do not match the identity binding")
        reasons = self.facts["blocked_reasons"]
        if not isinstance(reasons, (list, tuple)) or any(type(item) is not str for item in reasons):
            raise TypeError("blocked_reasons must contain exact strings")
        for reason in reasons:
            _require_code(reason, "blocked_reason")
        errors = self.facts["evidence_errors"]
        if not isinstance(errors, Mapping) or any(
            type(key) is not str or type(value) is not str for key, value in errors.items()
        ):
            raise TypeError("evidence_errors must be a text mapping")
        for key, value in errors.items():
            _require_text(key, "evidence_error_scope", maximum=320)
            _require_code(value, "evidence_error_code")
        currency = self.facts["currency"]
        if currency is not None and (
            type(currency) is not str or currency != currency.strip().upper()
        ):
            raise ValueError("currency must be canonical text or None")
        for key in (
            "baseline_equity",
            "current_equity",
            "loss_limit_bps",
            "loss_breached_at",
            "loss_amount",
            "loss_limit_amount",
            "loss_bps_observed",
            "peak_loss_bps",
        ):
            value = self.facts[key]
            if value is not None and type(value) not in (str, int, float):
                raise TypeError(f"{key} must be an immutable scalar or None")
        for key in ("baseline_equity_by_venue", "current_equity_by_venue"):
            value = self.facts[key]
            if value is None:
                continue
            if not isinstance(value, Mapping):
                raise TypeError(f"{key} must be a route mapping or None")
            for venue, row in value.items():
                if (
                    type(venue) is not str
                    or venue not in venues
                    or not isinstance(row, Mapping)
                    or set(row) != {"currency", "equity"}
                    or type(row["currency"]) is not str
                    or row["currency"] != row["currency"].strip().upper()
                    or type(row["equity"]) is not str
                ):
                    raise ValueError(f"{key} contains a noncanonical route row")
        if (
            self.facts["generation"] != self.identity_binding.fencing_epoch
            or self.facts["fencing_epoch"] != self.identity_binding.fencing_epoch
        ):
            raise ValueError("risk facts fence does not match the identity binding")
        object.__setattr__(self, "facts", _freeze_value(self.facts))


class AccountRiskSnapshotUnavailable(RuntimeError):
    """Finite failure to bind a risk snapshot to current SDK identity evidence."""

    _CODES = _BINDING_CODES

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in self._CODES else "account_risk_snapshot_unavailable"
        super().__init__(self.code)


__all__ = [
    "ACCOUNT_RISK_FACT_FIELDS",
    "AccountRiskSnapshot",
    "AccountRiskSnapshotUnavailable",
    "ExecutionIdentityVectorBinding",
    "ExecutionIdentityVectorBindingRef",
]
