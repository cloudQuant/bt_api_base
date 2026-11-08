"""Versioned source labels on prepared cancels are bounded data, not authority."""

from dataclasses import replace
from types import MappingProxyType

import pytest

from bt_api_base.direct_cancel_protocol import PreparedCancelError, PreparedCancelRequest
from bt_api_base.direct_write_protocol import NativeOrderIdentity, PreDispatchRecord, WriteOperation


@pytest.fixture
def v1():
    return PreparedCancelRequest(
        "cancel-reservation",
        NativeOrderIdentity(
            "CTP",
            "original-ref",
            {
                "trading_day": "20261107",
                "front_id": 2,
                "session_id": 3,
            },
            4,
        ),
        "IF2612",
        "20261108",
        5,
        {"RequestID": 42, "OrderActionRef": 42, "ActionFlag": "0"},
        ("attempt-key",),
    )


def test_v1_stays_byte_compatible_and_never_manufactures_source(v1):
    raw = v1.to_mapping()
    assert raw["schema_version"] == 1 and "source_binding" not in raw
    assert v1.digest() == "f4fb24a1491cdc09f4828f005101d484af9196633152da133203af94e5347020"
    restored = PreparedCancelRequest.from_mapping(raw)
    assert restored.source_binding is None and restored.to_mapping() == raw
    assert restored.digest() == v1.digest()


def test_v2_copies_and_seals_flat_source_and_preserves_predispatch_record(v1):
    source = {
        "schema": "ctp-cancel-source-v1",
        "login_request_id": 3,
        "truth": True,
        "optional": None,
        "empty": "",
    }
    prepared = replace(v1, source_binding=source)
    source["login_request_id"] = 4
    assert prepared.source_binding["login_request_id"] == 3
    assert type(prepared.source_binding) is type(MappingProxyType({}))
    with pytest.raises(TypeError):
        prepared.source_binding["login_request_id"] = 5
    raw = prepared.to_mapping()
    assert raw["schema_version"] == 2 and raw["source_binding"]["truth"] is True
    restored = PreparedCancelRequest.from_mapping(raw)
    assert restored == prepared and restored.digest() == prepared.digest()
    assert prepared.digest() != v1.digest()
    raw["source_binding"]["schema"] = "changed"
    assert prepared.source_binding["schema"] == "ctp-cancel-source-v1"
    record = PreDispatchRecord(
        WriteOperation.CANCEL,
        "scope",
        "CTP",
        "IF2612",
        None,
        prepared.target_identity,
        {},
        "20261108",
        5,
        "2026-11-08T00:00:00Z",
        prepared,
    )
    assert record.to_dict()["prepared_cancel"] == prepared.to_mapping()
    assert (
        record.to_dict()["prepared_cancel"]["target_identity"]["fields"]["trading_day"]
        == "20261107"
    )


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"bad key": 1},
        {"1key": "x"},
        {"x-y": "x"},
        {"x": 1.0},
        {"x": 2**63},
        {"x": -(2**63) - 1},
        {"x": "界" * 86},
        {"x": []},
        {"x": {}},
        {1: "value"},
        {f"k{i}": i for i in range(129)},
        ["not", "a", "mapping"],
    ],
)
def test_source_bounds_and_types_are_strict(v1, bad):
    with pytest.raises(PreparedCancelError):
        replace(v1, source_binding=bad)


def test_numeric_boolean_binding_types_have_distinct_wire_and_digest(v1):
    boolean = replace(v1, source_binding={"value": True})
    integer = replace(v1, source_binding={"value": 1})
    assert boolean.digest() != integer.digest()
    assert boolean != integer
    assert (
        type(PreparedCancelRequest.from_mapping(boolean.to_mapping()).source_binding["value"])
        is bool
    )
    assert (
        type(PreparedCancelRequest.from_mapping(integer.to_mapping()).source_binding["value"])
        is int
    )
    assert replace(v1, request_fields={"value": True}) != replace(v1, request_fields={"value": 1})
    with pytest.raises(TypeError):
        hash(boolean)


@pytest.mark.parametrize(
    "mutation",
    ["source", "remove", "insert_v1", "wrong_version", "bool_version", "null_source", "extra"],
)
def test_wire_versions_have_exact_shapes(v1, mutation):
    raw = replace(v1, source_binding={"id": 1}).to_mapping()
    if mutation == "source":
        raw["source_binding"] = {}
    elif mutation == "remove":
        del raw["source_binding"]
    elif mutation == "insert_v1":
        raw["schema_version"] = 1
    elif mutation == "wrong_version":
        raw["schema_version"] = 3
    elif mutation == "bool_version":
        raw["schema_version"] = True
    elif mutation == "null_source":
        raw["source_binding"] = None
    else:
        raw["extra"] = 1
    with pytest.raises(PreparedCancelError):
        PreparedCancelRequest.from_mapping(raw)


def test_frozen_source_tampering_invalidates_seal(v1):
    prepared = replace(v1, source_binding={"id": 1})
    equivalent = replace(v1, source_binding={"id": 1})
    object.__setattr__(prepared, "source_binding", MappingProxyType({"id": 2}))
    with pytest.raises(PreparedCancelError):
        prepared.to_mapping()
    with pytest.raises(PreparedCancelError):
        prepared.digest()
    with pytest.raises(PreparedCancelError):
        _ = prepared == equivalent
