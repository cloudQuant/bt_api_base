"""Small, bounded wire contract for ordinary SDK telemetry samples."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, ClassVar

TELEMETRY_SCHEMA_VERSION = 1
MAX_TELEMETRY_SAMPLE_BYTES = 8192
MAX_TELEMETRY_METRICS = 32

_MAX_I63 = 1 << 63
_METRIC_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,63}\Z", re.ASCII)
_SENSITIVE_METRIC_PARTS = ("secret", "token", "password", "credential", "apikey", "privatekey")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_WIRE_FIELDS = frozenset(
    {
        "schema_version",
        "stream_id",
        "sequence",
        "kind",
        "observed_at",
        "metrics",
        "dropped_queue_total",
        "dropped_delivery_total",
    }
)
_ERROR_CODES = frozenset(
    {
        "invalid_mapping",
        "invalid_field_set",
        "invalid_schema_version",
        "invalid_stream_id",
        "invalid_sequence",
        "invalid_kind",
        "invalid_observed_at",
        "invalid_metrics",
        "too_many_metrics",
        "invalid_metric_name",
        "sensitive_metric_name",
        "invalid_metric_value",
        "invalid_drop_count",
        "heartbeat_metrics_must_be_empty",
        "metrics_event_requires_metrics",
        "sample_too_large",
    }
)


class TelemetryProtocolError(ValueError):
    """A malformed or out-of-bounds telemetry sample with a finite error code."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown telemetry protocol error code")
        self.code = code
        super().__init__(code)


def _error(code: str) -> None:
    raise TelemetryProtocolError(code)


def _check_stream_id(value: Any) -> str:
    if type(value) is not str:
        _error("invalid_stream_id")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _error("invalid_stream_id")
    if (
        not encoded
        or len(encoded) > 64
        or any(char.isspace() or not char.isprintable() for char in value)
    ):
        _error("invalid_stream_id")
    return value


def _check_sequence(value: Any) -> int:
    if type(value) is not int or not 1 <= value < _MAX_I63:
        _error("invalid_sequence")
    return value


def _check_observed_at(value: Any) -> int | float:
    if type(value) not in (int, float):
        _error("invalid_observed_at")
    if type(value) is float and not math.isfinite(value):
        _error("invalid_observed_at")
    try:
        _EPOCH + timedelta(seconds=value)
    except (OverflowError, TypeError, ValueError):
        _error("invalid_observed_at")
    return value


def _check_metric_name(value: Any) -> str:
    if type(value) is not str or _METRIC_NAME.fullmatch(value) is None:
        _error("invalid_metric_name")
    normalized = value.casefold().replace(".", "").replace("_", "")
    if any(part in normalized for part in _SENSITIVE_METRIC_PARTS):
        _error("sensitive_metric_name")
    return value


def _normalize_metrics(value: Any) -> Mapping[str, int | float]:
    if not isinstance(value, Mapping):
        _error("invalid_metrics")

    normalized: dict[str, int | float] = {}
    try:
        for index, (raw_name, raw_value) in enumerate(value.items()):
            if index >= MAX_TELEMETRY_METRICS:
                _error("too_many_metrics")
            name = _check_metric_name(raw_name)
            if name in normalized:
                _error("invalid_metrics")
            if type(raw_value) not in (int, float):
                _error("invalid_metric_value")
            if type(raw_value) is float and not math.isfinite(raw_value):
                _error("invalid_metric_value")
            normalized[name] = raw_value
    except TelemetryProtocolError:
        raise
    except Exception:
        _error("invalid_metrics")

    return MappingProxyType(dict(sorted(normalized.items())))


def _check_drop_count(value: Any) -> int:
    if type(value) is not int or not 0 <= value < _MAX_I63:
        _error("invalid_drop_count")
    return value


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, OverflowError, UnicodeEncodeError):
        _error("sample_too_large")


@dataclass(frozen=True)
class TelemetrySample:
    """One heartbeat or flat numeric metric sample from a unique emitter stream."""

    stream_id: str
    sequence: int
    kind: str
    observed_at: int | float
    metrics: Mapping[str, int | float]
    dropped_queue_total: int
    dropped_delivery_total: int

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "stream_id",
            "sequence",
            "kind",
            "observed_at",
            "metrics",
            "dropped_queue_total",
            "dropped_delivery_total",
        }
    )

    def __post_init__(self) -> None:
        _check_stream_id(self.stream_id)
        _check_sequence(self.sequence)
        if type(self.kind) is not str or self.kind not in ("heartbeat", "metrics"):
            _error("invalid_kind")
        _check_observed_at(self.observed_at)
        normalized_metrics = _normalize_metrics(self.metrics)
        if self.kind == "heartbeat" and normalized_metrics:
            _error("heartbeat_metrics_must_be_empty")
        if self.kind == "metrics" and not normalized_metrics:
            _error("metrics_event_requires_metrics")
        _check_drop_count(self.dropped_queue_total)
        _check_drop_count(self.dropped_delivery_total)
        object.__setattr__(self, "metrics", normalized_metrics)

        if len(_canonical_json_bytes(self.to_dict())) > MAX_TELEMETRY_SAMPLE_BYTES:
            _error("sample_too_large")

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-ready mapping in the exact published shape."""
        return {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "stream_id": self.stream_id,
            "sequence": self.sequence,
            "kind": self.kind,
            "observed_at": self.observed_at,
            "metrics": dict(self.metrics),
            "dropped_queue_total": self.dropped_queue_total,
            "dropped_delivery_total": self.dropped_delivery_total,
        }


def parse_telemetry_sample(raw: Mapping[str, Any]) -> TelemetrySample:
    """Parse one complete telemetry wire object, rejecting unknown fields."""
    if not isinstance(raw, Mapping):
        _error("invalid_mapping")
    try:
        keys = tuple(raw.keys())
    except Exception:
        _error("invalid_mapping")
    if any(type(key) is not str for key in keys):
        _error("invalid_mapping")
    if frozenset(keys) != _WIRE_FIELDS or len(keys) != len(_WIRE_FIELDS):
        _error("invalid_field_set")
    try:
        schema_version = raw["schema_version"]
        stream_id = raw["stream_id"]
        sequence = raw["sequence"]
        kind = raw["kind"]
        observed_at = raw["observed_at"]
        metrics = raw["metrics"]
        dropped_queue_total = raw["dropped_queue_total"]
        dropped_delivery_total = raw["dropped_delivery_total"]
    except Exception:
        _error("invalid_mapping")
    if type(schema_version) is not int or schema_version != TELEMETRY_SCHEMA_VERSION:
        _error("invalid_schema_version")
    return TelemetrySample(
        stream_id=stream_id,
        sequence=sequence,
        kind=kind,
        observed_at=observed_at,
        metrics=metrics,
        dropped_queue_total=dropped_queue_total,
        dropped_delivery_total=dropped_delivery_total,
    )


def sample_size_bytes(sample: TelemetrySample) -> int:
    """Return the canonical UTF-8 JSON size, including every wire field."""
    if type(sample) is not TelemetrySample:
        _error("invalid_mapping")
    encoded = _canonical_json_bytes(sample.to_dict())
    if len(encoded) > MAX_TELEMETRY_SAMPLE_BYTES:
        _error("sample_too_large")
    return len(encoded)


__all__ = [
    "MAX_TELEMETRY_METRICS",
    "MAX_TELEMETRY_SAMPLE_BYTES",
    "TELEMETRY_SCHEMA_VERSION",
    "TelemetryProtocolError",
    "TelemetrySample",
    "parse_telemetry_sample",
    "sample_size_bytes",
]
