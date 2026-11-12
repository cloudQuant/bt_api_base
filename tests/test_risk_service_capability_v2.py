"""Structural Risk v2 checks; these DTOs alone do not authorize a write."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from bt_api_base.risk_service_capability_v2 import (
    RISK_DISPATCH_REQUEST_V2_SCHEMA,
    RISK_RESERVE_REPLY_V2_SCHEMA,
    RiskDispatchRequestV2,
    RiskReserveReplyV2,
)
from bt_api_base.risk_service_protocol import (
    RiskOrderResult,
    RiskServiceProtocolError,
    canonical_risk_json,
)

CAPABILITY = "1f" * 32  # synthetic syntax fixture, not an issued credential
VIEW_DIGEST = "2a" * 32


def reserved(**changes):
    values = {
        "request_key": "request-1",
        "outcome": "RESERVED",
        "state": "RESERVED",
        "permit_id": "permit-1",
        "reservation_id": "reservation-1",
        "view_digest": VIEW_DIGEST,
    }
    values.update(changes)
    return RiskOrderResult(**values)


def request(**changes):
    values = {
        "request_key": "request-1",
        "permit_id": "permit-1",
        "reservation_id": "reservation-1",
        "view_digest": VIEW_DIGEST,
        "dispatch_capability": CAPABILITY,
    }
    values.update(changes)
    return RiskDispatchRequestV2(**values)


def test_reserve_reply_round_trips_without_exposing_capability_in_repr():
    reply = RiskReserveReplyV2(reserved(), CAPABILITY)
    assert CAPABILITY not in repr(reply)
    wire = reply.to_mapping()
    assert wire["schema"] == RISK_RESERVE_REPLY_V2_SCHEMA
    assert wire["schema_version"] == 2
    assert wire["dispatch_capability"] == CAPABILITY
    assert RiskReserveReplyV2.from_mapping(json.loads(json.dumps(wire))) == reply
    wire["result"]["request_key"] = "other"
    assert reply.result.request_key == "request-1"


def test_dispatch_round_trip_and_repr_redaction():
    item = request()
    assert CAPABILITY not in repr(item)
    wire = item.to_mapping()
    assert wire["schema"] == RISK_DISPATCH_REQUEST_V2_SCHEMA
    assert wire["schema_version"] == 2
    assert wire["dispatch_capability"] == CAPABILITY
    assert RiskDispatchRequestV2.from_mapping(json.loads(json.dumps(wire))) == item


@pytest.mark.parametrize(
    "bad",
    [None, "", "0" * 63, "0" * 65, "F" * 64, "g" * 64, "１" * 64, True, b"0" * 64],
)
def test_reserved_reply_and_dispatch_reject_malformed_capabilities_without_echo(bad):
    for construct in (
        lambda: RiskReserveReplyV2(reserved(), bad),
        lambda: request(dispatch_capability=bad),
    ):
        with pytest.raises(RiskServiceProtocolError) as error:
            construct()
        assert str(error.value) in {
            "RISK_V2_RESERVE_REPLY_INVALID",
            "RISK_V2_DISPATCH_REQUEST_INVALID",
        }
        assert CAPABILITY not in str(error.value)


@pytest.mark.parametrize("outcome", ["UNKNOWN", "DENIED", "DISPATCHED", "RELEASED", "TERMINAL"])
def test_non_reserved_reply_cannot_carry_capability(outcome):
    state = outcome if outcome in ("DISPATCHED", "RELEASED", "TERMINAL") else None
    result = RiskOrderResult(
        "request-1", outcome, state=state, code="risk_unavailable" if outcome == "DENIED" else None
    )
    assert RiskReserveReplyV2.from_mapping(RiskReserveReplyV2(result).to_mapping()).result == result
    with pytest.raises(RiskServiceProtocolError, match="RISK_V2_RESERVE_REPLY_INVALID"):
        RiskReserveReplyV2(result, CAPABILITY)


@pytest.mark.parametrize(
    "state",
    [
        "RESERVING",
        "RESERVED",
        "CLAIMED",
        "DISPATCHED",
        "RELEASING",
        "RELEASED",
        "UNKNOWN",
        "TERMINAL",
    ],
)
def test_reserve_denial_cannot_describe_another_permit_state(state):
    denied = RiskOrderResult("request-1", "DENIED", state=state, code="risk_unavailable")
    with pytest.raises(RiskServiceProtocolError, match="RISK_V2_RESERVE_REPLY_INVALID"):
        RiskReserveReplyV2(denied)
    wire = RiskReserveReplyV2(
        RiskOrderResult("request-1", "DENIED", state="DENIED", code="risk_unavailable")
    ).to_mapping()
    wire["result"]["state"] = state
    with pytest.raises(RiskServiceProtocolError, match="RISK_V2_RESERVE_REPLY_INVALID"):
        RiskReserveReplyV2.from_mapping(wire)


@pytest.mark.parametrize("state", [None, "DENIED"])
def test_reserve_denial_accepts_only_its_own_state_or_none(state):
    denied = RiskOrderResult("request-1", "DENIED", state=state, code="risk_unavailable")
    reply = RiskReserveReplyV2(denied)
    assert RiskReserveReplyV2.from_mapping(reply.to_mapping()) == reply


@pytest.mark.parametrize(
    "state,permit_id,reservation_id",
    [
        (None, "permit-1", None),
        (None, None, "reservation-1"),
        (None, "permit-1", "reservation-1"),
        ("DENIED", None, "reservation-1"),
        ("DENIED", "permit-1", "reservation-1"),
    ],
)
def test_denial_cannot_claim_a_gateway_reservation_or_unpersisted_permit(
    state, permit_id, reservation_id
):
    denied = RiskOrderResult(
        "request-1",
        "DENIED",
        state=state,
        permit_id=permit_id,
        reservation_id=reservation_id,
        code="risk_gateway_refused",
    )
    with pytest.raises(RiskServiceProtocolError, match="RISK_V2_RESERVE_REPLY_INVALID"):
        RiskReserveReplyV2(denied)
    wire = RiskReserveReplyV2(
        RiskOrderResult("request-1", "DENIED", code="risk_gateway_refused")
    ).to_mapping()
    wire["result"].update(state=state, permit_id=permit_id, reservation_id=reservation_id)
    with pytest.raises(RiskServiceProtocolError, match="RISK_V2_RESERVE_REPLY_INVALID"):
        RiskReserveReplyV2.from_mapping(wire)


@pytest.mark.parametrize("state,permit_id", [(None, None), ("DENIED", None), ("DENIED", "p-1")])
def test_denial_retains_gateway_refusal_metadata_without_gateway_reservation(state, permit_id):
    denied = RiskOrderResult(
        "request-1",
        "DENIED",
        state=state,
        permit_id=permit_id,
        code="risk_gateway_refused",
        gateway_code="gateway_refused",
        gateway_state="DENIED",
    )
    reply = RiskReserveReplyV2(denied)
    restored = RiskReserveReplyV2.from_mapping(reply.to_mapping())
    assert restored.result == denied
    assert restored.result.gateway_code == "gateway_refused"
    assert restored.result.gateway_state == "DENIED"


@pytest.mark.parametrize(
    "state",
    [
        None,
        "RESERVING",
        "RESERVED",
        "CLAIMED",
        "DISPATCHED",
        "RELEASING",
        "RELEASED",
        "DENIED",
        "UNKNOWN",
        "TERMINAL",
    ],
)
def test_unknown_can_preserve_any_prior_state_without_capability(state):
    unknown = RiskOrderResult("request-1", "UNKNOWN", state=state)
    reply = RiskReserveReplyV2(unknown)
    assert RiskReserveReplyV2.from_mapping(reply.to_mapping()) == reply
    with pytest.raises(RiskServiceProtocolError, match="RISK_V2_RESERVE_REPLY_INVALID"):
        RiskReserveReplyV2(unknown, CAPABILITY)


@pytest.mark.parametrize("outcome", ["DISPATCHED", "RELEASED", "TERMINAL"])
@pytest.mark.parametrize(
    "state",
    [
        None,
        "RESERVING",
        "RESERVED",
        "CLAIMED",
        "DISPATCHED",
        "RELEASING",
        "RELEASED",
        "DENIED",
        "UNKNOWN",
        "TERMINAL",
    ],
)
def test_observed_result_requires_its_matching_state(outcome, state):
    result = RiskOrderResult("request-1", outcome, state=state)
    if state == outcome:
        reply = RiskReserveReplyV2(result)
        assert RiskReserveReplyV2.from_mapping(reply.to_mapping()) == reply
    else:
        with pytest.raises(RiskServiceProtocolError, match="RISK_V2_RESERVE_REPLY_INVALID"):
            RiskReserveReplyV2(result)


@pytest.mark.parametrize("outcome", ["DISPATCHED", "RELEASED", "TERMINAL"])
def test_observed_result_cannot_also_be_a_refusal(outcome):
    result = RiskOrderResult("request-1", outcome, state=outcome, code="risk_unavailable")
    with pytest.raises(RiskServiceProtocolError, match="RISK_V2_RESERVE_REPLY_INVALID"):
        RiskReserveReplyV2(result)


@pytest.mark.parametrize(
    "changes",
    [
        {"state": None},
        {"state": "UNKNOWN"},
        {"permit_id": None},
        {"reservation_id": None},
        {"view_digest": None},
        {"code": "risk_unavailable"},
    ],
)
def test_reserved_reply_needs_complete_identity_and_non_refusal(changes):
    with pytest.raises(RiskServiceProtocolError, match="RISK_V2_RESERVE_REPLY_INVALID"):
        RiskReserveReplyV2(reserved(**changes), CAPABILITY)


def test_status_result_is_not_a_capability_reply_and_v1_codec_rejects_v2():
    status = RiskOrderResult("request-1", "RESERVED", state="RESERVED", permit_id="permit-1")
    with pytest.raises(RiskServiceProtocolError):
        RiskReserveReplyV2.from_mapping(status.to_mapping())
    with pytest.raises(RiskServiceProtocolError):
        RiskOrderResult.from_mapping(RiskReserveReplyV2(reserved(), CAPABILITY).to_mapping())
    with pytest.raises(RiskServiceProtocolError):
        RiskReserveReplyV2(RiskOrderResult("request-1", "NOT_FOUND"))


@pytest.mark.parametrize("version", [True, 1, 3, "2", None])
def test_both_v2_messages_reject_invalid_versions(version):
    with pytest.raises(RiskServiceProtocolError):
        RiskReserveReplyV2(reserved(), CAPABILITY, schema_version=version)
    with pytest.raises(RiskServiceProtocolError):
        request(schema_version=version)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("request_key", ""),
        ("request_key", " padded"),
        ("permit_id", None),
        ("reservation_id", "with\nnewline"),
        ("view_digest", "a" * 63),
        ("view_digest", "A" * 64),
        ("dispatch_capability", CAPABILITY.upper()),
    ],
)
def test_dispatch_rejects_invalid_identity_and_digest(field, bad):
    with pytest.raises(RiskServiceProtocolError, match="RISK_V2_DISPATCH_REQUEST_INVALID"):
        request(**{field: bad})


@pytest.mark.parametrize("kind", ["reserve", "dispatch"])
def test_codec_rejects_extra_missing_and_wrong_schema(kind):
    item = RiskReserveReplyV2(reserved(), CAPABILITY) if kind == "reserve" else request()
    parse = (
        RiskReserveReplyV2.from_mapping if kind == "reserve" else RiskDispatchRequestV2.from_mapping
    )
    wire = item.to_mapping()
    for malformed in (
        {**wire, "extra": 1},
        {key: value for key, value in wire.items() if key != "dispatch_capability"},
        {**wire, "schema": "other"},
        {**wire, "schema_version": True},
        [],
    ):
        with pytest.raises(RiskServiceProtocolError):
            parse(malformed)


def test_malformed_nested_v1_result_has_finite_error_without_untrusted_value():
    wire = RiskReserveReplyV2(reserved(), CAPABILITY).to_mapping()
    wire["result"]["outcome"] = ["untrusted-secret"]
    with pytest.raises(RiskServiceProtocolError) as error:
        RiskReserveReplyV2.from_mapping(wire)
    assert str(error.value) == "RISK_V2_RESERVE_REPLY_INVALID"
    assert "untrusted-secret" not in str(error.value)


def test_v1_mapping_and_canonical_representation_are_unchanged():
    result = RiskOrderResult("key-1", "DENIED", state="DENIED", code="risk_unavailable")
    expected = {
        "schema": "bt_api.risk_service.v1",
        "schema_version": 1,
        "request_key": "key-1",
        "outcome": "DENIED",
        "state": "DENIED",
        "permit_id": None,
        "reservation_id": None,
        "code": "risk_unavailable",
        "gateway_code": None,
        "gateway_state": None,
        "policy_version": None,
        "view_digest": None,
    }
    assert result.to_mapping() == expected
    assert canonical_risk_json(result.to_mapping()) == canonical_risk_json(expected)
    assert RiskOrderResult.from_mapping(expected) == result
    assert replace(result, code="risk_request_invalid").to_mapping()["schema_version"] == 1
