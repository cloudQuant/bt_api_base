"""Focused contract tests for the neutral service wire protocol."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from bt_api_base.service_protocol import (
    MAX_WIRE_MESSAGE_BYTES,
    EventPublisher,
    EventSubscriber,
    RequestReplyTransport,
    WireEnvelope,
    WireErrorCode,
    WireField,
    WireHeader,
    WireIdentity,
    WireMessageKind,
    WireRole,
    WireScope,
    WireValidationError,
    decode_envelope,
    encode_envelope,
    validate_event,
    validate_reply,
    validate_request,
)


def _identity(role: WireRole = WireRole.STRATEGY_CLIENT) -> WireIdentity:
    return WireIdentity(role=role, principal_ref="principal-a", actor_ref="actor-a")


def _scope(account_ref: str | None = "account-a") -> WireScope:
    return WireScope(execution_domain_ref="paper:sim-a", account_ref=account_ref)


def _header(
    kind: WireMessageKind = WireMessageKind.REQUEST,
    *,
    message_id: str = "message-1",
    correlation_id: str | None = None,
    identity: WireIdentity | None = None,
    scope: WireScope | None = None,
    operation: str = "orders.submit",
    owner_epoch: str | None = None,
    stream_id: str | None = None,
    stream_epoch: str | None = None,
    sequence: int | None = None,
    protocol_version: int = 2,
    schema_version: int = 1,
) -> WireHeader:
    return WireHeader(
        protocol_version=protocol_version,
        kind=kind,
        message_id=message_id,
        correlation_id=correlation_id,
        identity=identity or _identity(),
        scope=scope or _scope(),
        operation=operation,
        schema_id="orders.request",
        schema_version=schema_version,
        sent_at_utc="2026-10-13T01:02:03.123456Z",
        owner_epoch=owner_epoch,
        stream_id=stream_id,
        stream_epoch=stream_epoch,
        sequence=sequence,
    )


def _envelope(
    kind: WireMessageKind = WireMessageKind.REQUEST,
    *,
    payload: dict[str, object] | None = None,
    **header_values: object,
) -> WireEnvelope:
    return WireEnvelope(
        header=_header(kind, **header_values),
        payload={} if payload is None else payload,
    )


def _assert_error(
    error: WireValidationError,
    code: WireErrorCode,
    field: WireField | None = None,
) -> None:
    assert error.code is code
    if field is not None:
        assert error.field is field
    assert "principal-a" not in str(error)


def test_request_round_trip_freezes_nested_payload_and_scope_input() -> None:
    accounts = ["account-a", "account-b"]
    group_scope = WireScope(
        execution_domain_ref="paper:sim-a",
        account_refs=accounts,
        portfolio_ref="portfolio-a",
        group_id="group-a",
    )
    accounts.append("account-c")
    assert group_scope.account_refs == ("account-a", "account-b")

    payload: dict[str, object] = {"nested": {"values": [1, 2]}}
    envelope = _envelope(scope=group_scope, payload=payload)
    nested = payload["nested"]
    assert isinstance(nested, dict)
    nested["values"].append(3)  # type: ignore[index,union-attr]

    encoded = encode_envelope(envelope)
    restored = decode_envelope(encoded)
    assert restored == envelope
    assert restored.payload["nested"]["values"] == (1, 2)  # type: ignore[index]
    assert restored.header.scope.account_refs == ("account-a", "account-b")
    assert encode_envelope(restored) == encoded

    with pytest.raises(TypeError):
        restored.payload["new"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        restored.payload["nested"]["new"] = "value"  # type: ignore[index]


def test_group_and_child_scope_shapes_do_not_invent_a_group_account() -> None:
    group_scope = WireScope(
        execution_domain_ref="live:venue-a",
        account_refs=("account-a", "account-b"),
        portfolio_ref="portfolio-a",
        group_id="group-a",
    )
    assert group_scope.account_ref is None

    child_scope = WireScope(
        execution_domain_ref="live:venue-a",
        account_ref="account-a",
        portfolio_ref="portfolio-a",
        group_id="group-a",
        leg_id="leg-a",
    )
    assert child_scope.account_refs == ()

    with pytest.raises(WireValidationError) as duplicate:
        WireScope(
            execution_domain_ref="live:venue-a",
            account_refs=("account-a", "account-a"),
        )
    _assert_error(duplicate.value, WireErrorCode.INVALID_VALUE, WireField.ACCOUNT_REFS)

    with pytest.raises(WireValidationError) as synthetic:
        WireScope(
            execution_domain_ref="live:venue-a",
            account_ref="synthetic-group-account",
            portfolio_ref="portfolio-a",
            group_id="group-a",
        )
    _assert_error(synthetic.value, WireErrorCode.INVALID_VALUE, WireField.GROUP_ID)


def test_message_kinds_have_distinct_correlation_and_stream_rules() -> None:
    with pytest.raises(WireValidationError) as request_correlation_error:
        _header(WireMessageKind.REQUEST, correlation_id="parent-request")
    _assert_error(
        request_correlation_error.value,
        WireErrorCode.INVALID_VALUE,
        WireField.CORRELATION_ID,
    )

    with pytest.raises(WireValidationError) as event_correlation_error:
        _header(
            WireMessageKind.EVENT,
            correlation_id="parent-request",
            stream_id="stream-a",
            stream_epoch="epoch-a",
            sequence=1,
        )
    _assert_error(
        event_correlation_error.value,
        WireErrorCode.INVALID_VALUE,
        WireField.CORRELATION_ID,
    )

    with pytest.raises(WireValidationError) as zero_sequence_error:
        _header(
            WireMessageKind.EVENT,
            stream_id="stream-a",
            stream_epoch="epoch-a",
            sequence=0,
        )
    _assert_error(
        zero_sequence_error.value,
        WireErrorCode.INVALID_VALUE,
        WireField.SEQUENCE,
    )

    with pytest.raises(WireValidationError) as non_service_reply_error:
        _header(
            WireMessageKind.REPLY,
            correlation_id="request-a",
            identity=_identity(WireRole.APPLICATION_CLIENT),
        )
    _assert_error(
        non_service_reply_error.value,
        WireErrorCode.INVALID_VALUE,
        WireField.ROLE,
    )

    snapshot_reply = _envelope(
        WireMessageKind.REPLY,
        message_id="snapshot-reply",
        correlation_id="snapshot-request",
        identity=_identity(WireRole.SERVICE),
        payload={"snapshot_head_sequence": 0},
    )
    assert decode_envelope(encode_envelope(snapshot_reply)).payload["snapshot_head_sequence"] == 0


def test_request_reply_validation_binds_correlation_operation_scope_and_peer() -> None:
    request = _envelope(
        message_id="request-7",
        scope=_scope("account-a"),
        owner_epoch="owner-3",
    )
    service_identity = _identity(WireRole.SERVICE)
    reply = _envelope(
        WireMessageKind.REPLY,
        message_id="reply-7",
        correlation_id="request-7",
        identity=service_identity,
        scope=_scope("account-a"),
        owner_epoch="owner-3",
    )

    validate_request(request)
    validate_reply(reply, request, expected_peer=service_identity)

    wrong_correlation = WireEnvelope(
        header=replace(reply.header, correlation_id="other-request"),
        payload={},
    )
    with pytest.raises(WireValidationError) as correlation_error:
        validate_reply(wrong_correlation, request)
    _assert_error(
        correlation_error.value,
        WireErrorCode.CORRELATION_MISMATCH,
        WireField.CORRELATION_ID,
    )

    wrong_scope = WireEnvelope(
        header=replace(reply.header, scope=_scope("account-b")),
        payload={},
    )
    with pytest.raises(WireValidationError) as scope_error:
        validate_reply(wrong_scope, request)
    _assert_error(scope_error.value, WireErrorCode.SCOPE_MISMATCH, WireField.SCOPE)

    wrong_owner_epoch = WireEnvelope(
        header=replace(reply.header, owner_epoch="owner-4"),
        payload={},
    )
    with pytest.raises(WireValidationError) as owner_error:
        validate_reply(wrong_owner_epoch, request)
    _assert_error(owner_error.value, WireErrorCode.SCOPE_MISMATCH, WireField.OWNER_EPOCH)

    wrong_operation = WireEnvelope(
        header=replace(reply.header, operation="orders.cancel"),
        payload={},
    )
    with pytest.raises(WireValidationError) as operation_error:
        validate_reply(wrong_operation, request)
    _assert_error(operation_error.value, WireErrorCode.OPERATION_MISMATCH, WireField.OPERATION)

    with pytest.raises(WireValidationError) as peer_error:
        validate_reply(reply, request, expected_peer=_identity(WireRole.APPLICATION_CLIENT))
    _assert_error(peer_error.value, WireErrorCode.IDENTITY_MISMATCH, WireField.IDENTITY)

    with pytest.raises(WireValidationError) as kind_error:
        validate_request(reply)
    _assert_error(kind_error.value, WireErrorCode.UNEXPECTED_KIND, WireField.KIND)


def test_event_validation_binds_scope_stream_epoch_and_sequence() -> None:
    scope = _scope("account-a")
    event = _envelope(
        WireMessageKind.EVENT,
        message_id="event-9",
        scope=scope,
        stream_id="account-events",
        stream_epoch="epoch-2",
        sequence=9,
        payload={"status": "accepted"},
    )
    validate_event(
        event,
        expected_scope=scope,
        expected_stream_id="account-events",
        expected_stream_epoch="epoch-2",
        expected_sequence=9,
    )

    with pytest.raises(WireValidationError) as stream_error:
        validate_event(event, expected_stream_id="account-events", expected_stream_epoch="epoch-1")
    _assert_error(stream_error.value, WireErrorCode.STREAM_MISMATCH, WireField.STREAM_ID)

    with pytest.raises(WireValidationError) as sequence_error:
        validate_event(event, expected_sequence=10)
    _assert_error(sequence_error.value, WireErrorCode.SEQUENCE_MISMATCH, WireField.SEQUENCE)

    with pytest.raises(WireValidationError) as scope_error:
        validate_event(event, expected_scope=_scope("account-b"))
    _assert_error(scope_error.value, WireErrorCode.SCOPE_MISMATCH, WireField.SCOPE)


@pytest.mark.parametrize(
    ("field", "value", "kind", "expected_field"),
    [
        ("protocol_version", True, WireMessageKind.REQUEST, WireField.PROTOCOL_VERSION),
        ("schema_version", True, WireMessageKind.REQUEST, WireField.SCHEMA_VERSION),
        ("sequence", True, WireMessageKind.EVENT, WireField.SEQUENCE),
    ],
)
def test_boolean_is_not_accepted_as_an_integer(
    field: str,
    value: bool,
    kind: WireMessageKind,
    expected_field: WireField,
) -> None:
    values: dict[str, object] = {field: value}
    if kind is WireMessageKind.EVENT:
        values.update(stream_id="stream-a", stream_epoch="epoch-a")
    with pytest.raises(WireValidationError) as error:
        _header(kind, **values)
    _assert_error(error.value, WireErrorCode.INVALID_TYPE, expected_field)


def test_decode_rejects_unsupported_versions_unknown_fields_and_bad_types() -> None:
    encoded = encode_envelope(_envelope())
    wire_value = json.loads(encoded)

    unsupported = json.loads(json.dumps(wire_value))
    unsupported["header"]["protocol_version"] = 1
    with pytest.raises(WireValidationError) as unsupported_error:
        decode_envelope(json.dumps(unsupported).encode())
    _assert_error(
        unsupported_error.value,
        WireErrorCode.UNSUPPORTED_VERSION,
        WireField.PROTOCOL_VERSION,
    )

    boolean_version = json.loads(json.dumps(wire_value))
    boolean_version["header"]["protocol_version"] = True
    with pytest.raises(WireValidationError) as type_error:
        decode_envelope(json.dumps(boolean_version).encode())
    _assert_error(type_error.value, WireErrorCode.INVALID_TYPE, WireField.PROTOCOL_VERSION)

    unknown = json.loads(json.dumps(wire_value))
    unknown["header"]["legacy_fallback"] = True
    with pytest.raises(WireValidationError) as unknown_error:
        decode_envelope(json.dumps(unknown).encode())
    _assert_error(unknown_error.value, WireErrorCode.UNKNOWN_FIELD, WireField.HEADER)


def test_json_rejects_duplicate_keys_and_non_finite_numbers_without_echoing_values() -> None:
    with pytest.raises(WireValidationError) as duplicate_error:
        decode_envelope(b'{"header":{},"header":{},"payload":{}}')
    _assert_error(duplicate_error.value, WireErrorCode.DUPLICATE_KEY, WireField.MESSAGE)

    valid = encode_envelope(_envelope(payload={"amount": 1}))
    duplicate_payload = valid.replace(b'"amount":1', b'"amount":1,"amount":2')
    with pytest.raises(WireValidationError) as nested_duplicate_error:
        decode_envelope(duplicate_payload)
    _assert_error(
        nested_duplicate_error.value,
        WireErrorCode.DUPLICATE_KEY,
        WireField.MESSAGE,
    )

    non_finite = valid.replace(b'"amount":1', b'"amount":1e400')
    with pytest.raises(WireValidationError) as non_finite_error:
        decode_envelope(non_finite)
    _assert_error(
        non_finite_error.value,
        WireErrorCode.NON_FINITE_NUMBER,
        WireField.PAYLOAD,
    )

    class SensitiveObject:
        def __repr__(self) -> str:
            return "secret-token-should-not-appear"

    with pytest.raises(WireValidationError) as object_error:
        _envelope(payload={"value": SensitiveObject()})  # type: ignore[arg-type]
    _assert_error(object_error.value, WireErrorCode.INVALID_TYPE, WireField.PAYLOAD)
    assert "secret-token-should-not-appear" not in str(object_error.value)


def test_message_size_and_input_types_are_bounded() -> None:
    oversized = _envelope(payload={"data": "x" * MAX_WIRE_MESSAGE_BYTES})
    with pytest.raises(WireValidationError) as encode_error:
        encode_envelope(oversized)
    _assert_error(encode_error.value, WireErrorCode.MESSAGE_TOO_LARGE, WireField.MESSAGE)

    with pytest.raises(WireValidationError) as decode_error:
        decode_envelope(b" " * (MAX_WIRE_MESSAGE_BYTES + 1))
    _assert_error(decode_error.value, WireErrorCode.MESSAGE_TOO_LARGE, WireField.MESSAGE)

    with pytest.raises(WireValidationError) as bytes_type_error:
        decode_envelope("{}")  # type: ignore[arg-type]
    _assert_error(bytes_type_error.value, WireErrorCode.INVALID_TYPE, WireField.MESSAGE)

    with pytest.raises(WireValidationError) as max_type_error:
        encode_envelope(_envelope(), max_bytes=True)
    _assert_error(max_type_error.value, WireErrorCode.INVALID_TYPE, WireField.MESSAGE)


def test_envelope_rejects_non_json_objects_and_non_finite_payloads() -> None:
    with pytest.raises(WireValidationError) as root_error:
        _envelope(payload=[1, 2])  # type: ignore[arg-type]
    _assert_error(root_error.value, WireErrorCode.INVALID_TYPE, WireField.PAYLOAD)

    with pytest.raises(WireValidationError) as finite_error:
        _envelope(payload={"value": float("inf")})
    _assert_error(finite_error.value, WireErrorCode.NON_FINITE_NUMBER, WireField.PAYLOAD)


def test_transport_protocols_are_structural_and_service_protocol_import_is_stdlib_only() -> None:
    class RpcPort:
        def request(self, request: WireEnvelope, *, timeout: float) -> WireEnvelope:
            assert timeout > 0
            return request

        def close(self) -> None:
            pass

    class PublisherPort:
        def publish(self, event: WireEnvelope) -> None:
            assert event.header.kind is WireMessageKind.EVENT

        def close(self) -> None:
            pass

    class SubscriberPort:
        def receive(self, *, timeout: float | None = None) -> WireEnvelope | None:
            assert timeout is None or timeout >= 0
            return None

        def close(self) -> None:
            pass

    assert isinstance(RpcPort(), RequestReplyTransport)
    assert isinstance(PublisherPort(), EventPublisher)
    assert isinstance(SubscriberPort(), EventSubscriber)

    package_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(package_root / "src")
    script = (
        "import sys; import bt_api_base.service_protocol; "
        "assert not {'zmq', 'pydantic', 'numpy'} & set(sys.modules)"
    )
    subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=package_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
