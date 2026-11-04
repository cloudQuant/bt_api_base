"""Iteration 60 R3: provider fee on trade observations (account execution event v2).

A trade observation may carry the provider fee of the fill (both fields or
none). The fee is part of the trade fact, so a corrected fee for the same fill
is a new fact (a fee correction) and the same fee is a duplicate. Version 1
events are refused explicitly; the minor-3 typed wire trade kind stays fee-free
and refuses a fee-bearing observation instead of dropping the fee. The shared
strategy client-order-id prefix is deterministic.
"""

from dataclasses import replace

import pytest
from test_wire_account_codec import _observation
from test_wire_execution_observations import _trade

from bt_api_base.execution_row_observation_protocol import (
    EXECUTION_EVENT_SCHEMA,
    EXECUTION_TRADE_EVENT_KIND,
    AccountExecutionTradeObservation,
    execution_observation_event,
    execution_observation_fact_digest,
    execution_observation_fact_id,
    execution_observation_from_event,
    strategy_client_order_id,
    strategy_client_order_prefix,
)
from bt_api_base.wire_codec_v1 import WireCodecError, decode_typed_part, encode_typed_part


def _trades(fee=None, currency=None, **changes):
    return AccountExecutionTradeObservation(
        _observation().account_key, replace(_trade(), **changes), fee, currency
    )


def test_v2_kind_and_schema_and_fee_round_trip():
    assert EXECUTION_TRADE_EVENT_KIND == "account.execution_trade.v2"
    assert EXECUTION_EVENT_SCHEMA == "bt_api.account.execution_event.v2"
    with_fee = _trades("0.25", "USDT")
    kind, event_id, payload = execution_observation_event(with_fee)
    assert payload["observation"]["fee"] == "0.25"
    assert payload["observation"]["fee_currency"] == "USDT"
    assert execution_observation_from_event(kind, event_id, payload) == with_fee
    plain = _trades()
    kind, event_id, payload = execution_observation_event(plain)
    assert set(payload["observation"]) == {"account_key", "trade"}
    assert execution_observation_from_event(kind, event_id, payload) == plain


def test_fee_is_part_of_the_trade_fact():
    base = _trades("0.25", "USDT")
    same = _trades("0.250", "USDT", observed_at_utc="2026-11-04T01:05:00Z")
    assert execution_observation_fact_id(base) == execution_observation_fact_id(same)
    assert execution_observation_fact_digest(base) == execution_observation_fact_digest(same)
    corrected = _trades("0.30", "USDT")
    assert execution_observation_fact_id(corrected) != execution_observation_fact_id(base)
    assert execution_observation_fact_id(_trades("0.25", "BTC")) != execution_observation_fact_id(
        base
    )
    assert execution_observation_fact_id(_trades()) != execution_observation_fact_id(base)


@pytest.mark.parametrize(
    ("fee", "currency"), [("0.1", None), (None, "USDT"), ("-1", "USDT"), ("x", "USDT"), ("1", "")]
)
def test_fee_pair_and_value_are_validated(fee, currency):
    with pytest.raises((TypeError, ValueError)):
        _trades(fee, currency)


def test_version_one_events_are_refused_explicitly():
    kind, event_id, payload = execution_observation_event(_trades())
    with pytest.raises(ValueError, match="version 1"):
        execution_observation_from_event("account.execution_trade.v1", event_id, payload)
    old = dict(payload, schema="bt_api.account.execution_event.v1")
    with pytest.raises(ValueError, match="version 1"):
        execution_observation_from_event(kind, event_id, old)
    # A fee field set with a missing value is not a v2 encoding.
    _kind, fee_id, fee_payload = execution_observation_event(_trades("1", "USDT"))
    broken = dict(fee_payload)
    broken["observation"] = dict(fee_payload["observation"], fee=None)
    with pytest.raises(ValueError):
        execution_observation_from_event(kind, fee_id, broken)


def test_typed_wire_trade_kind_refuses_fee_facts():
    part = encode_typed_part("execution_trade", _trades())
    decoded = decode_typed_part(part, kind="execution_trade")
    assert decoded.fee is None
    assert execution_observation_fact_digest(decoded) == execution_observation_fact_digest(
        _trades()
    )
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        encode_typed_part("execution_trade", _trades("0.25", "USDT"))


def test_strategy_client_order_prefix_is_deterministic_and_distinct():
    first = strategy_client_order_prefix("strategy-a")
    assert first == strategy_client_order_prefix("strategy-a")
    assert first != strategy_client_order_prefix("strategy-b")
    assert len(first) == 10 and first.startswith("s") and first.isalnum()
    for bad in ("", " a", None, "x" * 257):
        with pytest.raises(ValueError):
            strategy_client_order_prefix(bad)


def test_strategy_client_order_id_fits_the_strictest_venue_grammar():
    """OKX clOrdId (<= 32 alphanumerics) and Binance (<= 36 of [.A-Z:/a-z0-9_-])."""

    import re

    digest = "0123456789abcdef" * 4
    client_id = strategy_client_order_id("strategy-a", digest)
    assert client_id.startswith(strategy_client_order_prefix("strategy-a"))
    assert len(client_id) == 32 and client_id.isalnum() and client_id == client_id.lower()
    assert re.fullmatch(r"[A-Za-z0-9]{1,32}", client_id)  # OKX
    assert re.fullmatch(r"[.A-Z:/a-z0-9_-]{1,36}", client_id)  # Binance
    for bad in ("ABC" * 10, "0" * 21, "g" * 30, None):
        with pytest.raises(ValueError):
            strategy_client_order_id("strategy-a", bad)
