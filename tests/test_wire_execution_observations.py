"""Account-scoped observations are data, not evidence or write authority."""

from dataclasses import replace

import msgpack
import pytest
from test_wire_account_codec import _STREAM, _observation

from bt_api_base.account_protocol import AccountKey
from bt_api_base.execution_query_protocol import ExecutionOrderRecord, ExecutionTradeRecord
from bt_api_base.execution_row_observation_protocol import (
    AccountExecutionOrderObservation,
    AccountExecutionTradeObservation,
)
from bt_api_base.wire_codec_v1 import WireCodecError, codec_backend, decode_message, encode_message


def _order(status="unknown"):
    sample = _observation().positions[0]
    return ExecutionOrderRecord(
        resource=sample.resource,
        instrument=sample.instrument,
        order_id="opaque-order",
        client_order_id=None,
        intent_binding="unresolved",
        side="buy",
        position_effect="unavailable",
        position_side=None,
        position_side_status="unavailable",
        order_type="limit",
        status=status,
        quantity="123456789012345.1234500",
        filled_quantity="0",
        qty_unit="contracts",
        limit_price="10.2500",
        price_currency=None,
        price_currency_status="unavailable",
        created_at_utc=None,
        created_at_status="unavailable",
        observed_at_utc="2026-11-03T01:00:00Z",
    )


def _trade():
    sample = _observation().positions[0]
    return ExecutionTradeRecord(
        resource=sample.resource,
        instrument=sample.instrument,
        trade_id="opaque-trade",
        order_id=None,
        order_binding="unresolved",
        side="sell",
        position_effect="unavailable",
        position_side=None,
        position_side_status="unavailable",
        quantity="0.00000000000000000001",
        qty_unit="contracts",
        price="12345.6700",
        price_currency=None,
        price_currency_status="unavailable",
        traded_at_utc=None,
        traded_at_status="unavailable",
        observed_at_utc="2026-11-03T01:00:00Z",
    )


@pytest.mark.parametrize("status", ["unknown", "filled", "canceled", "rejected", "open"])
def test_order_observation_preserves_state_and_scope(status):
    account = _observation().account_key
    row = _order(status)
    if status == "filled":
        row = replace(row, filled_quantity=row.quantity)
    value = AccountExecutionOrderObservation(account, row)
    frame = encode_message("execution_order", value, stream=_STREAM)
    result = decode_message(frame)
    assert result.minor == 5  # produced at the current minor; introduced in 3
    assert result.payload.account_key == account
    assert result.payload.order.status == status
    assert result.payload.order.quantity == "123456789012345.12345"
    assert result.payload.order.limit_price == "10.25"
    assert result.payload.order.client_order_id is None
    assert result.payload.order.intent_binding == "unresolved"
    assert not hasattr(result.payload, "verified")


def test_inconsistent_provider_filled_status_remains_an_unconfirmed_observation():
    value = AccountExecutionOrderObservation(_observation().account_key, _order("filled"))
    result = decode_message(encode_message("execution_order", value, stream=_STREAM)).payload
    assert result.order.status == "filled"
    assert result.order.filled_quantity == "0"
    assert not hasattr(result, "terminal_confirmed")
    assert not hasattr(result.order, "terminal_confirmed")


def test_trade_observation_preserves_precise_single_fill_and_unknowns():
    value = AccountExecutionTradeObservation(_observation().account_key, _trade())
    result = decode_message(encode_message("execution_trade", value, stream=_STREAM)).payload
    assert result.trade.quantity == "0.00000000000000000001"
    assert result.trade.price == "12345.67"
    assert result.trade.order_id is None
    assert result.trade.price_currency is None
    assert result.trade.traded_at_utc is None
    assert not hasattr(result.trade, "fee")


@pytest.mark.parametrize(
    ("kind", "field", "wrapper", "factory"),
    [
        ("execution_order", "order", AccountExecutionOrderObservation, _order),
        ("execution_trade", "trade", AccountExecutionTradeObservation, _trade),
    ],
)
def test_execution_rows_reject_scope_tampering_legacy_minor_and_extra_fields(
    kind, field, wrapper, factory
):
    account = _observation().account_key
    value = wrapper(account, factory())
    frame = encode_message(kind, value, stream=_STREAM)
    wire = msgpack.unpackb(frame, raw=False)
    wire["data"][field]["instrument"]["venue"] = "other"
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))
    wire = msgpack.unpackb(frame, raw=False)
    wire["data"][field]["extra"] = "not allowed"
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))
    wire = msgpack.unpackb(frame, raw=False)
    wire["minor"] = 2
    with pytest.raises(WireCodecError, match="WIRE_MINOR_UNSUPPORTED"):
        decode_message(msgpack.packb(wire, use_bin_type=True))
    with pytest.raises(WireCodecError, match="WIRE_MINOR_UNSUPPORTED"):
        decode_message(frame, supported_minor=2)
    with pytest.raises(ValueError, match="account scope"):
        wrapper(replace(account, provider="other"), factory())


@pytest.mark.parametrize("bad", ["1.0", "-0", "1e3", 0.1])
def test_noncanonical_decimal_is_rejected(bad):
    value = AccountExecutionTradeObservation(_observation().account_key, _trade())
    wire = msgpack.unpackb(encode_message("execution_trade", value, stream=_STREAM), raw=False)
    wire["data"]["trade"]["quantity"] = bad
    with pytest.raises(WireCodecError):
        decode_message(msgpack.packb(wire, use_bin_type=True))


@pytest.mark.parametrize(
    ("field", "mutation"),
    [
        ("order", {"status": "unsupported"}),
        ("order", {"filled_quantity": "999999999999999999"}),
        ("order", {"quantity": "-1"}),
        ("trade", {"quantity": "0"}),
        ("trade", {"price": "-1"}),
        ("trade", {"order_binding": "provider_order_identity", "order_id": None}),
    ],
)
def test_execution_record_constraints_survive_the_wire(field, mutation):
    account = _observation().account_key
    value = (
        AccountExecutionOrderObservation(account, _order())
        if field == "order"
        else AccountExecutionTradeObservation(account, _trade())
    )
    kind = "execution_" + field
    wire = msgpack.unpackb(encode_message(kind, value, stream=_STREAM), raw=False)
    wire["data"][field].update(mutation)
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))


@pytest.mark.parametrize("field", ["order", "trade"])
@pytest.mark.parametrize("where", ["wrapper", "account", "record", "instrument", "resource"])
def test_sender_rejects_unrepresentable_attached_fields(field, where):
    account = _observation().account_key
    record = _order() if field == "order" else _trade()
    wrapper = (
        AccountExecutionOrderObservation(account, record)
        if field == "order"
        else AccountExecutionTradeObservation(account, record)
    )
    target = {
        "wrapper": wrapper,
        "account": account,
        "record": record,
        "instrument": record.instrument,
        "resource": record.resource,
    }[where]
    object.__setattr__(target, "extra_unrepresentable_fee_currency", "USD")
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        encode_message("execution_" + field, wrapper, stream=_STREAM)


def test_ctp_simnow_scopes_permitted_exchange_and_rejects_unknown_venue():
    record = _order()
    key = AccountKey("ctp", "simnow", "simnow", "account")
    instrument = replace(record.instrument, provider="ctp", venue="CZCE", environment="simnow")
    scoped = AccountExecutionOrderObservation(key, replace(record, instrument=instrument))
    assert (
        decode_message(
            encode_message("execution_order", scoped, stream=_STREAM)
        ).payload.account_key
        == key
    )
    with pytest.raises(ValueError, match="account scope"):
        AccountExecutionOrderObservation(
            key, replace(record, instrument=replace(instrument, venue="OTHER"))
        )


def test_codec_backend_checks_real_callables_not_just_import(monkeypatch):
    def c_unpack(*args, **kwargs):
        pass

    class CPacker:
        pass

    c_unpack.__module__ = "msgpack._cmsgpack"
    CPacker.__module__ = "msgpack._cmsgpack"
    monkeypatch.setattr(msgpack, "unpackb", c_unpack)
    monkeypatch.setattr(msgpack, "Packer", CPacker)
    assert codec_backend() == "c"
    c_unpack.__module__ = "msgpack.fallback"
    assert codec_backend() == "python"
    c_unpack.__module__ = "msgpack._cmsgpack"
    CPacker.__module__ = "msgpack.fallback"
    assert codec_backend() == "python"
