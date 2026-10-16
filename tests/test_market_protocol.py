"""Focused tests for the neutral market subscription-key contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from bt_api_base.market_protocol import (
    MARKET_EVENT_OPERATION,
    MARKET_EVENT_SCHEMA,
    MARKET_EVENT_SCHEMA_VERSION,
    MarketInstrumentKey,
    MarketProviderEvent,
    MarketSourceDescriptor,
    MarketSubscriptionKey,
)
from bt_api_base.service_protocol import (
    WireEnvelope,
    WireHeader,
    WireIdentity,
    WireMessageKind,
    WireRole,
    WireScope,
    decode_envelope,
    encode_envelope,
)


def _instrument(**updates: str) -> MarketInstrumentKey:
    values = {
        "provider": "alpha",
        "venue": "alpha-futures",
        "environment": "paper",
        "product_type": "linear-perpetual",
        "instrument_id": "BTC-USD-PERP",
        "native_symbol": "BTCUSD_PERP",
    }
    values.update(updates)
    return MarketInstrumentKey(**values)


def _key(**updates: object) -> MarketSubscriptionKey:
    values: dict[str, object] = {
        "source_ref": "market-source-a",
        "entitlement_ref": "entitlement-public-a",
        "instrument": _instrument(),
        "channel": "orderbook",
        "depth": 20,
        "timeframe": None,
    }
    values.update(updates)
    return MarketSubscriptionKey(**values)  # type: ignore[arg-type]


def _source_descriptor(**updates: object) -> MarketSourceDescriptor:
    key = _key()
    values: dict[str, object] = {
        "key": key,
        "stream_id": key.stream_id,
        "epoch": "epoch-1",
        "provider": key.instrument.provider,
        "source": "ctp.native.md",
        "connection_generation": 1,
        "clock_domain_id": "ctp-md-process:123:monotonic:session-a",
        "clock_source_session_id": "session-a",
        "clock_source": "time.monotonic_ns",
    }
    values.update(updates)
    return MarketSourceDescriptor(**values)  # type: ignore[arg-type]


def test_keys_are_frozen_hashable_and_round_trip_through_json() -> None:
    instrument = _instrument()
    key = _key(instrument=instrument)

    assert hash(instrument) == hash(_instrument())
    assert hash(key) == hash(_key())
    assert MarketInstrumentKey.from_dict(json.loads(json.dumps(instrument.to_dict()))) == instrument
    restored = MarketSubscriptionKey.from_dict(json.loads(json.dumps(key.to_dict())))
    assert restored == key
    assert restored.stream_id == key.stream_id

    with pytest.raises(FrozenInstanceError):
        instrument.provider = "other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        key.channel = "ticker"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        key.instrument = _instrument()  # type: ignore[misc]

    exported = key.to_dict()
    exported["instrument"]["native_symbol"] = "changed"  # type: ignore[index]
    assert key.instrument.native_symbol == "BTCUSD_PERP"


def test_source_descriptor_is_frozen_and_round_trips_exact_complete_key() -> None:
    descriptor = _source_descriptor()
    restored = MarketSourceDescriptor.from_dict(json.loads(json.dumps(descriptor.to_dict())))

    assert restored == descriptor
    assert restored.key == _key()
    assert restored.stream_id == descriptor.key.stream_id
    assert set(restored.to_dict()) == {
        "key",
        "stream_id",
        "epoch",
        "provider",
        "source",
        "connection_generation",
        "clock_domain_id",
        "clock_source_session_id",
        "clock_source",
    }
    with pytest.raises(FrozenInstanceError):
        descriptor.epoch = "epoch-2"  # type: ignore[misc]
    payload = descriptor.to_dict()
    payload["key"]["instrument"]["native_symbol"] = "changed"  # type: ignore[index]
    assert descriptor.key.instrument.native_symbol == "BTCUSD_PERP"


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("stream_id", "market-other", ValueError),
        ("epoch", " ", ValueError),
        ("provider", "other", ValueError),
        ("source", "", ValueError),
        ("connection_generation", True, TypeError),
        ("connection_generation", 0, ValueError),
        ("connection_generation", "1", TypeError),
        ("clock_domain_id", "", ValueError),
        ("clock_source_session_id", "", ValueError),
        ("clock_source", "", ValueError),
    ],
)
def test_source_descriptor_rejects_unbound_or_untyped_fields(
    field: str, value: object, error: type[Exception]
) -> None:
    with pytest.raises(error):
        _source_descriptor(**{field: value})


def test_source_descriptor_from_dict_rejects_nonexact_fields_and_nested_key() -> None:
    descriptor = _source_descriptor().to_dict()
    with pytest.raises(ValueError):
        MarketSourceDescriptor.from_dict({**descriptor, "quality": "verified"})
    with pytest.raises(ValueError):
        MarketSourceDescriptor.from_dict(
            {key: value for key, value in descriptor.items() if key != "source"}
        )
    wrong_nested_key = dict(descriptor)
    wrong_nested_key["key"] = {**descriptor["key"], "extra": "not-accepted"}  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        MarketSourceDescriptor.from_dict(wrong_nested_key)


def test_provider_event_copies_payload_and_carries_internal_generation() -> None:
    projection = {"price": 65000.25}
    event = MarketProviderEvent(
        generation="generation-1",
        observed_at_utc="2026-10-16T00:00:00Z",
        data=projection,
    )

    projection["price"] = 0.0
    assert event.data["price"] == 65000.25
    assert event.generation == "generation-1"
    with pytest.raises(TypeError):
        event.data["price"] = 0.0  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        event.generation = "generation-2"  # type: ignore[misc]

    with pytest.raises(TypeError, match="string-keyed mapping"):
        MarketProviderEvent(
            generation="generation-1",
            observed_at_utc="2026-10-16T00:00:00Z",
            data={1: "invalid"},  # type: ignore[dict-item]
        )


def test_stream_identity_includes_every_sharing_dimension() -> None:
    base = _key()
    variants = [
        replace(base, source_ref="market-source-b"),
        replace(base, entitlement_ref="entitlement-public-b"),
        replace(base, instrument=_instrument(provider="beta")),
        replace(base, instrument=_instrument(venue="beta-futures")),
        replace(base, instrument=_instrument(environment="live")),
        replace(base, instrument=_instrument(product_type="inverse-perpetual")),
        replace(base, instrument=_instrument(instrument_id="BTC-USD-202612")),
        replace(base, instrument=_instrument(native_symbol="BTCUSD_DEC26")),
        replace(base, channel="ticker"),
        replace(base, depth=10),
        replace(base, timeframe="1m"),
    ]

    stream_ids = {base.stream_id, *(variant.stream_id for variant in variants)}
    assert len(stream_ids) == len(variants) + 1
    assert base.stream_id.startswith("market-")
    assert len(base.stream_id) == len("market-") + 64
    assert MarketSubscriptionKey.from_dict(
        dict(reversed(list(base.to_dict().items())))
    ).stream_id == (base.stream_id)


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", ""),
        ("venue", " venue"),
        ("environment", "paper\nprod"),
        ("product_type", "x" * 257),
        ("instrument_id", "bad\ud800id"),
        ("native_symbol", "symbol\x7f"),
    ],
)
def test_instrument_text_is_strict_bounded_printable_utf8(field: str, value: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        _instrument(**{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_ref", ""),
        ("entitlement_ref", " "),
        ("channel", "bad\x85channel"),
        ("timeframe", "x" * 257),
    ],
)
def test_subscription_text_is_strict_bounded_printable_utf8(field: str, value: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        _key(**{field: value})


@pytest.mark.parametrize("depth", [True, False, 0, -1, 1_000_001, "20", 20.0])
def test_depth_rejects_bool_wrong_types_and_out_of_range_values(depth: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _key(depth=depth)


def test_from_dict_rejects_missing_unknown_and_wrong_nested_fields() -> None:
    instrument = _instrument().to_dict()
    key = _key().to_dict()

    missing_instrument = dict(instrument)
    del missing_instrument["venue"]
    with pytest.raises(ValueError):
        MarketInstrumentKey.from_dict(missing_instrument)

    unknown_instrument = {**instrument, "margin_asset": "USD"}
    with pytest.raises(ValueError):
        MarketInstrumentKey.from_dict(unknown_instrument)

    missing_subscription = dict(key)
    del missing_subscription["depth"]
    with pytest.raises(ValueError):
        MarketSubscriptionKey.from_dict(missing_subscription)

    wrong_nested = {**key, "instrument": {**instrument, "contract_size": 1}}
    with pytest.raises(ValueError):
        MarketSubscriptionKey.from_dict(wrong_nested)

    with pytest.raises(TypeError):
        MarketInstrumentKey.from_dict({1: "invalid"})  # type: ignore[dict-item]


def test_depth_none_and_spot_keys_are_valid_without_derivative_deduplication() -> None:
    spot = _instrument(product_type="spot", instrument_id="BTC-USD", native_symbol="BTCUSD")
    key = _key(instrument=spot, depth=None)
    assert MarketSubscriptionKey.from_dict(key.to_dict()) == key
    assert key.to_dict()["depth"] is None
    assert key.stream_id != _key().stream_id


def test_market_event_uses_the_existing_wire_envelope() -> None:
    key = _key()
    envelope = WireEnvelope(
        header=WireHeader(
            protocol_version=2,
            kind=WireMessageKind.EVENT,
            message_id="event-1",
            correlation_id=None,
            identity=WireIdentity(
                role=WireRole.SERVICE,
                principal_ref="market-hub",
                actor_ref="provider-alpha",
            ),
            scope=WireScope(execution_domain_ref="public:market"),
            operation=MARKET_EVENT_OPERATION,
            schema_id=MARKET_EVENT_SCHEMA,
            schema_version=MARKET_EVENT_SCHEMA_VERSION,
            sent_at_utc="2026-10-14T00:00:00Z",
            stream_id=key.stream_id,
            stream_epoch="epoch-1",
            sequence=1,
        ),
        payload={"key": key.to_dict(), "data": {"price": 65000.25}},
    )

    restored = decode_envelope(encode_envelope(envelope))
    assert restored.header.schema_id == MARKET_EVENT_SCHEMA
    assert restored.header.operation == MARKET_EVENT_OPERATION
    assert restored.header.stream_id == key.stream_id
    assert restored.payload["key"]["instrument"]["product_type"] == "linear-perpetual"  # type: ignore[index]


def test_import_does_not_load_provider_packages_or_native_vendor_modules() -> None:
    source_root = Path(__file__).parents[1] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(source_root), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    script = """
import importlib
import json
import sys

before = set(sys.modules)
market = importlib.import_module('bt_api_base.market_protocol')
added = set(sys.modules) - before
vendor = sorted(
    name for name in added
    if name.startswith('bt_api_') and not name.startswith('bt_api_base')
)
key = market.MarketSubscriptionKey(
    source_ref='market-source-a',
    entitlement_ref='entitlement-public-a',
    instrument=market.MarketInstrumentKey(
        provider='alpha', venue='alpha-futures', environment='paper',
        product_type='linear-perpetual', instrument_id='BTC-USD-PERP',
        native_symbol='BTCUSD_PERP',
    ),
    channel='orderbook', depth=20, timeframe=None,
)
print(json.dumps({'vendor_modules': vendor, 'stream_id': key.stream_id}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    output = json.loads(result.stdout)
    assert output["vendor_modules"] == []
    assert output["stream_id"] == _key().stream_id
