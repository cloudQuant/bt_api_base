"""Explicit fact/page versioning for cancel-error correlation."""

import json
from dataclasses import replace

import pytest
from test_gateway_execution_protocol import trade as trade

from bt_api_base.direct_write_protocol import DirectExecutionEventKind
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_protocol import GatewayExecutionProtocolError, GatewayReturnFact
from bt_api_base.gateway_execution_stream_protocol import (
    GatewayCancelErrorAttribution,
    GatewayExecutionStreamEvent,
    GatewayExecutionStreamPage,
    GatewayExecutionStreamProgress,
    GatewayExecutionStreamProtocolError,
    gateway_execution_consumer_ref,
    project_gateway_execution_observation,
)


def _cancel_fact(trade, *, key="native-attempt-one"):
    return replace(
        trade,
        kind=DirectExecutionEventKind.CANCEL_ERROR,
        trade_key=None,
        trade_quantity=None,
        trade_price=None,
        trade_time=None,
        schema_version=2,
        cancel_request_key=key,
        error_code="CANCEL_REJECTED",
    )


def _page(fact, *, attribution=None):
    binding = GatewayCommandBinding("journal", fact.account_scope, "strategy", "principal")
    consumer = gateway_execution_consumer_ref(
        principal_ref="principal",
        actor_ref="strategy",
        execution_domain_ref="domain",
        account_scope=fact.account_scope,
        strategy_scope="strategy",
    )
    event = GatewayExecutionStreamEvent(
        1,
        "order-request",
        "reservation",
        "a" * 64,
        "original-principal",
        fact.fact_digest(),
        project_gateway_execution_observation(fact),
        attribution,
    )
    return GatewayExecutionStreamPage(binding, consumer, "e" * 64, 1, 0, False, (event,))


def test_fact_v1_shape_and_digests_are_pinned(trade):
    raw = trade.to_mapping()
    assert raw["schema_version"] == 1 and "cancel_request_key" not in raw
    assert trade.fact_digest() == "1705101f6baaf40c0a07b6c9b9ad71995c92f40098b30276b2066c435d3898e3"
    assert (
        trade.trade_content_digest()
        == "6e3b6bf378cc58f30abeb4da3a9c4412b13dab6ff219b3cacdbffda56b8d280d"
    )
    assert GatewayReturnFact.from_mapping(raw) == trade


def test_v2_cancel_attempt_key_distinguishes_same_error_and_excludes_source(trade):
    one, two = _cancel_fact(trade), _cancel_fact(trade, key="native-attempt-two")
    assert one.fact_digest() != two.fact_digest()
    assert (
        replace(one, source_ref="another-source", session_generation=99).fact_digest()
        == one.fact_digest()
    )
    raw = one.to_mapping()
    assert raw["schema_version"] == 2 and raw["cancel_request_key"] == "native-attempt-one"
    assert GatewayReturnFact.from_mapping(raw) == one
    assert one.trade_content_digest() is None


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 2, "cancel_request_key": None},
        {"schema_version": 1, "cancel_request_key": "attempt"},
        {"schema_version": True, "cancel_request_key": "attempt"},
        {"schema_version": 3, "cancel_request_key": "attempt"},
        {"cancel_request_key": True},
        {"cancel_request_key": ""},
        {"cancel_request_key": "界" * 86},
    ],
)
def test_fact_v2_rejects_missing_or_bad_attempt_key_and_version(trade, change):
    with pytest.raises(GatewayExecutionProtocolError):
        replace(_cancel_fact(trade), **change)


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 1},
        {"schema_version": True},
        {"schema_version": 3},
        {"cancel_request_key": None},
        {"cancel_request_key": True},
        {"extra": 1},
    ],
)
def test_fact_wire_rejects_wrong_shape_and_types(trade, change):
    raw = _cancel_fact(trade).to_mapping()
    raw.update(change)
    with pytest.raises(GatewayExecutionProtocolError):
        GatewayReturnFact.from_mapping(raw)


def test_fact_wire_rejects_v2_for_any_non_cancel_kind(trade):
    raw = trade.to_mapping()
    raw.update(schema_version=2, cancel_request_key="attempt")
    with pytest.raises(GatewayExecutionProtocolError):
        GatewayReturnFact.from_mapping(raw)
    raw = _cancel_fact(trade).to_mapping()
    del raw["cancel_request_key"]
    with pytest.raises(GatewayExecutionProtocolError):
        GatewayReturnFact.from_mapping(raw)


def test_page_v3_exposes_only_attribution_and_accepts_old_pages(trade):
    attribution = GatewayCancelErrorAttribution("cancel-op", "attempt-id", "f" * 64)
    page = _page(_cancel_fact(trade), attribution=attribution)
    raw = page.to_mapping()
    assert raw["schema_version"] == 3
    assert raw["events"][0]["cancel_attribution"] == attribution.to_mapping()
    assert raw["events"][0]["observation"]["schema_version"] == 1
    encoded = json.dumps(raw)
    assert "native-attempt-one" not in encoded and "cancel_request_key" not in encoded
    assert "source_ref" not in encoded and "session_generation" not in encoded
    assert GatewayExecutionStreamPage.from_mapping(raw, expected_binding=page.binding) == page
    old_v2 = page.to_mapping()
    old_v2["schema_version"] = 2
    old_v2["events"] = [event.to_mapping(schema_version=2) for event in page.events]
    assert GatewayExecutionStreamPage.from_mapping(old_v2, expected_binding=page.binding) == page

    legacy = _page(trade)
    old = legacy.to_mapping()
    old["schema_version"] = 1
    old["events"] = [event.to_mapping(schema_version=1) for event in legacy.events]
    restored = GatewayExecutionStreamPage.from_mapping(old, expected_binding=legacy.binding)
    assert restored == legacy and restored.events[0].cancel_attribution is None
    assert restored.to_mapping()["schema_version"] == 3
    assert (
        GatewayExecutionStreamProgress(
            legacy.binding, legacy.consumer_ref, legacy.epoch, 1, 0
        ).to_mapping()["schema_version"]
        == 1
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"operation_id": "", "attempt_id": "attempt", "prepared_digest": "f" * 64},
        {"operation_id": "op", "attempt_id": True, "prepared_digest": "f" * 64},
        {"operation_id": "op", "attempt_id": "attempt", "prepared_digest": "F" * 64},
        {
            "operation_id": "op",
            "attempt_id": "attempt",
            "prepared_digest": "f" * 64,
            "source": "secret",
        },
    ],
)
def test_attribution_shape_and_values_are_strict(bad):
    with pytest.raises(GatewayExecutionStreamProtocolError):
        GatewayCancelErrorAttribution.from_mapping(bad)


def test_attribution_requires_cancel_error_and_strict_event_page_versions(trade):
    attribution = GatewayCancelErrorAttribution("op", "attempt", "f" * 64)
    with pytest.raises(GatewayExecutionStreamProtocolError):
        _page(trade, attribution=attribution)
    page = _page(_cancel_fact(trade), attribution=attribution)
    with pytest.raises(GatewayExecutionStreamProtocolError):
        page.events[0].to_mapping(schema_version=1)
    for schema, include_field in ((1, True), (2, False)):
        raw = page.to_mapping()
        raw["schema_version"] = schema
        if not include_field:
            del raw["events"][0]["cancel_attribution"]
        with pytest.raises(GatewayExecutionStreamProtocolError):
            GatewayExecutionStreamPage.from_mapping(raw, expected_binding=page.binding)
    raw = page.to_mapping()
    raw["schema_version"] = True
    with pytest.raises(GatewayExecutionStreamProtocolError):
        GatewayExecutionStreamPage.from_mapping(raw, expected_binding=page.binding)


def test_corrupted_attribution_and_fact_are_not_serialized(trade):
    attribution = GatewayCancelErrorAttribution("op", "attempt", "f" * 64)
    page = _page(_cancel_fact(trade), attribution=attribution)
    object.__setattr__(attribution, "prepared_digest", "bad")
    with pytest.raises(GatewayExecutionStreamProtocolError):
        page.to_mapping()
    fact = _cancel_fact(trade)
    object.__setattr__(fact, "cancel_request_key", None)
    with pytest.raises(GatewayExecutionProtocolError):
        fact.fact_digest()
