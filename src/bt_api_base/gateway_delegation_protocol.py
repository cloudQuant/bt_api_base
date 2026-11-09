"""Versioned declarations for a delegated Gateway command.

These immutable wire values are claims, not Registry credentials or Risk
approval. Gateway must bind them to current authenticated authority and commit
all source fields with the original command, in the same owner transaction.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from collections.abc import Mapping

from bt_api_base.gateway_direct_protocol import canonical_gateway_payload
from bt_api_base.market_protocol import MarketInstrumentKey


class GatewayDelegationProtocolError(ValueError):
    """Finite, value-free validation failure."""


def _ref(value: object) -> bool:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= 256
    except UnicodeError:
        return False


def _digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


@dataclass(frozen=True, slots=True)
class GatewayDelegatedCommand:
    """Exact actor and strategy claims for one canonical order request."""

    account_scope: str
    strategy_scope: str
    execution_domain_ref: str
    actor_principal: str
    actor_ref: str
    actor_kind: str
    run_id: str
    request_key: str
    payload_digest: str
    instrument: MarketInstrumentKey
    grant_revision: str
    parent_ref: str | None = None
    child_id: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (type(self.schema_version) is not int or self.schema_version != 1
                or type(self.actor_kind) is not str or self.actor_kind not in ("risk", "execution")
                or any(not _ref(value) for value in (self.account_scope, self.strategy_scope,
                       self.execution_domain_ref, self.actor_principal, self.actor_ref, self.run_id, self.request_key,
                       self.grant_revision))
                or not _digest(self.payload_digest)
                or type(self.instrument) is not MarketInstrumentKey
                or (self.parent_ref is None) != (self.child_id is None)
                or (self.parent_ref is not None and (not _ref(self.parent_ref) or not _ref(self.child_id)))
                or (self.actor_kind == "execution" and self.parent_ref is None)):
            raise GatewayDelegationProtocolError("INVALID_DELEGATED_COMMAND")

    @property
    def origin(self) -> str:
        return self.actor_kind + ":" + self.actor_principal

    def to_mapping(self) -> dict:
        return {"schema_version": self.schema_version, "account_scope": self.account_scope,
                "strategy_scope": self.strategy_scope, "execution_domain_ref": self.execution_domain_ref,
                "actor_principal": self.actor_principal,
                "actor_ref": self.actor_ref, "actor_kind": self.actor_kind, "run_id": self.run_id,
                "request_key": self.request_key, "payload_digest": self.payload_digest,
                "instrument": self.instrument.to_dict(), "grant_revision": self.grant_revision,
                "parent_ref": self.parent_ref, "child_id": self.child_id, "origin": self.origin}

    @classmethod
    def from_mapping(cls, value: Mapping) -> GatewayDelegatedCommand:
        fields = {"schema_version", "account_scope", "strategy_scope", "execution_domain_ref", "actor_principal", "actor_ref",
                  "actor_kind", "run_id", "request_key", "payload_digest", "instrument",
                  "grant_revision", "parent_ref", "child_id", "origin"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise GatewayDelegationProtocolError("INVALID_DELEGATED_COMMAND")
        try:
            kwargs = dict(value)
            origin = kwargs.pop("origin")
            kwargs["instrument"] = MarketInstrumentKey.from_dict(kwargs["instrument"])
            result = cls(**kwargs)
            if origin != result.origin:
                raise ValueError
            return result
        except (TypeError, ValueError, KeyError):
            raise GatewayDelegationProtocolError("INVALID_DELEGATED_COMMAND") from None

    @property
    def canonical_json(self) -> str:
        return canonical_gateway_payload(self.to_mapping())

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json.encode("ascii")).hexdigest()
