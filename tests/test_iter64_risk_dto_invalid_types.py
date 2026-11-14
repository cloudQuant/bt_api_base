"""Pure in-memory checks for the Risk DTO wire and constructor boundaries."""

import json
from dataclasses import replace
from decimal import Decimal

import pytest

import bt_api_base.risk_service_protocol as protocol
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.risk_service_protocol import (
    OFFSETS,
    ORIGINS,
    POSITION_SIDES,
    RISK_OUTCOMES,
    RISK_PERMIT_STATES,
    RISK_REFUSAL_CODES,
    SIDES,
    RiskOrderResult,
    RiskOrderView,
    RiskParentView,
    RiskServiceProtocolError,
)


INSTRUMENT = MarketInstrumentKey("ctp", "SHFE", "simnow", "future", "rb2701", "rb2701")
ORDER = RiskOrderView(
    "acct-hash", "CTP___FUTURE", "strategy-a", "strategy", "request-1", INSTRUMENT,
    "BUY", "OPEN", "NET", Decimal("2"), "lots", "LIMIT", Decimal("3500"),
)
PARENT = RiskParentView(
    "acct-hash", "CTP___FUTURE", "strategy-a", "parent-1", INSTRUMENT,
    "BUY", "OPEN", "NET", Decimal("2"), "lots", Decimal("3500"),
    "20261111", "20261112",
)


@pytest.mark.parametrize("view", [ORDER, PARENT], ids=["order", "parent"])
@pytest.mark.parametrize(
    "field,value",
    [("side", value) for value in sorted(SIDES)]
    + [("position_side", value) for value in sorted(POSITION_SIDES)]
    + [("offset", value) for value in (None, *sorted(OFFSETS))],
)
def test_accepted_values_round_trip_through_json(view, field, value):
    expected = replace(view, **{field: value})
    wire = json.loads(json.dumps(expected.to_mapping()))
    assert type(view).from_mapping(wire) == expected


@pytest.mark.parametrize("view,code", [(ORDER, "RISK_VIEW_INVALID"), (PARENT, "RISK_PARENT_INVALID")], ids=["order", "parent"])
@pytest.mark.parametrize("field", ["side", "position_side", "offset"])
@pytest.mark.parametrize("value", [["payload-marker"], {"payload-marker": 1}, True, False, 1, 1.5, "payload-marker"])
@pytest.mark.parametrize("entry", ["constructor", "mapping"])
def test_invalid_values_fail_with_fixed_protocol_error(view, code, field, value, entry):
    with pytest.raises(RiskServiceProtocolError) as exc:
        if entry == "constructor":
            replace(view, **{field: value})
        else:
            wire = view.to_mapping()
            wire[field] = value
            type(view).from_mapping(json.loads(json.dumps(wire)))
    assert exc.value.code == code
    assert str(exc.value) == code
    assert "payload-marker" not in str(exc.value)


@pytest.mark.parametrize("view,code", [(ORDER, "RISK_VIEW_INVALID"), (PARENT, "RISK_PARENT_INVALID")], ids=["order", "parent"])
@pytest.mark.parametrize("field", ["side", "position_side"])
@pytest.mark.parametrize("entry", ["constructor", "mapping"])
def test_required_values_reject_null(view, code, field, entry):
    with pytest.raises(RiskServiceProtocolError) as exc:
        if entry == "constructor":
            replace(view, **{field: None})
        else:
            wire = view.to_mapping()
            wire[field] = None
            type(view).from_mapping(json.loads(json.dumps(wire)))
    assert exc.value.code == str(exc.value) == code


@pytest.mark.parametrize("origin", sorted(ORIGINS))
def test_order_origin_accepted_values_round_trip(origin):
    changes = {"origin": origin}
    if origin == "execution":
        changes.update(parent_ref="parent-1", child_id="child-1")
    expected = replace(ORDER, **changes)
    assert RiskOrderView.from_mapping(json.loads(json.dumps(expected.to_mapping()))) == expected


@pytest.mark.parametrize("value", [["payload-marker"], {"payload-marker": 1}, True, False, 1, 1.5, None, "payload-marker"])
@pytest.mark.parametrize("entry", ["constructor", "mapping"])
def test_order_origin_invalid_values_fail_with_fixed_protocol_error(value, entry):
    with pytest.raises(RiskServiceProtocolError) as exc:
        if entry == "constructor":
            replace(ORDER, origin=value)
        else:
            wire = ORDER.to_mapping()
            wire["origin"] = value
            RiskOrderView.from_mapping(json.loads(json.dumps(wire)))
    assert exc.value.code == str(exc.value) == "RISK_VIEW_INVALID"
    assert "payload-marker" not in str(exc.value)


class UntrustedString(str):
    def __hash__(self):
        raise AssertionError("untrusted hash called")


@pytest.mark.parametrize("view,field", [(ORDER, "origin"), (ORDER, "side"), (ORDER, "position_side"), (ORDER, "offset"), (PARENT, "side"), (PARENT, "position_side"), (PARENT, "offset")])
def test_constructor_does_not_call_untrusted_string_subclass_hash(view, field):
    with pytest.raises(RiskServiceProtocolError):
        replace(view, **{field: UntrustedString("BUY")})


@pytest.mark.parametrize("view,field", [(ORDER, "origin"), (ORDER, "side"), (ORDER, "position_side"), (ORDER, "offset"), (PARENT, "side"), (PARENT, "position_side"), (PARENT, "offset")])
@pytest.mark.parametrize("entry", ["constructor", "mapping"])
def test_oversized_strings_are_rejected_without_echo(view, field, entry):
    value = "payload-marker" * 4096
    with pytest.raises(RiskServiceProtocolError) as exc:
        if entry == "constructor":
            replace(view, **{field: value})
        else:
            wire = view.to_mapping()
            wire[field] = value
            type(view).from_mapping(json.loads(json.dumps(wire)))
    assert str(exc.value) in ("RISK_VIEW_INVALID", "RISK_PARENT_INVALID")


@pytest.mark.parametrize("field,value", [("outcome", value) for value in sorted(RISK_OUTCOMES) if value != "DENIED"] + [("state", value) for value in (None, *sorted(RISK_PERMIT_STATES))] + [("code", value) for value in (None, *sorted(RISK_REFUSAL_CODES))])
def test_result_accepted_values_round_trip(field, value):
    result = replace(RiskOrderResult("request-1", "UNKNOWN"), **{field: value})
    assert RiskOrderResult.from_mapping(json.loads(json.dumps(result.to_mapping()))) == result


def test_result_denied_requires_and_accepts_code():
    result = RiskOrderResult("request-1", "DENIED", code="risk_unavailable")
    assert RiskOrderResult.from_mapping(json.loads(json.dumps(result.to_mapping()))) == result
    with pytest.raises(RiskServiceProtocolError):
        RiskOrderResult("request-1", "DENIED")


@pytest.mark.parametrize("field", ["outcome", "state", "code"])
@pytest.mark.parametrize("value", [["payload-marker"], {"payload-marker": 1}, True, False, 1, 1.5, "payload-marker"])
@pytest.mark.parametrize("entry", ["constructor", "mapping"])
def test_result_invalid_values_fail_with_fixed_protocol_error(field, value, entry):
    result = RiskOrderResult("request-1", "UNKNOWN")
    with pytest.raises(RiskServiceProtocolError) as exc:
        if entry == "constructor":
            replace(result, **{field: value})
        else:
            wire = result.to_mapping()
            wire[field] = value
            RiskOrderResult.from_mapping(json.loads(json.dumps(wire)))
    assert exc.value.code == str(exc.value) == "RISK_RESULT_INVALID"
    assert "payload-marker" not in str(exc.value)


def test_result_outcome_rejects_null():
    wire = RiskOrderResult("request-1", "UNKNOWN").to_mapping()
    wire["outcome"] = None
    with pytest.raises(RiskServiceProtocolError, match="^RISK_RESULT_INVALID$"):
        RiskOrderResult.from_mapping(wire)


@pytest.mark.parametrize("field", ["outcome", "state", "code"])
def test_result_does_not_call_untrusted_string_subclass_hash(field):
    with pytest.raises(RiskServiceProtocolError, match="^RISK_RESULT_INVALID$"):
        replace(RiskOrderResult("request-1", "UNKNOWN"), **{field: UntrustedString("UNKNOWN")})


@pytest.mark.parametrize(
    "values,bound",
    [
        (ORIGINS, protocol._MAX_ORIGIN_LENGTH),
        (SIDES, protocol._MAX_SIDE_LENGTH),
        (POSITION_SIDES, protocol._MAX_POSITION_SIDE_LENGTH),
        (OFFSETS, protocol._MAX_OFFSET_LENGTH),
        (RISK_OUTCOMES, protocol._MAX_OUTCOME_LENGTH),
        (RISK_PERMIT_STATES, protocol._MAX_PERMIT_STATE_LENGTH),
        (RISK_REFUSAL_CODES, protocol._MAX_REFUSAL_CODE_LENGTH),
    ],
)
def test_vocabulary_length_bound_tracks_every_declared_value(values, bound):
    assert values
    assert bound == max(map(len, values))


@pytest.mark.parametrize("field", ["outcome", "state", "code"])
@pytest.mark.parametrize("entry", ["constructor", "mapping"])
def test_result_oversized_strings_are_rejected_without_echo(field, entry):
    result = RiskOrderResult("request-1", "UNKNOWN")
    value = "payload-marker" * 4096
    with pytest.raises(RiskServiceProtocolError) as exc:
        if entry == "constructor":
            replace(result, **{field: value})
        else:
            wire = result.to_mapping()
            wire[field] = value
            RiskOrderResult.from_mapping(json.loads(json.dumps(wire)))
    assert exc.value.code == str(exc.value) == "RISK_RESULT_INVALID"
