"""Restricted command wire declarations require independent SDK admission."""

import subprocess
import sys
from dataclasses import replace

import msgpack
import pytest
from test_wire_account_codec import _STREAM, _observation

from bt_api_base.execution_command_wire_protocol import (
    StrategyCancelCommand,
    StrategyCommandResult,
    StrategySubmitCommand,
)
from bt_api_base.wire_codec_v1 import WireCodecError, decode_message, encode_message


def _submit():
    snapshot = _observation()
    return StrategySubmitCommand(
        account_key=snapshot.account_key,
        instrument=snapshot.positions[0].instrument,
        route="venue-route",
        strategy_ref="strategy-a",
        run_id="run-a",
        request_id="request-a",
        idempotency_key="idempotency-a",
        client_order_id="client-a",
        side="buy",
        order_type="limit",
        quantity="123456789012345.1234500",
        quantity_unit="contracts",
        limit_price="10.2500",
        price_currency=None,
        time_in_force="GTC",
        valid_until_utc_ns=None,
        reduce_only=False,
        position_side=None,
        position_effect=None,
        position_mode=None,
        hedge_class=None,
    )


def _cancel():
    submit = _submit()
    return StrategyCancelCommand(
        submit.account_key,
        submit.instrument,
        submit.route,
        submit.strategy_ref,
        submit.run_id,
        "cancel-a",
        "cancel-key",
        submit.client_order_id,
        None,
        None,
    )


def _result(outcome="unknown"):
    submit = _submit()
    return StrategyCommandResult(
        submit.account_key,
        submit.route,
        submit.strategy_ref,
        submit.run_id,
        submit.request_id,
        submit.idempotency_key,
        "submit",
        outcome,
        None,
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("strategy_submit", _submit()),
        ("strategy_cancel", _cancel()),
        ("strategy_result", _result()),
    ],
)
def test_command_roundtrip_and_version_fence(kind, value):
    frame = encode_message(kind, value, stream=_STREAM)
    result = decode_message(frame)
    assert result.minor == 4  # produced at the current minor; introduced in 3
    assert type(result.payload) is type(value)
    assert result.payload.account_key == value.account_key
    assert result.payload.request_id == value.request_id
    assert result.payload.idempotency_key == value.idempotency_key
    if kind == "strategy_submit":
        assert result.payload.quantity == "123456789012345.12345"
        assert result.payload.limit_price == "10.25"
        assert result.payload.price_currency is None
        assert result.payload.valid_until_utc_ns is None
    elif kind == "strategy_result":
        assert result.payload.outcome == "unknown"
        assert not hasattr(result.payload, "order_terminal")
        assert not hasattr(result.payload, "authorized")
    wire = msgpack.unpackb(frame, raw=False)
    wire["minor"] = 2
    with pytest.raises(WireCodecError, match="WIRE_MINOR_UNSUPPORTED"):
        decode_message(msgpack.packb(wire, use_bin_type=True))
    with pytest.raises(WireCodecError, match="WIRE_MINOR_UNSUPPORTED"):
        decode_message(frame, supported_minor=2)


@pytest.mark.parametrize("outcome", ["unknown", "accepted", "rejected"])
def test_result_is_only_a_correlated_acknowledgement_declaration(outcome):
    result = _result(outcome)
    decoded = decode_message(encode_message("strategy_result", result, stream=_STREAM)).payload
    assert decoded.outcome == outcome
    assert decoded.observed_at_utc_ns is None
    assert decoded.source_precision_ns is None


@pytest.mark.parametrize(
    "changes",
    [
        {"order_type": "stop"},
        {"quantity_unit": "unknown"},
        {"time_in_force": "auction"},
        {"side": "invalid"},
        {"quantity": "0"},
        {"quantity": -1.0},
        {"order_type": "market", "limit_price": "1"},
        {"order_type": "limit", "limit_price": None},
        {"reduce_only": 1},
        {"valid_until_utc_ns": True},
        {"valid_until_utc_ns": 2**63},
        {"idempotency_key": ""},
        {"position_effect": "unrecognized"},
        {"hedge_class": "unrecognized"},
        {"reduce_only": True, "position_effect": "open"},
    ],
)
def test_submit_rejects_unsupported_or_malformed_values(changes):
    with pytest.raises((TypeError, ValueError)):
        replace(_submit(), **changes)


def test_market_order_with_unknown_price_and_currency_roundtrips():
    value = replace(_submit(), order_type="market", limit_price=None, price_currency=None)
    result = decode_message(encode_message("strategy_submit", value, stream=_STREAM)).payload
    assert result.limit_price is None
    assert result.price_currency is None


@pytest.mark.parametrize(
    "kind,value", [("strategy_submit", _submit()), ("strategy_cancel", _cancel())]
)
def test_unrepresentable_extra_fields_and_account_scope_mismatch_are_rejected(kind, value):
    frame = encode_message(kind, value, stream=_STREAM)
    wire = msgpack.unpackb(frame, raw=False)
    wire["data"]["ctp_native_identity"] = "must not be dropped"
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))
    wire = msgpack.unpackb(frame, raw=False)
    wire["data"]["instrument"]["provider"] = "other"
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))


def test_wire_rejects_reduce_only_with_open_effect():
    wire = msgpack.unpackb(encode_message("strategy_submit", _submit(), stream=_STREAM), raw=False)
    wire["data"]["reduce_only"] = True
    wire["data"]["position_effect"] = "open"
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))


def test_result_rejects_terminal_status_and_precision_without_time():
    with pytest.raises(ValueError, match="outcome"):
        replace(_result(), outcome="filled")
    with pytest.raises(ValueError, match="precision"):
        replace(_result(), source_precision_ns=1)
    precise = replace(_result(), observed_at_utc_ns=1762131600000000000, source_precision_ns=1000)
    assert (
        decode_message(encode_message("strategy_result", precise, stream=_STREAM)).payload
        == precise
    )


def test_submit_rejects_overlong_decimal_and_malformed_ack_payload():
    with pytest.raises(WireCodecError, match="WIRE_DECIMAL_INVALID"):
        encode_message("strategy_submit", replace(_submit(), quantity="1" * 41), stream=_STREAM)
    wire = msgpack.unpackb(encode_message("strategy_result", _result(), stream=_STREAM), raw=False)
    wire["data"]["outcome"] = "filled"
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))


def test_command_id_and_parameter_tampering_remains_visible():
    command = _submit()
    changed = replace(command, quantity="2")
    first = decode_message(encode_message("strategy_submit", command, stream=_STREAM)).payload
    second = decode_message(encode_message("strategy_submit", changed, stream=_STREAM)).payload
    assert first.request_id == second.request_id
    assert first.idempotency_key == second.idempotency_key
    assert first.quantity != second.quantity
    # This DTO does not implement durable same-ID/content deduplication.


@pytest.mark.parametrize("where", ["command", "account", "instrument"])
def test_sender_cannot_silently_drop_unrepresentable_fields(where):
    command = _submit()
    target = {"command": command, "account": command.account_key, "instrument": command.instrument}[
        where
    ]
    object.__setattr__(target, "unsupported_native_identity", "must not be discarded")
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        encode_message("strategy_submit", command, stream=_STREAM)


def test_command_roundtrips_across_a_fresh_process():
    value = _submit()
    frame = encode_message("strategy_submit", value, stream=_STREAM)
    code = (
        "import sys; from bt_api_base.wire_codec_v1 import decode_message,encode_message; "
        "m=decode_message(sys.stdin.buffer.read()); "
        "sys.stdout.buffer.write(encode_message(m.kind,m.payload,stream=m.stream))"
    )
    process = subprocess.run(
        [sys.executable, "-c", code], input=frame, capture_output=True, check=True
    )
    decoded = decode_message(process.stdout)
    assert decoded.payload.request_id == value.request_id
    assert decoded.payload.account_key == value.account_key
    assert decoded.payload.quantity == "123456789012345.12345"
