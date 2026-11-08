"""Offline prepared-cancel DTO and durable record contracts."""
from dataclasses import FrozenInstanceError, replace

import pytest

from bt_api_base.direct_cancel_protocol import PreparedCancelError, PreparedCancelRequest
from bt_api_base.direct_write_protocol import NativeOrderIdentity, PreDispatchRecord, WriteOperation


@pytest.fixture
def prepared():
    return PreparedCancelRequest("cancel-reservation", NativeOrderIdentity(
        "CTP", "original-ref", {"trading_day": "20261107", "front_id": 2, "session_id": 3}, 4),
        "IF2612", "20261108", 5,
        {"RequestID": 42, "OrderActionRef": 42, "ActionFlag": "0"}, ("attempt-key",))


def record(prepared, **changes):
    fields = dict(operation=WriteOperation.CANCEL, host_scope="scope", exchange_name="CTP",
        symbol="IF2612", identity=None, target_identity=prepared.target_identity, request_summary={},
        trading_day="20261108", session_generation=5, created_at_utc="2026-11-08T00:00:00Z",
        prepared_cancel=prepared)
    fields.update(changes)
    return PreDispatchRecord(**fields)


def test_roundtrip_preserves_original_day_and_immutability(prepared):
    raw = prepared.to_mapping()
    assert raw["target_identity"]["fields"]["trading_day"] == "20261107"
    assert raw["trading_day"] == "20261108"
    assert PreparedCancelRequest.from_mapping(raw) == prepared
    assert PreparedCancelRequest.from_mapping(raw).digest() == prepared.digest()
    raw["request_fields"]["RequestID"] = 99
    assert prepared.request_fields["RequestID"] == 42
    with pytest.raises(TypeError):
        prepared.request_fields["RequestID"] = 99
    with pytest.raises(FrozenInstanceError):
        prepared.symbol = "other"


@pytest.mark.parametrize("change", [
    {"reservation_id": ""}, {"symbol": " "}, {"trading_day": "20260229"},
    {"session_generation": True}, {"session_generation": 0}, {"session_generation": 2**63},
    {"request_fields": {"bad key": 1}}, {"request_fields": {"Value": 1.0}},
    {"request_fields": {"Value": 2**63}}, {"request_fields": {"Value": "界" * 86}},
    {"request_keys": ()}, {"request_keys": ("same", "same")},
    {"request_keys": ("z", "a")}, {"request_keys": ["key"]}, {"request_keys": ("key",) * 17},
])
def test_invalid_inputs(prepared, change):
    with pytest.raises(PreparedCancelError):
        replace(prepared, **change)


def test_mapping_rejects_missing_extra_bool_version_and_nested_shape(prepared):
    for name in prepared.to_mapping():
        raw = prepared.to_mapping(); del raw[name]
        with pytest.raises(PreparedCancelError):
            PreparedCancelRequest.from_mapping(raw)
    for name, value in (("schema_version", True), ("request_keys", ("attempt-key",)),
                        ("extra", 1)):
        raw = prepared.to_mapping(); raw[name] = value
        with pytest.raises(PreparedCancelError):
            PreparedCancelRequest.from_mapping(raw)
    raw = prepared.to_mapping(); raw["target_identity"]["extra"] = 1
    with pytest.raises(PreparedCancelError):
        PreparedCancelRequest.from_mapping(raw)


@pytest.mark.parametrize("field,value", [("session_generation", 6), ("symbol", "other"),
                                         ("request_keys", ("other",))])
def test_post_construction_tampering_invalidates_serialization(prepared, field, value):
    object.__setattr__(prepared, field, value)
    with pytest.raises(PreparedCancelError):
        prepared.to_mapping()
    with pytest.raises(PreparedCancelError):
        prepared.digest()


def test_predispatch_preserves_old_shape_and_binds_prepared(prepared):
    bound = record(prepared)
    assert bound.to_dict()["prepared_cancel"] == prepared.to_mapping()
    assert "prepared_cancel" not in replace(bound, prepared_cancel=None).to_dict()
    for changes in ({"operation": WriteOperation.PLACE}, {"exchange_name": "other"},
                    {"symbol": "other"}, {"trading_day": "20261107"},
                    {"session_generation": 4}, {"session_generation": True},
                    {"identity": prepared.target_identity},
                    {"target_identity": NativeOrderIdentity("CTP", "other", {}, 4)}):
        with pytest.raises(ValueError):
            record(prepared, **changes)
    object.__setattr__(bound, "symbol", "changed")
    with pytest.raises(ValueError):
        bound.to_dict()
