"""Strict values for a proposed first Risk-delegated Gateway reservation.

These DTOs bind claims, not authority. Authenticated context, journal ownership,
freshness, atomic first insertion and any cross-process fencing must be supplied
and verified by the respective service owners. This module does not enable an
operation or establish that any claim or reply came from a trusted service.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from .gateway_delegation_protocol import GatewayDelegatedCommand, _digest, _ref
from .gateway_direct_protocol import gateway_payload_digest

RISK_FIRST_RESERVE_REQUEST_V2_SCHEMA = "bt_api.gateway.risk_first_reserve_request.v2"
RISK_FIRST_RESERVE_RESULT_V2_SCHEMA = "bt_api.gateway.risk_first_reserve_result.v2"
RISK_FIRST_RESERVE_NONCE_DOMAIN = b"bt_api.gateway.risk-first-reserve.v2\x00"


class GatewayRiskFirstReserveV2Error(ValueError):
    """Finite validation error; does not include request values."""


def risk_first_reserve_nonce_digest(nonce: bytes) -> str:
    """Hash 32 nonce bytes in this operation's domain; this does not prove entropy."""
    if type(nonce) is not bytes or len(nonce) != 32:
        raise GatewayRiskFirstReserveV2Error("INVALID_RISK_FIRST_RESERVE_NONCE")
    return hashlib.sha256(RISK_FIRST_RESERVE_NONCE_DOMAIN + nonce).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class GatewayRiskFirstReserveRequestV2:
    """Risk handler's versioned, value-only commitment to one v1 command.

    Scope, strategy, run, request key and payload digest come exclusively from
    ``command``. No dispatch bearer or nonce plaintext is a request field.
    The requested TTL is a bounded duration, not proof of any current deadline.
    """

    command: GatewayDelegatedCommand
    risk_service_id: str
    risk_instance_id: str
    strategy_principal: str
    risk_registration_id: str
    risk_service_epoch: str
    risk_permit_id: str
    risk_view_digest: str
    attempt_nonce_digest: str
    requested_ttl_ms: int
    schema_version: int = 2

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 2
            or type(self.command) is not GatewayDelegatedCommand
            or self.command.actor_kind != "risk"
            or not all(
                _ref(value)
                for value in (
                    self.risk_service_id,
                    self.risk_instance_id,
                    self.strategy_principal,
                    self.risk_registration_id,
                    self.risk_service_epoch,
                    self.risk_permit_id,
                )
            )
            or not _digest(self.risk_view_digest)
            or not _digest(self.attempt_nonce_digest)
            or type(self.requested_ttl_ms) is not int
            or not 1 <= self.requested_ttl_ms <= 30000
        ):
            raise GatewayRiskFirstReserveV2Error("INVALID_RISK_FIRST_RESERVE_REQUEST")

    def to_mapping(self) -> dict:
        """Return the exact wire mapping; it contains identities and digests."""
        return {
            "schema": RISK_FIRST_RESERVE_REQUEST_V2_SCHEMA,
            "schema_version": self.schema_version,
            "command": self.command.to_mapping(),
            "risk_service_id": self.risk_service_id,
            "risk_instance_id": self.risk_instance_id,
            "strategy_principal": self.strategy_principal,
            "risk_registration_id": self.risk_registration_id,
            "risk_service_epoch": self.risk_service_epoch,
            "risk_permit_id": self.risk_permit_id,
            "risk_view_digest": self.risk_view_digest,
            "attempt_nonce_digest": self.attempt_nonce_digest,
            "requested_ttl_ms": self.requested_ttl_ms,
        }

    @classmethod
    def from_mapping(cls, value: Mapping) -> GatewayRiskFirstReserveRequestV2:
        fields = {
            "schema",
            "schema_version",
            "command",
            "risk_service_id",
            "risk_instance_id",
            "strategy_principal",
            "risk_registration_id",
            "risk_service_epoch",
            "risk_permit_id",
            "risk_view_digest",
            "attempt_nonce_digest",
            "requested_ttl_ms",
        }
        if (
            type(value) is not dict
            or set(value) != fields
            or type(value.get("schema")) is not str
            or value["schema"] != RISK_FIRST_RESERVE_REQUEST_V2_SCHEMA
            or type(value.get("command")) is not dict
        ):
            raise GatewayRiskFirstReserveV2Error("INVALID_RISK_FIRST_RESERVE_REQUEST")
        try:
            return cls(
                command=GatewayDelegatedCommand.from_mapping(value["command"]),
                risk_service_id=value["risk_service_id"],
                risk_instance_id=value["risk_instance_id"],
                strategy_principal=value["strategy_principal"],
                risk_registration_id=value["risk_registration_id"],
                risk_service_epoch=value["risk_service_epoch"],
                risk_permit_id=value["risk_permit_id"],
                risk_view_digest=value["risk_view_digest"],
                attempt_nonce_digest=value["attempt_nonce_digest"],
                requested_ttl_ms=value["requested_ttl_ms"],
                schema_version=value["schema_version"],
            )
        except (TypeError, ValueError, KeyError, RecursionError):
            raise GatewayRiskFirstReserveV2Error("INVALID_RISK_FIRST_RESERVE_REQUEST") from None

    @property
    def digest(self) -> str:
        """Hash the canonical, schema-domain-separated complete request mapping."""
        return gateway_payload_digest(self.to_mapping())


@dataclass(frozen=True, slots=True, repr=False)
class GatewayRiskFirstReserveResultV2:
    """A proposed first-reservation result, not authenticated evidence.

    The TTL is the remaining time observed at the producer, in whole
    milliseconds rounded down. It is not a receiver deadline or a freshness
    proof. A producer with less than 1 ms remaining must return UNKNOWN instead.
    """

    request_commitment_digest: str
    journal_id: str
    owner_generation: str
    reservation_generation: str
    account_scope: str
    strategy_scope: str
    execution_domain_ref: str
    run_id: str
    request_key: str
    reservation_id: str
    payload_digest: str
    remaining_ttl_ms: int
    state: str = "RESERVED"
    version: int = 1
    schema_version: int = 2

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 2
            or type(self.version) is not int
            or self.version != 1
            or type(self.state) is not str
            or self.state != "RESERVED"
            or type(self.remaining_ttl_ms) is not int
            or not 1 <= self.remaining_ttl_ms <= 30000
            or not all(
                _ref(value)
                for value in (
                    self.journal_id,
                    self.owner_generation,
                    self.reservation_generation,
                    self.account_scope,
                    self.strategy_scope,
                    self.execution_domain_ref,
                    self.run_id,
                    self.request_key,
                    self.reservation_id,
                )
            )
            or self.owner_generation != self.reservation_generation
            or not _digest(self.request_commitment_digest)
            or not _digest(self.payload_digest)
        ):
            raise GatewayRiskFirstReserveV2Error("INVALID_RISK_FIRST_RESERVE_RESULT")

    def to_mapping(self) -> dict:
        """Return exact wire fields; the mapping contains identities and digests."""
        return {
            "schema": RISK_FIRST_RESERVE_RESULT_V2_SCHEMA,
            "schema_version": self.schema_version,
            "request_commitment_digest": self.request_commitment_digest,
            "journal_id": self.journal_id,
            "owner_generation": self.owner_generation,
            "reservation_generation": self.reservation_generation,
            "account_scope": self.account_scope,
            "strategy_scope": self.strategy_scope,
            "execution_domain_ref": self.execution_domain_ref,
            "run_id": self.run_id,
            "request_key": self.request_key,
            "reservation_id": self.reservation_id,
            "payload_digest": self.payload_digest,
            "remaining_ttl_ms": self.remaining_ttl_ms,
            "state": self.state,
            "version": self.version,
        }

    @classmethod
    def from_mapping(cls, value: Mapping) -> GatewayRiskFirstReserveResultV2:
        """Decode shape only; it must still be bound to the original request."""
        fields = {
            "schema",
            "schema_version",
            "request_commitment_digest",
            "journal_id",
            "owner_generation",
            "reservation_generation",
            "account_scope",
            "strategy_scope",
            "execution_domain_ref",
            "run_id",
            "request_key",
            "reservation_id",
            "payload_digest",
            "remaining_ttl_ms",
            "state",
            "version",
        }
        if (
            type(value) is not dict
            or set(value) != fields
            or type(value.get("schema")) is not str
            or value["schema"] != RISK_FIRST_RESERVE_RESULT_V2_SCHEMA
        ):
            raise GatewayRiskFirstReserveV2Error("INVALID_RISK_FIRST_RESERVE_RESULT")
        try:
            return cls(
                request_commitment_digest=value["request_commitment_digest"],
                journal_id=value["journal_id"],
                owner_generation=value["owner_generation"],
                reservation_generation=value["reservation_generation"],
                account_scope=value["account_scope"],
                strategy_scope=value["strategy_scope"],
                execution_domain_ref=value["execution_domain_ref"],
                run_id=value["run_id"],
                request_key=value["request_key"],
                reservation_id=value["reservation_id"],
                payload_digest=value["payload_digest"],
                remaining_ttl_ms=value["remaining_ttl_ms"],
                state=value["state"],
                version=value["version"],
                schema_version=value["schema_version"],
            )
        except (TypeError, ValueError, KeyError, RecursionError):
            raise GatewayRiskFirstReserveV2Error("INVALID_RISK_FIRST_RESERVE_RESULT") from None

    @classmethod
    def from_mapping_for_request(
        cls, value: Mapping, request: GatewayRiskFirstReserveRequestV2
    ) -> GatewayRiskFirstReserveResultV2:
        """Decode and check the original request; no authenticity is implied."""
        result = cls.from_mapping(value)
        if not result.matches_request(request):
            raise GatewayRiskFirstReserveV2Error("RISK_FIRST_RESERVE_REQUEST_MISMATCH")
        return result

    def matches_request(self, request: object) -> bool:
        """Compare fields and TTL cap; this does not authenticate or date either value."""
        if type(request) is not GatewayRiskFirstReserveRequestV2:
            return False
        return (
            self.request_commitment_digest == request.digest
            and self.account_scope == request.command.account_scope
            and self.strategy_scope == request.command.strategy_scope
            and self.execution_domain_ref == request.command.execution_domain_ref
            and self.run_id == request.command.run_id
            and self.request_key == request.command.request_key
            and self.payload_digest == request.command.payload_digest
            and self.remaining_ttl_ms <= request.requested_ttl_ms
        )

    @property
    def digest(self) -> str:
        """Hash the canonical, schema-domain-separated complete result mapping."""
        return gateway_payload_digest(self.to_mapping())
