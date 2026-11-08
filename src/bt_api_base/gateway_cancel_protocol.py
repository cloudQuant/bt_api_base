"""Bounded public cancel-attempt observations; never proof of venue cancellation."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from bt_api_base.gateway_direct_protocol import GatewayCommandBinding, GatewayDirectProtocolError

_STATES = {"REQUESTED": 1, "DISPATCHING": 2, "SENT": 3, "NOT_SENT": 3, "UNKNOWN": 3}
_ERRORS = {
    "REQUESTED": {None},
    "DISPATCHING": {None},
    "SENT": {None},
    "NOT_SENT": {None, "CANCEL_NOT_SENT", "CANCEL_FAILED"},
    "UNKNOWN": {None, "CANCEL_OUTCOME_UNKNOWN", "CANCEL_FAILED"},
}
_BINDING = ("journal_id", "account_scope", "strategy_scope", "principal")


def _ref(value: object) -> bool:
    if type(value) is not str or not value or value != value.strip() or len(value) > 256:
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= 256
    except UnicodeError:
        return False


def _digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _map(value: object) -> bool:
    return type(value) in (dict, type(MappingProxyType({})))


@dataclass(frozen=True, slots=True)
class GatewayCancelRecord:
    schema_version: int
    binding: GatewayCommandBinding
    operation_id: str
    attempt_id: str
    request_key: str
    target_reservation_id: str
    target_digest: str
    state: str
    version: int
    owner_generation: str
    attempt_generation: str
    generation_current: bool
    error_code: str | None

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or type(self.binding) is not GatewayCommandBinding
            or not all(
                _ref(value)
                for value in (
                    self.operation_id,
                    self.attempt_id,
                    self.request_key,
                    self.target_reservation_id,
                    self.owner_generation,
                    self.attempt_generation,
                )
            )
            or not _digest(self.target_digest)
            or type(self.state) is not str
            or self.state not in _STATES
            or type(self.version) is not int
            or self.version != _STATES[self.state]
            or type(self.generation_current) is not bool
            or self.generation_current != (self.owner_generation == self.attempt_generation)
            or (self.error_code is not None and type(self.error_code) is not str)
            or self.error_code not in _ERRORS[self.state]
        ):
            raise GatewayDirectProtocolError("INVALID_CANCEL_RECORD")
        GatewayCommandBinding(*(getattr(self.binding, field) for field in _BINDING))

    def to_mapping(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "schema_version": self.schema_version,
            "binding": {field: getattr(self.binding, field) for field in _BINDING},
            **{
                field: getattr(self, field)
                for field in (
                    "operation_id",
                    "attempt_id",
                    "request_key",
                    "target_reservation_id",
                    "target_digest",
                    "state",
                    "version",
                    "owner_generation",
                    "attempt_generation",
                    "generation_current",
                    "error_code",
                )
            },
        }

    @classmethod
    def from_mapping(
        cls, value: object, *, expected_binding: GatewayCommandBinding
    ) -> GatewayCancelRecord:
        if type(expected_binding) is not GatewayCommandBinding or not _map(value):
            raise GatewayDirectProtocolError("INVALID_CANCEL_RECORD")
        try:
            data = dict(value)
            if set(data) != set(cls.__dataclass_fields__):
                raise ValueError
            binding = data.pop("binding")
            if not _map(binding) or set(binding) != set(_BINDING):
                raise ValueError
            binding = GatewayCommandBinding(*(binding[field] for field in _BINDING))
            if binding != expected_binding:
                raise GatewayDirectProtocolError("BINDING_MISMATCH")
            return cls(binding=binding, **data)
        except GatewayDirectProtocolError:
            raise
        except Exception:
            raise GatewayDirectProtocolError("INVALID_CANCEL_RECORD") from None
