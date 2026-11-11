"""Iteration 64 (64.02): neutral Risk service contracts."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.risk_service_protocol import (
    KILL_SWITCH_ACTIONS,
    KILL_SWITCH_SCOPES,
    RISK_REFUSAL_CODES,
    KillSwitchCommand,
    RiskOrderResult,
    RiskOrderView,
    RiskParentView,
    RiskServiceProtocolError,
    canonical_risk_json,
    risk_digest,
)

RB = MarketInstrumentKey("ctp", "SHFE", "simnow", "future", "rb2701", "rb2701")


def _view(**changes):
    base = {
        "account_scope": "acct-hash",
        "route": "CTP___FUTURE",
        "strategy_ref": "11111111-2222-3333-4444-555555555555",
        "origin": "strategy",
        "request_key": "11111111-2222-3333-4444-555555555555:7",
        "instrument": RB,
        "side": "BUY",
        "offset": "OPEN",
        "position_side": "NET",
        "quantity": Decimal("2"),
        "quantity_unit": "lots",
        "order_type": "LIMIT",
        "limit_price": Decimal("3500"),
        "time_in_force": "DAY",
        "trading_day": "20261112",
        "session_epoch": "s-1",
    }
    base.update(changes)
    return RiskOrderView(**base)


def test_view_roundtrip_keeps_exact_decimals_and_digest():
    view = _view(quantity=Decimal("2.50"), limit_price=Decimal("3500.0"))
    mapping = view.to_mapping()
    assert mapping["quantity"] == "2.5" and mapping["limit_price"] == "3500"
    again = RiskOrderView.from_mapping(json.loads(json.dumps(mapping)))
    assert again == view and again.digest() == view.digest()
    assert type(again.quantity) is Decimal and again.quantity == Decimal("2.5")


def test_view_digest_changes_with_any_semantic_field():
    view = _view()
    for change in (
        {"side": "SELL"},
        {"offset": "CLOSE"},
        {"quantity": Decimal("3")},
        {"limit_price": Decimal("3501")},
        {"request_key": "other:1"},
        {"order_type": "MARKET"},
    ):
        assert replace(view, **change).digest() != view.digest()


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": Decimal("0")},
        {"quantity": Decimal("-1")},
        {"quantity": Decimal("NaN")},
        {"quantity": 2},
        {"quantity": 2.0},
        {"limit_price": Decimal("0")},
        {"limit_price": 3500.0},
        {"side": "buy"},
        {"offset": "open"},
        {"position_side": "BOTH"},
        {"origin": "risk"},
        {"trading_day": "2026-11-12"},
        {"request_key": " padded"},
        {"strategy_ref": ""},
        {"parent_ref": "p-1"},
        {"origin": "execution"},
    ],
)
def test_view_rejects_invalid_values_with_a_finite_code(change):
    with pytest.raises(RiskServiceProtocolError) as error:
        _view(**change)
    assert error.value.code == "RISK_VIEW_INVALID"


def test_empty_optional_fields_mean_unknown_not_zero():
    view = _view(
        limit_price=None,
        order_type="MARKET",
        offset=None,
        time_in_force=None,
        trading_day=None,
        session_epoch=None,
    )
    mapping = view.to_mapping()
    assert (
        mapping["limit_price"] is None
        and mapping["offset"] is None
        and mapping["trading_day"] is None
    )
    assert RiskOrderView.from_mapping(mapping) == view
    assert not view.is_close and _view(offset="CLOSE_TODAY").is_close


def test_execution_child_requires_parent_identity():
    child = _view(origin="execution", parent_ref="parent-1", child_id="child-1")
    assert RiskOrderView.from_mapping(child.to_mapping()) == child


def test_view_from_mapping_rejects_unknown_or_missing_keys_and_float_numbers():
    mapping = _view().to_mapping()
    for broken in (
        {**mapping, "extra": 1},
        {k: v for k, v in mapping.items() if k != "route"},
        {**mapping, "quantity": 2},
        {**mapping, "schema": "other"},
        {**mapping, "quantity": "abc"},
    ):
        with pytest.raises(RiskServiceProtocolError):
            RiskOrderView.from_mapping(broken)


def test_result_codes_are_finite_and_denied_requires_a_code():
    result = RiskOrderResult(
        "k:1",
        "DENIED",
        state="DENIED",
        code="risk_order_quantity_exceeds_cap",
        policy_version="p-1",
        view_digest=_view().digest(),
    )
    assert result.definite_refusal
    assert RiskOrderResult.from_mapping(json.loads(json.dumps(result.to_mapping()))) == result
    with pytest.raises(RiskServiceProtocolError):
        RiskOrderResult("k:1", "DENIED")
    with pytest.raises(RiskServiceProtocolError):
        RiskOrderResult("k:1", "DENIED", code="made_up_code")
    with pytest.raises(RiskServiceProtocolError):
        RiskOrderResult("k:1", "MAYBE")
    unknown = RiskOrderResult("k:1", "UNKNOWN", state="UNKNOWN", permit_id="p", reservation_id="r")
    assert not unknown.definite_refusal


def test_refusal_codes_cover_plan_names():
    for code in (
        "risk_order_quantity_exceeds_cap",
        "risk_order_notional_exceeds_cap",
        "risk_price_band_exceeded",
        "risk_position_limit_exceeded",
        "risk_order_count_limit",
        "risk_self_trade",
        "risk_self_trade_unverifiable",
        "risk_duplicate_order",
        "risk_loss_limit",
        "risk_pnl_unknown",
        "risk_instrument_facts_unavailable",
        "risk_position_facts_unavailable",
        "risk_closable_unverified",
        "risk_limit_unconfigured",
        "risk_breach_latched",
        "risk_requires_gateway",
        "risk_unavailable",
        "risk_parent_envelope_exceeded",
    ):
        assert code in RISK_REFUSAL_CODES
    assert all(code == code.lower() and code.startswith("risk_") for code in RISK_REFUSAL_CODES)


def test_parent_view_roundtrip_and_bounds():
    parent = RiskParentView(
        "acct-hash",
        "CTP___FUTURE",
        "strategy-a",
        "parent-1",
        RB,
        "SELL",
        "CLOSE_TODAY",
        "LONG",
        Decimal("5"),
        "lots",
        None,
        "20261111",
        "20261112",
    )
    assert RiskParentView.from_mapping(json.loads(json.dumps(parent.to_mapping()))) == parent
    with pytest.raises(RiskServiceProtocolError):
        replace(parent, valid_until_trading_day="20261110")
    with pytest.raises(RiskServiceProtocolError):
        replace(parent, total_quantity=Decimal("0"))


def test_kill_switch_vocabulary_matches_gateway_strings():
    assert {"FREEZE", "STOP_NEW", "DRAIN", "RESUME"} == KILL_SWITCH_ACTIONS
    assert {"account", "strategy", "instrument"} == KILL_SWITCH_SCOPES
    command = KillSwitchCommand(
        "cmd-1", "STOP_NEW", "instrument", "SHFE.rb2701", "risk_order_count_limit", "risk"
    )
    assert command.to_mapping()["scope_value"] == "SHFE.rb2701"
    with pytest.raises(RiskServiceProtocolError):
        KillSwitchCommand("cmd-1", "STOP_NEW", "account", "x", "r", "risk")
    with pytest.raises(RiskServiceProtocolError):
        KillSwitchCommand("cmd-1", "PAUSE", "account", "", "r", "risk")


def test_canonical_json_refuses_floats_and_sorts_keys():
    assert canonical_risk_json({"b": 1, "a": "x"}) == '{"a":"x","b":1}'
    assert len(risk_digest({"a": "x"})) == 64
    with pytest.raises(RiskServiceProtocolError):
        canonical_risk_json({"a": 1.5})
