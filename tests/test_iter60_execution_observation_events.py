"""Iteration 60 R2-C: account-journal envelope for execution observations.

The event id is a fact id (same provider fact -> same id across
redeliveries); the digest detects a conflicting fact under one id. Neither is
evidence of the fact, its source or an intent binding.
"""

from dataclasses import replace
from types import MappingProxyType

import pytest
from test_wire_account_codec import _observation
from test_wire_execution_observations import _order, _trade

from bt_api_base.execution_row_observation_protocol import (
    EXECUTION_ORDER_EVENT_KIND,
    EXECUTION_TRADE_EVENT_KIND,
    AccountExecutionOrderObservation,
    AccountExecutionTradeObservation,
    execution_observation_event,
    execution_observation_fact_digest,
    execution_observation_fact_id,
    execution_observation_from_event,
)


def _orders(**changes):
    return AccountExecutionOrderObservation(
        _observation().account_key, replace(_order("open"), **changes)
    )


def _trades(**changes):
    return AccountExecutionTradeObservation(
        _observation().account_key, replace(_trade(), **changes)
    )


def test_fact_id_ignores_observation_time_and_decimal_spelling():
    first = _orders()
    later = _orders(observed_at_utc="2026-11-03T01:05:00Z", quantity="123456789012345.12345")
    assert execution_observation_fact_id(first) == execution_observation_fact_id(later)
    assert execution_observation_fact_digest(first) == execution_observation_fact_digest(later)
    assert execution_observation_fact_id(first).startswith("xo-")
    assert execution_observation_fact_id(_trades()).startswith("xt-")


def test_order_state_and_cumulative_quantity_change_the_fact():
    base = execution_observation_fact_id(_orders())
    assert (
        execution_observation_fact_id(_orders(status="partially_filled", filled_quantity="1"))
        != base
    )
    assert execution_observation_fact_id(_orders(filled_quantity="2")) != base
    assert execution_observation_fact_id(_orders(order_id="other")) != base


def test_conflicting_content_keeps_the_id_but_changes_the_digest():
    one, other = _trades(), _trades(price="12345.68")
    assert execution_observation_fact_id(one) == execution_observation_fact_id(other)
    assert execution_observation_fact_digest(one) != execution_observation_fact_digest(other)


@pytest.mark.parametrize(
    "factory, kind", [(_orders, EXECUTION_ORDER_EVENT_KIND), (_trades, EXECUTION_TRADE_EVENT_KIND)]
)
def test_event_round_trip_through_frozen_json(factory, kind):
    observation = factory()
    event_kind, event_id, payload = execution_observation_event(observation)
    assert event_kind == kind and event_id == payload["fact_id"]

    def freeze(value):
        if isinstance(value, dict):
            return MappingProxyType({k: freeze(v) for k, v in value.items()})
        if isinstance(value, list):
            return tuple(freeze(v) for v in value)
        return value

    assert execution_observation_from_event(event_kind, event_id, freeze(payload)) == observation


def test_decoding_rejects_forged_ids_digests_kinds_and_fields():
    kind, event_id, payload = execution_observation_event(_trades())
    with pytest.raises(ValueError):
        execution_observation_from_event(kind, "xt-forged", payload)
    with pytest.raises(ValueError):
        execution_observation_from_event(kind, event_id, dict(payload, fact_digest="0" * 64))
    with pytest.raises(ValueError):
        execution_observation_from_event(EXECUTION_ORDER_EVENT_KIND, event_id, payload)
    with pytest.raises(ValueError):
        execution_observation_from_event("position_update", event_id, payload)
    with pytest.raises(ValueError):
        execution_observation_from_event(kind, event_id, dict(payload, extra=1))
    with pytest.raises(ValueError):
        execution_observation_from_event(kind, event_id, dict(payload, schema="v0"))
    tampered = dict(payload, observation=dict(payload["observation"]))
    tampered["observation"]["trade"] = dict(tampered["observation"]["trade"], quantity="9")
    with pytest.raises(ValueError):
        execution_observation_from_event(kind, event_id, tampered)


def test_non_observations_are_rejected():
    with pytest.raises(TypeError):
        execution_observation_fact_id(_order())
