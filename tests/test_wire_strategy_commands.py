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
        submit.semantic_fingerprint,
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
    assert result.minor == 5  # produced at the current minor; revised in 5
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
    for older in (2, 3, 4):
        # Minor 3/4 had the command shape without fingerprint and SDK fields.
        wire = msgpack.unpackb(frame, raw=False)
        wire["minor"] = older
        with pytest.raises(WireCodecError, match="WIRE_MINOR_UNSUPPORTED"):
            decode_message(msgpack.packb(wire, use_bin_type=True))
        with pytest.raises(WireCodecError, match="WIRE_MINOR_UNSUPPORTED"):
            decode_message(frame, supported_minor=older)


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
    # Same idempotency key, different content: the fingerprints disagree, so a
    # durable same-ID check can refuse the second command (plan §7.4).
    assert first.semantic_fingerprint != second.semantic_fingerprint


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


# ---------------------------------------------------------------------------
# Minor 5: SDK request fields and the semantic fingerprint (60.08, G5)
# ---------------------------------------------------------------------------


def _full_submit():
    return replace(
        _submit(),
        position_side="long",
        position_effect="close_today",
        position_bucket="today",
        reduce_only=True,
        signal_id="signal-a",
        metadata_version="meta-7",
        tags=(("alpha", "x"), ("desk", "a b")),
        valid_until_utc_ns=1_762_131_600_123_456_789,
    )


def test_sdk_request_fields_roundtrip_exactly():
    value = _full_submit()
    decoded = decode_message(encode_message("strategy_submit", value, stream=_STREAM)).payload
    assert decoded.signal_id == "signal-a"
    assert decoded.metadata_version == "meta-7"
    assert decoded.tags == (("alpha", "x"), ("desk", "a b"))
    assert decoded.position_bucket == "today"
    # Nanosecond deadline survives exactly (no float, no rounding).
    assert decoded.valid_until_utc_ns == 1_762_131_600_123_456_789
    assert decoded.semantic_fingerprint == value.semantic_fingerprint
    cancel = replace(_cancel(), metadata_version="meta-7", tags=(("k", "v"),))
    decoded_cancel = decode_message(
        encode_message("strategy_cancel", cancel, stream=_STREAM)
    ).payload
    assert decoded_cancel == cancel
    assert decoded_cancel.semantic_fingerprint == cancel.semantic_fingerprint


def test_fingerprint_is_semantic_and_excludes_only_attempt_identity():
    base = _full_submit()
    fingerprint = base.semantic_fingerprint
    assert len(fingerprint) == 64 and set(fingerprint) <= set("0123456789abcdef")
    # Not content: the attempt id and the sending run.
    assert replace(base, request_id="request-b").semantic_fingerprint == fingerprint
    assert replace(base, run_id="run-b").semantic_fingerprint == fingerprint
    # Equivalent decimal spelling is the same content.
    assert replace(base, limit_price="10.25").semantic_fingerprint == fingerprint
    # Every covered change differs.
    for changes in (
        {"quantity": "2"},
        {"limit_price": "10.26"},
        {"route": "other-route"},
        {"strategy_ref": "strategy-b"},
        {"idempotency_key": "idempotency-b"},
        {"client_order_id": "client-b"},
        {"side": "sell"},
        {"signal_id": "signal-b"},
        {"metadata_version": "meta-8"},
        {"tags": (("alpha", "y"), ("desk", "a b"))},
        {"tags": ()},
        {"valid_until_utc_ns": None},
        {"position_bucket": None},
        {"time_in_force": "IOC"},
    ):
        assert replace(base, **changes).semantic_fingerprint != fingerprint, changes
    other_account = replace(base.account_key, account_id="other-account")
    assert replace(base, account_key=other_account).semantic_fingerprint != fingerprint
    # A cancel and a submit never share a fingerprint.
    assert _cancel().semantic_fingerprint != _submit().semantic_fingerprint


def test_decoder_recomputes_the_fingerprint_and_refuses_tampering():
    frame = encode_message("strategy_submit", _full_submit(), stream=_STREAM)
    wire = msgpack.unpackb(frame, raw=False)
    assert wire["data"]["semantic_fingerprint"] == _full_submit().semantic_fingerprint
    tampered = msgpack.unpackb(frame, raw=False)
    tampered["data"]["quantity"] = "1"
    with pytest.raises(WireCodecError, match="WIRE_COMMAND_FINGERPRINT_MISMATCH"):
        decode_message(msgpack.packb(tampered, use_bin_type=True))
    tampered = msgpack.unpackb(frame, raw=False)
    tampered["data"]["tags"]["alpha"] = "changed"
    with pytest.raises(WireCodecError, match="WIRE_COMMAND_FINGERPRINT_MISMATCH"):
        decode_message(msgpack.packb(tampered, use_bin_type=True))
    missing = msgpack.unpackb(frame, raw=False)
    del missing["data"]["semantic_fingerprint"]
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(msgpack.packb(missing, use_bin_type=True))
    # The attempt id is outside the fingerprint and may differ per attempt.
    retried = msgpack.unpackb(frame, raw=False)
    retried["data"]["request_id"] = "request-retry"
    assert decode_message(msgpack.packb(retried, use_bin_type=True)).payload.request_id == (
        "request-retry"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"position_bucket": "all"},
        {"position_bucket": "today", "position_side": "net"},
        {"position_bucket": "today", "position_side": None},
        {"position_bucket": "today", "position_effect": "open", "reduce_only": False},
        {"tags": {"a": "b"}},
        {"tags": (("b", "1"), ("a", "2"))},
        {"tags": (("a", "1"), ("a", "2"))},
        {"tags": (("bad key", "1"),)},
        {"tags": (("k", " padded"),)},
        {"tags": tuple((f"k{i:02d}", "v") for i in range(17))},
        {"signal_id": ""},
        {"metadata_version": " meta"},
    ],
)
def test_minor_five_fields_reject_unsupported_values(changes):
    with pytest.raises((TypeError, ValueError)):
        replace(_full_submit(), **changes)


def test_result_carries_the_answered_command_fingerprint():
    result = _result()
    assert result.command_fingerprint == _submit().semantic_fingerprint
    decoded = decode_message(encode_message("strategy_result", result, stream=_STREAM)).payload
    assert decoded.command_fingerprint == result.command_fingerprint
    for bad in ("", "A" * 64, "a" * 63, None, 1):
        with pytest.raises((TypeError, ValueError)):
            replace(result, command_fingerprint=bad)
