"""Neutral, strict v2 wire contracts for optional service transports.

The header carries claims supplied by a peer. It is not an authorization
credential; a server must resolve identity and scope against trusted state.
Payload schemas and their domain meaning belong to the SDK and service adapters.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, NoReturn, Protocol, Union, runtime_checkable

WIRE_PROTOCOL_VERSION = 2
MAX_WIRE_MESSAGE_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_REFERENCE_BYTES = 256

JsonScalar = Union[None, bool, int, float, str]
JsonValue = Union[JsonScalar, tuple["JsonValue", ...], Mapping[str, "JsonValue"]]

_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")


class WireRole(str, Enum):
    """Closed set of v2 process roles; a role claim does not prove identity."""

    STRATEGY_CLIENT = "strategy_client"
    APPLICATION_CLIENT = "application_client"
    SERVICE = "service"


class WireMessageKind(str, Enum):
    """Requests/events are uncorrelated; replies point to a request message ID."""

    REQUEST = "request"
    REPLY = "reply"
    EVENT = "event"


class WireErrorCode(str, Enum):
    """Stable, finite validation error categories."""

    INVALID_TYPE = "invalid_type"
    INVALID_VALUE = "invalid_value"
    MISSING_FIELD = "missing_field"
    UNKNOWN_FIELD = "unknown_field"
    UNSUPPORTED_VERSION = "unsupported_version"
    INVALID_JSON = "invalid_json"
    DUPLICATE_KEY = "duplicate_key"
    NON_FINITE_NUMBER = "non_finite_number"
    MESSAGE_TOO_LARGE = "message_too_large"
    UNEXPECTED_KIND = "unexpected_kind"
    CORRELATION_MISMATCH = "correlation_mismatch"
    OPERATION_MISMATCH = "operation_mismatch"
    SCOPE_MISMATCH = "scope_mismatch"
    IDENTITY_MISMATCH = "identity_mismatch"
    STREAM_MISMATCH = "stream_mismatch"
    SEQUENCE_MISMATCH = "sequence_mismatch"


class WireField(str, Enum):
    """Finite field context attached to a wire validation error."""

    MESSAGE = "message"
    HEADER = "header"
    PROTOCOL_VERSION = "protocol_version"
    KIND = "kind"
    MESSAGE_ID = "message_id"
    CORRELATION_ID = "correlation_id"
    IDENTITY = "identity"
    ROLE = "role"
    PRINCIPAL_REF = "principal_ref"
    ACTOR_REF = "actor_ref"
    DELEGATE_REF = "delegate_ref"
    SCOPE = "scope"
    EXECUTION_DOMAIN_REF = "execution_domain_ref"
    ACCOUNT_REF = "account_ref"
    ACCOUNT_REFS = "account_refs"
    STRATEGY_REF = "strategy_ref"
    RUN_ID = "run_id"
    MANUAL_BOOK_REF = "manual_book_ref"
    PORTFOLIO_REF = "portfolio_ref"
    GROUP_ID = "group_id"
    LEG_ID = "leg_id"
    OWNER_EPOCH = "owner_epoch"
    OPERATION = "operation"
    SCHEMA_ID = "schema_id"
    SCHEMA_VERSION = "schema_version"
    SENT_AT_UTC = "sent_at_utc"
    STREAM_ID = "stream_id"
    STREAM_EPOCH = "stream_epoch"
    SEQUENCE = "sequence"
    PAYLOAD = "payload"


class WireValidationError(ValueError):
    """A stable wire error that never includes untrusted values or payloads."""

    def __init__(self, code: WireErrorCode, field: WireField) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code.value}:{field.value}")


def _fail(code: WireErrorCode, field: WireField) -> NoReturn:
    raise WireValidationError(code, field)


def _check_text(value: Any, field: WireField) -> str:
    if type(value) is not str:
        _fail(WireErrorCode.INVALID_TYPE, field)
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail(WireErrorCode.INVALID_VALUE, field)
    if (
        not encoded
        or len(encoded) > MAX_REFERENCE_BYTES
        or value != value.strip()
        or any(ord(character) < 32 or 0x7F <= ord(character) <= 0x9F for character in value)
    ):
        _fail(WireErrorCode.INVALID_VALUE, field)
    return value


def _check_optional_text(value: Any, field: WireField) -> str | None:
    if value is None:
        return None
    return _check_text(value, field)


@dataclass(frozen=True)
class WireIdentity:
    """Untrusted sender claims; trusted transport/service state must verify them."""

    role: WireRole
    principal_ref: str
    actor_ref: str
    delegate_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self.role) is not WireRole:
            _fail(WireErrorCode.INVALID_TYPE, WireField.ROLE)
        _check_text(self.principal_ref, WireField.PRINCIPAL_REF)
        _check_text(self.actor_ref, WireField.ACTOR_REF)
        _check_optional_text(self.delegate_ref, WireField.DELEGATE_REF)


@dataclass(frozen=True)
class WireScope:
    """Immutable routing/ownership scope claims, not authorization decisions."""

    execution_domain_ref: str
    account_ref: str | None = None
    account_refs: tuple[str, ...] = ()
    strategy_ref: str | None = None
    run_id: str | None = None
    manual_book_ref: str | None = None
    portfolio_ref: str | None = None
    group_id: str | None = None
    leg_id: str | None = None

    def __post_init__(self) -> None:
        _check_text(self.execution_domain_ref, WireField.EXECUTION_DOMAIN_REF)
        _check_optional_text(self.account_ref, WireField.ACCOUNT_REF)
        _check_optional_text(self.strategy_ref, WireField.STRATEGY_REF)
        _check_optional_text(self.run_id, WireField.RUN_ID)
        _check_optional_text(self.manual_book_ref, WireField.MANUAL_BOOK_REF)
        _check_optional_text(self.portfolio_ref, WireField.PORTFOLIO_REF)
        _check_optional_text(self.group_id, WireField.GROUP_ID)
        _check_optional_text(self.leg_id, WireField.LEG_ID)

        if type(self.account_refs) not in (tuple, list):
            _fail(WireErrorCode.INVALID_TYPE, WireField.ACCOUNT_REFS)
        copied_account_refs = tuple(self.account_refs)
        for account_ref in copied_account_refs:
            _check_text(account_ref, WireField.ACCOUNT_REFS)
        if len(set(copied_account_refs)) != len(copied_account_refs):
            _fail(WireErrorCode.INVALID_VALUE, WireField.ACCOUNT_REFS)
        object.__setattr__(self, "account_refs", copied_account_refs)

        if self.run_id is not None and self.strategy_ref is None:
            _fail(WireErrorCode.INVALID_VALUE, WireField.RUN_ID)
        if self.manual_book_ref is not None and self.strategy_ref is not None:
            _fail(WireErrorCode.INVALID_VALUE, WireField.MANUAL_BOOK_REF)

        if self.group_id is None:
            if self.leg_id is not None:
                _fail(WireErrorCode.INVALID_VALUE, WireField.LEG_ID)
            if self.account_ref is not None and copied_account_refs:
                _fail(WireErrorCode.INVALID_VALUE, WireField.ACCOUNT_REFS)
        elif self.leg_id is None:
            if (
                self.portfolio_ref is None
                or self.account_ref is not None
                or not copied_account_refs
            ):
                _fail(WireErrorCode.INVALID_VALUE, WireField.GROUP_ID)
        elif self.portfolio_ref is None or self.account_ref is None or copied_account_refs:
            _fail(WireErrorCode.INVALID_VALUE, WireField.LEG_ID)


@dataclass(frozen=True)
class WireHeader:
    """Immutable v2 routing header with explicit RPC or event-stream identity."""

    protocol_version: int
    kind: WireMessageKind
    message_id: str
    correlation_id: str | None
    identity: WireIdentity
    scope: WireScope
    operation: str
    schema_id: str
    schema_version: int
    sent_at_utc: str
    owner_epoch: str | None = None
    stream_id: str | None = None
    stream_epoch: str | None = None
    sequence: int | None = None

    def __post_init__(self) -> None:
        if type(self.protocol_version) is not int:
            _fail(WireErrorCode.INVALID_TYPE, WireField.PROTOCOL_VERSION)
        if self.protocol_version != WIRE_PROTOCOL_VERSION:
            _fail(WireErrorCode.UNSUPPORTED_VERSION, WireField.PROTOCOL_VERSION)
        if type(self.kind) is not WireMessageKind:
            _fail(WireErrorCode.INVALID_TYPE, WireField.KIND)
        _check_text(self.message_id, WireField.MESSAGE_ID)
        _check_optional_text(self.correlation_id, WireField.CORRELATION_ID)
        if type(self.identity) is not WireIdentity:
            _fail(WireErrorCode.INVALID_TYPE, WireField.IDENTITY)
        if type(self.scope) is not WireScope:
            _fail(WireErrorCode.INVALID_TYPE, WireField.SCOPE)
        _check_text(self.operation, WireField.OPERATION)
        _check_text(self.schema_id, WireField.SCHEMA_ID)
        if type(self.schema_version) is not int:
            _fail(WireErrorCode.INVALID_TYPE, WireField.SCHEMA_VERSION)
        if self.schema_version <= 0:
            _fail(WireErrorCode.INVALID_VALUE, WireField.SCHEMA_VERSION)
        _check_utc_timestamp(self.sent_at_utc)
        _check_optional_text(self.owner_epoch, WireField.OWNER_EPOCH)
        _check_optional_text(self.stream_id, WireField.STREAM_ID)
        _check_optional_text(self.stream_epoch, WireField.STREAM_EPOCH)

        if self.kind is WireMessageKind.EVENT:
            if self.correlation_id is not None:
                _fail(WireErrorCode.INVALID_VALUE, WireField.CORRELATION_ID)
            if self.stream_id is None:
                _fail(WireErrorCode.MISSING_FIELD, WireField.STREAM_ID)
            if self.stream_epoch is None:
                _fail(WireErrorCode.MISSING_FIELD, WireField.STREAM_EPOCH)
            if type(self.sequence) is not int:
                _fail(WireErrorCode.INVALID_TYPE, WireField.SEQUENCE)
            if self.sequence < 1:
                _fail(WireErrorCode.INVALID_VALUE, WireField.SEQUENCE)
            if self.owner_epoch is not None:
                _fail(WireErrorCode.INVALID_VALUE, WireField.OWNER_EPOCH)
        else:
            if (
                self.stream_id is not None
                or self.stream_epoch is not None
                or self.sequence is not None
            ):
                _fail(WireErrorCode.INVALID_VALUE, WireField.STREAM_ID)
            if self.kind is WireMessageKind.REQUEST and self.correlation_id is not None:
                _fail(WireErrorCode.INVALID_VALUE, WireField.CORRELATION_ID)
            if self.kind is WireMessageKind.REPLY:
                if self.correlation_id is None:
                    _fail(WireErrorCode.MISSING_FIELD, WireField.CORRELATION_ID)
                if self.identity.role is not WireRole.SERVICE:
                    _fail(WireErrorCode.INVALID_VALUE, WireField.ROLE)


@dataclass(frozen=True)
class WireEnvelope:
    """Immutable envelope containing a frozen JSON object payload."""

    header: WireHeader
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        if type(self.header) is not WireHeader:
            _fail(WireErrorCode.INVALID_TYPE, WireField.HEADER)
        frozen_payload = _freeze_payload(self.payload)
        object.__setattr__(self, "payload", frozen_payload)


def _check_utc_timestamp(value: Any) -> str:
    if type(value) is not str:
        _fail(WireErrorCode.INVALID_TYPE, WireField.SENT_AT_UTC)
    if _TIMESTAMP_RE.fullmatch(value) is None:
        _fail(WireErrorCode.INVALID_VALUE, WireField.SENT_AT_UTC)
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail(WireErrorCode.INVALID_VALUE, WireField.SENT_AT_UTC)
    return value


def _freeze_payload(value: Any) -> Mapping[str, JsonValue]:
    if type(value) not in (dict, _MAPPING_PROXY_TYPE):
        _fail(WireErrorCode.INVALID_TYPE, WireField.PAYLOAD)
    try:
        frozen = _freeze_json_value(value, depth=0)
    except RecursionError:
        _fail(WireErrorCode.INVALID_VALUE, WireField.PAYLOAD)
    if type(frozen) is not _MAPPING_PROXY_TYPE:
        _fail(WireErrorCode.INVALID_TYPE, WireField.PAYLOAD)
    return frozen


def _freeze_json_value(value: Any, *, depth: int) -> JsonValue:
    if depth > MAX_JSON_DEPTH:
        _fail(WireErrorCode.INVALID_VALUE, WireField.PAYLOAD)
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _fail(WireErrorCode.NON_FINITE_NUMBER, WireField.PAYLOAD)
        return value
    if type(value) is str:
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            _fail(WireErrorCode.INVALID_VALUE, WireField.PAYLOAD)
        return value
    if type(value) in (dict, _MAPPING_PROXY_TYPE):
        frozen_items: dict[str, JsonValue] = {}
        for key, item in value.items():
            if type(key) is not str:
                _fail(WireErrorCode.INVALID_TYPE, WireField.PAYLOAD)
            try:
                key.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                _fail(WireErrorCode.INVALID_VALUE, WireField.PAYLOAD)
            frozen_items[key] = _freeze_json_value(item, depth=depth + 1)
        return MappingProxyType(frozen_items)
    if type(value) in (list, tuple):
        return tuple(_freeze_json_value(item, depth=depth + 1) for item in value)
    _fail(WireErrorCode.INVALID_TYPE, WireField.PAYLOAD)


def _thaw_json_value(value: JsonValue) -> Any:
    if type(value) is _MAPPING_PROXY_TYPE:
        return {key: _thaw_json_value(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_json_value(item) for item in value]
    return value


_HEADER_KEYS = frozenset(
    {
        "protocol_version",
        "kind",
        "message_id",
        "correlation_id",
        "identity",
        "scope",
        "operation",
        "schema_id",
        "schema_version",
        "sent_at_utc",
        "owner_epoch",
        "stream_id",
        "stream_epoch",
        "sequence",
    }
)
_IDENTITY_KEYS = frozenset({"role", "principal_ref", "actor_ref", "delegate_ref"})
_SCOPE_KEYS = frozenset(
    {
        "execution_domain_ref",
        "account_ref",
        "account_refs",
        "strategy_ref",
        "run_id",
        "manual_book_ref",
        "portfolio_ref",
        "group_id",
        "leg_id",
    }
)


def _check_object_keys(value: dict[str, Any], expected: frozenset[str], field: WireField) -> None:
    if any(key not in expected for key in value):
        _fail(WireErrorCode.UNKNOWN_FIELD, field)
    if any(key not in value for key in expected):
        _fail(WireErrorCode.MISSING_FIELD, field)


def _expect_object(value: Any, field: WireField) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(WireErrorCode.INVALID_TYPE, field)
    return value


def _parse_identity(value: Any) -> WireIdentity:
    identity = _expect_object(value, WireField.IDENTITY)
    _check_object_keys(identity, _IDENTITY_KEYS, WireField.IDENTITY)
    role_value = identity["role"]
    if type(role_value) is not str:
        _fail(WireErrorCode.INVALID_TYPE, WireField.ROLE)
    try:
        role = WireRole(role_value)
    except ValueError:
        _fail(WireErrorCode.INVALID_VALUE, WireField.ROLE)
    return WireIdentity(
        role=role,
        principal_ref=identity["principal_ref"],
        actor_ref=identity["actor_ref"],
        delegate_ref=identity["delegate_ref"],
    )


def _parse_scope(value: Any) -> WireScope:
    scope = _expect_object(value, WireField.SCOPE)
    _check_object_keys(scope, _SCOPE_KEYS, WireField.SCOPE)
    account_refs = scope["account_refs"]
    if type(account_refs) is not list:
        _fail(WireErrorCode.INVALID_TYPE, WireField.ACCOUNT_REFS)
    return WireScope(
        execution_domain_ref=scope["execution_domain_ref"],
        account_ref=scope["account_ref"],
        account_refs=account_refs,
        strategy_ref=scope["strategy_ref"],
        run_id=scope["run_id"],
        manual_book_ref=scope["manual_book_ref"],
        portfolio_ref=scope["portfolio_ref"],
        group_id=scope["group_id"],
        leg_id=scope["leg_id"],
    )


def _parse_header(value: Any) -> WireHeader:
    header = _expect_object(value, WireField.HEADER)
    _check_object_keys(header, _HEADER_KEYS, WireField.HEADER)
    kind_value = header["kind"]
    if type(kind_value) is not str:
        _fail(WireErrorCode.INVALID_TYPE, WireField.KIND)
    try:
        kind = WireMessageKind(kind_value)
    except ValueError:
        _fail(WireErrorCode.INVALID_VALUE, WireField.KIND)
    return WireHeader(
        protocol_version=header["protocol_version"],
        kind=kind,
        message_id=header["message_id"],
        correlation_id=header["correlation_id"],
        identity=_parse_identity(header["identity"]),
        scope=_parse_scope(header["scope"]),
        operation=header["operation"],
        schema_id=header["schema_id"],
        schema_version=header["schema_version"],
        sent_at_utc=header["sent_at_utc"],
        owner_epoch=header["owner_epoch"],
        stream_id=header["stream_id"],
        stream_epoch=header["stream_epoch"],
        sequence=header["sequence"],
    )


def _header_to_wire(header: WireHeader) -> dict[str, Any]:
    scope = header.scope
    identity = header.identity
    return {
        "protocol_version": header.protocol_version,
        "kind": header.kind.value,
        "message_id": header.message_id,
        "correlation_id": header.correlation_id,
        "identity": {
            "role": identity.role.value,
            "principal_ref": identity.principal_ref,
            "actor_ref": identity.actor_ref,
            "delegate_ref": identity.delegate_ref,
        },
        "scope": {
            "execution_domain_ref": scope.execution_domain_ref,
            "account_ref": scope.account_ref,
            "account_refs": list(scope.account_refs),
            "strategy_ref": scope.strategy_ref,
            "run_id": scope.run_id,
            "manual_book_ref": scope.manual_book_ref,
            "portfolio_ref": scope.portfolio_ref,
            "group_id": scope.group_id,
            "leg_id": scope.leg_id,
        },
        "operation": header.operation,
        "schema_id": header.schema_id,
        "schema_version": header.schema_version,
        "sent_at_utc": header.sent_at_utc,
        "owner_epoch": header.owner_epoch,
        "stream_id": header.stream_id,
        "stream_epoch": header.stream_epoch,
        "sequence": header.sequence,
    }


def _validate_max_bytes(max_bytes: Any) -> int:
    if type(max_bytes) is not int:
        _fail(WireErrorCode.INVALID_TYPE, WireField.MESSAGE)
    if not 1 <= max_bytes <= MAX_WIRE_MESSAGE_BYTES:
        _fail(WireErrorCode.INVALID_VALUE, WireField.MESSAGE)
    return max_bytes


def encode_envelope(envelope: WireEnvelope, *, max_bytes: int = MAX_WIRE_MESSAGE_BYTES) -> bytes:
    """Serialize one envelope as bounded UTF-8 JSON; no object fallback exists."""

    max_bytes = _validate_max_bytes(max_bytes)
    if type(envelope) is not WireEnvelope:
        _fail(WireErrorCode.INVALID_TYPE, WireField.MESSAGE)
    wire_value = {
        "header": _header_to_wire(envelope.header),
        "payload": _thaw_json_value(envelope.payload),
    }
    try:
        encoded = json.dumps(
            wire_value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeEncodeError):
        _fail(WireErrorCode.INVALID_VALUE, WireField.MESSAGE)
    if len(encoded) > max_bytes:
        _fail(WireErrorCode.MESSAGE_TOO_LARGE, WireField.MESSAGE)
    return encoded


class _DuplicateJSONKeyError(ValueError):
    pass


class _NonFiniteJSONNumberError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKeyError
        result[key] = value
    return result


def _parse_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise _NonFiniteJSONNumberError
    return parsed


def _reject_json_constant(_value: str) -> NoReturn:
    raise _NonFiniteJSONNumberError


def decode_envelope(data: bytes, *, max_bytes: int = MAX_WIRE_MESSAGE_BYTES) -> WireEnvelope:
    """Decode one strict v2 JSON envelope, rejecting duplicate keys and fallback formats."""

    max_bytes = _validate_max_bytes(max_bytes)
    if type(data) is not bytes:
        _fail(WireErrorCode.INVALID_TYPE, WireField.MESSAGE)
    if len(data) > max_bytes:
        _fail(WireErrorCode.MESSAGE_TOO_LARGE, WireField.MESSAGE)
    try:
        text = data.decode("utf-8", errors="strict")
        wire_value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=_parse_json_float,
            parse_constant=_reject_json_constant,
        )
    except _DuplicateJSONKeyError:
        _fail(WireErrorCode.DUPLICATE_KEY, WireField.MESSAGE)
    except _NonFiniteJSONNumberError:
        _fail(WireErrorCode.NON_FINITE_NUMBER, WireField.PAYLOAD)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError, OverflowError):
        _fail(WireErrorCode.INVALID_JSON, WireField.MESSAGE)

    wire_object = _expect_object(wire_value, WireField.MESSAGE)
    _check_object_keys(wire_object, frozenset({"header", "payload"}), WireField.MESSAGE)
    header = _parse_header(wire_object["header"])
    return WireEnvelope(header=header, payload=wire_object["payload"])


def validate_request(envelope: WireEnvelope) -> None:
    """Require an RPC request envelope without making an authorization decision."""

    _require_envelope(envelope)
    if envelope.header.kind is not WireMessageKind.REQUEST:
        _fail(WireErrorCode.UNEXPECTED_KIND, WireField.KIND)


def validate_reply(
    reply: WireEnvelope,
    request: WireEnvelope,
    *,
    expected_peer: WireIdentity | None = None,
) -> None:
    """Match a reply to its request; optional peer identity must come from trusted setup."""

    validate_request(request)
    _require_envelope(reply)
    reply_header = reply.header
    request_header = request.header
    if reply_header.kind is not WireMessageKind.REPLY:
        _fail(WireErrorCode.UNEXPECTED_KIND, WireField.KIND)
    if reply_header.correlation_id != request_header.message_id:
        _fail(WireErrorCode.CORRELATION_MISMATCH, WireField.CORRELATION_ID)
    if reply_header.operation != request_header.operation:
        _fail(WireErrorCode.OPERATION_MISMATCH, WireField.OPERATION)
    if reply_header.scope != request_header.scope:
        _fail(WireErrorCode.SCOPE_MISMATCH, WireField.SCOPE)
    if reply_header.owner_epoch != request_header.owner_epoch:
        _fail(WireErrorCode.SCOPE_MISMATCH, WireField.OWNER_EPOCH)
    if expected_peer is not None:
        if type(expected_peer) is not WireIdentity:
            _fail(WireErrorCode.INVALID_TYPE, WireField.IDENTITY)
        if reply_header.identity != expected_peer:
            _fail(WireErrorCode.IDENTITY_MISMATCH, WireField.IDENTITY)


def validate_event(
    event: WireEnvelope,
    *,
    expected_scope: WireScope | None = None,
    expected_stream_id: str | None = None,
    expected_stream_epoch: str | None = None,
    expected_sequence: int | None = None,
) -> None:
    """Validate event kind and any supplied scope/stream cursor expectations.

    Stream head cursors belong in RPC payloads; event sequence numbers start at one.
    """

    _require_envelope(event)
    header = event.header
    if header.kind is not WireMessageKind.EVENT:
        _fail(WireErrorCode.UNEXPECTED_KIND, WireField.KIND)
    if (expected_stream_id is None) != (expected_stream_epoch is None):
        _fail(WireErrorCode.INVALID_VALUE, WireField.STREAM_ID)
    if expected_scope is not None:
        if type(expected_scope) is not WireScope:
            _fail(WireErrorCode.INVALID_TYPE, WireField.SCOPE)
        if header.scope != expected_scope:
            _fail(WireErrorCode.SCOPE_MISMATCH, WireField.SCOPE)
    if expected_stream_id is not None:
        _check_text(expected_stream_id, WireField.STREAM_ID)
        _check_text(expected_stream_epoch, WireField.STREAM_EPOCH)
        if header.stream_id != expected_stream_id or header.stream_epoch != expected_stream_epoch:
            _fail(WireErrorCode.STREAM_MISMATCH, WireField.STREAM_ID)
    if expected_sequence is not None:
        if type(expected_sequence) is not int:
            _fail(WireErrorCode.INVALID_TYPE, WireField.SEQUENCE)
        if expected_sequence < 0:
            _fail(WireErrorCode.INVALID_VALUE, WireField.SEQUENCE)
        if header.sequence != expected_sequence:
            _fail(WireErrorCode.SEQUENCE_MISMATCH, WireField.SEQUENCE)


def _require_envelope(envelope: Any) -> None:
    if type(envelope) is not WireEnvelope:
        _fail(WireErrorCode.INVALID_TYPE, WireField.MESSAGE)


@runtime_checkable
class RequestReplyTransport(Protocol):
    """Port for serial, bounded RPC; backends must match reply to the sent request."""

    def request(self, request: WireEnvelope, *, timeout: float) -> WireEnvelope:
        """Send one request and return its correlated reply within the timeout."""

    def close(self) -> None:
        """Release resources owned by this transport instance."""


@runtime_checkable
class EventPublisher(Protocol):
    """Port for publishing non-durable events to an authorized stream."""

    def publish(self, event: WireEnvelope) -> None:
        """Publish one event envelope."""

    def close(self) -> None:
        """Release resources owned by this publisher."""


@runtime_checkable
class EventSubscriber(Protocol):
    """Port for receiving events; timeout returns ``None`` and does not imply a gap."""

    def receive(self, *, timeout: float | None = None) -> WireEnvelope | None:
        """Receive one event envelope, or return ``None`` when the wait expires."""

    def close(self) -> None:
        """Release resources owned by this subscriber."""
