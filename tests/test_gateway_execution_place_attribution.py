"""Place-error facts and public v3 events, without native source disclosure."""

import copy
import json
from dataclasses import replace

import pytest
from test_gateway_execution_protocol import trade as trade

from bt_api_base.direct_write_protocol import DirectExecutionEventKind, DirectOrderStatus
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_protocol import GatewayExecutionProtocolError, GatewayReturnFact
from bt_api_base.gateway_execution_stream_protocol import (
    GatewayCancelErrorAttribution,
    GatewayExecutionStreamEvent,
    GatewayExecutionStreamPage,
    GatewayExecutionStreamProtocolError,
    GatewayPlaceErrorAttribution,
    gateway_execution_consumer_ref,
    project_gateway_execution_observation,
)


def place_fact(trade, key="private-place-key"):
    return replace(
        trade,
        kind=DirectExecutionEventKind.ORDER_ERROR,
        trade_key=None,
        trade_quantity=None,
        trade_price=None,
        trade_time=None,
        error_code="ORDER_REJECTED",
        schema_version=3,
        place_request_key=key,
    )


def page(fact, attribution=None):
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
        "principal",
        fact.fact_digest(),
        project_gateway_execution_observation(fact),
        place_attribution=attribution,
    )
    return GatewayExecutionStreamPage(binding, consumer, "e" * 64, 1, 0, False, (event,))


def test_fact_v3_digests_and_strict_mapping(trade):
    first, second = place_fact(trade), place_fact(trade, "another-key")
    assert first.fact_digest() != second.fact_digest()
    assert (
        first.fact_digest()
        == replace(first, source_ref="different", session_generation=77).fact_digest()
    )
    raw = first.to_mapping()
    assert raw["schema_version"] == 3 and raw["place_request_key"] == "private-place-key"
    assert "cancel_request_key" not in raw
    assert GatewayReturnFact.from_mapping(raw) == first
    for key, value in (
        ("schema_version", True),
        ("schema_version", 4),
        ("place_request_key", True),
        ("place_request_key", ""),
        ("cancel_request_key", "unexpected"),
        ("extra", 1),
    ):
        bad = copy.deepcopy(raw)
        bad[key] = value
        with pytest.raises(GatewayExecutionProtocolError):
            GatewayReturnFact.from_mapping(bad)
    del raw["place_request_key"]
    with pytest.raises(GatewayExecutionProtocolError):
        GatewayReturnFact.from_mapping(raw)
    assert trade.fact_digest() == "1705101f6baaf40c0a07b6c9b9ad71995c92f40098b30276b2066c435d3898e3"
    assert "place_request_key" not in trade.to_mapping()


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": DirectExecutionEventKind.CANCEL_ERROR},
        {"status": DirectOrderStatus.ACCEPTED},
        {"place_request_key": None},
        {"place_request_key": True},
        {"cancel_request_key": "other"},
        {"schema_version": 2},
        {"schema_version": 1},
    ],
)
def test_fact_rejects_invalid_place_combinations(trade, changes):
    with pytest.raises(GatewayExecutionProtocolError):
        replace(place_fact(trade), **changes)


def test_page_v3_attribution_and_old_event_versions(trade):
    attribution = GatewayPlaceErrorAttribution("f" * 64)
    current = page(place_fact(trade), attribution)
    mapping = current.to_mapping()
    assert mapping["schema_version"] == 3
    assert mapping["events"][0]["place_attribution"] == {"prepared_digest": "f" * 64}
    assert mapping["events"][0]["observation"]["schema_version"] == 1
    text = json.dumps(mapping)
    assert "private-place-key" not in text and "place_request_key" not in text
    assert "source_ref" not in text and "session_generation" not in text
    assert (
        GatewayExecutionStreamPage.from_mapping(mapping, expected_binding=current.binding)
        == current
    )
    for version in (1, 2):
        with pytest.raises(GatewayExecutionStreamProtocolError):
            current.events[0].to_mapping(schema_version=version)
        old_page = page(trade)
        old_mapping = old_page.to_mapping()
        old_mapping["schema_version"] = version
        old_mapping["events"] = [
            event.to_mapping(schema_version=version) for event in old_page.events
        ]
        assert (
            GatewayExecutionStreamPage.from_mapping(old_mapping, expected_binding=old_page.binding)
            == old_page
        )
        old_mapping["events"][0]["place_attribution"] = None
        with pytest.raises(GatewayExecutionStreamProtocolError):
            GatewayExecutionStreamPage.from_mapping(old_mapping, expected_binding=old_page.binding)


def test_event_attribution_must_match_kind_and_not_coexist(trade):
    attribution = GatewayPlaceErrorAttribution("f" * 64)
    with pytest.raises(GatewayExecutionStreamProtocolError):
        page(trade, attribution)
    event = page(place_fact(trade), attribution).events[0]
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(event, cancel_attribution=GatewayCancelErrorAttribution("op", "attempt", "e" * 64))
    rejected = replace(event.observation, status=DirectOrderStatus.REJECTED)
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(event, observation=rejected)
    raw = page(place_fact(trade), attribution).to_mapping()
    raw["events"][0]["observation"]["status"] = DirectOrderStatus.REJECTED.value
    with pytest.raises(GatewayExecutionStreamProtocolError):
        GatewayExecutionStreamPage.from_mapping(
            raw, expected_binding=page(place_fact(trade)).binding
        )
    for raw in (
        {"prepared_digest": "F" * 64},
        {"prepared_digest": True},
        {"prepared_digest": "f" * 64, "source": "hidden"},
        {},
    ):
        with pytest.raises(GatewayExecutionStreamProtocolError):
            GatewayPlaceErrorAttribution.from_mapping(raw)
    object.__setattr__(attribution, "prepared_digest", "bad")
    with pytest.raises(GatewayExecutionStreamProtocolError):
        event.to_mapping()
