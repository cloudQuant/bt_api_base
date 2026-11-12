"""Wire envelope object representations do not display bearer payloads."""

from __future__ import annotations

import traceback

import pytest

from bt_api_base.risk_service_capability_v2 import RiskDispatchRequestV2, RiskReserveReplyV2
from bt_api_base.risk_service_protocol import RiskOrderResult
from bt_api_base.service_protocol import (
    WireEnvelope,
    WireHeader,
    WireIdentity,
    WireMessageKind,
    WireRole,
    WireScope,
    decode_envelope,
    encode_envelope,
    envelope_to_wire_mapping,
)

CAPABILITY = "a1" * 32  # synthetic test value; not an issued credential
DIGEST = "b2" * 32


def _header(kind: WireMessageKind) -> WireHeader:
    is_reply = kind is WireMessageKind.REPLY
    return WireHeader(
        protocol_version=3,
        kind=kind,
        message_id="message-1",
        correlation_id="request-1" if is_reply else None,
        identity=WireIdentity(
            role=WireRole.SERVICE if is_reply else WireRole.STRATEGY_CLIENT,
            principal_ref="principal-a",
            actor_ref="actor-a",
        ),
        scope=WireScope(execution_domain_ref="paper:sim-a", account_ref="account-a"),
        operation="risk.order.dispatch" if not is_reply else "risk.order.reserve",
        schema_id="risk-capability-v2",
        schema_version=2,
        sent_at_utc="2026-11-13T01:02:03Z",
    )


@pytest.mark.parametrize("kind", [WireMessageKind.REQUEST, WireMessageKind.REPLY])
def test_capability_envelopes_hide_payload_in_repr_nested_repr_and_exceptions(kind):
    if kind is WireMessageKind.REQUEST:
        payload = RiskDispatchRequestV2(
            "request-1", "permit-1", "reservation-1", DIGEST, CAPABILITY
        ).to_mapping()
    else:
        result = RiskOrderResult(
            "request-1",
            "RESERVED",
            state="RESERVED",
            permit_id="permit-1",
            reservation_id="reservation-1",
            view_digest=DIGEST,
        )
        payload = {"result": RiskReserveReplyV2(result, CAPABILITY).to_mapping()}
    envelope = WireEnvelope(header=_header(kind), payload=payload)

    assert "WireEnvelope(header=" in repr(envelope)
    assert "risk.order." in repr(envelope)
    assert "payload=" not in repr(envelope)
    assert CAPABILITY not in repr(envelope)
    assert CAPABILITY not in str(envelope)
    assert CAPABILITY not in repr({"nested": [envelope]})
    try:
        raise RuntimeError("synthetic failure", envelope)
    except RuntimeError as error:
        assert CAPABILITY not in repr(error)
        assert CAPABILITY not in str(error)
        assert CAPABILITY not in "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )

    # This change protects repr only: explicit serialization still transports
    # the payload and callers must protect the resulting bytes and mappings.
    encoded = encode_envelope(envelope)
    restored = decode_envelope(encoded)
    assert restored == envelope
    assert encode_envelope(restored) == encoded
    assert envelope_to_wire_mapping(restored)["payload"] == payload
    assert CAPABILITY not in repr(restored)


def test_payload_still_participates_in_equality():
    header = _header(WireMessageKind.REQUEST)
    assert WireEnvelope(header, {"value": 1}) == WireEnvelope(header, {"value": 1})
    assert WireEnvelope(header, {"value": 1}) != WireEnvelope(header, {"value": 2})
