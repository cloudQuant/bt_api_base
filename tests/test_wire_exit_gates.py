"""Iteration 60.08 exit gates (plan §9.4 / §10) across every registered kind.

Strict decode (truncation, trailing bytes, concatenation, duplicate keys at
any depth, unknown major/minor, unknown critical fields), strict decimals,
nanosecond/int64 width, stream sequence width and epoch switching, typed
parts, the service-operation registry and connect-time typed negotiation,
including a mixed-version check against a separate "old" process.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from decimal import Decimal

import msgpack
import pytest
from test_wire_account_codec import _observation
from test_wire_codec_v1 import _bar, _fill, _tick
from test_wire_execution_observations import _order, _trade
from test_wire_strategy_account_book import _book
from test_wire_strategy_commands import _cancel, _full_submit, _result

import bt_api_base.wire_codec_v1 as codec
from bt_api_base.account_row_observation_protocol import (
    AccountOpenOrderObservation,
    AccountPositionObservation,
)
from bt_api_base.execution_row_observation_protocol import (
    AccountExecutionOrderObservation,
    AccountExecutionTradeObservation,
)
from bt_api_base.wire_codec_v1 import (
    GENERIC_SERVICE_OPERATIONS,
    SUPPORTED_MINOR,
    TYPED_SERVICE_OPERATIONS,
    StreamPosition,
    WireCodecError,
    canonical_decimal,
    check_stream_successor,
    check_typed_contract_declaration,
    decode_message,
    decode_typed_part,
    encode_message,
    encode_typed_part,
    parse_decimal,
    typed_contract_declaration,
)

STREAM = StreamPosition("gate-stream", "epoch-1", 3)


def _samples():
    snapshot = _observation()
    account = snapshot.account_key
    return {
        "tick": _tick(),
        "bar": _bar(),
        "fill": _fill(),
        "account": snapshot,
        "account_position": AccountPositionObservation(account, snapshot.positions[0]),
        "account_open_order": AccountOpenOrderObservation(account, snapshot.open_orders[0]),
        "execution_order": AccountExecutionOrderObservation(account, _order()),
        "execution_trade": AccountExecutionTradeObservation(account, _trade()),
        "strategy_submit": _full_submit(),
        "strategy_cancel": _cancel(),
        "strategy_result": _result(),
        "strategy_account_book": _book(),
    }


SAMPLES = _samples()
KINDS = sorted(SAMPLES)
PART_KINDS = sorted(set(KINDS) - {"tick", "bar", "fill"})


def test_every_registered_kind_has_a_gate_sample():
    assert set(KINDS) == set(codec._KINDS)


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_round_trips_into_its_base_object(kind):
    decoded = decode_message(encode_message(kind, SAMPLES[kind], stream=STREAM))
    assert decoded.kind == kind and decoded.minor == SUPPORTED_MINOR
    if kind == "fill":
        assert dict(decoded.payload) == {
            key: value for key, value in decoded.payload.items()
        }
    elif kind != "tick":
        assert type(decoded.payload) is type(SAMPLES[kind])


@pytest.mark.parametrize("kind", KINDS)
def test_every_truncation_is_refused(kind):
    frame = encode_message(kind, SAMPLES[kind], stream=STREAM)
    for size in range(len(frame)):
        with pytest.raises(WireCodecError) as raised:
            decode_message(frame[:size])
        assert raised.value.code in {"WIRE_FRAME_INVALID", "WIRE_TRAILING_BYTES"}


@pytest.mark.parametrize("kind", KINDS)
def test_trailing_bytes_and_concatenation_are_refused(kind):
    frame = encode_message(kind, SAMPLES[kind], stream=STREAM)
    for data in (frame + b"\x00", frame + frame, frame + b"\xc0"):
        with pytest.raises(WireCodecError, match="WIRE_TRAILING_BYTES"):
            decode_message(data)


def _duplicate_first_data_key(frame: bytes) -> bytes:
    """Re-pack ``data`` with its first key written twice (msgpack allows it)."""

    wire = msgpack.unpackb(frame, raw=False)
    data = wire.pop("data")
    first = next(iter(data))
    packer = msgpack.Packer(use_bin_type=True)
    body = packer.pack_map_header(len(data) + 1)
    body += packer.pack(first) + packer.pack(data[first])
    for key, value in data.items():
        body += packer.pack(key) + packer.pack(value)
    head = packer.pack_map_header(len(wire) + 1)
    for key, value in wire.items():
        head += packer.pack(key) + packer.pack(value)
    return head + packer.pack("data") + body


@pytest.mark.parametrize("kind", KINDS)
def test_duplicate_keys_inside_data_are_refused(kind):
    frame = encode_message(kind, SAMPLES[kind], stream=STREAM)
    with pytest.raises(WireCodecError, match="WIRE_DUPLICATE_KEY"):
        decode_message(_duplicate_first_data_key(frame))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "change, code",
    [
        ({"major": 2}, "WIRE_MAJOR_UNSUPPORTED"),
        ({"major": 0}, "WIRE_MAJOR_UNSUPPORTED"),
        ({"minor": SUPPORTED_MINOR + 1}, "WIRE_MINOR_UNSUPPORTED"),
        ({"minor": -1}, "WIRE_MINOR_UNSUPPORTED"),
        ({"minor": True}, "WIRE_MINOR_UNSUPPORTED"),
        ({"schema_id": "bt_api.wire.v2"}, "WIRE_SCHEMA_UNSUPPORTED"),
        ({"critical": True}, "WIRE_FIELD_SET_INVALID"),
    ],
)
def test_unknown_versions_and_envelope_fields_are_refused(kind, change, code):
    wire = msgpack.unpackb(encode_message(kind, SAMPLES[kind], stream=STREAM), raw=False)
    wire.update(change)
    with pytest.raises(WireCodecError, match=code):
        decode_message(msgpack.packb(wire, use_bin_type=True))


@pytest.mark.parametrize("kind", KINDS)
def test_unknown_critical_data_field_is_never_ignored(kind):
    wire = msgpack.unpackb(encode_message(kind, SAMPLES[kind], stream=STREAM), raw=False)
    wire["data"]["provider_private_binding"] = "ctp-front-1:session-2:order-ref-3"
    with pytest.raises(WireCodecError) as raised:
        decode_message(msgpack.packb(wire, use_bin_type=True))
    assert raised.value.code in {"WIRE_FIELD_SET_INVALID", "WIRE_PAYLOAD_INVALID"}


@pytest.mark.parametrize(
    "lexeme",
    ["1e3", "1E-2", "NaN", "nan", "Infinity", "-0", "-0.0", "01", "00.5", "1.50", "1.", ".5",
     "+1", " 1", "1 ", "0x10", "1_000", "١", "1" * 41],
)
def test_strict_decimal_grammar_rejects_non_canonical_lexemes(lexeme):
    with pytest.raises(WireCodecError):
        parse_decimal(lexeme)


def test_canonical_decimal_normalizes_equivalent_values():
    for value, expected in [
        (Decimal("1.500"), "1.5"),
        (Decimal("-0.0"), "0"),
        (Decimal("1E+2"), "100"),
        (Decimal("0.000001"), "0.000001"),
        (1.25, "1.25"),
        (7, "7"),
    ]:
        assert canonical_decimal(value) == expected
        assert parse_decimal(expected) == Decimal(expected)
    for bad in (float("nan"), float("inf"), Decimal("NaN"), True, "1e999999999", None):
        with pytest.raises(WireCodecError):
            canonical_decimal(bad)


def test_decimal_inside_a_typed_kind_must_be_canonical():
    wire = msgpack.unpackb(
        encode_message("strategy_submit", SAMPLES["strategy_submit"], stream=STREAM), raw=False
    )
    wire["data"]["quantity"] = "1.0"
    with pytest.raises(WireCodecError, match="WIRE_DECIMAL_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))
    wire["data"]["quantity"] = 1.0
    with pytest.raises(WireCodecError, match="WIRE_FLOAT_FORBIDDEN"):
        decode_message(msgpack.packb(wire, use_bin_type=True))


def test_nanosecond_times_are_exact_int64_and_out_of_range_is_refused():
    largest = 2**63 - 1
    submit = replace(SAMPLES["strategy_submit"], valid_until_utc_ns=largest)
    decoded = decode_message(encode_message("strategy_submit", submit, stream=STREAM)).payload
    assert decoded.valid_until_utc_ns == largest
    precise = replace(
        _result(), observed_at_utc_ns=1_762_131_600_000_000_001, source_precision_ns=1
    )
    decoded = decode_message(encode_message("strategy_result", precise, stream=STREAM)).payload
    assert (decoded.observed_at_utc_ns, decoded.source_precision_ns) == (
        1_762_131_600_000_000_001,
        1,
    )
    wire = msgpack.unpackb(encode_message("strategy_submit", submit, stream=STREAM), raw=False)
    wire["data"]["valid_until_utc_ns"] = 2**63
    with pytest.raises(WireCodecError, match="WIRE_INTEGER_RANGE"):
        decode_message(msgpack.packb(wire, use_bin_type=True))
    with pytest.raises((TypeError, ValueError)):
        replace(submit, valid_until_utc_ns=1.762e18)


def test_sequence_width_and_epoch_switch():
    last = StreamPosition("s", "e1", 2**63 - 1)
    with pytest.raises(WireCodecError, match="WIRE_SEQUENCE_EXHAUSTED"):
        last.next()
    with pytest.raises(WireCodecError, match="WIRE_STREAM_INVALID"):
        StreamPosition("s", "e1", 2**63)
    with pytest.raises(WireCodecError, match="WIRE_STREAM_INVALID"):
        StreamPosition("s", "e1", 0)
    switched = last.switch_epoch("e2")
    assert switched == StreamPosition("s", "e2", 1)
    with pytest.raises(WireCodecError, match="WIRE_EPOCH_SWITCH_INVALID"):
        last.switch_epoch("e1")
    first = StreamPosition("s", "e1", 1)
    check_stream_successor(None, first)
    check_stream_successor(first, first.next())
    check_stream_successor(last, switched)
    for current, code in [
        (first, "WIRE_SEQUENCE_REPLAY"),
        (StreamPosition("s", "e1", 3), "WIRE_SEQUENCE_GAP"),
        (StreamPosition("s", "e2", 5), "WIRE_EPOCH_SWITCH_INVALID"),
        (StreamPosition("other", "e1", 2), "WIRE_STREAM_MISMATCH"),
    ]:
        with pytest.raises(WireCodecError, match=code):
            check_stream_successor(first, current)
    with pytest.raises(WireCodecError, match="WIRE_EPOCH_RETIRED"):
        check_stream_successor(switched, first, retired_epochs=frozenset({"e1"}))
    # A sequence that wrapped inside the epoch is a replay, never a restart.
    with pytest.raises(WireCodecError, match="WIRE_SEQUENCE_REPLAY"):
        check_stream_successor(last, StreamPosition("s", "e1", 1))


@pytest.mark.parametrize("kind", PART_KINDS)
def test_typed_parts_round_trip_directly_into_base_objects(kind):
    part = encode_typed_part(kind, SAMPLES[kind])
    assert part["schema_id"] == codec.TYPED_PART_SCHEMA
    assert part["registry_digest"] == codec.schema_digest()
    decoded = decode_typed_part(part, kind=kind)
    assert type(decoded) is type(SAMPLES[kind])
    # Same canonical Base object as the stream codec yields for this kind.
    assert decoded == decode_message(encode_message(kind, SAMPLES[kind], stream=STREAM)).payload


@pytest.mark.parametrize("kind", PART_KINDS)
def test_typed_parts_refuse_other_contracts_and_shapes(kind):
    part = encode_typed_part(kind, SAMPLES[kind])
    for change, code in [
        ({"minor": SUPPORTED_MINOR - 1}, "WIRE_TYPED_CONTRACT_MISMATCH"),
        ({"minor": SUPPORTED_MINOR + 1}, "WIRE_TYPED_CONTRACT_MISMATCH"),
        ({"registry_digest": "0" * 64}, "WIRE_TYPED_CONTRACT_MISMATCH"),
        ({"major": 2}, "WIRE_MAJOR_UNSUPPORTED"),
        ({"schema_id": "other"}, "WIRE_SCHEMA_UNSUPPORTED"),
        ({"extra": 1}, "WIRE_FIELD_SET_INVALID"),
        ({"data": [1]}, "WIRE_PAYLOAD_INVALID"),
    ]:
        with pytest.raises(WireCodecError, match=code):
            decode_typed_part({**part, **change}, kind=kind)
    other = "strategy_result" if kind != "strategy_result" else "strategy_cancel"
    with pytest.raises(WireCodecError, match="WIRE_KIND_INVALID"):
        decode_typed_part(part, kind=other)
    with pytest.raises(WireCodecError, match="WIRE_KIND_INVALID"):
        encode_typed_part(other, SAMPLES[kind])


def test_stream_kinds_are_not_rpc_parts():
    for kind in ("tick", "bar", "fill"):
        with pytest.raises(WireCodecError, match="WIRE_KIND_INVALID"):
            encode_typed_part(kind, SAMPLES[kind])


def test_operation_registries_are_disjoint_and_cover_typed_kinds():
    assert not set(TYPED_SERVICE_OPERATIONS) & set(GENERIC_SERVICE_OPERATIONS)
    for name, entry in TYPED_SERVICE_OPERATIONS.items():
        assert entry["reply"] in codec._KINDS, name
        assert entry["form"] in {"typed_part", "account_observation_map"}
    assert all(type(reason) is str and reason for reason in GENERIC_SERVICE_OPERATIONS.values())
    with pytest.raises(TypeError):
        TYPED_SERVICE_OPERATIONS["x"] = {}  # type: ignore[index]


def test_registry_changes_are_part_of_the_typed_contract(monkeypatch):
    declaration = typed_contract_declaration()
    check_typed_contract_declaration(declaration)
    monkeypatch.setattr(
        codec,
        "GENERIC_SERVICE_OPERATIONS",
        {**GENERIC_SERVICE_OPERATIONS, "account.new_generic": "unreviewed"},
    )
    with pytest.raises(WireCodecError, match="WIRE_TYPED_CONTRACT_MISMATCH"):
        check_typed_contract_declaration(declaration)


@pytest.mark.parametrize(
    "value, code",
    [
        ({}, "WIRE_TYPED_CONTRACT_INVALID"),
        ([], "WIRE_TYPED_CONTRACT_INVALID"),
        (None, "WIRE_TYPED_CONTRACT_INVALID"),
        ({"schema_id": "x", "major": "1", "minor": 5, "registry_digest": ""},
         "WIRE_TYPED_CONTRACT_INVALID"),
        ({"schema_id": codec.SCHEMA_ID, "major": 1, "minor": SUPPORTED_MINOR - 1,
          "registry_digest": codec.schema_digest()}, "WIRE_TYPED_CONTRACT_MISMATCH"),
        ({"schema_id": codec.SCHEMA_ID, "major": 1, "minor": SUPPORTED_MINOR,
          "registry_digest": "0" * 64}, "WIRE_TYPED_CONTRACT_MISMATCH"),
    ],
)
def test_typed_declaration_refuses_malformed_and_mismatched_peers(value, code):
    with pytest.raises(WireCodecError, match=code):
        check_typed_contract_declaration(value)


_OLD_PEER = """
import sys
import bt_api_base.wire_codec_v1 as codec
# Simulate a peer built against the previous typed contract (minor 4).
codec.SUPPORTED_MINOR = 4
real_digest = codec.schema_digest
codec.schema_digest = lambda: "4" * 64
mode = sys.argv[1]
if mode == "declare":
    import json
    sys.stdout.write(json.dumps(codec.typed_contract_declaration()))
elif mode == "read-part":
    import json
    part = json.loads(sys.stdin.read())
    try:
        codec.decode_typed_part(part, kind="strategy_result")
    except codec.WireCodecError as error:
        sys.stdout.write(error.code)
elif mode == "read-message":
    try:
        codec.decode_message(sys.stdin.buffer.read())
    except codec.WireCodecError as error:
        sys.stdout.write(error.code)
"""


def _old_peer(mode: str, data: bytes = b"") -> str:
    process = subprocess.run(
        [sys.executable, "-c", _OLD_PEER, mode],
        input=data,
        capture_output=True,
        check=True,
    )
    return process.stdout.decode()


def test_mixed_version_matrix_against_a_separate_old_process():
    import json

    # new reader <- old peer: the declaration is refused explicitly.
    old_declaration = json.loads(_old_peer("declare"))
    with pytest.raises(WireCodecError, match="WIRE_TYPED_CONTRACT_MISMATCH"):
        check_typed_contract_declaration(old_declaration)
    # old reader <- new typed part: refused explicitly, not reinterpreted.
    part = encode_typed_part("strategy_result", SAMPLES["strategy_result"])
    assert _old_peer("read-part", json.dumps(part).encode()) == "WIRE_TYPED_CONTRACT_MISMATCH"
    # old reader <- new minor-5 stream message: unknown minor.
    frame = encode_message("strategy_submit", SAMPLES["strategy_submit"], stream=STREAM)
    assert _old_peer("read-message", frame) == "WIRE_MINOR_UNSUPPORTED"
    # equal peers: the current declaration is accepted.
    check_typed_contract_declaration(typed_contract_declaration())


def test_operation_contract_lookup_is_exact_then_family_then_refused():
    from bt_api_base.wire_codec_v1 import service_operation_contract

    assert service_operation_contract("account.snapshot.typed")[0] == "typed"
    assert service_operation_contract("execution.account_books.query")[0] == "typed"
    assert service_operation_contract("account.snapshot") == (
        "generic",
        GENERIC_SERVICE_OPERATIONS["account.snapshot"],
    )
    assert service_operation_contract("orders.submit")[0] == "typed"
    assert service_operation_contract("orders.submit")[1]["request"] == "strategy_submit"
    assert service_operation_contract("orders.cancel")[1]["request"] == "strategy_cancel"
    assert service_operation_contract("orders.submit:binding-less-hosts")[0] == "generic"
    assert service_operation_contract("orders.query_group_leg")[1] == (
        GENERIC_SERVICE_OPERATIONS["orders.*"]
    )
    for unknown in ("account.new_unreviewed", "unknown.op", "", None):
        with pytest.raises(WireCodecError, match="WIRE_OPERATION_UNREGISTERED"):
            service_operation_contract(unknown)
