"""Offline R30 return-date and independently versioned stream contracts."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import pytest
from test_gateway_execution_cancel_attribution import _cancel_fact
from test_gateway_execution_place_attribution import place_fact
from test_gateway_execution_protocol import trade as trade
from test_gateway_execution_stream_protocol import consumer as consumer
from test_gateway_execution_stream_protocol import page as page

from bt_api_base.direct_write_protocol import DirectExecutionEventKind
from bt_api_base.gateway_execution_protocol import GatewayExecutionProtocolError, GatewayReturnFact
from bt_api_base.gateway_execution_stream_protocol import (
    GatewayExecutionObservation,
    GatewayExecutionStreamEvent,
    GatewayExecutionStreamPage,
    GatewayExecutionStreamProtocolError,
    project_gateway_execution_observation,
)


def _hash_mapping(value):
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def test_old_fact_observation_and_page_golden_bytes(trade, page):
    assert trade.fact_digest() == "1705101f6baaf40c0a07b6c9b9ad71995c92f40098b30276b2066c435d3898e3"
    assert (
        trade.trade_content_digest()
        == "6e3b6bf378cc58f30abeb4da3a9c4412b13dab6ff219b3cacdbffda56b8d280d"
    )
    assert (
        _hash_mapping(trade.to_mapping())
        == "309b5d295b8ecef5501235104e54636d6730d627704e0839209e5cd7812a0f9a"
    )
    assert (
        _hash_mapping(page.events[0].observation.to_mapping())
        == "de191e409373d0a5c2a8a6993ff6d117c0b17bde5b11fe23233617eff2f86d47"
    )
    assert (
        _hash_mapping(page.to_mapping())
        == "4605bd5b13b89641f91bc671190028f4ff5e9c2a0ab23dbd4a5a11d260e75ce9"
    )
    for fact, digest, mapping_hash in (
        (
            _cancel_fact(trade),
            "76ed1029fb1bf629e16740ef6e971730901f64297eb5ed58637ca29b2067daa9",
            "0a14537875ea8eeab293f1c63cc2b4842a20232d30168bec848e9cd12e30dbba",
        ),
        (
            place_fact(trade),
            "42b0c6ffd5902b42ba13ce2f70a7854ec93e7b782b7eea9907928d3f7d79c2c0",
            "9ed752d7e94ea33fe57601e1326dbe4d1fb28f9691f025bb10a1af8c50119c0b",
        ),
    ):
        assert fact.fact_digest() == digest
        assert _hash_mapping(fact.to_mapping()) == mapping_hash
        with pytest.raises(GatewayExecutionProtocolError):
            replace(fact, trade_date="20261107")


@pytest.mark.parametrize("date", [None, "20240229", "20261107"])
def test_trade_date_roundtrips_and_does_not_change_economic_identity(trade, page, date):
    fact = replace(trade, schema_version=4, trade_date=date)
    assert GatewayReturnFact.from_mapping(fact.to_mapping()) == fact
    assert fact.to_mapping()["trade_date"] == date
    assert fact.fact_digest() != trade.fact_digest()
    assert fact.trade_content_digest() == trade.trade_content_digest()
    observation = project_gateway_execution_observation(fact, trade_metadata_only=date is not None)
    assert observation.schema_version == 2 and observation.trade_date == date
    assert observation.trade_metadata_only is (date is not None)
    assert GatewayExecutionObservation.from_mapping(observation.to_mapping()) == observation
    event = replace(page.events[0], fact_digest=fact.fact_digest(), observation=observation)
    stream = replace(page, events=(event,))
    raw = stream.to_mapping()
    assert raw["schema_version"] == 3
    assert raw["events"][0]["observation"]["trade_date"] == date
    restored = GatewayExecutionStreamPage.from_mapping(raw, expected_binding=stream.binding)
    assert restored.to_mapping() == raw and restored == stream
    for version in (1, 2, 3):
        event_raw = event.to_mapping(schema_version=version)
        assert GatewayExecutionStreamEvent.from_mapping(event_raw, schema_version=version) == event
        versioned_page = dict(raw, schema_version=version, events=[event_raw])
        restored = GatewayExecutionStreamPage.from_mapping(
            versioned_page, expected_binding=stream.binding
        )
        assert restored.to_mapping() == raw
    with pytest.raises(FrozenInstanceError):
        observation.trade_date = "20261108"


@pytest.mark.parametrize(
    "date",
    [
        "20230229",
        "19000229",
        "20241301",
        "20240001",
        "20241131",
        "00000101",
        "2026118",
        "２０２６１１０８",
        "2026110a",
        True,
        False,
        0,
        "",
    ],
)
def test_invalid_natural_dates_rejected(trade, date):
    with pytest.raises(GatewayExecutionProtocolError):
        replace(trade, schema_version=4, trade_date=date)
    raw = replace(trade, schema_version=4).to_mapping()
    raw["trade_date"] = date
    with pytest.raises(GatewayExecutionProtocolError):
        GatewayReturnFact.from_mapping(raw)
    obs = project_gateway_execution_observation(replace(trade, schema_version=4)).to_mapping()
    obs["trade_date"] = date
    with pytest.raises(GatewayExecutionStreamProtocolError):
        GatewayExecutionObservation.from_mapping(obs)


def test_exact_versioned_keys_and_strict_flag(trade):
    old_fact = trade.to_mapping()
    old_obs = project_gateway_execution_observation(trade).to_mapping()
    new_fact = replace(trade, schema_version=4, trade_date="20261107").to_mapping()
    new_obs = project_gateway_execution_observation(
        GatewayReturnFact.from_mapping(new_fact)
    ).to_mapping()
    for raw, decoder, error in (
        (old_fact, GatewayReturnFact.from_mapping, GatewayExecutionProtocolError),
        (new_fact, GatewayReturnFact.from_mapping, GatewayExecutionProtocolError),
        (old_obs, GatewayExecutionObservation.from_mapping, GatewayExecutionStreamProtocolError),
        (new_obs, GatewayExecutionObservation.from_mapping, GatewayExecutionStreamProtocolError),
    ):
        for key in raw:
            bad = dict(raw)
            del bad[key]
            with pytest.raises(error):
                decoder(bad)
        with pytest.raises(error):
            decoder(dict(raw, extra=None))
    for flag in (0, 1, None, "false"):
        with pytest.raises(GatewayExecutionStreamProtocolError):
            GatewayExecutionObservation.from_mapping(dict(new_obs, trade_metadata_only=flag))
        with pytest.raises(GatewayExecutionStreamProtocolError):
            project_gateway_execution_observation(trade, trade_metadata_only=flag)
    with pytest.raises(GatewayExecutionProtocolError):
        replace(trade, trade_date="20261107")
    with pytest.raises(GatewayExecutionStreamProtocolError):
        GatewayExecutionObservation.from_mapping(dict(old_obs, trade_date=None))


def test_projection_only_accepts_metadata_for_known_date(trade):
    # Metadata-only supplements need a v4 fact carrying a natural date or a
    # trade time (date and time may come from distinct trusted facts).
    for fact in (trade, replace(trade, schema_version=4, trade_time=None)):
        with pytest.raises(GatewayExecutionStreamProtocolError):
            project_gateway_execution_observation(fact, trade_metadata_only=True)
    time_only = project_gateway_execution_observation(
        replace(trade, schema_version=4), trade_metadata_only=True)
    assert time_only.trade_date is None and time_only.trade_time == trade.trade_time
    dated = replace(trade, schema_version=4, trade_date="20261107")
    with pytest.raises(GatewayExecutionStreamProtocolError):
        GatewayExecutionObservation.from_mapping(
            dict(
                project_gateway_execution_observation(dated).to_mapping(),
                trade_date=None,
                trade_time=None,
                trade_metadata_only=True,
            )
        )
    order = replace(
        trade,
        kind=DirectExecutionEventKind.ORDER,
        trade_key=None,
        trade_quantity=None,
        trade_price=None,
        trade_time=None,
    )
    with pytest.raises(GatewayExecutionProtocolError):
        replace(order, schema_version=4)
    with pytest.raises(GatewayExecutionStreamProtocolError):
        project_gateway_execution_observation(order, trade_metadata_only=True)
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(project_gateway_execution_observation(order), schema_version=2)


@pytest.mark.parametrize(
    "fact_field,observation_field",
    [
        ("trade_key", "trade_key_digest"),
        ("trade_quantity", "trade_quantity"),
        ("trade_price", "trade_price"),
        ("side", "side"),
        ("venue_key", "venue_key_digest"),
    ],
)
def test_metadata_requires_complete_correlation_fields(trade, fact_field, observation_field):
    dated = replace(trade, schema_version=4, trade_date="20261107")
    full = project_gateway_execution_observation(dated, trade_metadata_only=True)
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(full, **{observation_field: None})
    with pytest.raises(GatewayExecutionStreamProtocolError):
        project_gateway_execution_observation(
            replace(dated, **{fact_field: None}), trade_metadata_only=True
        )
    raw = full.to_mapping()
    raw[observation_field] = None
    with pytest.raises(GatewayExecutionStreamProtocolError):
        GatewayExecutionObservation.from_mapping(raw)

    # Incomplete ordinary trade observations retain their existing contract.
    incomplete = project_gateway_execution_observation(replace(dated, **{fact_field: None}))
    assert getattr(incomplete, observation_field) is None
    assert GatewayExecutionObservation.from_mapping(incomplete.to_mapping()) == incomplete


def test_complete_metadata_event_roundtrip(trade, page):
    fact = replace(trade, schema_version=4, trade_date="20261107")
    observation = project_gateway_execution_observation(fact, trade_metadata_only=True)
    event = replace(page.events[0], fact_digest=fact.fact_digest(), observation=observation)
    assert GatewayExecutionStreamEvent.from_mapping(event.to_mapping()) == event
    stream = replace(page, events=(event,))
    assert GatewayExecutionStreamPage.from_mapping(
        stream.to_mapping(), expected_binding=stream.binding
    ) == stream
