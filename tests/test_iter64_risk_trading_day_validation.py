"""Synthetic Risk order/parent calendar validation, not a clock attestation."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.risk_service_protocol import (
    RiskOrderView,
    RiskParentView,
    RiskServiceProtocolError,
)


INSTRUMENT = MarketInstrumentKey("ctp", "SHFE", "simnow", "future", "rb2701", "rb2701")


def _order(day="20240229"):
    return RiskOrderView(
        "account", "route", "strategy", "strategy", "request", INSTRUMENT,
        "BUY", "OPEN", "NET", Decimal("2.50"), "lots", "LIMIT", Decimal("3500.0"),
        trading_day=day,
    )


def _parent(created="20240229", expiry="20240301"):
    return RiskParentView(
        "account", "route", "strategy", "parent", INSTRUMENT,
        "SELL", "OPEN", "NET", Decimal("5.00"), "lots", Decimal("3500.0"),
        created, expiry,
    )


@pytest.mark.parametrize("day", ["00010101", "16000229", "20000229", "20240229", "99991231"])
def test_valid_order_and_parent_days_roundtrip(day):
    order = _order(day)
    parent = _parent(day, day)
    for view, key in ((order, "trading_day"), (parent, "created_trading_day")):
        mapping = view.to_mapping()
        assert mapping[key] == day
        result = type(view).from_mapping(mapping)
        assert result == view
        assert result.digest() == view.digest()


@pytest.mark.parametrize("day", [
    "00000101", "19000229", "20230229", "20240001", "20241301", "20240431",
    "20240100", "20240132", "99990229", "99991232", "２０２４０２２９",
    "٢٠٢٤٠٢٢٩", "2024-02-29", "2024022", "202402290", "", " 20240229",
    20240229, True, date(2024, 2, 29), ["20240229"],
])
def test_invalid_calendar_days_rejected_in_constructors_and_wire(day):
    with pytest.raises(RiskServiceProtocolError, match="^RISK_VIEW_INVALID$"):
        _order(day)
    wire = _order().to_mapping()
    wire["trading_day"] = day
    with pytest.raises(RiskServiceProtocolError, match="^RISK_VIEW_INVALID$"):
        RiskOrderView.from_mapping(wire)

    for field in ("created_trading_day", "valid_until_trading_day"):
        with pytest.raises(RiskServiceProtocolError, match="^RISK_PARENT_INVALID$"):
            replace(_parent(), **{field: day})
        wire = _parent().to_mapping()
        wire[field] = day
        with pytest.raises(RiskServiceProtocolError, match="^RISK_PARENT_INVALID$"):
            RiskParentView.from_mapping(wire)


def test_order_day_is_optional_but_parent_days_are_required():
    order = _order(None)
    assert order.to_mapping()["trading_day"] is None
    assert RiskOrderView.from_mapping(order.to_mapping()).digest() == order.digest()
    for field in ("created_trading_day", "valid_until_trading_day"):
        with pytest.raises(RiskServiceProtocolError, match="^RISK_PARENT_INVALID$"):
            replace(_parent(), **{field: None})
        wire = _parent().to_mapping()
        wire[field] = None
        with pytest.raises(RiskServiceProtocolError, match="^RISK_PARENT_INVALID$"):
            RiskParentView.from_mapping(wire)


def test_parent_end_before_start_remains_invalid():
    with pytest.raises(RiskServiceProtocolError, match="^RISK_PARENT_INVALID$"):
        _parent("20240301", "20240229")


def test_existing_golden_order_and_parent_digests_are_unchanged():
    order = RiskOrderView(
        "acct-hash", "CTP___FUTURE", "11111111-2222-3333-4444-555555555555",
        "strategy", "11111111-2222-3333-4444-555555555555:7", INSTRUMENT,
        "BUY", "OPEN", "NET", Decimal("2.50"), "lots", "LIMIT", Decimal("3500.0"),
        "DAY", "20261112", "s-1",
    )
    parent = RiskParentView(
        "acct-hash", "CTP___FUTURE", "strategy-a", "parent-1", INSTRUMENT,
        "SELL", "CLOSE_TODAY", "LONG", Decimal("5.00"), "lots", Decimal("3500.0"),
        "20261111", "20261112",
    )
    assert order.digest() == "9c58fc72c2aa9cf46676e733ce0afa3f4264058e0cd8d94ae5a03d5a16f54425"
    assert parent.digest() == "691055e68efff27963235df9e2d882250382ce3344da74f54ad66b513c2cee15"
