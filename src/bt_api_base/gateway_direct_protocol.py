"""Neutral, bounded Gateway command observations and payload digest contract.

These immutable values do not authenticate provider facts, identify an account
owner, or authorize dispatch. TTL is a relative observation, not a deadline
on the receiving host. Wire duplicate-key rejection belongs to the transport.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from bt_api_base.direct_write_protocol import NativeOrderIdentity


class GatewayDirectProtocolError(ValueError):
    """Finite validation failure without untrusted payload values."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise GatewayDirectProtocolError(code)


def canonical_gateway_payload(payload: object) -> str:
    """Canonical JSON with max depth 16, 4096 nodes and 65536 ASCII bytes.

    Supported values are None, exact bool/int64/string, lists and dicts with
    nonempty string keys. Strings have at most 16384 characters, map keys at
    most 256. Binary floats are refused. This is encoding, not redaction.
    """
    count = 0

    def check(item: Any, depth: int) -> None:
        nonlocal count
        count += 1
        if count > 4096 or depth > 16:
            _fail("INVALID_PAYLOAD")
        if item is None or type(item) in (bool, int, str):
            if type(item) is str and len(item) > 16384:
                _fail("INVALID_PAYLOAD")
            if type(item) is int and not -(2**63) <= item < 2**63:
                _fail("INVALID_PAYLOAD")
            return
        if type(item) is list:
            for nested in item:
                check(nested, depth + 1)
            return
        if type(item) is dict:
            for key, nested in item.items():
                if not isinstance(key, str) or not key or len(key) > 256:
                    _fail("INVALID_PAYLOAD")
                check(nested, depth + 1)
            return
        _fail("INVALID_PAYLOAD")

    try:
        check(payload, 0)
        result = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        if len(result.encode("ascii")) > 65536:
            _fail("INVALID_PAYLOAD")
        return result
    except (TypeError, ValueError, RecursionError, OverflowError):
        _fail("INVALID_PAYLOAD")


def gateway_payload_digest(payload: object) -> str:
    """Return SHA-256 of the canonical ASCII encoding; no authority implied."""
    return hashlib.sha256(canonical_gateway_payload(payload).encode("ascii")).hexdigest()


def _ref(value: object) -> bool:
    if type(value) is not str or not value or value != value.strip() or len(value) > 256:
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True


def _digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _map(value: object) -> bool:
    return type(value) is dict or type(value) is type(MappingProxyType({}))


_SENSITIVE = (
    "password",
    "secret",
    "token",
    "credential",
    "private_key",
    "privatekey",
    "api_key",
    "apikey",
)
_STATES = {
    "RESERVED": 1,
    "DISPATCHING": 2,
    "SENT": 3,
    "NOT_SENT": 3,
    "UNKNOWN": 3,
    "RELEASED": 2,
    "EXPIRED": 2,
}


def validate_gateway_native_identity(identity: NativeOrderIdentity) -> None:
    """Validate bounded, redacted neutral identity fields, without proving their source."""
    if type(identity) is not NativeOrderIdentity:
        _fail("INVALID_IDENTITY")
    if not _ref(identity.exchange_name) or (
        identity.client_order_id is not None and not _ref(identity.client_order_id)
    ):
        _fail("INVALID_IDENTITY")
    if identity.session_generation is not None and (
        type(identity.session_generation) is not int or not 0 <= identity.session_generation < 2**63
    ):
        _fail("INVALID_IDENTITY")
    fields = identity.fields
    if not _map(fields) or len(fields) > 128 or (identity.client_order_id is None and not fields):
        _fail("INVALID_IDENTITY")
    for key, value in fields.items():
        if not _ref(key):
            _fail("INVALID_IDENTITY")
        normalized = key.lower().replace("-", "_").replace(" ", "_")
        if any(part in normalized for part in _SENSITIVE):
            _fail("INVALID_IDENTITY")
        if type(value) not in (str, int, bool, type(None)):
            _fail("INVALID_IDENTITY")
        if type(value) is str and len(value) > 256:
            _fail("INVALID_IDENTITY")
        if type(value) is str:
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeError:
                _fail("INVALID_IDENTITY")
        if type(value) is int and not -(2**63) <= value < 2**63:
            _fail("INVALID_IDENTITY")
    try:
        canonical_gateway_payload(dict(fields))
    except GatewayDirectProtocolError:
        _fail("INVALID_IDENTITY")


@dataclass(frozen=True)
class GatewayCommandBinding:
    """Client-expected scope and journal identity; not authentication evidence."""

    journal_id: str
    account_scope: str
    strategy_scope: str
    principal: str

    def __post_init__(self) -> None:
        if not all(
            _ref(value)
            for value in (self.journal_id, self.account_scope, self.strategy_scope, self.principal)
        ):
            _fail("INVALID_BINDING")


@dataclass(frozen=True)
class GatewayCommandRecord:
    """One bounded command observation tied to its expected local client binding."""

    schema_version: int
    binding: GatewayCommandBinding
    request_key: str
    reservation_id: str
    digest: str
    state: str
    version: int
    owner_generation: str
    reservation_generation: str
    generation_current: bool
    remaining_ttl_seconds: float | int | None
    expiry_pending: bool
    release_operation_id: str | None
    release_expected_version: int | None
    native_identity: NativeOrderIdentity | None
    strong_identity_key_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            _fail("INVALID_RECORD")
        if type(self.binding) is not GatewayCommandBinding:
            _fail("INVALID_BINDING")
        GatewayCommandBinding(
            self.binding.journal_id,
            self.binding.account_scope,
            self.binding.strategy_scope,
            self.binding.principal,
        )
        if not all(
            _ref(x)
            for x in (
                self.request_key,
                self.reservation_id,
                self.owner_generation,
                self.reservation_generation,
            )
        ) or not _digest(self.digest):
            _fail("INVALID_RECORD")
        if (
            type(self.state) is not str
            or self.state not in _STATES
            or type(self.version) is not int
            or self.version != _STATES[self.state]
        ):
            _fail("INVALID_RECORD")
        if (
            type(self.generation_current) is not bool
            or self.generation_current != (self.owner_generation == self.reservation_generation)
            or type(self.expiry_pending) is not bool
        ):
            _fail("INVALID_RECORD")
        ttl = self.remaining_ttl_seconds
        if self.state == "RESERVED":
            if type(ttl) not in (int, float) or not 0 <= ttl <= 30 or not math.isfinite(ttl):
                _fail("INVALID_RECORD")
            if self.expiry_pending != (ttl == 0) or (not self.generation_current and ttl != 0):
                _fail("INVALID_RECORD")
        elif ttl is not None or self.expiry_pending:
            _fail("INVALID_RECORD")
        release_id, release_version = self.release_operation_id, self.release_expected_version
        if self.state == "RELEASED":
            if not _ref(release_id) or type(release_version) is not int or release_version != 1:
                _fail("INVALID_RECORD")
        elif self.state == "EXPIRED":
            if (release_id is None) != (release_version is None):
                _fail("INVALID_RECORD")
            if release_id is not None and (
                not _ref(release_id)
                or type(release_version) is not int
                or release_version not in (1, 2)
            ):
                _fail("INVALID_RECORD")
        elif release_id is not None or release_version is not None:
            _fail("INVALID_RECORD")
        keys = self.strong_identity_key_digests
        if (
            type(keys) is not tuple
            or len(keys) > 16
            or any(not _digest(k) for k in keys)
            or len(set(keys)) != len(keys)
        ):
            _fail("INVALID_RECORD")
        if self.state in {"DISPATCHING", "SENT", "NOT_SENT", "UNKNOWN"}:
            if self.native_identity is None or not keys:
                _fail("INVALID_RECORD")
            validate_gateway_native_identity(self.native_identity)
        elif self.native_identity is not None or keys:
            _fail("INVALID_RECORD")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "journal_id": self.binding.journal_id,
            "account_scope": self.binding.account_scope,
            "strategy_scope": self.binding.strategy_scope,
            "principal": self.binding.principal,
            "request_key": self.request_key,
            "reservation_id": self.reservation_id,
            "digest": self.digest,
            "state": self.state,
            "version": self.version,
            "owner_generation": self.owner_generation,
            "reservation_generation": self.reservation_generation,
            "generation_current": self.generation_current,
            "remaining_ttl_seconds": self.remaining_ttl_seconds,
            "expiry_pending": self.expiry_pending,
            "release_operation_id": self.release_operation_id,
            "release_expected_version": self.release_expected_version,
            "native_identity": (
                None if self.native_identity is None else self.native_identity.to_dict()
            ),
            "strong_identity_key_digests": list(self.strong_identity_key_digests),
        }

    @classmethod
    def from_mapping(
        cls, value: object, *, expected_binding: GatewayCommandBinding
    ) -> GatewayCommandRecord:
        if type(expected_binding) is not GatewayCommandBinding:
            _fail("INVALID_BINDING")
        if not _map(value):
            _fail("INVALID_RECORD")
        try:
            data = dict(value)
            expected_fields = set(cls.__dataclass_fields__) - {"binding"} | {
                "journal_id",
                "account_scope",
                "strategy_scope",
                "principal",
            }
            if set(data) != expected_fields:
                _fail("INVALID_RECORD")
            binding = GatewayCommandBinding(
                *(
                    data.pop(name)
                    for name in ("journal_id", "account_scope", "strategy_scope", "principal")
                )
            )
            if binding != expected_binding:
                _fail("BINDING_MISMATCH")
            identity = data["native_identity"]
            if identity is not None:
                if (
                    not _map(identity)
                    or set(identity)
                    != {"exchange_name", "client_order_id", "fields", "session_generation"}
                    or not _map(identity["fields"])
                ):
                    _fail("INVALID_IDENTITY")
                data["native_identity"] = NativeOrderIdentity(
                    identity["exchange_name"],
                    identity["client_order_id"],
                    dict(identity["fields"]),
                    identity["session_generation"],
                )
            keys = data["strong_identity_key_digests"]
            if type(keys) not in (list, tuple):
                _fail("INVALID_RECORD")
            data["strong_identity_key_digests"] = tuple(keys)
            return cls(binding=binding, **data)
        except GatewayDirectProtocolError:
            raise
        except (TypeError, ValueError, KeyError, OverflowError):
            _fail("INVALID_RECORD")
