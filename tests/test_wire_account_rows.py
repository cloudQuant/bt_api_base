"""Account-scoped row messages do not imply completeness or authority."""

from dataclasses import replace

import msgpack
import pytest
from test_wire_account_codec import _STREAM, _observation

from bt_api_base.account_protocol import AccountKey
from bt_api_base.account_row_observation_protocol import (
    AccountOpenOrderObservation,
    AccountPositionObservation,
)
from bt_api_base.wire_codec_v1 import WireCodecError, decode_message, encode_message


@pytest.mark.parametrize(
    ("kind", "wrapper", "field"),
    [
        ("account_position", AccountPositionObservation, "position"),
        ("account_open_order", AccountOpenOrderObservation, "open_order"),
    ],
)
def test_scoped_account_row_roundtrip_and_tampering(kind, wrapper, field):
    snapshot = _observation()
    row = snapshot.positions[0] if field == "position" else snapshot.open_orders[0]
    frame = encode_message(kind, wrapper(snapshot.account_key, row), stream=_STREAM)
    decoded = decode_message(frame).payload
    assert type(decoded) is wrapper
    assert decoded.account_key == snapshot.account_key
    actual = getattr(decoded, field)
    assert actual.instrument == row.instrument
    assert actual.qty_unit == row.qty_unit
    assert not hasattr(decoded, "complete")
    if field == "position":
        assert actual.quantity == "-2.5"
        assert actual.average_price is None
    else:
        assert actual.quantity == "2"
        assert actual.filled_quantity == "0.5"
        assert actual.stop_price is None

    body = msgpack.unpackb(frame, raw=False)
    body["data"][field]["instrument"]["venue"] = "other"
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(body, use_bin_type=True))

    body = msgpack.unpackb(frame, raw=False)
    del body["data"][field]["quantity"]
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(body, use_bin_type=True))

    body = msgpack.unpackb(frame, raw=False)
    body["data"][field]["unknown"] = "present"
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(body, use_bin_type=True))

    body = msgpack.unpackb(frame, raw=False)
    body["minor"] = 1
    with pytest.raises(WireCodecError, match="WIRE_MINOR_UNSUPPORTED"):
        decode_message(msgpack.packb(body, use_bin_type=True))


def test_scoped_account_row_checks_product_and_simnow_venue_rules():
    snapshot = _observation()
    row = snapshot.positions[0]
    wrong_product = replace(row, resource=replace(row.resource, product_type="spot"))
    with pytest.raises(ValueError, match="account scope"):
        AccountPositionObservation(snapshot.account_key, wrong_product)

    ctp = AccountKey("ctp", "simnow", "simnow", "account-a")
    instrument = replace(row.instrument, provider="ctp", venue="CZCE", environment="simnow")
    ctp_row = replace(row, instrument=instrument)
    scoped = AccountPositionObservation(ctp, ctp_row)
    assert decode_message(encode_message("account_position", scoped, stream=_STREAM)).payload.account_key == ctp

    wrong_venue = replace(ctp_row, instrument=replace(instrument, venue="OTHER"))
    with pytest.raises(ValueError, match="account scope"):
        AccountPositionObservation(ctp, wrong_venue)


@pytest.mark.parametrize("field", ["position", "open_order"])
@pytest.mark.parametrize("where", ["wrapper", "account", "row", "instrument", "resource"])
def test_account_row_refuses_attached_unrepresentable_fields(field, where):
    snapshot = _observation()
    row = snapshot.positions[0] if field == "position" else snapshot.open_orders[0]
    wrapper_type = AccountPositionObservation if field == "position" else AccountOpenOrderObservation
    value = wrapper_type(snapshot.account_key, row)
    target = {"wrapper": value, "account": snapshot.account_key, "row": row,
              "instrument": row.instrument, "resource": row.resource}[where]
    object.__setattr__(target, "extra_unrepresentable_field", "unretained data")
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        encode_message("account_" + field, value, stream=_STREAM)


def test_scoped_open_order_cannot_claim_terminal_status():
    snapshot = _observation()
    wire = msgpack.unpackb(
        encode_message(
            "account_open_order",
            AccountOpenOrderObservation(snapshot.account_key, snapshot.open_orders[0]),
            stream=_STREAM,
        ),
        raw=False,
    )
    wire["data"]["open_order"]["status"] = "filled"
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))


@pytest.mark.parametrize(
    ("changes",),
    [
        ({"quantity": "0"},),
        ({"quantity": "-1"},),
        ({"filled_quantity": "-1"},),
        ({"filled_quantity": "2"},),
        ({"status": "open", "filled_quantity": "0.5"},),
        ({"status": "partially_filled", "filled_quantity": "0"},),
        ({"side": "unknown"},),
        ({"position_side": "unknown"},),
        ({"reduce_only": 1},),
    ],
)
def test_open_order_semantic_contract_rejects_inconsistent_rows(changes):
    snapshot = _observation()
    wire = msgpack.unpackb(
        encode_message(
            "account_open_order",
            AccountOpenOrderObservation(snapshot.account_key, snapshot.open_orders[0]),
            stream=_STREAM,
        ),
        raw=False,
    )
    wire["data"]["open_order"].update(changes)
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))


@pytest.mark.parametrize("side", ["long", "short"])
def test_position_semantic_contract_rejects_negative_hedged_leg(side):
    snapshot = _observation()
    wire = msgpack.unpackb(
        encode_message(
            "account_position",
            AccountPositionObservation(snapshot.account_key, snapshot.positions[0]),
            stream=_STREAM,
        ),
        raw=False,
    )
    wire["data"]["position"]["side"] = side
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))
