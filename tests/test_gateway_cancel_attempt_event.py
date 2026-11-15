"""Pure wire-contract checks; no journal or source authority is exercised."""

from copy import deepcopy
from dataclasses import replace

import pytest

from bt_api_base.gateway_cancel_attempt_event import (
    GatewayCancelAttemptEvent,
    GatewayCancelAttemptEventError,
)
from bt_api_base.gateway_cancel_protocol import GatewayCancelRecord
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.market_protocol import MarketInstrumentKey


@pytest.fixture
def requested():
    binding = GatewayCommandBinding("journal", "account", "strategy", "principal")
    record = GatewayCancelRecord(
        1,
        binding,
        "operation",
        "attempt",
        "request",
        "reservation",
        "a" * 64,
        "REQUESTED",
        1,
        "g1",
        "g1",
        True,
        None,
    )
    instrument = MarketInstrumentKey("CTP", "venue", "sim", "future", "instrument", "symbol")
    return GatewayCancelAttemptEvent(1, record, instrument, "20261115", None)


def state(event, name, version, digest="b" * 64, **kwargs):
    return replace(
        event,
        record=replace(event.record, state=name, version=version, **kwargs),
        prepared_digest=digest,
    )


@pytest.mark.parametrize(
    "name,version", [("DISPATCHING", 2), ("SENT", 3), ("UNKNOWN", 3), ("NOT_SENT", 3)]
)
def test_roundtrip_all_states_and_business_identity(requested, name, version):
    event = state(requested, name, version)
    for candidate in (requested, event):
        assert (
            GatewayCancelAttemptEvent.from_mapping(
                candidate.to_mapping(), expected_binding=candidate.record.binding
            )
            == candidate
        )
        assert candidate.business_key == ("account", "journal", "attempt")
    requested.check_successor(event)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.pop("trading_day"),
        lambda m: m.update(extra="x"),
        lambda m: m["record"].pop("attempt_id"),
        lambda m: m["record"].update(extra="x"),
        lambda m: m["instrument"].pop("native_symbol"),
        lambda m: m["instrument"].update(extra="x"),
        lambda m: m.update(schema_version=True),
        lambda m: m.update(trading_day="20260229"),
        lambda m: m.update(trading_day="2026-01-01"),
        lambda m: m.update(prepared_digest="b" * 64),
        lambda m: m["record"].update(attempt_id=" attempt"),
        lambda m: m["record"].update(operation_id="x" * 257),
        lambda m: m["record"]["binding"].update(account_scope="other"),
    ],
)
def test_reject_noncanonical_or_incomplete_wire(requested, mutation):
    raw = deepcopy(requested.to_mapping())
    mutation(raw)
    with pytest.raises(GatewayCancelAttemptEventError):
        GatewayCancelAttemptEvent.from_mapping(raw, expected_binding=requested.record.binding)


def test_prepared_digest_state_validation(requested):
    for digest in (None, "A" * 64, "a" * 63):
        with pytest.raises(GatewayCancelAttemptEventError):
            state(requested, "DISPATCHING", 2, digest)
    raw = state(requested, "SENT", 3).to_mapping()
    raw["record"]["version"] = 2
    with pytest.raises(GatewayCancelAttemptEventError):
        GatewayCancelAttemptEvent.from_mapping(raw, expected_binding=requested.record.binding)


def test_successor_conflict_and_day_rollover(requested):
    dispatch = state(requested, "DISPATCHING", 2)
    sent = state(requested, "SENT", 3)
    requested.check_successor(requested)
    dispatch.check_successor(replace(sent, trading_day="20261116"))
    for other in (
        replace(dispatch, trading_day="20261116"),
        replace(sent, prepared_digest="c" * 64),
        replace(sent, record=replace(sent.record, operation_id="other")),
        replace(sent, instrument=replace(sent.instrument, instrument_id="other")),
        requested,
        state(requested, "UNKNOWN", 3),
    ):
        with pytest.raises(GatewayCancelAttemptEventError, match="CANCEL_ATTEMPT_CONFLICT"):
            (
                sent if other.record.state == "UNKNOWN" or other is requested else dispatch
            ).check_successor(other)


def test_same_version_owner_restart_preserves_attempt_identity(requested):
    dispatch = state(requested, "DISPATCHING", 2)
    after_restart = replace(
        dispatch,
        record=replace(dispatch.record, owner_generation="g2", generation_current=False),
    )
    dispatch.check_successor(after_restart)
    after_restart.check_successor(dispatch)
    for changed in (
        replace(after_restart, trading_day="20261116"),
        replace(after_restart, prepared_digest="c" * 64),
        replace(after_restart, record=replace(after_restart.record, operation_id="other")),
        replace(
            after_restart,
            record=replace(after_restart.record, attempt_generation="g2", generation_current=True),
        ),
        state(requested, "UNKNOWN", 3),
    ):
        with pytest.raises(GatewayCancelAttemptEventError, match="CANCEL_ATTEMPT_CONFLICT"):
            (
                state(requested, "SENT", 3) if changed.record.version == 3 else dispatch
            ).check_successor(changed)


def test_later_version_may_cross_day_but_never_go_backwards(requested):
    dispatch = state(requested, "DISPATCHING", 2)
    sent = state(requested, "SENT", 3)
    dispatch.check_successor(sent)
    dispatch.check_successor(replace(sent, trading_day="20261116"))
    with pytest.raises(GatewayCancelAttemptEventError, match="CANCEL_ATTEMPT_CONFLICT"):
        dispatch.check_successor(replace(sent, trading_day="20261114"))
