"""Strict public cancellation observations contain no native details."""

from dataclasses import replace

import pytest

from bt_api_base.gateway_cancel_protocol import GatewayCancelRecord
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding, GatewayDirectProtocolError


@pytest.fixture
def record():
    return GatewayCancelRecord(
        1,
        GatewayCommandBinding("journal", "account", "strategy", "principal"),
        "operation",
        "attempt",
        "order",
        "reservation",
        "a" * 64,
        "REQUESTED",
        1,
        "generation",
        "generation",
        True,
        None,
    )


def test_strict_roundtrip_and_detached_binding(record):
    mapping = record.to_mapping()
    with pytest.raises(TypeError):
        GatewayCancelRecord.from_mapping(mapping)
    assert GatewayCancelRecord.from_mapping(mapping, expected_binding=record.binding) == record
    assert set(mapping) == {
        "schema_version",
        "binding",
        "operation_id",
        "attempt_id",
        "request_key",
        "target_reservation_id",
        "target_digest",
        "state",
        "version",
        "owner_generation",
        "attempt_generation",
        "generation_current",
        "error_code",
    }
    mapping["binding"]["principal"] = "other"
    with pytest.raises(GatewayDirectProtocolError, match="BINDING_MISMATCH"):
        GatewayCancelRecord.from_mapping(mapping, expected_binding=record.binding)
    assert record.binding.principal == "principal"


@pytest.mark.parametrize(
    "state,version,error",
    [
        ("REQUESTED", 1, None),
        ("DISPATCHING", 2, None),
        ("SENT", 3, None),
        ("NOT_SENT", 3, "CANCEL_NOT_SENT"),
        ("NOT_SENT", 3, "CANCEL_FAILED"),
        ("UNKNOWN", 3, "CANCEL_OUTCOME_UNKNOWN"),
        ("UNKNOWN", 3, "CANCEL_FAILED"),
    ],
)
def test_state_versions_and_error_codes(record, state, version, error):
    candidate = replace(record, state=state, version=version, error_code=error)
    assert (
        GatewayCancelRecord.from_mapping(candidate.to_mapping(), expected_binding=record.binding)
        == candidate
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": True},
        {"version": True},
        {"version": 2},
        {"state": "CANCELLED", "version": 3},
        {"target_digest": "A" * 64},
        {"generation_current": False},
        {"operation_id": " "},
        {"attempt_id": "x" * 257},
        {"error_code": "native secret"},
        {"error_code": "CANCEL_FAILED"},
        {"state": "SENT", "version": 3, "error_code": "CANCEL_FAILED"},
        {"state": "UNKNOWN", "version": 3, "error_code": "CANCEL_NOT_SENT"},
        {"state": "NOT_SENT", "version": 3, "error_code": "CANCEL_OUTCOME_UNKNOWN"},
    ],
)
def test_bad_fields_fail_closed(record, changes):
    with pytest.raises(GatewayDirectProtocolError):
        replace(record, **changes)


def test_extra_wire_fields_and_mutation_are_rejected(record):
    raw = record.to_mapping()
    raw["prepared_cancel"] = {}
    with pytest.raises(GatewayDirectProtocolError):
        GatewayCancelRecord.from_mapping(raw, expected_binding=record.binding)
    object.__setattr__(record, "error_code", "exchange raw text")
    with pytest.raises(GatewayDirectProtocolError):
        record.to_mapping()
