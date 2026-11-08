"""Strict neutral Gateway command wire values and canonical payloads."""

import hashlib
from dataclasses import FrozenInstanceError, replace
from types import MappingProxyType

import pytest

from bt_api_base.direct_write_protocol import NativeOrderIdentity
from bt_api_base.gateway_direct_protocol import (
    GatewayCommandBinding,
    GatewayCommandRecord,
    GatewayDirectProtocolError,
    canonical_gateway_payload,
    gateway_payload_digest,
)

BINDING = GatewayCommandBinding("journal", "account", "strategy", "principal")
DIGEST = "a" * 64
KEY = "b" * 64


def reserved(**changes):
    values = {
        "schema_version": 1,
        "binding": BINDING,
        "request_key": "key",
        "reservation_id": "reservation",
        "digest": DIGEST,
        "state": "RESERVED",
        "version": 1,
        "owner_generation": "g1",
        "reservation_generation": "g1",
        "generation_current": True,
        "remaining_ttl_seconds": 10.0,
        "expiry_pending": False,
        "release_operation_id": None,
        "release_expected_version": None,
        "native_identity": None,
        "strong_identity_key_digests": (),
    }
    values.update(changes)
    return GatewayCommandRecord(**values)


def native():
    return NativeOrderIdentity("CTP___FUTURE", "ref", {"front_id": 1, "trading_day": "20300101"}, 7)


def test_roundtrip_reservation_and_nested_readonly_wire_values():
    value = reserved()
    wire = value.to_mapping()
    wire["strong_identity_key_digests"] = tuple(wire["strong_identity_key_digests"])
    assert (
        GatewayCommandRecord.from_mapping(MappingProxyType(wire), expected_binding=BINDING) == value
    )
    with pytest.raises(FrozenInstanceError):
        value.version = 2


@pytest.mark.parametrize(
    "state,version", [("DISPATCHING", 2), ("SENT", 3), ("NOT_SENT", 3), ("UNKNOWN", 3)]
)
def test_post_dispatch_requires_identity_and_digest(state, version):
    value = reserved(
        state=state,
        version=version,
        remaining_ttl_seconds=None,
        native_identity=native(),
        strong_identity_key_digests=(KEY,),
    )
    assert GatewayCommandRecord.from_mapping(value.to_mapping(), expected_binding=BINDING) == value
    wire = value.to_mapping()
    wire["native_identity"]["fields"] = MappingProxyType(wire["native_identity"]["fields"])
    wire["native_identity"] = MappingProxyType(wire["native_identity"])
    wire["strong_identity_key_digests"] = tuple(wire["strong_identity_key_digests"])
    assert (
        GatewayCommandRecord.from_mapping(MappingProxyType(wire), expected_binding=BINDING) == value
    )
    with pytest.raises(GatewayDirectProtocolError):
        replace(value, native_identity=None)
    with pytest.raises(GatewayDirectProtocolError):
        replace(value, strong_identity_key_digests=())


@pytest.mark.parametrize("release_id,expected", [(None, None), ("release", 1), ("release", 2)])
def test_expired_may_preserve_release_idempotency(release_id, expected):
    value = reserved(
        state="EXPIRED",
        version=2,
        remaining_ttl_seconds=None,
        release_operation_id=release_id,
        release_expected_version=expected,
    )
    assert GatewayCommandRecord.from_mapping(value.to_mapping(), expected_binding=BINDING) == value


def test_released_requires_exact_release_pair():
    value = reserved(
        state="RELEASED",
        version=2,
        remaining_ttl_seconds=None,
        release_operation_id="release",
        release_expected_version=1,
    )
    assert GatewayCommandRecord.from_mapping(value.to_mapping(), expected_binding=BINDING) == value
    for change in (
        {"release_operation_id": None},
        {"release_expected_version": 2},
        {"release_expected_version": True},
    ):
        with pytest.raises(GatewayDirectProtocolError):
            replace(value, **change)


def test_generation_and_ttl_are_bounded_relative_observations():
    assert reserved(
        owner_generation="g2",
        generation_current=False,
        remaining_ttl_seconds=0,
        expiry_pending=True,
    )
    for change in (
        {"owner_generation": "g2", "generation_current": True},
        {"owner_generation": "g2", "generation_current": False, "remaining_ttl_seconds": 1},
        {"remaining_ttl_seconds": 0},
        {"expiry_pending": True},
        {"remaining_ttl_seconds": True},
        {"remaining_ttl_seconds": float("nan")},
        {"remaining_ttl_seconds": float("inf")},
        {"remaining_ttl_seconds": 31},
    ):
        with pytest.raises(GatewayDirectProtocolError):
            replace(reserved(), **change)


@pytest.mark.parametrize(
    "change",
    [
        {"state": "OTHER"},
        {"version": True},
        {"version": 2},
        {"schema_version": True},
        {"schema_version": 2},
        {"request_key": " "},
        {"digest": "A" * 64},
        {"generation_current": 1},
        {"expiry_pending": 0},
        {"release_operation_id": "id", "release_expected_version": 1},
        {"native_identity": native()},
        {"strong_identity_key_digests": (KEY,)},
    ],
)
def test_invalid_record_values_fail_closed(change):
    with pytest.raises(GatewayDirectProtocolError):
        replace(reserved(), **change)


def test_binding_is_required_exact_and_wire_fields_are_closed():
    wire = reserved().to_mapping()
    for name in wire:
        missing = dict(wire)
        del missing[name]
        with pytest.raises(GatewayDirectProtocolError):
            GatewayCommandRecord.from_mapping(missing, expected_binding=BINDING)
    for key in ("journal_id", "account_scope", "strategy_scope", "principal"):
        bad = dict(wire, **{key: "other"})
        with pytest.raises(GatewayDirectProtocolError, match="BINDING_MISMATCH"):
            GatewayCommandRecord.from_mapping(bad, expected_binding=BINDING)
    with pytest.raises(GatewayDirectProtocolError):
        GatewayCommandRecord.from_mapping(dict(wire, run_id="extra"), expected_binding=BINDING)
    with pytest.raises(GatewayDirectProtocolError):
        GatewayCommandRecord.from_mapping(wire, expected_binding=None)


@pytest.mark.parametrize(
    "bad_identity",
    [
        {"exchange_name": "CTP", "client_order_id": None, "fields": {}, "session_generation": 1},
        {
            "exchange_name": "CTP",
            "client_order_id": "ref",
            "fields": {"api_key": "secret"},
            "session_generation": 1,
        },
        {
            "exchange_name": "CTP",
            "client_order_id": "ref",
            "fields": {"user_token": "x"},
            "session_generation": 1,
        },
        {
            "exchange_name": "CTP",
            "client_order_id": "ref",
            "fields": {"x": "a" * 257},
            "session_generation": 1,
        },
        {
            "exchange_name": "CTP",
            "client_order_id": "ref",
            "fields": {"x": "\ud800"},
            "session_generation": 1,
        },
        {
            "exchange_name": "CTP",
            "client_order_id": "ref",
            "fields": {str(i): "中" * 100 for i in range(120)},
            "session_generation": 1,
        },
        {
            "exchange_name": "CTP",
            "client_order_id": "ref",
            "fields": {"x": 1.5},
            "session_generation": 1,
        },
        {
            "exchange_name": "CTP",
            "client_order_id": "ref",
            "fields": {},
            "session_generation": True,
        },
        {
            "exchange_name": "CTP",
            "client_order_id": "ref",
            "fields": {},
            "session_generation": 1,
            "extra": 1,
        },
    ],
)
def test_bad_identity_or_sensitive_field_rejected(bad_identity):
    value = reserved(
        state="SENT",
        version=3,
        remaining_ttl_seconds=None,
        native_identity=native(),
        strong_identity_key_digests=(KEY,),
    )
    wire = value.to_mapping()
    wire["native_identity"] = bad_identity
    with pytest.raises(GatewayDirectProtocolError):
        GatewayCommandRecord.from_mapping(wire, expected_binding=BINDING)


def test_digest_set_is_bounded_strict_and_unique():
    value = reserved(
        state="SENT",
        version=3,
        remaining_ttl_seconds=None,
        native_identity=native(),
        strong_identity_key_digests=(KEY,),
    )
    for bad in ((KEY, KEY), ("A" * 64,), tuple(f"{i:064x}" for i in range(17)), ([1],)):
        with pytest.raises(GatewayDirectProtocolError):
            replace(value, strong_identity_key_digests=bad)


def test_tampered_frozen_binding_and_identity_still_fail_closed():
    binding = GatewayCommandBinding("journal", "account", "strategy", "principal")
    object.__setattr__(binding, "account_scope", "")
    with pytest.raises(GatewayDirectProtocolError, match="INVALID_BINDING"):
        replace(reserved(), binding=binding)
    identity = native()
    object.__setattr__(identity, "fields", None)
    with pytest.raises(GatewayDirectProtocolError, match="INVALID_IDENTITY"):
        reserved(
            state="SENT",
            version=3,
            remaining_ttl_seconds=None,
            native_identity=identity,
            strong_identity_key_digests=(KEY,),
        )


def test_canonical_payload_unicode_order_and_digest_are_stable():
    first = {"中": [True, None, {"z": 2, "a": "值"}], "a": 1}
    second = {"a": 1, "中": [True, None, {"a": "值", "z": 2}]}
    encoded = canonical_gateway_payload(first)
    assert encoded == '{"a":1,"\\u4e2d":[true,null,{"a":"\\u503c","z":2}]}'
    assert canonical_gateway_payload(second) == encoded
    assert gateway_payload_digest(first) == hashlib.sha256(encoded.encode("ascii")).hexdigest()
    assert gateway_payload_digest(first) == gateway_payload_digest(second)


@pytest.mark.parametrize(
    "value",
    [
        1.0,
        float("nan"),
        {"x": float("inf")},
        {1: "x"},
        {"x": 2**63},
        {"x": object()},
        [0] * 4097,
        {"x": "a" * 16385},
        ["a" * 16384] * 4,
    ],
)
def test_invalid_or_oversized_payloads_fail(value):
    with pytest.raises(GatewayDirectProtocolError, match="INVALID_PAYLOAD"):
        canonical_gateway_payload(value)


def test_payload_nesting_limit():
    value = 0
    for _ in range(17):
        value = [value]
    with pytest.raises(GatewayDirectProtocolError):
        canonical_gateway_payload(value)


def test_payload_limits_accept_valid_boundary_values():
    assert canonical_gateway_payload([0] * 4095).count("0") == 4095
    nested = 0
    for _ in range(16):
        nested = [nested]
    assert canonical_gateway_payload(nested).count("[") == 16
    assert canonical_gateway_payload([-(2**63), 2**63 - 1]) == (
        "[-9223372036854775808,9223372036854775807]"
    )
