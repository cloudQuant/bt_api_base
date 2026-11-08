"""Offline strict public Gateway execution stream contracts."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import pytest
from test_gateway_execution_protocol import trade as trade

from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_stream_protocol import (
    GatewayExecutionObservation,
    GatewayExecutionStreamEvent,
    GatewayExecutionStreamPage,
    GatewayExecutionStreamProgress,
    GatewayExecutionStreamProtocolError,
    gateway_execution_consumer_ref,
    project_gateway_execution_observation,
)


@pytest.fixture
def consumer():
    return gateway_execution_consumer_ref(
        principal_ref="principal",
        actor_ref="strategy",
        execution_domain_ref="domain",
        account_scope="account-a",
        strategy_scope="strategy",
    )


@pytest.fixture
def page(trade, consumer):
    obs = project_gateway_execution_observation(trade)
    event = GatewayExecutionStreamEvent(
        1, "request", "reservation", "a" * 64, "original-principal", trade.fact_digest(), obs
    )
    return GatewayExecutionStreamPage(
        GatewayCommandBinding("journal", "account-a", "strategy", "principal"),
        consumer,
        "e" * 64,
        3,
        0,
        False,
        (event, replace(event, sequence=3)),
    )


def test_consumer_digest_is_fixed_and_stable(consumer):
    fields = [
        1,
        "strategy_client",
        "principal",
        "strategy",
        None,
        "domain",
        "account-a",
        "strategy",
    ]
    expected = hashlib.sha256(
        json.dumps(fields, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    assert consumer == "gexec:" + expected
    assert (
        gateway_execution_consumer_ref(
            principal_ref="principal",
            actor_ref="strategy",
            execution_domain_ref="domain",
            account_scope="account-a",
            strategy_scope="strategy",
        )
        == consumer
    )
    assert (
        gateway_execution_consumer_ref(
            principal_ref="principal2",
            actor_ref="strategy",
            execution_domain_ref="domain",
            account_scope="account-a",
            strategy_scope="strategy",
        )
        != consumer
    )


@pytest.mark.parametrize("value", ["", " ", "\ud800", "界" * 86, 1, None])
def test_consumer_rejects_bad_refs(value):
    with pytest.raises(GatewayExecutionStreamProtocolError):
        gateway_execution_consumer_ref(
            principal_ref=value,
            actor_ref="strategy",
            execution_domain_ref="domain",
            account_scope="account",
            strategy_scope="strategy",
        )


def test_projection_redacts_raw_keys_and_roundtrips(trade):
    obs = project_gateway_execution_observation(trade)
    raw = obs.to_mapping()
    assert set(raw).isdisjoint(
        {
            "identity_keys",
            "binding_keys",
            "venue_key",
            "trade_key",
            "source_ref",
            "session_generation",
        }
    )
    assert "identity" not in raw
    encoded_identity = json.dumps(
        trade.identity.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    assert raw["native_identity_digest"] == hashlib.sha256(encoded_identity).hexdigest()
    assert obs.identity_key_digests == tuple(
        sorted(hashlib.sha256(k.encode()).hexdigest() for k in trade.identity_keys)
    )
    assert obs.venue_key_digest == hashlib.sha256(b"venue").hexdigest()
    expected = hashlib.sha256(
        json.dumps(list(trade.trade_key), ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    assert obs.trade_key_digest == expected
    assert GatewayExecutionObservation.from_mapping(raw) == obs
    raw["instrument"]["instrument_id"] = "other"
    assert obs.instrument.instrument_id == "SA701"
    with pytest.raises(FrozenInstanceError):
        obs.route = "different"


def test_page_progress_roundtrip_sparse_sequences_and_historical_offer(page):
    raw = page.to_mapping()
    decoded = GatewayExecutionStreamPage.from_mapping(
        raw, expected_binding=page.binding, expected_consumer_ref=page.consumer_ref
    )
    assert decoded == page and [x.sequence for x in decoded.events] == [1, 3]
    historical = replace(page, offered_sequence=7, acknowledged_sequence=6)
    assert (
        GatewayExecutionStreamPage.from_mapping(
            historical.to_mapping(), expected_binding=page.binding
        )
        == historical
    )
    progress = GatewayExecutionStreamProgress(page.binding, page.consumer_ref, "e" * 64, 7, 6)
    assert (
        GatewayExecutionStreamProgress.from_mapping(
            progress.to_mapping(),
            expected_binding=page.binding,
            expected_consumer_ref=page.consumer_ref,
        )
        == progress
    )
    assert page.events[0].command_principal != page.binding.principal


@pytest.mark.parametrize(
    "field,value",
    [
        ("sequence", True),
        ("sequence", 0),
        ("sequence", 2**63),
        ("request_key", ""),
        ("reservation_id", "界" * 86),
        ("command_digest", "A" * 64),
        ("fact_digest", "a" * 63),
        ("command_principal", "\ud800"),
    ],
)
def test_event_invalid_fields(page, field, value):
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(page.events[0], **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("offered_sequence", True),
        ("offered_sequence", -1),
        ("offered_sequence", 2**63),
        ("acknowledged_sequence", True),
        ("acknowledged_sequence", 4),
        ("epoch", ""),
        ("epoch", "界" * 86),
        ("has_more", 1),
        ("consumer_ref", "gexec:bad"),
    ],
)
def test_page_invalid_progress(page, field, value):
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(page, **{field: value})


def test_page_rejects_reordered_duplicates_other_account_and_overflow(page):
    first, last = page.events
    for events in (
        (last, first),
        (first, first),
        (replace(last, sequence=4),),
        tuple(replace(first, sequence=i) for i in range(1, 258)),
    ):
        with pytest.raises(GatewayExecutionStreamProtocolError):
            replace(page, events=events)
    other = replace(first, observation=replace(first.observation, account_scope="other"))
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(page, events=(other,))


@pytest.mark.parametrize(
    "field,value",
    [
        ("identity_key_digests", ("f" * 64, "0" * 64)),
        ("identity_key_digests", ("a" * 64, "a" * 64)),
        ("binding_key_digests", ("1" * 64,)),
        ("venue_key_digest", "1" * 64),
        ("trade_key_digest", "A" * 64),
        ("trading_day", "20260229"),
        ("trade_quantity", "NaN"),
        ("trade_quantity", 1.0),
        ("trade_quantity", "0"),
        ("filled_quantity", "-1"),
        ("error_code", "raw error text"),
    ],
)
def test_observation_reuses_fact_validation(trade, field, value):
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(project_gateway_execution_observation(trade), **{field: value})


@pytest.mark.parametrize(
    "extra",
    [
        "identity",
        "identity_keys",
        "binding_keys",
        "venue_key",
        "trade_key",
        "source_ref",
        "session_generation",
    ],
)
def test_raw_fields_are_rejected_on_input(trade, extra):
    raw = project_gateway_execution_observation(trade).to_mapping()
    raw[extra] = "do-not-expose"
    with pytest.raises(GatewayExecutionStreamProtocolError):
        GatewayExecutionObservation.from_mapping(raw)


def test_strict_mapping_unknown_fields_and_bindings(page):
    for owner in (
        page,
        GatewayExecutionStreamProgress(page.binding, page.consumer_ref, page.epoch, 3, 0),
    ):
        cls = type(owner)
        for field in owner.to_mapping():
            raw = owner.to_mapping()
            del raw[field]
            with pytest.raises(GatewayExecutionStreamProtocolError):
                cls.from_mapping(raw, expected_binding=page.binding)
        raw = owner.to_mapping()
        raw["extra"] = 1
        with pytest.raises(GatewayExecutionStreamProtocolError):
            cls.from_mapping(raw, expected_binding=page.binding)
        raw = owner.to_mapping()
        raw["schema_version"] = True
        with pytest.raises(GatewayExecutionStreamProtocolError):
            cls.from_mapping(raw, expected_binding=page.binding)
        with pytest.raises(GatewayExecutionStreamProtocolError, match="BINDING_MISMATCH"):
            cls.from_mapping(
                owner.to_mapping(), expected_binding=replace(page.binding, principal="other")
            )
        with pytest.raises(GatewayExecutionStreamProtocolError, match="BINDING_MISMATCH"):
            cls.from_mapping(
                owner.to_mapping(),
                expected_binding=page.binding,
                expected_consumer_ref="gexec:" + "1" * 64,
            )
    raw = page.to_mapping()
    raw["events"][0]["observation"]["instrument"]["extra"] = 1
    with pytest.raises(GatewayExecutionStreamProtocolError):
        GatewayExecutionStreamPage.from_mapping(raw, expected_binding=page.binding)


def test_trade_key_digest_uses_canonical_json_array(trade):
    first = replace(trade, trade_key=("上期", "成交-1"))
    second = replace(trade, trade_key=("上", "期成交-1"))
    digest = project_gateway_execution_observation(first).trade_key_digest
    encoded = json.dumps(["上期", "成交-1"], ensure_ascii=True, separators=(",", ":")).encode(
        "ascii"
    )
    assert digest == hashlib.sha256(encoded).hexdigest()
    assert digest != project_gateway_execution_observation(second).trade_key_digest


def test_native_identity_digest_hides_all_nested_provider_fields(trade):
    from bt_api_base.direct_write_protocol import NativeOrderIdentity

    private = NativeOrderIdentity(
        trade.route,
        "client-private",
        {
            "trading_day": trade.trading_day,
            "source_ref": "source-private",
            "identity_keys": "identity-private",
            "binding_keys": "binding-private",
            "venue_key": "venue-private",
            "trade_key": "trade-private",
            "raw_provider_payload": "payload-private",
        },
        123,
    )
    fact = replace(trade, identity=private)
    raw = project_gateway_execution_observation(fact).to_mapping()
    text = json.dumps(raw, ensure_ascii=True)
    for value in (
        "client-private",
        "source-private",
        "identity-private",
        "binding-private",
        "venue-private",
        "trade-private",
        "payload-private",
        "public_digest",
    ):
        assert value not in text
    encoded = json.dumps(
        private.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    assert raw["native_identity_digest"] == hashlib.sha256(encoded).hexdigest()
    assert GatewayExecutionObservation.from_mapping(raw).to_mapping() == raw


def test_native_identity_digest_required_for_strong_keys(trade):
    observation = project_gateway_execution_observation(trade)
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(observation, native_identity_digest=None)
    raw = observation.to_mapping()
    raw["native_identity_digest"] = None
    with pytest.raises(GatewayExecutionStreamProtocolError):
        GatewayExecutionObservation.from_mapping(raw)
    for value in (True, "A" * 64, "f" * 63):
        raw = observation.to_mapping()
        raw["native_identity_digest"] = value
        with pytest.raises(GatewayExecutionStreamProtocolError):
            GatewayExecutionObservation.from_mapping(raw)


def test_absent_native_identity_can_project_without_strong_keys(trade):
    fact = replace(trade, identity=None, identity_keys=(), binding_keys=(), venue_key=None)
    obs = project_gateway_execution_observation(fact)
    assert obs.native_identity_digest is None
    assert GatewayExecutionObservation.from_mapping(obs.to_mapping()) == obs


@pytest.mark.parametrize("epoch", ["f" * 63, "A" * 64, "g" * 64, True])
@pytest.mark.parametrize("dto_type", [GatewayExecutionStreamPage, GatewayExecutionStreamProgress])
def test_epoch_must_be_lowercase_sha256_in_construction_and_mapping(page, epoch, dto_type):
    original = (
        page
        if dto_type is GatewayExecutionStreamPage
        else GatewayExecutionStreamProgress(
            page.binding,
            page.consumer_ref,
            page.epoch,
            page.offered_sequence,
            page.acknowledged_sequence,
        )
    )
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(original, epoch=epoch)
    raw = original.to_mapping()
    raw["epoch"] = epoch
    with pytest.raises(GatewayExecutionStreamProtocolError):
        dto_type.from_mapping(raw, expected_binding=page.binding)


def test_page_rejects_empty_has_more_for_constructor_and_mapping(page):
    with pytest.raises(GatewayExecutionStreamProtocolError):
        replace(page, events=(), has_more=True)
    raw = page.to_mapping()
    raw["events"] = []
    raw["has_more"] = True
    with pytest.raises(GatewayExecutionStreamProtocolError):
        GatewayExecutionStreamPage.from_mapping(raw, expected_binding=page.binding)
    assert replace(page, events=(), has_more=False).events == ()
    assert replace(page, events=page.events[:1], has_more=True).has_more
