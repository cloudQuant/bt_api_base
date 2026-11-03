"""Typed account snapshots retain scope, missing facts and bounded decimals."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace

import msgpack
import pytest

import bt_api_base.wire_codec_v1 as codec
from bt_api_base.account_protocol import (
    AccountBalance,
    AccountKey,
    AccountObservation,
    AccountOpenOrder,
    AccountPosition,
    AccountResourceKey,
    AccountValuation,
)
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.wire_codec_v1 import (
    StreamPosition,
    WireCodecError,
    decode_message,
    encode_message,
    schema_digest,
)

_STREAM = StreamPosition("account-stream", "epoch-1", 1)
_TIME = "2026-10-13T04:05:06Z"


def _observation(*, with_orders=True):
    account = AccountKey("alpha", "venue-a", "paper", "account-a", None)
    resource = AccountResourceKey("future", "pool")
    instrument = MarketInstrumentKey("alpha", "venue-a", "paper", "future", "x", "X")
    position = AccountPosition(
        resource, instrument, "net", "-2.500", "contracts", None, None, _TIME
    )
    balance = AccountBalance(resource, "USD", "100.00", None, "0.00", _TIME)
    order = AccountOpenOrder(
        resource,
        instrument,
        "id-1",
        "buy",
        "net",
        "limit",
        "partially_filled",
        "2.00",
        "0.50",
        "contracts",
        _TIME,
        _TIME,
        client_order_id=None,
        limit_price="10.250",
        stop_price=None,
        price_currency="USD",
        reduce_only=None,
    )
    return AccountObservation(
        account,
        "snapshot-1",
        (resource,),
        (balance,),
        (position,),
        AccountValuation("USD", None, "100.00", _TIME),
        _TIME,
        _TIME,
        "multi_query",
        True,
        False,
        open_orders=(order,) if with_orders else None,
        open_orders_complete=with_orders,
    )


def _frame(observation=None):
    return encode_message("account", observation or _observation(), stream=_STREAM)


def test_account_snapshot_roundtrip_preserves_scope_and_unknown_values():
    result = decode_message(_frame()).payload
    assert type(result) is AccountObservation
    assert result.account_key.account_id == "account-a"
    assert result.balances[0].available is None
    assert result.balances[0].locked == "0"
    assert result.positions[0].quantity == "-2.5"
    assert result.positions[0].average_price is None
    assert result.positions_complete is False
    assert result.open_orders[0].filled_quantity == "0.5"
    assert result.open_orders[0].limit_price == "10.25"
    assert result.open_orders[0].client_order_id is None
    assert result.valuation.available_cash is None


@pytest.mark.parametrize(
    "where",
    ["snapshot", "account", "coverage", "balance", "position", "order", "valuation",
     "instrument", "resource"],
)
def test_account_snapshot_refuses_attached_unrepresentable_fields(where):
    observation = _observation()
    targets = {
        "snapshot": observation,
        "account": observation.account_key,
        "coverage": observation.coverage[0],
        "balance": observation.balances[0],
        "position": observation.positions[0],
        "order": observation.open_orders[0],
        "valuation": observation.valuation,
        "instrument": observation.positions[0].instrument,
        "resource": observation.positions[0].resource,
    }
    object.__setattr__(targets[where], "extra_unrepresentable_field", "unretained data")
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        _frame(observation)


def test_account_snapshot_refuses_mutated_tuple_subclass_even_if_values_compare_equal():
    class Positions(tuple):
        pass

    observation = _observation()
    altered = Positions(observation.positions)
    assert altered == observation.positions
    object.__setattr__(observation, "positions", altered)
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        _frame(observation)


def test_unknown_open_orders_differ_from_confirmed_empty():
    unknown = _observation(with_orders=False)
    empty = replace(unknown, open_orders=(), open_orders_complete=True)
    assert decode_message(_frame(unknown)).payload.open_orders is None
    decoded_empty = decode_message(_frame(empty)).payload
    assert decoded_empty.open_orders == () and decoded_empty.open_orders_complete is True


@pytest.mark.parametrize("mutation", ["noncanonical", "scope", "unknown_field", "wrong_minor"])
def test_account_rejects_invalid_wire_facts(mutation):
    body = msgpack.unpackb(_frame(), raw=False)
    if mutation == "noncanonical":
        body["data"]["positions"][0]["quantity"] = "-2.500"
    elif mutation == "scope":
        body["data"]["positions"][0]["instrument"]["provider"] = "other"
    elif mutation == "unknown_field":
        body["data"]["positions"][0]["unrecognized"] = True
    else:
        body["minor"] = 1
    with pytest.raises(WireCodecError):
        decode_message(msgpack.packb(body, use_bin_type=True))


def test_old_minor_rejects_account_frame_and_digest_changes(monkeypatch):
    with pytest.raises(WireCodecError, match="WIRE_MINOR_UNSUPPORTED"):
        decode_message(_frame(), supported_minor=1)
    previous = {
        "schema_id": codec.SCHEMA_ID,
        "major": codec.SUPPORTED_MAJOR,
        "minor": 1,
        "kinds": {
            "tick": {
                "payload_schema_version": codec.MARKET_TICK_SCHEMA_VERSION,
                "quality_contract_ref": "nullable-v2-non-executable-when-null",
                "fields": list(codec._TICK_FIELDS),
                "instrument": list(codec._INSTRUMENT_FIELDS),
                "decimals": sorted(codec._TICK_FLOATS),
                "enums": {k: [m.value for m in v] for k, v in sorted(codec._TICK_ENUMS.items())},
            },
            "bar": {"fields": list(codec._BAR_FIELDS)},
            "fill": {
                "schema": codec.MANAGED_PAPER_FILL_V2_SCHEMA,
                "fields": sorted(codec.MANAGED_PAPER_FILL_V2_FIELDS),
                "decimals": list(codec._FILL_DECIMALS),
                "integers": list(codec._FILL_INTEGERS),
            },
        },
    }
    old_digest = hashlib.sha256(
        json.dumps(previous, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert schema_digest() != old_digest
    # 60.08: the registry digest is negotiated at connect (typed_contract);
    # a peer still declaring the old registry is refused explicitly.
    current_declaration = codec.typed_contract_declaration()
    monkeypatch.setattr(codec, "schema_digest", lambda: old_digest)
    old_declaration = codec.typed_contract_declaration()
    assert old_declaration != current_declaration
    monkeypatch.undo()
    with pytest.raises(WireCodecError, match="WIRE_TYPED_CONTRACT_MISMATCH"):
        codec.check_typed_contract_declaration(old_declaration)


@pytest.mark.parametrize(
    "section", ["account_scope", "snapshot", "balance", "valuation", "position", "open_order"]
)
def test_account_semantic_revision_changes_wire_and_service_digest(monkeypatch, section):
    old_wire = schema_digest()
    old_declaration = codec.typed_contract_declaration()
    updated = deepcopy(codec._ACCOUNT_WIRE_SEMANTICS)
    updated["revision"] += 1
    updated[section]["reviewed_semantic_revision"] = 2
    monkeypatch.setattr(codec, "_ACCOUNT_WIRE_SEMANTICS", updated)
    assert schema_digest() != old_wire
    # The semantic revision is fenced by the connect-time typed negotiation.
    with pytest.raises(WireCodecError, match="WIRE_TYPED_CONTRACT_MISMATCH"):
        codec.check_typed_contract_declaration(old_declaration)


def test_account_codec_rejects_unrepresentable_decimal_and_oversized_array():
    observation = _observation(with_orders=False)
    oversized_decimal = replace(observation.positions[0], quantity="1" * 41)
    with pytest.raises(WireCodecError, match="WIRE_DECIMAL_INVALID"):
        _frame(replace(observation, positions=(oversized_decimal,)))
    balances = tuple(replace(observation.balances[0], currency=f"C{i}") for i in range(257))
    with pytest.raises(WireCodecError, match="WIRE_VALUE_INVALID"):
        _frame(replace(observation, balances=balances))


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("balances", "total"),
        ("balances", "available"),
        ("positions", "quantity"),
        ("positions", "average_price"),
        ("open_orders", "quantity"),
        ("open_orders", "filled_quantity"),
        ("open_orders", "limit_price"),
        ("valuation", "equity"),
    ],
)
@pytest.mark.parametrize("noncanonical", ["1.0", "-0", "1e2", 1, True])
def test_account_requires_canonical_wire_decimal_for_every_numeric_section(
    section, field, noncanonical
):
    wire = msgpack.unpackb(_frame(), raw=False)
    rows = wire["data"][section]
    row = rows if section == "valuation" else rows[0]
    row[field] = noncanonical
    with pytest.raises(WireCodecError, match="WIRE_DECIMAL_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))


def test_account_encode_revalidates_low_level_mutated_frozen_snapshot():
    observation = _observation()
    object.__setattr__(observation, "balances_complete", "true")
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        _frame(observation)


def test_account_encode_does_not_discard_inconsistent_missing_order_flag():
    observation = _observation(with_orders=False)
    # The legacy mapping omits the flag when open_orders is missing.  An
    # inconsistent object must not be normalized into a plausible snapshot.
    object.__setattr__(observation, "open_orders_complete", True)
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        _frame(observation)


def test_account_encode_rejects_non_utf8_stream_identity_with_finite_error():
    stream = StreamPosition("\ud800", "epoch", 1)
    with pytest.raises(WireCodecError, match="WIRE_VALUE_INVALID"):
        encode_message("account", _observation(), stream=stream)


@pytest.mark.parametrize("unsupported", [-1, True, 6, "2", None])
def test_decoder_cannot_be_configured_to_accept_unknown_minor(unsupported):
    with pytest.raises(WireCodecError, match="WIRE_MINOR_UNSUPPORTED"):
        decode_message(_frame(), supported_minor=unsupported)


def test_account_decode_rejects_oversized_array_and_depth():
    wire = msgpack.unpackb(_frame(), raw=False)
    wire["data"]["balances"] = wire["data"]["balances"] * 257
    with pytest.raises(WireCodecError, match="WIRE_FRAME_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))

    wire = msgpack.unpackb(_frame(), raw=False)
    wire["data"]["unrecognized"] = {"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}}
    with pytest.raises(WireCodecError, match="WIRE_DEPTH_EXCEEDED"):
        decode_message(msgpack.packb(wire, use_bin_type=True))


def test_account_snapshot_cross_process_roundtrip():
    script = (
        "import sys; from bt_api_base.wire_codec_v1 import decode_message; "
        "a=decode_message(sys.stdin.buffer.read()).payload; "
        "assert a.account_key.account_id=='account-a'; "
        "assert a.positions[0].quantity=='-2.5'; "
        "assert a.balances[0].available is None"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=_frame(),
        capture_output=True,
        check=False,
        env=os.environ.copy(),
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode()
