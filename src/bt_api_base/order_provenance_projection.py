"""Project finite order-source facts with caller-selected field contracts.

Projection and hashing do not establish that the original source is trusted.
The SDK composer selects fields and remains responsible for source binding.
"""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from enum import Enum

from .order_observation_contracts import NormalizationProvenance


def _provenance_scalar(value):
    """Project only inert scalar facts; arbitrary provider objects are omitted."""
    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, Decimal) and value.is_finite():
        return format(value, "f")
    if isinstance(value, float) and math.isfinite(value):
        return format(value, ".17g")
    if isinstance(value, Enum):
        return _provenance_scalar(value.value)
    return None


def project_order_source_provenance(
    raw, operation, row=None, *, source_value_fields, envelope_value_fields,
    v2_source_fields, v2_envelope_fields, schema_v1, schema_v2,
):
    """Bind explicit raw order/fill fields without retaining arbitrary values."""
    envelope = raw if isinstance(raw, dict) else {}
    row = row if isinstance(row, dict) else {}
    source_fields = tuple(sorted(key for key in row if type(key) is str))
    envelope_fields = tuple(sorted(key for key in envelope if type(key) is str))
    source_values = {
        key: _provenance_scalar(value)
        for key, value in row.items()
        if key in source_value_fields and _provenance_scalar(value) is not None
    }
    envelope_values = {
        key: _provenance_scalar(value)
        for key, value in envelope.items()
        if key in envelope_value_fields and _provenance_scalar(value) is not None
    }
    nested_rows = envelope.get("data")
    explicit_v2 = bool(
        set(row).intersection(v2_source_fields)
        or set(envelope).intersection(v2_envelope_fields)
        or (
            isinstance(nested_rows, list)
            and any(
                isinstance(item, dict) and bool(set(item).intersection(v2_source_fields))
                for item in nested_rows
            )
        )
    )
    schema = schema_v2 if explicit_v2 else schema_v1
    projection = {
        "envelope_values": envelope_values,
        "operation": operation,
        "schema": schema,
        "source_fields": source_fields,
        "source_values": source_values,
    }
    digest = hashlib.sha256(
        json.dumps(
            projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        ).encode("utf-8", errors="strict")
    ).hexdigest()
    return NormalizationProvenance(
        schema=schema,
        operation=operation,
        source_fields=source_fields,
        source_values=tuple(sorted(source_values.items())),
        envelope_fields=envelope_fields,
        envelope_values=tuple(sorted(envelope_values.items())),
        source_sha256=digest,
    )


def provenance_snapshot_matches(value: object, *, operation: str, schema: str, canonical_json, sha256_text) -> bool:
    if type(value) is not dict or set(value) != {
        "schema",
        "operation",
        "source_fields",
        "source_values",
        "envelope_fields",
        "envelope_values",
        "source_sha256",
    }:
        return False
    if (
        value.get("schema") != schema
        or value.get("operation") != operation
        or type(value.get("source_fields")) is not list
        or type(value.get("envelope_fields")) is not list
        or type(value.get("source_values")) is not dict
        or type(value.get("envelope_values")) is not dict
    ):
        return False
    source_fields = value["source_fields"]
    envelope_fields = value["envelope_fields"]
    source_values = value["source_values"]
    envelope_values = value["envelope_values"]
    if (
        source_fields != sorted(set(source_fields))
        or envelope_fields != sorted(set(envelope_fields))
        or set(source_values) - set(source_fields)
        or set(envelope_values) - set(envelope_fields)
        or any(type(key) is not str or type(item) not in (str, int, bool) for key, item in source_values.items())
        or any(type(key) is not str or type(item) not in (str, int, bool) for key, item in envelope_values.items())
    ):
        return False
    expected = sha256_text(
        canonical_json(
            {
                "envelope_values": envelope_values,
                "operation": operation,
                "schema": value["schema"],
                "source_fields": source_fields,
                "source_values": source_values,
            }
        )
    )
    return value.get("source_sha256") == expected


__all__ = ("project_order_source_provenance", "provenance_snapshot_matches")
