"""Typed v1.4 ``strategy_account_book`` (iteration 60, re-verification G5).

A ``StrategyAccountBookSnapshot`` crosses processes as one typed kind with
exact field sets at every level, canonical Decimal lexemes and an exact
round trip; older peers and claims of an older minor are refused.
"""

from __future__ import annotations

from decimal import Decimal

import msgpack
import pytest

from bt_api_base.account_book_protocol import (
    StrategyAccountBookSnapshot,
    StrategyFinancialLedgerCut,
    StrategyFinancialWatermark,
    StrategyPositionCost,
)
from bt_api_base.wire_codec_v1 import (
    SUPPORTED_MINOR,
    StreamPosition,
    WireCodecError,
    decode_message,
    encode_message,
    schema_digest,
)

_STREAM = StreamPosition("strategy-book:A", "epoch-1", 7)


def _cut():
    marks = tuple(
        StrategyFinancialWatermark(kind, "acct-1", "gen-1", 5, 1_800_000_000_000_000_000)
        for kind in ("execution_outbox", "account_facts", "account_activity")
    )
    return StrategyFinancialLedgerCut("acct-1", "strategy-ledger.v2", 1_800_000_000_000_000_001, marks)


def _book(*, financial=True, **overrides):
    base = dict(
        strategy_ref="A",
        account_ref="acct-1",
        scope_directory_revision="strategy-ledger.v2",
        journal_generation="gen-1",
        baseline_execution_cursor=0,
        current_execution_cursor=5,
        positions={"SIM:X": Decimal("2.000"), "SIM:Y": Decimal("-1.5")},
        fees_since_baseline={"CNY": Decimal("0.75")},
    )
    if financial:
        base.update(
            cash_by_currency={"CNY": Decimal("19799.25"), "BNB": Decimal("-0.01")},
            position_costs={
                "SIM:X": StrategyPositionCost(
                    Decimal("2"),
                    Decimal("200"),
                    "CNY",
                    "spot",
                    "instrument-terms.v1:spot:CNY:1",
                    Decimal("100"),
                )
            },
            cumulative_fees_by_currency={"CNY": Decimal("0.75")},
            financial_available=True,
            cost_basis_complete=True,
            financial_error_code="",
            financial_source="strategy-ledger.v2:strategy_cash_spot.v1",
            financial_freshness="RECONCILED_IN_SNAPSHOT",
            financial_cut_relationship="SAME_TRANSACTION",
            financial_ledger_cut=_cut(),
            account_key="acct-1",
        )
    base.update(overrides)
    return StrategyAccountBookSnapshot(**base)


@pytest.mark.parametrize("financial", [True, False])
def test_round_trip_rebuilds_an_equal_snapshot(financial):
    book = _book(financial=financial)
    result = decode_message(encode_message("strategy_account_book", book, stream=_STREAM))
    assert result.kind == "strategy_account_book" and result.minor == SUPPORTED_MINOR == 5
    assert type(result.payload) is StrategyAccountBookSnapshot
    assert result.payload == book
    assert result.payload.positions["SIM:Y"] == Decimal("-1.5")
    if financial:
        assert result.payload.financial_ledger_cut == book.financial_ledger_cut
        assert result.payload.position_costs["SIM:X"].average_cost == Decimal("100")


def _wire(book=None):
    return msgpack.unpackb(
        encode_message("strategy_account_book", book or _book(), stream=_STREAM), raw=False
    )


def _expect(wire, code):
    with pytest.raises(WireCodecError, match=code):
        decode_message(msgpack.packb(wire, use_bin_type=True))


def test_decimals_must_be_canonical_lexemes():
    wire = _wire()
    wire["data"]["positions"]["SIM:X"] = "2.000"
    _expect(wire, "WIRE_DECIMAL_INVALID")
    wire = _wire()
    wire["data"]["cash_by_currency"]["CNY"] = 19799
    _expect(wire, "WIRE_DECIMAL_INVALID")


@pytest.mark.parametrize(
    "path",
    [
        ("data",),
        ("data", "position_costs", "SIM:X"),
        ("data", "financial_ledger_cut"),
        ("data", "financial_ledger_cut", "watermarks", 0),
    ],
)
def test_every_level_has_an_exact_field_set(path):
    for change in ("extra", "missing"):
        wire = _wire()
        target = wire
        for key in path:
            target = target[key]
        if change == "extra":
            target["injected"] = None
        else:
            target.pop(next(iter(target)))
        _expect(wire, "WIRE_FIELD_SET_INVALID")


def test_container_validation_still_applies_after_decode():
    wire = _wire()
    wire["data"]["financial_ledger_cut"]["watermarks"].pop()  # two of three sources
    _expect(wire, "WIRE_PAYLOAD_INVALID")
    wire = _wire()
    wire["data"]["financial_available"] = 1  # not an exact bool
    _expect(wire, "WIRE_PAYLOAD_INVALID")


def _map(pairs):
    """A MessagePack map with the given (possibly repeated) keys, in order."""

    assert len(pairs) < 16
    return bytes([0x80 | len(pairs)]) + b"".join(
        msgpack.packb(key) + (value if type(value) is bytes else msgpack.packb(value))
        for key, value in pairs
    )


def test_duplicate_keys_are_refused():
    wire = _wire()
    data = list(wire["data"].items())
    nested = msgpack.packb(dict(data[:-1]), use_bin_type=True)  # sanity: packs
    assert nested
    # data map with "strategy_ref" twice (A, then B) and nothing else changed.
    body = bytes([0xDE]) + len(data + [("strategy_ref", "B")]).to_bytes(2, "big") + b"".join(
        msgpack.packb(key) + msgpack.packb(value, use_bin_type=True)
        for key, value in data + [("strategy_ref", "B")]
    )
    envelope = _map(
        [(key, body if key == "data" else value) for key, value in wire.items()]
    )
    with pytest.raises(WireCodecError, match="WIRE_DUPLICATE_KEY"):
        decode_message(envelope)


def test_older_minor_claims_and_older_peers_are_refused():
    wire = _wire()
    wire["minor"] = 3  # the kind did not exist before minor 4
    _expect(wire, "WIRE_MINOR_UNSUPPORTED")
    frame = encode_message("strategy_account_book", _book(), stream=_STREAM)
    with pytest.raises(WireCodecError, match="WIRE_MINOR_UNSUPPORTED"):
        decode_message(frame, supported_minor=3)  # a minor-3 peer


def test_unrepresentable_snapshots_are_refused_on_encode():
    many = {f"SIM:{index}": Decimal(1) for index in range(300)}  # > container limit
    with pytest.raises(WireCodecError):
        encode_message(
            "strategy_account_book", _book(financial=False, positions=many), stream=_STREAM
        )
    with pytest.raises(WireCodecError, match="WIRE_DECIMAL_INVALID"):
        encode_message(
            "strategy_account_book",
            _book(financial=False, positions={"SIM:X": Decimal("1." + "1" * 60)}),
            stream=_STREAM,
        )


def test_schema_digest_covers_the_new_kind():
    import bt_api_base.wire_codec_v1 as codec

    before = schema_digest()
    original = codec._COST_DECIMALS
    try:
        codec._COST_DECIMALS = ("quantity",)
        assert schema_digest() != before
    finally:
        codec._COST_DECIMALS = original
    assert schema_digest() == before
