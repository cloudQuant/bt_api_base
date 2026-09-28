"""Portable, read-only deployment-evidence contracts for Iteration 41.

The contracts deliberately separate *evidence* from trading authority.  An AI
product may create or validate evidence, but cannot create a RiskPermit, send a
gateway command, resume a frozen account, or supply a provider credential.  A
trusted deployment service may evaluate an evidence record with a separate
principal policy and issue an admission receipt, which still does not replace
per-child execution/risk admission.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

DEPLOYMENT_EVIDENCE_SCHEMA_VERSION = "bt-api-deployment-evidence/v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ACTOR_KINDS = frozenset({"agent", "mcp", "operator", "skills"})
_EVIDENCE_PERMISSIONS = frozenset({"read_evidence", "request_review"})
_REVIEW_STATUSES = frozenset({"human_reviewed", "mechanically_mapped", "review_required"})
_MANAGED_LIVE_PRESETS = frozenset({"managed_live_direct", "managed_live_gateway"})
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "passphrase",
    "password",
    "private_key",
    "secret",
    "token",
)


class DeploymentEvidenceError(ValueError):
    """A portable evidence or authorization request violates the wire contract."""


def canonical_json(value: object) -> str:
    """Return canonical redacted JSON with no non-finite numeric values."""
    snapshot = _snapshot_json(value)
    return json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def evidence_sha256(value: object) -> str:
    """Return the SHA-256 digest of the canonical evidence payload."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _identifier(value: object, field_name: str) -> str:
    if type(value) is not str or value != value.strip() or not _IDENTIFIER.fullmatch(value):
        raise DeploymentEvidenceError("invalid " + field_name)
    return value


def _string_collection(value: object, field_name: str) -> tuple[str, ...]:
    """Snapshot a supported finite string collection without accepting mappings."""
    if type(value) not in (tuple, list, set, frozenset):
        raise DeploymentEvidenceError(
            field_name + " must be a tuple, list, set, or frozenset of strings"
        )
    items = tuple(value)
    if any(type(item) is not str for item in items):
        raise DeploymentEvidenceError(field_name + " must contain only strings")
    return items


def _digest(value: object, field_name: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise DeploymentEvidenceError("invalid " + field_name)
    return value


def _timestamp(value: object, field_name: str) -> float:
    if type(value) not in (int, float):
        raise DeploymentEvidenceError("invalid " + field_name)
    try:
        normalized = float(value)
    except OverflowError:
        raise DeploymentEvidenceError("invalid " + field_name) from None
    if not math.isfinite(normalized):
        raise DeploymentEvidenceError("invalid " + field_name)
    return normalized


def _snapshot_json(value: object, path: str = "") -> object:
    """Validate and recursively snapshot JSON data into exact built-in containers."""
    if value is None or type(value) in (str, bool):
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise DeploymentEvidenceError("non-finite JSON value at " + (path or "payload"))
        return value
    if isinstance(value, Mapping):
        snapshot: dict[str, object] = {}
        for key, nested in value.items():
            if type(key) is not str:
                raise DeploymentEvidenceError("JSON object keys must be strings")
            normalized = key.lower().replace("-", "_")
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                raise DeploymentEvidenceError("secret-shaped field is forbidden at " + path + key)
            snapshot[key] = _snapshot_json(nested, path + key + ".")
        return snapshot
    if type(value) in (list, tuple):
        return [
            _snapshot_json(nested, path + str(index) + ".")
            for index, nested in enumerate(value)
        ]
    raise DeploymentEvidenceError("unsupported JSON type at " + (path or "payload"))


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(nested) for key, nested in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(nested) for nested in value)
    return value


@dataclass(frozen=True)
class ActorContext:
    """A caller identity for read-only evidence operations only.

    It is intentionally not a gateway principal and does not carry account
    write, risk, control, freeze, drain, or resume authority.
    """

    actor_id: str
    actor_kind: str
    tenant_id: str
    issued_at: float
    expires_at: float
    permissions: tuple[str, ...] = ("read_evidence",)

    def __post_init__(self) -> None:
        object.__setattr__(self, "actor_id", _identifier(self.actor_id, "actor_id"))
        if type(self.actor_kind) is not str or self.actor_kind not in _ACTOR_KINDS:
            raise DeploymentEvidenceError("invalid actor_kind")
        object.__setattr__(self, "tenant_id", _identifier(self.tenant_id, "tenant_id"))
        issued_at = _timestamp(self.issued_at, "issued_at")
        expires_at = _timestamp(self.expires_at, "expires_at")
        if expires_at <= issued_at:
            raise DeploymentEvidenceError("expires_at must be after issued_at")
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)
        permissions = tuple(
            _identifier(item, "permission")
            for item in _string_collection(self.permissions, "permissions")
        )
        if not permissions or len(set(permissions)) != len(permissions):
            raise DeploymentEvidenceError("permissions must be non-empty and unique")
        if not set(permissions).issubset(_EVIDENCE_PERMISSIONS):
            raise DeploymentEvidenceError(
                "actor context contains an unsupported evidence permission"
            )
        object.__setattr__(self, "permissions", permissions)

    def to_dict(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "actor_kind": self.actor_kind,
            "expires_at": self.expires_at,
            "issued_at": self.issued_at,
            "permissions": list(self.permissions),
            "tenant_id": self.tenant_id,
        }


@dataclass(frozen=True)
class PrincipalPolicy:
    """A local policy for accepting AI evidence, separate from trading rights."""

    policy_id: str
    allowed_actor_kinds: tuple[str, ...]
    allowed_permissions: tuple[str, ...] = ("read_evidence", "request_review")

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        kinds = _string_collection(self.allowed_actor_kinds, "allowed_actor_kinds")
        permissions = _string_collection(self.allowed_permissions, "allowed_permissions")
        if not kinds or not set(kinds).issubset(_ACTOR_KINDS):
            raise DeploymentEvidenceError("invalid allowed_actor_kinds")
        if not permissions or any(not item for item in permissions):
            raise DeploymentEvidenceError("invalid allowed_permissions")
        if not set(permissions).issubset(_EVIDENCE_PERMISSIONS):
            raise DeploymentEvidenceError(
                "principal policy contains an unsupported evidence permission"
            )
        object.__setattr__(self, "allowed_actor_kinds", kinds)
        object.__setattr__(self, "allowed_permissions", permissions)

    def authorize(self, actor: ActorContext, permission: str, now: float) -> None:
        """Fail closed for an expired, incompatible, or over-privileged actor."""
        if not isinstance(actor, ActorContext):
            raise DeploymentEvidenceError("actor context is required")
        if type(permission) is not str:
            raise DeploymentEvidenceError("permission must be a string")
        if permission not in _EVIDENCE_PERMISSIONS:
            raise DeploymentEvidenceError("actor permission is not permitted by policy")
        current_time = _timestamp(now, "now")
        if actor.actor_kind not in self.allowed_actor_kinds:
            raise DeploymentEvidenceError("actor kind is not permitted by policy")
        if current_time < actor.issued_at or current_time >= actor.expires_at:
            raise DeploymentEvidenceError("actor context is expired or not yet valid")
        if permission not in actor.permissions or permission not in self.allowed_permissions:
            raise DeploymentEvidenceError("actor permission is not permitted by policy")


@dataclass(frozen=True)
class StrategyDeploymentEvidence:
    """An immutable, redacted statement about a generated strategy artifact."""

    evidence_id: str
    producer_product: str
    producer_version: str
    producer_commit: str
    producer_wheel_sha256: str
    tenant_id: str
    strategy_id: str
    artifact_sha256: str
    config_effective_digest: str
    review_status: str
    created_at: float
    expires_at: float
    metadata: Mapping[str, object]
    schema_version: str = DEPLOYMENT_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not str
            or self.schema_version != DEPLOYMENT_EVIDENCE_SCHEMA_VERSION
        ):
            raise DeploymentEvidenceError("unsupported evidence schema_version")
        for field_name in (
            "evidence_id",
            "producer_product",
            "producer_version",
            "producer_commit",
            "tenant_id",
            "strategy_id",
        ):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        for field_name in ("producer_wheel_sha256", "artifact_sha256", "config_effective_digest"):
            object.__setattr__(self, field_name, _digest(getattr(self, field_name), field_name))
        if type(self.review_status) is not str or self.review_status not in _REVIEW_STATUSES:
            raise DeploymentEvidenceError("invalid review_status")
        created_at = _timestamp(self.created_at, "created_at")
        expires_at = _timestamp(self.expires_at, "expires_at")
        if expires_at <= created_at:
            raise DeploymentEvidenceError("evidence expires_at must be after created_at")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "expires_at", expires_at)
        if not isinstance(self.metadata, Mapping):
            raise DeploymentEvidenceError("metadata must be an object")
        metadata_snapshot = _snapshot_json(self.metadata)
        if type(metadata_snapshot) is not dict:
            raise DeploymentEvidenceError("metadata must be an object")
        object.__setattr__(
            self,
            "metadata",
            _freeze_json(
                json.loads(
                    json.dumps(
                        metadata_snapshot,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                        allow_nan=False,
                    )
                )
            ),
        )

    @property
    def digest(self) -> str:
        return evidence_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "config_effective_digest": self.config_effective_digest,
            "created_at": self.created_at,
            "evidence_id": self.evidence_id,
            "expires_at": self.expires_at,
            "metadata": _to_mutable_json(self.metadata),
            "producer": {
                "commit": self.producer_commit,
                "product": self.producer_product,
                "version": self.producer_version,
                "wheel_sha256": self.producer_wheel_sha256,
            },
            "review_status": self.review_status,
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> StrategyDeploymentEvidence:
        """Load only the exact published wire shape, rejecting silent extensions."""
        expected = {
            "artifact_sha256",
            "config_effective_digest",
            "created_at",
            "evidence_id",
            "expires_at",
            "metadata",
            "producer",
            "review_status",
            "schema_version",
            "strategy_id",
            "tenant_id",
        }
        if not isinstance(raw, Mapping) or any(type(key) is not str for key in raw):
            raise DeploymentEvidenceError("invalid evidence wire fields")
        if set(raw) != expected or not isinstance(raw.get("producer"), Mapping):
            raise DeploymentEvidenceError("invalid evidence wire fields")
        producer = raw["producer"]
        if any(type(key) is not str for key in producer):
            raise DeploymentEvidenceError("invalid producer wire fields")
        if set(producer) != {"commit", "product", "version", "wheel_sha256"}:
            raise DeploymentEvidenceError("invalid producer wire fields")
        return cls(
            evidence_id=raw["evidence_id"],
            producer_product=producer["product"],
            producer_version=producer["version"],
            producer_commit=producer["commit"],
            producer_wheel_sha256=producer["wheel_sha256"],
            tenant_id=raw["tenant_id"],
            strategy_id=raw["strategy_id"],
            artifact_sha256=raw["artifact_sha256"],
            config_effective_digest=raw["config_effective_digest"],
            review_status=raw["review_status"],
            created_at=raw["created_at"],
            expires_at=raw["expires_at"],
            metadata=raw["metadata"],
            schema_version=raw["schema_version"],
        )


@dataclass(frozen=True)
class DeploymentAdmissionReceipt:
    """A separately issued deployment receipt, never an execution RiskPermit."""

    receipt_id: str
    evidence_digest: str
    tenant_id: str
    strategy_id: str
    config_effective_digest: str
    approved_by: str
    runtime_mode: str
    runtime_preset: str
    issued_at: float
    expires_at: float

    def __post_init__(self) -> None:
        for field_name in ("receipt_id", "tenant_id", "strategy_id", "approved_by"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        for field_name in ("evidence_digest", "config_effective_digest"):
            object.__setattr__(self, field_name, _digest(getattr(self, field_name), field_name))
        if (
            type(self.runtime_mode) is not str
            or self.runtime_mode != "live"
            or type(self.runtime_preset) is not str
            or self.runtime_preset not in _MANAGED_LIVE_PRESETS
        ):
            raise DeploymentEvidenceError("admission receipts bind only a managed live runtime")
        issued_at = _timestamp(self.issued_at, "issued_at")
        expires_at = _timestamp(self.expires_at, "expires_at")
        if expires_at <= issued_at:
            raise DeploymentEvidenceError("receipt expires_at must be after issued_at")
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)

    def validates_evidence(self, evidence: StrategyDeploymentEvidence, now: float) -> bool:
        """Check binding and review state; callers still need per-child risk permits."""
        if type(evidence) is not StrategyDeploymentEvidence:
            return False
        current_time = _timestamp(now, "now")
        return bool(
            evidence.review_status in {"human_reviewed", "mechanically_mapped"}
            and evidence.created_at <= self.issued_at
            and self.issued_at <= current_time
            and current_time < self.expires_at
            and current_time < evidence.expires_at
            and self.evidence_digest == evidence.digest
            and self.tenant_id == evidence.tenant_id
            and self.strategy_id == evidence.strategy_id
            and self.config_effective_digest == evidence.config_effective_digest
        )


def _to_mutable_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _to_mutable_json(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_to_mutable_json(nested) for nested in value]
    return value


__all__ = [
    "ActorContext",
    "DEPLOYMENT_EVIDENCE_SCHEMA_VERSION",
    "DeploymentAdmissionReceipt",
    "DeploymentEvidenceError",
    "PrincipalPolicy",
    "StrategyDeploymentEvidence",
    "canonical_json",
    "evidence_sha256",
]
