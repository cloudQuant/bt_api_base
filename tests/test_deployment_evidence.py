from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from bt_api_base.deployment_evidence import (
    ActorContext,
    DeploymentAdmissionReceipt,
    DeploymentEvidenceError,
    PrincipalPolicy,
    StrategyDeploymentEvidence,
)


class _EvilStr(str):
    """A str subclass that compares equal to any value with one chosen hash."""

    def __new__(cls, value: str, hash_target: str):
        instance = super().__new__(cls, value)
        instance._forced_hash = hash(hash_target)
        return instance

    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return self._forced_hash


class _SwitchingDict(dict):
    """A hostile mapping whose safe iterator output changes after two reads."""

    def __init__(self) -> None:
        super().__init__({"api_key": "synthetic-placeholder"})
        self.items_calls = 0

    def items(self):
        self.items_calls += 1
        if self.items_calls <= 2:
            return (("source", "offline"),)
        return super().items()


def _evidence(review_status: str = "review_required") -> StrategyDeploymentEvidence:
    return StrategyDeploymentEvidence(
        evidence_id="evidence-1",
        producer_product="backtrader-agent",
        producer_version="0.2.0",
        producer_commit="commit-1",
        producer_wheel_sha256="a" * 64,
        tenant_id="tenant-a",
        strategy_id="strategy-a",
        artifact_sha256="b" * 64,
        config_effective_digest="c" * 64,
        review_status=review_status,
        created_at=100.0,
        expires_at=200.0,
        metadata={"source": "offline"},
    )


def test_evidence_round_trip_is_immutable_and_deterministic() -> None:
    evidence = _evidence()
    decoded = StrategyDeploymentEvidence.from_dict(evidence.to_dict())
    assert decoded == evidence
    assert decoded.digest == evidence.digest
    with pytest.raises(TypeError):
        evidence.metadata["source"] = "tampered"  # type: ignore[index]


@pytest.mark.parametrize(
    "metadata",
    (
        {"api_key": "blocked"},
        {"nested": {"password": "blocked"}},
        {"value": float("nan")},
    ),
)
def test_evidence_rejects_secrets_and_non_finite_values(metadata: dict) -> None:
    with pytest.raises(DeploymentEvidenceError):
        StrategyDeploymentEvidence(
            evidence_id="evidence-1",
            producer_product="backtrader-agent",
            producer_version="0.2.0",
            producer_commit="commit-1",
            producer_wheel_sha256="a" * 64,
            tenant_id="tenant-a",
            strategy_id="strategy-a",
            artifact_sha256="b" * 64,
            config_effective_digest="c" * 64,
            review_status="review_required",
            created_at=100.0,
            expires_at=200.0,
            metadata=metadata,
        )


def test_actor_policy_cannot_be_promoted_to_execution_or_control_authority() -> None:
    actor = ActorContext("agent-a", "agent", "tenant-a", 100.0, 200.0, ("request_review",))
    policy = PrincipalPolicy("policy-a", ("agent",), ("request_review",))
    policy.authorize(actor, "request_review", now=150.0)
    with pytest.raises(DeploymentEvidenceError):
        ActorContext("agent-a", "agent", "tenant-a", 100.0, 200.0, ("freeze",))
    with pytest.raises(DeploymentEvidenceError):
        policy.authorize(actor, "submit_order", now=150.0)


@pytest.mark.parametrize("permission", ("cancel_order", "set_leverage", "write_config"))
def test_actor_context_rejects_unrecognized_permissions(permission: str) -> None:
    with pytest.raises(DeploymentEvidenceError, match="unsupported evidence permission"):
        ActorContext("agent-a", "agent", "tenant-a", 100.0, 200.0, (permission,))


@pytest.mark.parametrize("permission", ("cancel_order", "set_leverage", "write_config"))
def test_principal_policy_rejects_unrecognized_permissions(permission: str) -> None:
    with pytest.raises(DeploymentEvidenceError, match="unsupported evidence permission"):
        PrincipalPolicy("policy-a", ("agent",), (permission,))


def test_actor_context_rejects_mapping_permissions() -> None:
    with pytest.raises(DeploymentEvidenceError, match="permissions must be a tuple, list, set"):
        ActorContext("agent-a", "agent", "tenant-a", 100.0, 200.0, {"request_review": False})


def test_principal_policy_rejects_mapping_actor_kinds_and_permissions() -> None:
    with pytest.raises(
        DeploymentEvidenceError,
        match="allowed_actor_kinds must be a tuple, list, set",
    ):
        PrincipalPolicy("policy-a", {"agent": False})
    with pytest.raises(
        DeploymentEvidenceError,
        match="allowed_permissions must be a tuple, list, set",
    ):
        PrincipalPolicy("policy-a", ("agent",), {"request_review": False})


def test_actor_context_rejects_string_subclass_permission() -> None:
    permission = _EvilStr("submit_order", "read_evidence")
    with pytest.raises(DeploymentEvidenceError, match="permissions must contain only strings"):
        ActorContext("agent-a", "agent", "tenant-a", 100.0, 200.0, (permission,))


def test_principal_policy_authorize_rejects_string_subclass_permission() -> None:
    actor = ActorContext("agent-a", "agent", "tenant-a", 100.0, 200.0, ("read_evidence",))
    policy = PrincipalPolicy("policy-a", ("agent",), ("read_evidence",))
    permission = _EvilStr("submit_order", "read_evidence")

    with pytest.raises(DeploymentEvidenceError, match="permission must be a string"):
        policy.authorize(actor, permission, now=150.0)  # type: ignore[arg-type]


def test_principal_policy_rejects_string_subclass_permission() -> None:
    permission = _EvilStr("submit_order", "read_evidence")
    with pytest.raises(
        DeploymentEvidenceError, match="allowed_permissions must contain only strings"
    ):
        PrincipalPolicy("policy-a", ("agent",), (permission,))


def test_actor_context_rejects_string_subclass_actor_kind() -> None:
    actor_kind = _EvilStr("unknown", "agent")
    with pytest.raises(DeploymentEvidenceError, match="invalid actor_kind"):
        ActorContext("agent-a", actor_kind, "tenant-a", 100.0, 200.0)


def test_principal_policy_rejects_string_subclass_actor_kind() -> None:
    actor_kind = _EvilStr("unknown", "agent")
    with pytest.raises(
        DeploymentEvidenceError, match="allowed_actor_kinds must contain only strings"
    ):
        PrincipalPolicy("policy-a", (actor_kind,))


@pytest.mark.parametrize("collection_type", (tuple, list, set, frozenset))
def test_actor_context_and_policy_accept_supported_string_collections(
    collection_type: type,
) -> None:
    actor = ActorContext(
        "agent-a", "agent", "tenant-a", 100.0, 200.0, collection_type(("request_review",))
    )
    policy = PrincipalPolicy(
        "policy-a",
        collection_type(("agent",)),
        collection_type(("request_review",)),
    )

    assert isinstance(actor.permissions, tuple)
    assert isinstance(policy.allowed_actor_kinds, tuple)
    assert isinstance(policy.allowed_permissions, tuple)
    policy.authorize(actor, "request_review", now=150.0)


@pytest.mark.parametrize("permission", ("READ_EVIDENCE", "Request_Review"))
def test_actor_context_rejects_case_variant_permissions(permission: str) -> None:
    with pytest.raises(DeploymentEvidenceError, match="unsupported evidence permission"):
        ActorContext("agent-a", "agent", "tenant-a", 100.0, 200.0, (permission,))


@pytest.mark.parametrize("permission", ("READ_EVIDENCE", "Request_Review"))
def test_principal_policy_rejects_case_variant_permissions(permission: str) -> None:
    with pytest.raises(DeploymentEvidenceError, match="unsupported evidence permission"):
        PrincipalPolicy("policy-a", ("agent",), (permission,))


@pytest.mark.parametrize("actor_kind", ("AGENT", "Agent"))
def test_principal_policy_rejects_case_variant_actor_kinds(actor_kind: str) -> None:
    with pytest.raises(DeploymentEvidenceError, match="invalid allowed_actor_kinds"):
        PrincipalPolicy("policy-a", (actor_kind,))


def test_principal_policy_authorize_rejects_non_string_permission_with_custom_equality() -> None:
    class EqualToAnything:
        def __eq__(self, other: object) -> bool:
            return True

    actor = ActorContext("agent-a", "agent", "tenant-a", 100.0, 200.0, ("request_review",))
    policy = PrincipalPolicy("policy-a", ("agent",), ("request_review",))

    with pytest.raises(DeploymentEvidenceError, match="permission must be a string"):
        policy.authorize(actor, EqualToAnything(), now=150.0)  # type: ignore[arg-type]


@pytest.mark.parametrize("now", (float("nan"), float("inf"), float("-inf"), True))
def test_principal_policy_authorize_rejects_non_finite_or_boolean_time(now: object) -> None:
    actor = ActorContext("agent-a", "agent", "tenant-a", 100.0, 200.0, ("request_review",))
    policy = PrincipalPolicy("policy-a", ("agent",), ("request_review",))

    with pytest.raises(DeploymentEvidenceError, match="invalid now"):
        policy.authorize(actor, "request_review", now=now)  # type: ignore[arg-type]


def test_principal_policy_authorize_rejects_integer_too_large_for_float_time() -> None:
    actor = ActorContext("agent-a", "agent", "tenant-a", 100.0, 200.0, ("request_review",))
    policy = PrincipalPolicy("policy-a", ("agent",), ("request_review",))

    with pytest.raises(DeploymentEvidenceError, match="invalid now"):
        policy.authorize(actor, "request_review", now=10**10000)


def test_evidence_rejects_string_subclass_review_status_and_schema_version() -> None:
    with pytest.raises(DeploymentEvidenceError, match="invalid review_status"):
        replace(_evidence(), review_status=_EvilStr("unexpected", "review_required"))
    with pytest.raises(DeploymentEvidenceError, match="unsupported evidence schema_version"):
        replace(
            _evidence(),
            schema_version=_EvilStr("unexpected", "bt-api-deployment-evidence/v1"),
        )


@pytest.mark.parametrize(
    ("runtime_mode", "runtime_preset"),
    (
        (_EvilStr("paper", "live"), "managed_live_direct"),
        ("live", _EvilStr("unmanaged", "managed_live_direct")),
    ),
)
def test_receipt_rejects_string_subclass_runtime_labels(
    runtime_mode: str,
    runtime_preset: str,
) -> None:
    with pytest.raises(DeploymentEvidenceError, match="managed live runtime"):
        DeploymentAdmissionReceipt(
            receipt_id="receipt-1",
            evidence_digest="a" * 64,
            tenant_id="tenant-a",
            strategy_id="strategy-a",
            config_effective_digest="b" * 64,
            approved_by="operator-a",
            runtime_mode=runtime_mode,
            runtime_preset=runtime_preset,
            issued_at=100.0,
            expires_at=200.0,
        )


def test_evidence_rejects_string_subclass_identifiers_digests_and_metadata() -> None:
    evidence = _evidence()
    with pytest.raises(DeploymentEvidenceError, match="invalid evidence_id"):
        replace(evidence, evidence_id=_EvilStr("evidence-1", "evidence-1"))
    with pytest.raises(DeploymentEvidenceError, match="invalid producer_wheel_sha256"):
        replace(evidence, producer_wheel_sha256=_EvilStr("a" * 64, "a" * 64))
    with pytest.raises(DeploymentEvidenceError, match="unsupported JSON type"):
        replace(evidence, metadata={"note": _EvilStr("value", "value")})
    with pytest.raises(DeploymentEvidenceError, match="JSON object keys must be strings"):
        replace(evidence, metadata={_EvilStr("api_key", "api_key"): "placeholder"})


def test_metadata_is_snapshotted_once_before_validation_and_encoding() -> None:
    source = _SwitchingDict()
    evidence = replace(_evidence(), metadata=source)

    assert source.items_calls == 1
    assert evidence.metadata == {"source": "offline"}


def test_evidence_from_dict_rejects_string_subclass_field_keys() -> None:
    raw = _evidence().to_dict()
    review_status = raw.pop("review_status")
    raw[_EvilStr("review_status", "review_status")] = review_status

    with pytest.raises(DeploymentEvidenceError, match="invalid evidence wire fields"):
        StrategyDeploymentEvidence.from_dict(raw)


@pytest.mark.parametrize("actor_kind", ("AGENT", "Agent"))
def test_actor_context_rejects_case_variant_actor_kinds(actor_kind: str) -> None:
    with pytest.raises(DeploymentEvidenceError, match="invalid actor_kind"):
        ActorContext("agent-a", actor_kind, "tenant-a", 100.0, 200.0)


def test_receipt_never_accepts_review_required_evidence_and_binds_every_identity() -> None:
    review_required = _evidence()
    receipt = DeploymentAdmissionReceipt(
        receipt_id="receipt-1",
        evidence_digest=review_required.digest,
        tenant_id="tenant-a",
        strategy_id="strategy-a",
        config_effective_digest="c" * 64,
        approved_by="operator-a",
        runtime_mode="live",
        runtime_preset="managed_live_direct",
        issued_at=120.0,
        expires_at=180.0,
    )
    assert receipt.validates_evidence(review_required, now=150.0) is False

    reviewed = _evidence("human_reviewed")
    reviewed_receipt = DeploymentAdmissionReceipt(
        receipt_id="receipt-2",
        evidence_digest=reviewed.digest,
        tenant_id="tenant-a",
        strategy_id="strategy-a",
        config_effective_digest="c" * 64,
        approved_by="operator-a",
        runtime_mode="live",
        runtime_preset="managed_live_gateway",
        issued_at=120.0,
        expires_at=180.0,
    )
    assert reviewed_receipt.validates_evidence(reviewed, now=150.0) is True
    assert reviewed_receipt.validates_evidence(reviewed, now=190.0) is False
    with pytest.raises(DeploymentEvidenceError, match="invalid now"):
        reviewed_receipt.validates_evidence(reviewed, now=float("nan"))


def test_receipt_rejects_evidence_created_after_receipt_was_issued() -> None:
    evidence = replace(
        _evidence("human_reviewed"), created_at=130.0, metadata={"source": "offline"}
    )
    receipt = DeploymentAdmissionReceipt(
        receipt_id="receipt-1",
        evidence_digest=evidence.digest,
        tenant_id="tenant-a",
        strategy_id="strategy-a",
        config_effective_digest="c" * 64,
        approved_by="operator-a",
        runtime_mode="live",
        runtime_preset="managed_live_direct",
        issued_at=120.0,
        expires_at=180.0,
    )

    assert receipt.validates_evidence(evidence, now=150.0) is False


def test_receipt_requires_exact_evidence_type_even_when_fake_fields_match() -> None:
    evidence = _evidence("human_reviewed")
    receipt = DeploymentAdmissionReceipt(
        receipt_id="receipt-1",
        evidence_digest=evidence.digest,
        tenant_id="tenant-a",
        strategy_id="strategy-a",
        config_effective_digest="c" * 64,
        approved_by="operator-a",
        runtime_mode="live",
        runtime_preset="managed_live_direct",
        issued_at=120.0,
        expires_at=180.0,
    )
    fake = SimpleNamespace(
        review_status=evidence.review_status,
        created_at=evidence.created_at,
        expires_at=evidence.expires_at,
        digest=evidence.digest,
        tenant_id=evidence.tenant_id,
        strategy_id=evidence.strategy_id,
        config_effective_digest=evidence.config_effective_digest,
    )

    assert receipt.validates_evidence(fake, now=150.0) is False  # type: ignore[arg-type]


def test_receipt_allows_evidence_created_at_issue_time_and_now_boundary() -> None:
    evidence = replace(
        _evidence("human_reviewed"), created_at=120.0, metadata={"source": "offline"}
    )
    receipt = DeploymentAdmissionReceipt(
        receipt_id="receipt-1",
        evidence_digest=evidence.digest,
        tenant_id="tenant-a",
        strategy_id="strategy-a",
        config_effective_digest="c" * 64,
        approved_by="operator-a",
        runtime_mode="live",
        runtime_preset="managed_live_direct",
        issued_at=120.0,
        expires_at=180.0,
    )

    assert receipt.validates_evidence(evidence, now=120.0) is True
