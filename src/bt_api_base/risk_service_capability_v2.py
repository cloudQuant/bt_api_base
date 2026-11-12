"""Strict wire shapes for a prospective Risk v2 first-reservation capability.

Only the dedicated reserve reply carries a capability. The v1 status result
remains unchanged and cannot decode that reply. These data shapes alone cannot
establish that a reply is the first one, that a capability is random, or that a
caller is authorized. Issuance, binding, single-use consumption and replay
protection require independently verified service and registry implementations.

``to_mapping`` explicitly exposes the bearer capability for wire transport;
callers must not log, persist or otherwise disclose that mapping.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .risk_service_protocol import RiskOrderResult, RiskServiceProtocolError, _ref

RISK_RESERVE_REPLY_V2_SCHEMA = "bt_api.risk_order.reserve_reply.v2"
RISK_DISPATCH_REQUEST_V2_SCHEMA = "bt_api.risk_order.dispatch_request.v2"


def _hex_256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True, slots=True)
class RiskReserveReplyV2:
    """Risk reserve answer with a bearer capability only for a reserved result.

    Construction validates shape, not freshness or actual first issuance. The
    service must issue this reply only when the original reservation was newly
    committed and bind its capability to the authenticated owner and session.
    DISPATCHED, RELEASED and TERMINAL describe observed prior states and never
    carry a capability. Other state combinations require a contract update.
    """

    result: RiskOrderResult
    dispatch_capability: str | None = field(default=None, repr=False)
    schema_version: int = 2

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 2:
            raise RiskServiceProtocolError("RISK_V2_RESERVE_REPLY_INVALID")
        if type(self.result) is not RiskOrderResult:
            raise RiskServiceProtocolError("RISK_V2_RESERVE_REPLY_INVALID")
        if self.result.outcome == "RESERVED":
            if (
                self.result.state != "RESERVED"
                or self.result.code is not None
                or not _ref(self.result.permit_id)
                or not _ref(self.result.reservation_id)
                or not _hex_256(self.result.view_digest)
                or not _hex_256(self.dispatch_capability)
            ):
                raise RiskServiceProtocolError("RISK_V2_RESERVE_REPLY_INVALID")
        elif (
            self.dispatch_capability is not None
            or self.result.outcome == "NOT_FOUND"
            or (self.result.outcome == "DENIED" and self.result.state not in (None, "DENIED"))
            or (
                self.result.outcome == "DENIED"
                and (
                    self.result.reservation_id is not None
                    or (self.result.state is None and self.result.permit_id is not None)
                )
            )
            or (
                self.result.outcome in ("DISPATCHED", "RELEASED", "TERMINAL")
                and (self.result.state != self.result.outcome or self.result.code is not None)
            )
        ):
            raise RiskServiceProtocolError("RISK_V2_RESERVE_REPLY_INVALID")

    def to_mapping(self) -> dict:
        """Return a fresh transport mapping that includes the bearer capability."""
        return {
            "schema": RISK_RESERVE_REPLY_V2_SCHEMA,
            "schema_version": self.schema_version,
            "result": self.result.to_mapping(),
            "dispatch_capability": self.dispatch_capability,
        }

    @classmethod
    def from_mapping(cls, value: Mapping) -> RiskReserveReplyV2:
        if (
            type(value) is not dict
            or set(value) != {"schema", "schema_version", "result", "dispatch_capability"}
            or type(value.get("schema")) is not str
            or value.get("schema") != RISK_RESERVE_REPLY_V2_SCHEMA
        ):
            raise RiskServiceProtocolError("RISK_V2_RESERVE_REPLY_INVALID")
        try:
            result = RiskOrderResult.from_mapping(value["result"])
            return cls(result, value["dispatch_capability"], value["schema_version"])
        except (RiskServiceProtocolError, TypeError, ValueError, RecursionError):
            raise RiskServiceProtocolError("RISK_V2_RESERVE_REPLY_INVALID") from None


@dataclass(frozen=True, slots=True)
class RiskDispatchRequestV2:
    """Single-use capability request; validation is not an authorization."""

    request_key: str
    permit_id: str
    reservation_id: str
    view_digest: str
    dispatch_capability: str = field(repr=False)
    schema_version: int = 2

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 2
            or not _ref(self.request_key)
            or not _ref(self.permit_id)
            or not _ref(self.reservation_id)
            or not _hex_256(self.view_digest)
            or not _hex_256(self.dispatch_capability)
        ):
            raise RiskServiceProtocolError("RISK_V2_DISPATCH_REQUEST_INVALID")

    def to_mapping(self) -> dict:
        """Return a fresh transport mapping that includes the bearer capability."""
        return {
            "schema": RISK_DISPATCH_REQUEST_V2_SCHEMA,
            "schema_version": self.schema_version,
            "request_key": self.request_key,
            "permit_id": self.permit_id,
            "reservation_id": self.reservation_id,
            "view_digest": self.view_digest,
            "dispatch_capability": self.dispatch_capability,
        }

    @classmethod
    def from_mapping(cls, value: Mapping) -> RiskDispatchRequestV2:
        if (
            type(value) is not dict
            or set(value)
            != {
                "schema",
                "schema_version",
                "request_key",
                "permit_id",
                "reservation_id",
                "view_digest",
                "dispatch_capability",
            }
            or type(value.get("schema")) is not str
            or value.get("schema") != RISK_DISPATCH_REQUEST_V2_SCHEMA
        ):
            raise RiskServiceProtocolError("RISK_V2_DISPATCH_REQUEST_INVALID")
        return cls(
            request_key=value["request_key"],
            permit_id=value["permit_id"],
            reservation_id=value["reservation_id"],
            view_digest=value["view_digest"],
            dispatch_capability=value["dispatch_capability"],
            schema_version=value["schema_version"],
        )
