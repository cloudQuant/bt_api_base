"""Neutral return-fact contracts and replay digests, using synthetic values."""

from dataclasses import FrozenInstanceError, replace
from types import MappingProxyType

import pytest

from bt_api_base.direct_write_protocol import (
    DirectExecutionEventKind,
    DirectOrderStatus,
    NativeOrderIdentity,
)
from bt_api_base.gateway_execution_protocol import GatewayExecutionProtocolError, GatewayReturnFact
from bt_api_base.market_protocol import MarketInstrumentKey


@pytest.fixture
def trade():
    return GatewayReturnFact(
        account_scope="account-a",
        route="CTP___FUTURE",
        instrument=MarketInstrumentKey("ctp", "CZCE", "paper", "future", "SA701", "SA701"),
        trading_day="20261108",
        kind=DirectExecutionEventKind.TRADE,
        source_ref="session-a",
        identity=NativeOrderIdentity(
            "CTP___FUTURE", "00001", {"trading_day": "20261108", "front_id": 1}, 1
        ),
        identity_keys=("anchor", "venue"),
        binding_keys=("anchor",),
        venue_key="venue",
        trade_key=("CZCE", "trade-1"),
        side="buy",
        offset="open",
        order_quantity="2",
        filled_quantity="1",
        remaining_quantity="1",
        limit_price="100.25",
        trade_quantity="1",
        trade_price="100.25",
        trade_time="09:00:00",
        session_generation=1,
    )


def test_roundtrip_copies_and_freezes_nested_data(trade):
    raw = trade.to_mapping()
    assert GatewayReturnFact.from_mapping(MappingProxyType(raw)) == trade
    raw["instrument"]["instrument_id"] = "other"
    raw["identity"]["fields"]["front_id"] = 9
    raw["identity_keys"].append("other")
    assert trade.instrument.instrument_id == "SA701"
    assert trade.identity.fields["front_id"] == 1
    assert trade.identity_keys == ("anchor", "venue")
    with pytest.raises(FrozenInstanceError):
        trade.route = "other"
    with pytest.raises(TypeError):
        trade.identity.fields["front_id"] = 2


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"account_scope": ""},
        {"route": ""},
        {"source_ref": ""},
        {"trading_day": "20260229"},
        {"trading_day": "2026118"},
        {"kind": "trade"},
        {"status": "accepted"},
        {"session_generation": True},
        {"session_generation": -1},
        {"session_generation": 2**63},
        {"identity_keys": ("venue", "anchor")},
        {"identity_keys": ("anchor", "anchor")},
        {"identity_keys": ("x",) * 17},
        {"identity_keys": ["anchor", "venue"]},
        {"binding_keys": ("missing",)},
        {"venue_key": "missing"},
        {"identity": None},
        {"trade_key": ()},
        {"trade_key": ("one",)},
        {"trade_key": ("x",) * 9},
        {"side": "BUY"},
        {"offset": "unknown"},
        {"trade_time": "\n"},
        {"error_code": "raw error message"},
    ],
)
def test_invalid_exact_fields_rejected(trade, change):
    with pytest.raises(GatewayExecutionProtocolError):
        replace(trade, **change)


@pytest.mark.parametrize(
    "field",
    [
        "order_quantity",
        "filled_quantity",
        "remaining_quantity",
        "limit_price",
        "trade_quantity",
        "trade_price",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        True,
        1,
        1.0,
        "",
        "-1",
        "+1",
        "01",
        "1.0",
        "1.00",
        "1e2",
        "NaN",
        "Infinity",
        "1." + "1" * 19,
        "9" * 37,
    ],
)
def test_noncanonical_numeric_values_rejected(trade, field, value):
    with pytest.raises(GatewayExecutionProtocolError):
        replace(trade, **{field: value})


@pytest.mark.parametrize(
    "field", ["order_quantity", "limit_price", "trade_quantity", "trade_price"]
)
def test_positive_fields_reject_zero(trade, field):
    with pytest.raises(GatewayExecutionProtocolError):
        replace(trade, **{field: "0"})


def test_zero_is_valid_for_filled_and_remaining(trade):
    assert replace(trade, filled_quantity="0", remaining_quantity="0").filled_quantity == "0"
    boundary = "9" * 36 + "." + "1" * 18
    assert replace(trade, trade_quantity=boundary).trade_quantity == boundary
    assert replace(trade, trade_quantity="0." + "0" * 17 + "1").trade_quantity.endswith("1")


def test_trade_and_nontrade_have_distinct_field_contracts(trade):
    with pytest.raises(GatewayExecutionProtocolError):
        replace(trade, status=DirectOrderStatus.ACCEPTED)
    with pytest.raises(GatewayExecutionProtocolError):
        replace(trade, kind=DirectExecutionEventKind.ORDER)
    order = replace(
        trade,
        kind=DirectExecutionEventKind.ORDER,
        trade_key=None,
        trade_quantity=None,
        trade_price=None,
        trade_time=None,
        status=DirectOrderStatus.ACCEPTED,
    )
    assert order.trade_content_digest() is None
    incomplete = replace(
        trade, trade_key=None, venue_key=None, side=None, trade_quantity=None, trade_price=None
    )
    assert incomplete.trade_content_digest() is not None


def test_identity_route_day_sensitive_fields_and_large_payload(trade):
    for identity in (
        NativeOrderIdentity("OTHER", "ref", {"trading_day": "20261108"}, 1),
        NativeOrderIdentity("CTP___FUTURE", "ref", {"trading_day": "20261107"}, 1),
        NativeOrderIdentity("CTP___FUTURE", "ref", {"password": "do-not-store"}, 1),
        NativeOrderIdentity(
            "CTP___FUTURE", "ref", {"large" + str(i): "界" * 256 for i in range(100)}, 1
        ),
    ):
        with pytest.raises(GatewayExecutionProtocolError):
            replace(trade, identity=identity)


def test_mapping_is_exact_and_rejects_type_confusion(trade):
    for key in trade.to_mapping():
        raw = trade.to_mapping()
        del raw[key]
        with pytest.raises(GatewayExecutionProtocolError):
            GatewayReturnFact.from_mapping(raw)
    raw = trade.to_mapping()
    raw["extra"] = True
    with pytest.raises(GatewayExecutionProtocolError):
        GatewayReturnFact.from_mapping(raw)
    for key in ("identity_keys", "binding_keys", "trade_key"):
        raw = trade.to_mapping()
        raw[key] = tuple(raw[key])
        with pytest.raises(GatewayExecutionProtocolError):
            GatewayReturnFact.from_mapping(raw)
    raw = trade.to_mapping()
    raw["identity"]["extra"] = 1
    with pytest.raises(GatewayExecutionProtocolError):
        GatewayReturnFact.from_mapping(raw)


def test_digests_ignore_only_their_documented_fields(trade):
    diagnostic = replace(trade, source_ref="session-b", session_generation=99)
    assert diagnostic.fact_digest() == trade.fact_digest()
    assert diagnostic.trade_content_digest() == trade.trade_content_digest()
    enriched = replace(
        trade,
        identity=NativeOrderIdentity("CTP___FUTURE", "new-ref", {"trading_day": "20261108"}, 2),
        identity_keys=("anchor", "client", "venue"),
        binding_keys=("anchor", "client"),
        trade_time="10:00:00",
    )
    assert enriched.fact_digest() != trade.fact_digest()
    assert enriched.trade_content_digest() == trade.trade_content_digest()
    for change in (
        {"trade_quantity": "2"},
        {"trade_price": "100.26"},
        {"side": "sell"},
        {"trade_key": ("CZCE", "trade-2")},
        {"venue_key": None},
    ):
        assert replace(trade, **change).trade_content_digest() != trade.trade_content_digest()
