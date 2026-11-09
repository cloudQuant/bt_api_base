"""Gateway-asserted trade alias proof remains separate from provider facts."""
from dataclasses import replace

import pytest
from test_gateway_execution_protocol import trade as trade
from test_gateway_execution_stream_protocol import consumer as consumer
from test_gateway_execution_stream_protocol import page as page

from bt_api_base.direct_write_protocol import DirectExecutionEventKind
from bt_api_base.gateway_execution_stream_protocol import (
    GatewayExecutionObservation,
    GatewayExecutionStreamPage,
    GatewayExecutionStreamProtocolError,
    GatewayTradeAttribution,
    project_gateway_execution_observation,
)


def _proof(trade, event, **changes):
    observation = project_gateway_execution_observation(trade)
    proof = GatewayTradeAttribution(
        account_scope=trade.account_scope,
        strategy_scope="strategy",
        fact_digest=trade.fact_digest(),
        reservation_id=event.reservation_id,
        command_digest=event.command_digest,
        anchor_fact_digest="d" * 64,
        anchor_sequence=1,
        venue_key_digest=observation.venue_key_digest,
        original_binding_key_digests=("c" * 64,),
    )
    return replace(proof, **changes)


def test_trade_proof_roundtrip_does_not_change_fact_or_old_versions(trade, page):
    fact_mapping, fact_digest = trade.to_mapping(), trade.fact_digest()
    old_observation = project_gateway_execution_observation(trade).to_mapping()
    event = replace(page.events[0], sequence=3)
    proof = _proof(trade, event)
    obs = project_gateway_execution_observation(trade, trade_attribution=proof)
    assert obs.schema_version == 3
    assert obs.binding_key_digests == project_gateway_execution_observation(trade).binding_key_digests
    assert GatewayExecutionObservation.from_mapping(obs.to_mapping()) == obs
    event = replace(event, observation=obs)
    stream = replace(page, events=(event,))
    encoded = stream.to_mapping()
    assert encoded["schema_version"] == 3
    assert GatewayExecutionStreamPage.from_mapping(encoded, expected_binding=stream.binding) == stream
    assert trade.to_mapping() == fact_mapping and trade.fact_digest() == fact_digest
    assert project_gateway_execution_observation(trade).to_mapping() == old_observation
    for version in (1, 2):
        with pytest.raises(GatewayExecutionStreamProtocolError):
            event.to_mapping(schema_version=version)


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("account_scope", ""),
    ("strategy_scope", ""), ("fact_digest", "bad"), ("reservation_id", ""),
    ("command_digest", "bad"), ("anchor_fact_digest", "bad"),
    ("anchor_sequence", 0), ("anchor_sequence", True), ("venue_key_digest", "bad"),
    ("original_binding_key_digests", ()), ("original_binding_key_digests", ("f" * 64, "f" * 64)),
])
def test_invalid_proof_fields_rejected(trade, page, field, value):
    with pytest.raises(GatewayExecutionStreamProtocolError):
        _proof(trade, page.events[0], **{field: value})


def test_reject_cross_event_scope_order_and_false_anchor(trade, page):
    event = replace(page.events[0], sequence=3)
    proof = _proof(trade, event)
    obs = project_gateway_execution_observation(trade, trade_attribution=proof)
    valid = replace(event, observation=obs)
    for changed in (
        {"fact_digest": "e" * 64}, {"reservation_id": "other"},
        {"command_digest": "e" * 64}, {"sequence": 1},
    ):
        with pytest.raises(GatewayExecutionStreamProtocolError):
            replace(valid, **changed)
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(page, events=(replace(valid, observation=replace(obs, trade_attribution=replace(proof, strategy_scope="other"))),))
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(proof, anchor_fact_digest=proof.fact_digest)
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(proof, original_binding_key_digests=(proof.venue_key_digest,))
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(obs, account_scope="wrong")
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(obs, trade_attribution=None)
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(obs, schema_version=2)
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(obs, kind=DirectExecutionEventKind.ORDER)
