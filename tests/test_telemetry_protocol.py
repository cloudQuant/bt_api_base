"""Focused tests for the bounded telemetry wire contract."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from bt_api_base.telemetry_protocol import (
    MAX_TELEMETRY_METRICS,
    MAX_TELEMETRY_SAMPLE_BYTES,
    TELEMETRY_SCHEMA_VERSION,
    TelemetryProtocolError,
    TelemetrySample,
    parse_telemetry_sample,
    sample_size_bytes,
)


def _sample(**overrides: object) -> TelemetrySample:
    values: dict[str, object] = {
        "stream_id": "monitor-main-1",
        "sequence": 1,
        "kind": "metrics",
        "observed_at": 1_797_000_000.25,
        "metrics": {"queue.depth": 3, "events.sent": 12.5},
        "dropped_queue_total": 0,
        "dropped_delivery_total": 2,
    }
    values.update(overrides)
    return TelemetrySample(**values)  # type: ignore[arg-type]


def _assert_code(code: str, callback: object) -> None:
    with pytest.raises(TelemetryProtocolError) as raised:
        callback()  # type: ignore[operator]
    assert raised.value.code == code


def test_round_trip_is_detached_sorted_and_byte_counted() -> None:
    original_metrics = {"zeta": 2.5, "alpha": 4}
    sample = _sample(metrics=original_metrics)
    original_metrics["later"] = 8

    assert list(sample.metrics) == ["alpha", "zeta"]
    with pytest.raises(TypeError):
        sample.metrics["alpha"] = 99  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        sample.sequence = 2  # type: ignore[misc]

    wire = sample.to_dict()
    assert set(wire) == {
        "schema_version",
        "stream_id",
        "sequence",
        "kind",
        "observed_at",
        "metrics",
        "dropped_queue_total",
        "dropped_delivery_total",
    }
    assert wire["schema_version"] == TELEMETRY_SCHEMA_VERSION
    wire["metrics"]["alpha"] = -1
    assert sample.metrics["alpha"] == 4
    assert parse_telemetry_sample(sample.to_dict()) == sample
    assert sample_size_bytes(sample) > 0
    assert sample_size_bytes(sample) <= MAX_TELEMETRY_SAMPLE_BYTES


def test_schema_and_counter_boundaries_are_strict() -> None:
    valid = _sample().to_dict()
    _assert_code("invalid_field_set", lambda: parse_telemetry_sample({**valid, "extra": 1}))
    _assert_code(
        "invalid_schema_version",
        lambda: parse_telemetry_sample({**valid, "schema_version": True}),
    )
    _assert_code(
        "invalid_sequence",
        lambda: _sample(sequence=True),
    )
    _assert_code("invalid_sequence", lambda: _sample(sequence=1 << 63))
    _assert_code("invalid_drop_count", lambda: _sample(dropped_queue_total=-1))
    _assert_code(
        "invalid_drop_count",
        lambda: _sample(dropped_delivery_total=1 << 63),
    )


def test_kind_timestamp_and_stream_constraints() -> None:
    _assert_code(
        "heartbeat_metrics_must_be_empty",
        lambda: _sample(kind="heartbeat"),
    )
    _assert_code(
        "metrics_event_requires_metrics",
        lambda: _sample(metrics={}),
    )
    _assert_code("invalid_kind", lambda: _sample(kind="Heartbeat"))
    _assert_code("invalid_observed_at", lambda: _sample(observed_at=float("inf")))
    _assert_code("invalid_observed_at", lambda: _sample(observed_at=253_402_300_800))
    _assert_code("invalid_stream_id", lambda: _sample(stream_id="stream\n1"))
    _assert_code("invalid_stream_id", lambda: _sample(stream_id="é" * 33))


def test_metric_names_values_and_cardinality_are_bounded() -> None:
    _assert_code("invalid_metric_name", lambda: _sample(metrics={"1latency": 1}))
    _assert_code("sensitive_metric_name", lambda: _sample(metrics={"api_key.age": 1}))
    _assert_code("invalid_metric_value", lambda: _sample(metrics={"enabled": True}))
    _assert_code("invalid_metric_value", lambda: _sample(metrics={"load": float("nan")}))
    many = {f"metric{index}": index for index in range(MAX_TELEMETRY_METRICS + 1)}
    _assert_code("too_many_metrics", lambda: _sample(metrics=many))


def test_payload_cap_counts_full_canonical_wire_object() -> None:
    # 32 individually valid numbers exceed the cap only when the complete
    # serialized sample is counted.
    large_metrics = {f"m{index:02d}": 10**300 for index in range(MAX_TELEMETRY_METRICS)}
    _assert_code("sample_too_large", lambda: _sample(metrics=large_metrics))
    _assert_code("invalid_mapping", lambda: sample_size_bytes({}))
