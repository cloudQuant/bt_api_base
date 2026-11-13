"""Local wire/value checks only; no provider, authority, or dispatch evidence."""

import threading
from dataclasses import replace
from decimal import Decimal

import pytest
from bt_api_base.gateway_direct_protocol import gateway_payload_digest
from bt_api_base.gateway_risk_order_values import (
    GatewayRiskOrderValuesError,
    validate_gateway_risk_order_values,
)
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.risk_service_protocol import RiskOrderView


def payload():
    # Exact OrderRequest.to_dict() shape; constructed independently of the SDK.
    return {
        "symbol": "rb2701", "side": "buy", "order_type": "limit", "quantity": "2.50",
        "account_id": "account", "client_order_id": "client", "price": "3500.00",
        "time_in_force": "DAY", "reduce_only": False, "idempotency_key": "request",
        "quantity_unit": "lots", "position_side": None, "offset": "open",
        "position_id": None, "position_mode": None, "exchange_id": "SHFE",
        "execution_cycle_id": None, "execution_role": None, "strategy_identity_sha256": None,
        "ctp_order_identity": None, "managed_intent_id": None, "hedge_flag": None,
        "runtime_order_id": None, "hedge_class": None, "instrument": None,
    }


def view():
    return RiskOrderView(
        account_scope="account", route="route", strategy_ref="strategy", origin="strategy",
        request_key="request", instrument=MarketInstrumentKey(
            "ctp", "SHFE", "simnow", "future", "rb2701", "rb2701"
        ), side="BUY", offset="OPEN", position_side="NET", quantity=Decimal("2.50"),
        quantity_unit="lots", order_type="LIMIT", limit_price=Decimal("3500.00"),
        time_in_force="DAY",
    )


def check(p, v):
    return validate_gateway_risk_order_values(p, v, gateway_payload_digest(p))


def test_full_payload_digest_and_equal_value():
    p = payload()
    assert check(p, view()).payload_digest == gateway_payload_digest(p)
    p["client_order_id"] = "different-client"
    assert check(p, view()).payload_digest == gateway_payload_digest(p)
    with pytest.raises(GatewayRiskOrderValuesError):
        validate_gateway_risk_order_values(p, view(), "0" * 64)


@pytest.mark.parametrize("field,value", [
    ("account_id", "other"), ("idempotency_key", "other"), ("symbol", "other"),
    ("exchange_id", "DCE"), ("quantity", "3"), ("price", "3501"),
    ("side", "sell"), ("order_type", "market"), ("offset", "close"),
    ("position_side", "long"), ("quantity_unit", "base"), ("time_in_force", "GTC"),
])
def test_recomputed_digest_does_not_hide_mismatched_values(field, value):
    p = payload()
    p[field] = value
    if field == "order_type":
        p["price"] = None
    with pytest.raises(GatewayRiskOrderValuesError):
        check(p, view())


@pytest.mark.parametrize("field,value", [
    ("extra", "x"), ("quantity", "2e0"), ("quantity", "02.50"), ("quantity", "0"),
    ("quantity", 2), ("price", "NaN"), ("side", "BUY"), ("offset", "OPEN"),
    ("reduce_only", 0), ("instrument", {}), ("ctp_order_identity", {"order_ref": "1"}),
    ("hedge_flag", "4"), ("position_mode", "hedged"),
])
def test_reject_unsupported_wire(field, value):
    p = payload()
    p[field] = value
    with pytest.raises(GatewayRiskOrderValuesError):
        check(p, view())


def test_missing_field_and_absent_venue_rejected():
    p = payload()
    del p["hedge_class"]
    with pytest.raises(GatewayRiskOrderValuesError):
        check(p, view())
    p = payload()
    p["exchange_id"] = None
    with pytest.raises(GatewayRiskOrderValuesError):
        check(p, view())


def test_market_and_decimal_boundaries():
    p = payload()
    p.update(order_type="market", price=None, quantity="0.00000001", position_side="short")
    v = replace(view(), order_type="MARKET", limit_price=None, quantity=Decimal("0.00000001"),
                position_side="SHORT")
    check(p, v)
    p["price"] = "1"
    with pytest.raises(GatewayRiskOrderValuesError):
        check(p, v)
    p.update(order_type="limit", price="1", quantity="12345678901234567890123456789")
    v = replace(v, order_type="LIMIT", limit_price=Decimal("1"),
                quantity=Decimal(p["quantity"]))
    # Existing Risk digest normalizes under the decimal context and refuses loss.
    with pytest.raises(GatewayRiskOrderValuesError):
        check(p, v)


def test_matching_values_do_not_prove_native_or_full_instrument_identity():
    p = payload()
    v = view()
    other = replace(v, route="unrelated", strategy_ref="other", instrument=replace(
        v.instrument, provider="other", environment="other", product_type="other",
        instrument_id="other"))
    assert check(p, v).payload_digest == check(p, other).payload_digest
    assert check(p, v).view_digest != check(p, other).view_digest
    p.update(hedge_flag="1", hedge_class="hedge", position_id="native-id")
    assert check(p, other).payload_digest == gateway_payload_digest(p)


def test_str_subclass_key_cannot_run_sort_callback():
    p = payload()
    ran = []

    class CallbackKey(str):
        def __lt__(self, other):
            ran.append(True)
            p["quantity"] = "99"
            return super().__lt__(other)

    p[CallbackKey("zzz")] = None
    with pytest.raises(GatewayRiskOrderValuesError):
        validate_gateway_risk_order_values(p, view(), "0" * 64)
    assert not ran and p["quantity"] == "2.50"


def test_original_payload_change_during_encoding_does_not_change_returned_bytes(monkeypatch):
    import bt_api_base.gateway_risk_order_values as module

    p = payload()
    expected_digest = gateway_payload_digest(p)
    original = module.canonical_gateway_payload

    def change_original(snapshot):
        p["quantity"] = "99"
        return original(snapshot)

    monkeypatch.setattr(module, "canonical_gateway_payload", change_original)
    result = validate_gateway_risk_order_values(p, view(), expected_digest)
    assert p["quantity"] == "99"
    assert '"quantity":"2.50"' in result.canonical_payload
    assert result.payload_digest == expected_digest


def test_concurrent_view_change_after_snapshot_preserves_checked_view_digest(monkeypatch):
    import bt_api_base.gateway_risk_order_values as module

    p, v = payload(), view()
    original_digest = v.digest()
    started, changed = threading.Event(), threading.Event()
    original = module.canonical_gateway_payload

    def wait_for_mutation(snapshot):
        started.set()
        assert changed.wait(2)
        return original(snapshot)

    def mutate():
        assert started.wait(2)
        object.__setattr__(v, "quantity", Decimal("99"))
        changed.set()

    monkeypatch.setattr(module, "canonical_gateway_payload", wait_for_mutation)
    thread = threading.Thread(target=mutate)
    thread.start()
    try:
        result = validate_gateway_risk_order_values(p, v, gateway_payload_digest(p))
    finally:
        thread.join(timeout=2)
    assert not thread.is_alive()
    assert v.quantity == Decimal("99")
    assert result.view_digest == original_digest != v.digest()
