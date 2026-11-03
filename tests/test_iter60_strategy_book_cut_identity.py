"""Strategy account book contract 2: declared cut identity (iteration 60, R2-D).

A ``SAME_TRANSACTION`` financial cut names one ledger transaction for the
positions and for cash/costs/terms and carries that transaction's BALANCED
reconciliation verdict. Version 1 snapshots (no cut identity) are refused.
"""

from __future__ import annotations

import msgpack
import pytest

from bt_api_base.account_book_protocol import (
    STRATEGY_ACCOUNT_BOOK_CONTRACT_VERSION,
    AccountBookProjectionError,
    StrategyAccountBookSnapshot,
)
from bt_api_base.wire_codec_v1 import (
    WireCodecError,
    decode_message,
    decode_typed_part,
    encode_message,
    encode_typed_part,
)

from tests.test_wire_strategy_account_book import _STREAM, _book


def _code(call):
    with pytest.raises(AccountBookProjectionError) as raised:
        call()
    return raised.value.code


def test_contract_version_two_round_trips_the_cut_identity():
    assert STRATEGY_ACCOUNT_BOOK_CONTRACT_VERSION == 2
    book = _book()
    assert book.contract_version == 2
    part = encode_typed_part("strategy_account_book", book)
    assert part["data"]["contract_version"] == 2
    assert part["data"]["position_cut_id"] == part["data"]["financial_cut_id"] == "gen-1:5:cut"
    assert part["data"]["reconciliation_state"] == "BALANCED"
    rebuilt = decode_typed_part(part, kind="strategy_account_book")
    assert rebuilt == book
    frame = decode_message(encode_message("strategy_account_book", book, stream=_STREAM))
    assert frame.payload == book


@pytest.mark.parametrize("version", [1, 3, 0, "2", True])
def test_other_contract_versions_are_refused(version):
    assert _code(lambda: _book(contract_version=version)) == (
        "STRATEGY_BOOK_CONTRACT_VERSION_UNSUPPORTED"
    )
    part = encode_typed_part("strategy_account_book", _book())
    part["data"]["contract_version"] = version
    with pytest.raises(WireCodecError):
        decode_typed_part(part, kind="strategy_account_book")


def test_a_version_one_payload_without_cut_identity_is_refused():
    wire = msgpack.unpackb(
        encode_message("strategy_account_book", _book(), stream=_STREAM), raw=False
    )
    for name in ("contract_version", "position_cut_id", "financial_cut_id",
                 "reconciliation_state"):
        wire["data"].pop(name)
    with pytest.raises(WireCodecError, match="WIRE_FIELD_SET_INVALID"):
        decode_message(msgpack.packb(wire, use_bin_type=True))


@pytest.mark.parametrize(
    "changes",
    [
        {"financial_cut_id": "gen-1:5:other"},
        {"financial_cut_id": None},
        {"position_cut_id": None, "financial_cut_id": None},
        {"reconciliation_state": "IN_FLIGHT"},
        {"reconciliation_state": None},
    ],
)
def test_same_transaction_claim_needs_one_cut_and_a_balanced_verdict(changes):
    assert _code(lambda: _book(**changes)) == "STRATEGY_FINANCIAL_CUT_MISMATCH"


def test_a_tampered_typed_part_cannot_claim_mismatched_cuts():
    part = encode_typed_part("strategy_account_book", _book())
    part["data"]["financial_cut_id"] = "gen-1:5:other"
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_typed_part(part, kind="strategy_account_book")


def test_unavailable_financials_cannot_carry_a_financial_cut_id():
    assert _code(
        lambda: _book(financial=False, financial_cut_id="x", position_cut_id="x")
    ) == "INVALID_FINANCIAL_CUT"
    book = _book(financial=False, position_cut_id="gen-1:5:cut", reconciliation_state="IN_FLIGHT")
    assert type(book) is StrategyAccountBookSnapshot and book.financial_cut_id is None


def test_unknown_reconciliation_states_are_refused():
    assert _code(lambda: _book(financial=False, reconciliation_state="MAYBE")) == (
        "INVALID_RECONCILIATION_STATE"
    )
