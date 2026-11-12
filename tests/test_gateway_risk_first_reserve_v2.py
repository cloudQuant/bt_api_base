"""Wire shape checks only: no DTO here proves first insertion or authority."""

from __future__ import annotations

import hashlib
import json
import traceback
from dataclasses import replace

import pytest

from bt_api_base.gateway_delegation_protocol import GatewayDelegatedCommand
from bt_api_base.gateway_risk_first_reserve_v2 import (
    RISK_FIRST_RESERVE_NONCE_DOMAIN,
    GatewayRiskFirstReserveRequestV2,
    GatewayRiskFirstReserveResultV2,
    GatewayRiskFirstReserveV2Error,
    risk_first_reserve_nonce_digest,
)
from bt_api_base.market_protocol import MarketInstrumentKey

NONCE = b"n" * 32  # synthetic only, not generated entropy
NONCE_DIGEST = risk_first_reserve_nonce_digest(NONCE)
PAYLOAD_DIGEST = "ab" * 32
VIEW_DIGEST = "cd" * 32


def command(**changes):
    values = {
        "account_scope": "account-a",
        "strategy_scope": "strategy-a",
        "execution_domain_ref": "domain-a",
        "actor_principal": "risk-principal",
        "actor_ref": "risk-actor",
        "actor_kind": "risk",
        "run_id": "run-a",
        "request_key": "request-a",
        "payload_digest": PAYLOAD_DIGEST,
        "instrument": MarketInstrumentKey("ctp", "SHFE", "simnow", "future", "rb2701", "rb2701"),
        "grant_revision": "grant-a",
    }
    values.update(changes)
    return GatewayDelegatedCommand(**values)


def request(**changes):
    values = {
        "command": command(),
        "risk_service_id": "risk-service-a",
        "risk_instance_id": "risk-instance-a",
        "strategy_principal": "strategy-principal-a",
        "risk_registration_id": "registration-a",
        "risk_service_epoch": "epoch-a",
        "risk_permit_id": "permit-a",
        "risk_view_digest": VIEW_DIGEST,
        "attempt_nonce_digest": NONCE_DIGEST,
        "requested_ttl_ms": 5000,
    }
    values.update(changes)
    return GatewayRiskFirstReserveRequestV2(**values)


def result(**changes):
    original = request()
    values = {
        "request_commitment_digest": original.digest,
        "journal_id": "journal-a",
        "owner_generation": "generation-a",
        "reservation_generation": "generation-a",
        "account_scope": original.command.account_scope,
        "strategy_scope": original.command.strategy_scope,
        "execution_domain_ref": original.command.execution_domain_ref,
        "run_id": original.command.run_id,
        "request_key": original.command.request_key,
        "reservation_id": "reservation-a",
        "payload_digest": original.command.payload_digest,
        "remaining_ttl_ms": 1200,
    }
    values.update(changes)
    return GatewayRiskFirstReserveResultV2(**values)


def test_nonce_digest_is_exact_and_domain_separated_without_persisting_nonce():
    assert RISK_FIRST_RESERVE_NONCE_DOMAIN == b"bt_api.gateway.risk-first-reserve.v2\x00"
    assert NONCE_DIGEST == "9df8e60c0e5e173176241bb094aac56d3b6c4cb63026c2af58cb126fee2501eb"
    assert hashlib.sha256(RISK_FIRST_RESERVE_NONCE_DOMAIN + NONCE).hexdigest() == NONCE_DIGEST
    assert hashlib.sha256(NONCE).hexdigest() != NONCE_DIGEST
    wire = request().to_mapping()
    assert wire["attempt_nonce_digest"] == NONCE_DIGEST
    assert "nonce" not in wire
    assert "dispatch_capability" not in wire
    assert NONCE.decode() not in json.dumps(wire)


@pytest.mark.parametrize("bad", [None, "a" * 32, b"", b"x" * 31, b"x" * 33, bytearray(32), True])
def test_nonce_helper_rejects_non_exact_bytes_without_echo(bad):
    with pytest.raises(GatewayRiskFirstReserveV2Error) as error:
        risk_first_reserve_nonce_digest(bad)
    assert str(error.value) == "INVALID_RISK_FIRST_RESERVE_NONCE"


def test_request_mapping_roundtrip_commitment_and_redacted_repr():
    initial = request()
    wire = initial.to_mapping()
    reloaded = GatewayRiskFirstReserveRequestV2.from_mapping(json.loads(json.dumps(wire)))
    assert reloaded == initial
    assert reloaded.digest == initial.digest and len(initial.digest) == 64
    assert initial.digest == "d586650caba04a3d6959d2090a455023509f3a96468f19245d828d0f58419eae"
    assert reloaded.command.to_mapping() == command().to_mapping()
    assert set(wire).isdisjoint(
        {"account_scope", "strategy_scope", "run_id", "request_key", "payload_digest"}
    )
    for sensitive in ("account-a", "strategy-principal-a", VIEW_DIGEST, NONCE_DIGEST):
        assert sensitive not in repr(initial)
        assert sensitive not in repr({"nested": [initial]})


@pytest.mark.parametrize(
    "field,value",
    [
        ("risk_service_id", "risk-service-b"),
        ("risk_instance_id", "risk-instance-b"),
        ("strategy_principal", "strategy-principal-b"),
        ("risk_registration_id", "registration-b"),
        ("risk_service_epoch", "epoch-b"),
        ("risk_permit_id", "permit-b"),
        ("risk_view_digest", "ef" * 32),
        ("attempt_nonce_digest", "12" * 32),
        ("requested_ttl_ms", 5001),
    ],
)
def test_request_commitment_changes_with_each_binding(field, value):
    original = request()
    assert replace(original, **{field: value}).digest != original.digest


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_scope", "account-b"),
        ("strategy_scope", "strategy-b"),
        ("execution_domain_ref", "domain-b"),
        ("actor_principal", "risk-principal-b"),
        ("actor_ref", "risk-actor-b"),
        ("run_id", "run-b"),
        ("request_key", "request-b"),
        ("payload_digest", "34" * 32),
        ("instrument", MarketInstrumentKey("ctp", "DCE", "simnow", "future", "rb2701", "rb2701")),
        ("grant_revision", "grant-b"),
    ],
)
def test_request_commitment_changes_with_each_nested_scope_binding(field, value):
    original = request()
    assert (
        replace(original, command=replace(original.command, **{field: value})).digest
        != original.digest
    )


def test_request_commitment_binds_parent_and_child_when_present():
    original = request()
    changed = replace(original.command, parent_ref="parent-a", child_id="child-a")
    assert replace(original, command=changed).digest != original.digest


@pytest.mark.parametrize(
    "field,bad",
    [
        ("risk_service_id", ""),
        ("risk_instance_id", " padded"),
        ("strategy_principal", None),
        ("risk_registration_id", "line\nbreak"),
        ("risk_service_epoch", "x" * 257),
        ("risk_permit_id", True),
        ("risk_view_digest", "F" * 64),
        ("attempt_nonce_digest", "0" * 63),
        ("requested_ttl_ms", 0),
        ("requested_ttl_ms", 30001),
        ("requested_ttl_ms", True),
        ("requested_ttl_ms", 1.0),
        ("schema_version", True),
        ("schema_version", 1),
        ("command", None),
    ],
)
def test_invalid_request_fields_raise_finite_error_without_value(field, bad):
    with pytest.raises(GatewayRiskFirstReserveV2Error) as error:
        request(**{field: bad})
    assert str(error.value) == "INVALID_RISK_FIRST_RESERVE_REQUEST"
    assert VIEW_DIGEST not in repr(error.value)


def test_request_requires_risk_actor_not_execution_actor():
    other = command(actor_kind="execution", parent_ref="parent-a", child_id="child-a")
    with pytest.raises(GatewayRiskFirstReserveV2Error):
        request(command=other)


def test_request_wire_shape_refuses_extra_secret_or_contradictory_nested_command():
    wire = request().to_mapping()
    bad_values = [
        {**wire, "nonce": NONCE.hex()},
        {**wire, "dispatch_capability": "e0" * 32},
        {**wire, "run_id": "another-run"},
        {key: value for key, value in wire.items() if key != "risk_registration_id"},
        {key: value for key, value in wire.items() if key != "requested_ttl_ms"},
        {**wire, "schema": "wrong"},
        {**wire, "command": {**wire["command"], "origin": "risk:wrong"}},
        {**wire, "command": {**wire["command"], "unrecognized": 1}},
        {**wire, "command": []},
        [],
    ]
    for bad in bad_values:
        with pytest.raises(GatewayRiskFirstReserveV2Error) as error:
            GatewayRiskFirstReserveRequestV2.from_mapping(bad)
        assert str(error.value) == "INVALID_RISK_FIRST_RESERVE_REQUEST"


def test_result_roundtrip_matches_request_and_hides_identities_in_repr():
    original = result()
    wire = original.to_mapping()
    restored = GatewayRiskFirstReserveResultV2.from_mapping(json.loads(json.dumps(wire)))
    assert restored == original
    assert restored.digest == original.digest and len(original.digest) == 64
    assert original.digest == "b957861eadfbb988f4c9ac6116d65a5c3faed04227037101079f4d69d50b7cf9"
    assert restored.matches_request(request())
    assert GatewayRiskFirstReserveResultV2.from_mapping_for_request(wire, request()) == original
    assert not restored.matches_request(None)
    assert "dispatch_capability" not in wire and "nonce" not in wire
    for sensitive in ("account-a", "strategy-a", "journal-a", PAYLOAD_DIGEST, original.digest):
        assert sensitive not in repr(original)
        assert sensitive not in repr({"nested": [original]})


@pytest.mark.parametrize("value_factory", [request, result])
def test_nested_exception_does_not_expose_object_claims(value_factory):
    value = value_factory()
    try:
        raise RuntimeError("synthetic failure", {"nested": [value]})
    except RuntimeError as error:
        rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        for sensitive in ("account-a", "strategy-a", "request-a", PAYLOAD_DIGEST, value.digest):
            assert sensitive not in str(error)
            assert sensitive not in repr(error)
            assert sensitive not in rendered


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("request_commitment_digest", "99" * 32),
        ("account_scope", "account-b"),
        ("strategy_scope", "strategy-b"),
        ("execution_domain_ref", "domain-b"),
        ("run_id", "run-b"),
        ("request_key", "request-b"),
        ("payload_digest", "98" * 32),
    ],
)
def test_result_does_not_match_conflicting_request_fields(field, wrong):
    original = result()
    altered = replace(original, **{field: wrong})
    assert not altered.matches_request(request())
    assert altered.digest != original.digest
    with pytest.raises(GatewayRiskFirstReserveV2Error, match="RISK_FIRST_RESERVE_REQUEST_MISMATCH"):
        GatewayRiskFirstReserveResultV2.from_mapping_for_request(altered.to_mapping(), request())


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("risk_service_id", "risk-service-b"),
        ("risk_instance_id", "risk-instance-b"),
        ("strategy_principal", "strategy-principal-b"),
        ("risk_registration_id", "registration-b"),
        ("risk_service_epoch", "epoch-b"),
        ("risk_permit_id", "permit-b"),
        ("risk_view_digest", "ef" * 32),
        ("attempt_nonce_digest", "12" * 32),
        ("requested_ttl_ms", 5001),
    ],
)
def test_result_commitment_binds_nonduplicated_request_fields(field, wrong):
    assert not result().matches_request(replace(request(), **{field: wrong}))
    with pytest.raises(GatewayRiskFirstReserveV2Error, match="RISK_FIRST_RESERVE_REQUEST_MISMATCH"):
        GatewayRiskFirstReserveResultV2.from_mapping_for_request(
            result().to_mapping(), replace(request(), **{field: wrong})
        )


@pytest.mark.parametrize("ttl", [1, 2, 29999, 30000])
def test_request_ttl_accepts_positive_bounded_integer_ms(ttl):
    assert request(requested_ttl_ms=ttl).requested_ttl_ms == ttl


@pytest.mark.parametrize("ttl", [None, True, False, 0, -1, 30001, 1.0, float("nan"), "1"])
def test_request_ttl_rejects_noninteger_and_out_of_range_values(ttl):
    with pytest.raises(GatewayRiskFirstReserveV2Error, match="INVALID_RISK_FIRST_RESERVE_REQUEST"):
        request(requested_ttl_ms=ttl)


@pytest.mark.parametrize("remaining", [1, 4999, 5000])
def test_result_ttl_at_or_below_requested_limit_matches(remaining):
    assert result(remaining_ttl_ms=remaining).matches_request(request())


@pytest.mark.parametrize("ttl", [1, 30000])
def test_result_ttl_matches_request_at_protocol_boundaries(ttl):
    original = request(requested_ttl_ms=ttl)
    reply = result(request_commitment_digest=original.digest, remaining_ttl_ms=ttl)
    assert (
        GatewayRiskFirstReserveResultV2.from_mapping_for_request(reply.to_mapping(), original)
        == reply
    )


@pytest.mark.parametrize("remaining", [5001, 30000])
def test_result_ttl_above_requested_limit_fails_bound_decode(remaining):
    response = result(remaining_ttl_ms=remaining)
    assert not response.matches_request(request())
    with pytest.raises(GatewayRiskFirstReserveV2Error, match="RISK_FIRST_RESERVE_REQUEST_MISMATCH"):
        GatewayRiskFirstReserveResultV2.from_mapping_for_request(response.to_mapping(), request())


def test_bound_decode_requires_original_request():
    with pytest.raises(GatewayRiskFirstReserveV2Error, match="RISK_FIRST_RESERVE_REQUEST_MISMATCH"):
        GatewayRiskFirstReserveResultV2.from_mapping_for_request(result().to_mapping(), None)


@pytest.mark.parametrize("ttl", [1, 2, 29999, 30000])
def test_result_ttl_accepts_only_positive_bounded_integer_ms(ttl):
    assert result(remaining_ttl_ms=ttl).remaining_ttl_ms == ttl


@pytest.mark.parametrize("ttl", [None, True, False, 0, -1, 30001, 1.0, float("nan"), "1"])
def test_result_ttl_rejects_expired_noninteger_and_out_of_range_values(ttl):
    with pytest.raises(GatewayRiskFirstReserveV2Error) as error:
        result(remaining_ttl_ms=ttl)
    assert str(error.value) == "INVALID_RISK_FIRST_RESERVE_RESULT"


@pytest.mark.parametrize(
    "field,bad",
    [
        ("schema_version", 1),
        ("schema_version", True),
        ("version", 2),
        ("version", True),
        ("state", "DISPATCHING"),
        ("state", "UNKNOWN"),
        ("owner_generation", "generation-b"),
        ("reservation_generation", "generation-b"),
        ("journal_id", ""),
        ("account_scope", " padded"),
        ("strategy_scope", "x" * 257),
        ("execution_domain_ref", None),
        ("run_id", "line\nbreak"),
        ("request_key", True),
        ("reservation_id", ""),
        ("payload_digest", "G" * 64),
        ("request_commitment_digest", "1" * 63),
    ],
)
def test_result_rejects_invalid_fields_with_value_free_error(field, bad):
    with pytest.raises(GatewayRiskFirstReserveV2Error) as error:
        result(**{field: bad})
    assert str(error.value) == "INVALID_RISK_FIRST_RESERVE_RESULT"
    assert "account-a" not in repr(error.value)
    assert PAYLOAD_DIGEST not in repr(error.value)


def test_result_wire_shape_rejects_duplicate_secret_and_wrong_schema_fields():
    wire = result().to_mapping()
    bad_values = [
        {**wire, "nonce": NONCE.hex()},
        {**wire, "dispatch_capability": "e0" * 32},
        {**wire, "extra": "x"},
        {key: value for key, value in wire.items() if key != "run_id"},
        {**wire, "schema": "wrong"},
        {**wire, "state": "RELEASED"},
        {**wire, "version": 2},
        [],
    ]
    for bad in bad_values:
        with pytest.raises(GatewayRiskFirstReserveV2Error) as error:
            GatewayRiskFirstReserveResultV2.from_mapping(bad)
        assert str(error.value) == "INVALID_RISK_FIRST_RESERVE_RESULT"
