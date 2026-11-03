"""MessagePack wire contract v1 (iteration 60, step 60.08)."""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal

import pytest

msgpack = pytest.importorskip("msgpack")

from bt_api_base.market_history_protocol import MarketBar
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.market_tick_protocol import (
    MARKET_TICK_SCHEMA_VERSION,
    MarketClockQuality,
    MarketFreshnessStatus,
    MarketTickContractError,
    MarketTickPayload,
)
from bt_api_base.wire_codec_v1 import (
    MAX_MESSAGE_BYTES,
    SCHEMA_ID,
    SUPPORTED_MINOR,
    StreamPosition,
    WireCodecError,
    canonical_decimal,
    command_fingerprint,
    decode_message,
    encode_message,
    parse_decimal,
    schema_digest,
)

INSTRUMENT = MarketInstrumentKey("ctp", "CZCE", "simulation", "future", "SA609", "SA609")
STREAM = StreamPosition("stream-1", "epoch-1", 7)


def _tick(**overrides):
    values = dict(
        instrument=INSTRUMENT,
        last_price=1500.5,
        bid_price=1500.0,
        ask_price=1501.0,
        bid_size=10.0,
        ask_size=12.0,
        lower_limit=1400.0,
        upper_limit=1600.0,
        turnover=123456789.25,
        open_interest=5000.0,
        delta_volume=3.0,
        cumulative_volume=12345.0,
        volume_complete=True,
        volume_quality="CONTINUOUS",
        continuity_status="continuous",
        trading_date="2026-11-02",
        event_session_date="2026-11-02",
        provider_event_time_utc="2026-11-02T02:00:00.500000Z",
        event_time_provenance="provider_reported",
        received_at_utc="2026-11-02T02:00:00.600000Z",
        received_monotonic_ns=123456789,
        provider_source="ctp.native.md",
        quality_contract_ref="ctp.quote.v2",
        provider_connection_generation=1,
        provider_sequence=7,
        provider_subscription_epoch=1,
        clock_domain_id="clock-domain-1",
        clock_source_session_id="clock-session-1",
        clock_source="ctp.exchange",
        source_clock_quality=MarketClockQuality.VERIFIED,
        receive_clock_quality=MarketClockQuality.VERIFIED,
        source_clock_error_ms=1.0,
        receive_clock_error_ms=1.0,
        freshness_status=MarketFreshnessStatus.FRESH,
        freshness_reason_codes=(),
        execution_eligible=True,
        quality_flags=("A",),
    )
    values.update(overrides)
    return MarketTickPayload(**values)


def _bar():
    return MarketBar(
        open_time_utc="2026-11-02T02:00:00Z",
        close_time_utc="2026-11-02T02:01:00Z",
        open="1500",
        high="1502.5",
        low="1499",
        close="1501",
        volume="30",
        open_interest=None,
    )


def _raw(message: dict) -> bytes:
    return msgpack.packb(message, use_bin_type=True)


def _envelope(**overrides):
    message = msgpack.unpackb(encode_message("tick", _tick(), stream=STREAM), raw=False)
    message.update(overrides)
    return message


# --- round trips ----------------------------------------------------------


def test_tick_round_trip_rebuilds_the_same_frozen_container():
    payload = _tick()
    decoded = decode_message(encode_message("tick", payload, stream=STREAM))
    assert decoded.kind == "tick"
    assert type(decoded.payload) is MarketTickPayload
    assert decoded.payload == payload
    assert decoded.stream == STREAM
    assert decoded.minor == SUPPORTED_MINOR == 4


@pytest.mark.parametrize("invalid_kind", [[], {}, 1, None, True])
def test_non_string_kind_is_a_finite_codec_error(invalid_kind):
    with pytest.raises(WireCodecError, match="WIRE_KIND_INVALID"):
        encode_message(invalid_kind, _tick(), stream=STREAM)
    frame = _envelope(kind=invalid_kind)
    with pytest.raises(WireCodecError, match="WIRE_KIND_INVALID"):
        decode_message(_raw(frame))


def test_unknown_quality_reference_is_read_only_and_versioned():
    tick = _tick(quality_contract_ref=None, execution_eligible=False)
    assert MarketTickPayload.from_dict(tick.to_dict()) == tick
    assert tick.to_dict()["schema_version"] == MARKET_TICK_SCHEMA_VERSION == 2
    frame = encode_message("tick", tick, stream=STREAM)
    assert decode_message(frame).payload == tick
    with pytest.raises(MarketTickContractError):
        _tick(quality_contract_ref=None, execution_eligible=True)
    with pytest.raises(WireCodecError, match="WIRE_MINOR_UNSUPPORTED"):
        decode_message(frame, supported_minor=0)


def test_legacy_tick_requires_quality_reference_in_both_formats():
    tick = _tick()
    legacy = tick.to_dict()
    legacy["schema_version"] = 1
    assert MarketTickPayload.from_dict(legacy) == tick
    legacy["quality_contract_ref"] = None
    legacy["execution_eligible"] = False
    with pytest.raises(MarketTickContractError):
        MarketTickPayload.from_dict(legacy)

    frame = _envelope(minor=0)
    assert decode_message(_raw(frame)).payload == tick
    frame["data"]["quality_contract_ref"] = None
    frame["data"]["execution_eligible"] = False
    with pytest.raises(WireCodecError, match="WIRE_PAYLOAD_INVALID"):
        decode_message(_raw(frame))


@pytest.mark.parametrize("invalid", ["", " ", 0, False])
def test_tick_quality_reference_rejects_invalid_values(invalid):
    with pytest.raises(MarketTickContractError):
        _tick(quality_contract_ref=invalid, execution_eligible=False)


def test_unknown_values_stay_unknown_across_the_wire():
    payload = _tick(
        delta_volume=None,
        volume_complete=False,
        source_clock_quality=MarketClockQuality.UNKNOWN,
        receive_clock_quality=MarketClockQuality.UNKNOWN,
        source_clock_error_ms=None,
        receive_clock_error_ms=None,
        freshness_status=MarketFreshnessStatus.UNAVAILABLE,
        freshness_reason_codes=("NO_CLOCK",),
        execution_eligible=False,
    )
    decoded = decode_message(encode_message("tick", payload, stream=STREAM)).payload
    assert decoded.delta_volume is None
    assert decoded.execution_eligible is False
    assert decoded == payload


def test_bar_round_trip_preserves_decimal_lexemes():
    decoded = decode_message(encode_message("bar", _bar(), stream=STREAM))
    assert type(decoded.payload) is MarketBar
    assert decoded.payload == _bar()


def test_provider_extensions_are_namespaced_and_preserved():
    data = encode_message(
        "tick", _tick(), stream=STREAM, extensions={"ctp": {"trading_day": "20261102"}}
    )
    assert decode_message(data).extensions == {"ctp": {"trading_day": "20261102"}}
    with pytest.raises(WireCodecError):
        encode_message("tick", _tick(), stream=STREAM, extensions={"CTP": {"x": 1}})
    with pytest.raises(WireCodecError):
        encode_message("tick", _tick(), stream=STREAM, extensions={"ctp": {"x": 1.5}})


# --- decimal grammar ------------------------------------------------------


@pytest.mark.parametrize(
    "value, text",
    [
        (1.5, "1.5"),
        (Decimal("1.500"), "1.5"),
        ("100", "100"),
        (0.0, "0"),
        (-0.0, "0"),
        ("1e5", "100000"),
        (-2.25, "-2.25"),
        (0.1, "0.1"),
    ],
)
def test_canonical_decimal(value, text):
    assert canonical_decimal(value) == text
    assert parse_decimal(text) == Decimal(text)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "NaN", "Infinity", True, None])
def test_canonical_decimal_rejects_non_finite(value):
    with pytest.raises(WireCodecError):
        canonical_decimal(value)


@pytest.mark.parametrize(
    "text", ["1e5", "-0", "01", "1.50", "1.", ".5", "+1", " 1", "NaN", "1" * 41, 1, None]
)
def test_parse_decimal_rejects_non_canonical(text):
    with pytest.raises(WireCodecError):
        parse_decimal(text)


# --- strict decoding ------------------------------------------------------


def test_trailing_bytes_and_concatenated_objects_are_rejected():
    data = encode_message("tick", _tick(), stream=STREAM)
    for bad in (data + b"\x00", data + data):
        with pytest.raises(WireCodecError) as info:
            decode_message(bad)
        assert info.value.code == "WIRE_TRAILING_BYTES"


def test_duplicate_map_keys_are_rejected():
    # fixmap of 2 entries with the same key "kind".
    duplicate = b"\x82" + msgpack.packb("kind") + msgpack.packb("a") * 0 + msgpack.packb(
        "tick"
    ) + msgpack.packb("kind") + msgpack.packb("bar")
    with pytest.raises(WireCodecError) as info:
        decode_message(duplicate)
    assert info.value.code == "WIRE_DUPLICATE_KEY"


def test_non_text_keys_ext_types_and_floats_are_rejected():
    with pytest.raises(WireCodecError) as info:
        decode_message(_raw({1: "x"}))
    assert info.value.code == "WIRE_MAP_KEY_INVALID"
    with pytest.raises(WireCodecError):
        decode_message(_raw({"x": msgpack.ExtType(5, b"abc")}))
    message = _envelope()
    message["data"]["last_price"] = 1500.5  # a binary float sneaking in
    with pytest.raises(WireCodecError) as info:
        decode_message(_raw(message))
    assert info.value.code == "WIRE_FLOAT_FORBIDDEN"


def test_size_depth_and_integer_limits():
    with pytest.raises(WireCodecError) as info:
        decode_message(b"\x00" * (MAX_MESSAGE_BYTES + 1))
    assert info.value.code == "WIRE_MESSAGE_TOO_LARGE"
    nested: object = "x"
    for _ in range(12):
        nested = {"a": nested}
    with pytest.raises(WireCodecError) as info:
        decode_message(_raw(nested))
    assert info.value.code == "WIRE_DEPTH_EXCEEDED"
    message = _envelope()
    message["stream"]["sequence"] = 2**63
    with pytest.raises(WireCodecError):
        decode_message(_raw(message))


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"schema_id": "other"}, "WIRE_SCHEMA_UNSUPPORTED"),
        ({"major": 2}, "WIRE_MAJOR_UNSUPPORTED"),
        ({"minor": 5}, "WIRE_MINOR_UNSUPPORTED"),
        ({"kind": "order"}, "WIRE_KIND_INVALID"),
        ({"unexpected": 1}, "WIRE_FIELD_SET_INVALID"),
    ],
)
def test_envelope_version_and_field_rules(overrides, code):
    with pytest.raises(WireCodecError) as info:
        decode_message(_raw(_envelope(**overrides)))
    assert info.value.code == code


def test_newer_minor_is_accepted_only_when_supported():
    data = _raw(_envelope(minor=1))
    assert decode_message(data, supported_minor=1).minor == 1


def test_unknown_or_missing_data_fields_are_rejected():
    message = _envelope()
    message["data"]["new_critical_field"] = "x"
    with pytest.raises(WireCodecError) as info:
        decode_message(_raw(message))
    assert info.value.code == "WIRE_FIELD_SET_INVALID"
    message = _envelope()
    del message["data"]["execution_eligible"]
    with pytest.raises(WireCodecError):
        decode_message(_raw(message))


def test_values_rejected_by_the_base_container_are_rejected():
    message = _envelope()
    message["data"]["provider_event_time_utc"] = "not-a-time"
    with pytest.raises(WireCodecError) as info:
        decode_message(_raw(message))
    assert info.value.code == "WIRE_PAYLOAD_INVALID"
    message = _envelope()
    message["data"]["last_price"] = "1.50"  # non-canonical decimal lexeme
    with pytest.raises(WireCodecError) as info:
        decode_message(_raw(message))
    assert info.value.code == "WIRE_DECIMAL_INVALID"


def test_encode_rejects_wrong_kind_payload_pairs():
    with pytest.raises(WireCodecError):
        encode_message("bar", _tick(), stream=STREAM)
    with pytest.raises(WireCodecError):
        StreamPosition("s", "e", 0)


# --- handshake and command identity --------------------------------------


def test_schema_digest_is_stable_and_identifies_the_contract():
    digest = schema_digest()
    assert digest == schema_digest()
    assert len(digest) == 64
    # v1.0's digest must not match the nullable-reference v1.1 contract.
    assert digest != "8f1b1d4997d95230571f2d8c886c42c49e1ef1ff8fa290dc89f0b5b93447947f"
    assert SCHEMA_ID == "bt_api.wire.v1"


def test_command_fingerprint_equivalence_and_conflicts():
    base = {
        "account_ref": "acct",
        "route": "ctp",
        "strategy_ref": "strategy-a",
        "command": "submit",
        "side": "SELL",
        "quantity": "2",
        "price": "1500.50",
        "tags": None,
    }
    same = {
        "price": 1500.5,
        "quantity": Decimal("2.0"),
        "side": "SELL",
        "command": "submit",
        "strategy_ref": "strategy-a",
        "route": "ctp",
        "account_ref": "acct",
    }
    assert command_fingerprint(base) == command_fingerprint(same)
    for key, value in (("strategy_ref", "strategy-b"), ("quantity", "3"), ("account_ref", "x")):
        assert command_fingerprint({**base, key: value}) != command_fingerprint(base)
    # Opaque identifiers are compared verbatim, not numerically.
    assert command_fingerprint({**base, "order_ref": "007"}) != command_fingerprint(
        {**base, "order_ref": "7"}
    )
    with pytest.raises(WireCodecError):
        command_fingerprint({**base, "quantity": "NaN"})


def test_importing_the_contract_does_not_import_msgpack():
    code = (
        "import sys; import bt_api_base.wire_codec_v1; "
        "print('msgpack' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.stdout.strip() == "False", result.stderr


def test_codec_backend_reports_the_active_implementation():
    from bt_api_base.wire_codec_v1 import codec_backend

    backend = codec_backend()
    assert backend in {"c", "python"}
    expected = (
        "c" if msgpack.unpackb.__module__ == "msgpack._cmsgpack"
        and msgpack.Packer.__module__ == "msgpack._cmsgpack" else "python"
    )
    assert backend == expected


# --- fill facts (managed_paper_fill.v2) ------------------------------------

from bt_api_base.paper_fill_protocol import MANAGED_PAPER_FILL_V2_FIELDS


def _fill(**overrides):
    fill = {name: f"v-{name}" for name in MANAGED_PAPER_FILL_V2_FIELDS}
    fill.update(
        schema="managed_paper_fill.v2",
        match_time_ns=1_700_000_000_000_000_000,
        event_sequence=7,
        quote_cursor=3,
        quantity="1.250",
        price="10.02",
        commission="0.0125",
    )
    fill.update(overrides)
    return fill


def test_fill_fact_round_trip_is_frozen_and_canonical():
    decoded = decode_message(encode_message("fill", _fill(), stream=STREAM))
    assert decoded.kind == "fill"
    payload = decoded.payload
    assert set(payload) == MANAGED_PAPER_FILL_V2_FIELDS
    assert payload["quantity"] == "1.25"  # canonical decimal lexeme
    assert payload["event_sequence"] == 7
    with pytest.raises(TypeError):
        payload["quantity"] = "2"  # read-only view shared by consumers


@pytest.mark.parametrize(
    "overrides",
    [{"extra": "x"}, {"schema": "managed_paper_fill.v1"}],
    ids=["extra-field", "other-schema"],
)
def test_fill_fact_shape_is_the_shared_contract(overrides):
    with pytest.raises(WireCodecError):
        encode_message("fill", _fill(**overrides), stream=STREAM)


def test_fill_fact_rejects_bad_values_on_decode():
    raw = msgpack.unpackb(encode_message("fill", _fill(), stream=STREAM), raw=False)
    for name, value in (("price", "1.50"), ("quantity", "-1"), ("event_sequence", "7"), ("fill_id", "")):
        bad = dict(raw, data=dict(raw["data"], **{name: value}))
        with pytest.raises(WireCodecError):
            decode_message(_raw(bad))


def test_schema_digest_covers_the_fill_contract():
    assert len(schema_digest()) == 64
