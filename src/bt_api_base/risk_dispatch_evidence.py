"""Provider declaration for validating venue-specific risk dispatch evidence.

This contract supplies field/schema names and validators only. It is not a
source attestation, a Risk permit, or an authorization to dispatch an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RiskDispatchEvidenceProfile:
    provider: str
    binding_field: str
    terminal_evidence_field: str
    terminal_proof_schema: str
    terminal_ack_schema: str
    validate_claim: Callable
    validate_zero_fill: Callable
    validate_terminal_binding: Callable
    validate_terminal_evidence: Callable
    validate_terminal_observations: Callable
    terminal_state: Callable
    # Optional provider-specific canonical target-order contract.
    target_order_schema: str | None = None
    validate_target_order: Callable | None = None

    def __post_init__(self):
        if self.target_order_schema is None:
            if self.validate_target_order is not None:
                raise ValueError("target order schema is required with a validator")
        elif (
            type(self.target_order_schema) is not str
            or not self.target_order_schema
            or self.target_order_schema != self.target_order_schema.strip()
            or not self.target_order_schema.isascii()
            or not callable(self.validate_target_order)
        ):
            raise ValueError("invalid target order evidence contract")
        for name in (
            "provider", "binding_field", "terminal_evidence_field",
            "terminal_proof_schema", "terminal_ack_schema",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip() or not value.isascii():
                raise ValueError("invalid risk dispatch evidence profile field")
        if self.binding_field in {
            "dispatch_attempt_count", "permit_id", "risk_intent_id", "updated_at_ns"
        }:
            raise ValueError("risk dispatch binding field collides with journal fields")
        for name in (
            "validate_claim", "validate_zero_fill", "validate_terminal_binding",
            "validate_terminal_evidence", "validate_terminal_observations", "terminal_state",
        ):
            if not callable(getattr(self, name)):
                raise TypeError("risk dispatch evidence profile callback is required")


__all__ = ("RiskDispatchEvidenceProfile",)
