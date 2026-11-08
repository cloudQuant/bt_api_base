"""Offline v1 prepared-place seal and pre-dispatch binding tests."""

from dataclasses import FrozenInstanceError, replace

import pytest

from bt_api_base.direct_place_protocol import PreparedPlaceError, PreparedPlaceRequest
from bt_api_base.direct_write_protocol import NativeOrderIdentity, PreDispatchRecord, WriteOperation


@pytest.fixture
def prepared():
    return PreparedPlaceRequest(
        "reservation",
        NativeOrderIdentity("CTP", "order-ref", {"trading_day": "20261108", "front_id": 2}, 5),
        "IF2612",
        "20261108",
        5,
        {"RequestID": 42, "LimitPrice": 100.25.hex(), "Flag": True},
        ("place-key",),
        {"schema": "ctp-place-source-v1", "login_request_id": 3},
    )


def marker(prepared, **changes):
    args = {
        "operation": WriteOperation.PLACE,
        "host_scope": "scope",
        "exchange_name": "CTP",
        "symbol": "IF2612",
        "identity": prepared.identity,
        "target_identity": None,
        "request_summary": {},
        "trading_day": "20261108",
        "session_generation": 5,
        "created_at_utc": "2026-11-08T00:00:00Z",
        "prepared_place": prepared,
    }
    args.update(changes)
    return PreDispatchRecord(**args)


def test_copy_seal_mapping_and_digest(prepared):
    mapping = prepared.to_mapping()
    assert mapping["schema_version"] == 1
    assert PreparedPlaceRequest.from_mapping(mapping) == prepared
    assert PreparedPlaceRequest.from_mapping(mapping).digest() == prepared.digest()
    mapping["request_fields"]["RequestID"] = 1
    mapping["source_binding"]["schema"] = "changed"
    mapping["identity"]["fields"]["front_id"] = 9
    assert prepared.request_fields["RequestID"] == 42
    assert prepared.source_binding["schema"] == "ctp-place-source-v1"
    assert prepared.identity.fields["front_id"] == 2
    with pytest.raises(TypeError):
        prepared.source_binding["schema"] = "bad"
    with pytest.raises(FrozenInstanceError):
        prepared.symbol = "other"
    with pytest.raises(TypeError):
        hash(prepared)


@pytest.mark.parametrize(
    "change",
    [
        {"identity": NativeOrderIdentity("CTP", "ref", {"trading_day": "20261107"}, 5)},
        {"identity": NativeOrderIdentity("CTP", "ref", {"trading_day": "20261108"}, 6)},
        {
            "identity": NativeOrderIdentity(
                "CTP", "ref", {"trading_day": "20261108", "symbol": "other"}, 5
            )
        },
        {"identity": NativeOrderIdentity("CTP", "ref", {}, 5)},
        {"reservation_id": ""},
        {"trading_day": "20260229"},
        {"session_generation": True},
        {"request_fields": {"Price": 1.0}},
        {"request_fields": {"Price": 2**63}},
        {"request_fields": {"bad key": 1}},
        {"source_binding": {}},
        {"source_binding": None},
        {"source_binding": {"bad key": 1}},
        {"request_keys": ()},
        {"request_keys": ("z", "a")},
        {"request_keys": ("a", "a")},
        {"request_keys": ["a"]},
    ],
)
def test_reject_invalid_fields(prepared, change):
    with pytest.raises(PreparedPlaceError):
        replace(prepared, **change)


def test_strict_mapping_and_tamper_detection(prepared):
    for key in prepared.to_mapping():
        raw = prepared.to_mapping()
        del raw[key]
        with pytest.raises(PreparedPlaceError):
            PreparedPlaceRequest.from_mapping(raw)
    for key, value in (
        ("schema_version", True),
        ("schema_version", 2),
        ("extra", 1),
        ("request_keys", ("place-key",)),
        ("source_binding", []),
    ):
        raw = prepared.to_mapping()
        raw[key] = value
        with pytest.raises(PreparedPlaceError):
            PreparedPlaceRequest.from_mapping(raw)
    other = PreparedPlaceRequest.from_mapping(prepared.to_mapping())
    object.__setattr__(prepared, "symbol", "other")
    for operation in (prepared.to_mapping, prepared.digest, lambda: prepared == other):
        with pytest.raises(PreparedPlaceError):
            operation()


def test_canonical_equality_distinguishes_bool_and_integer(prepared):
    for field in ("request_fields", "source_binding"):
        first = replace(prepared, **{field: {"value": True}})
        second = replace(prepared, **{field: {"value": 1}})
        assert first != second
        assert first.digest() != second.digest()


def test_marker_revalidates_all_bindings_and_old_shape(prepared):
    bound = marker(prepared)
    assert bound.to_dict()["prepared_place"] == prepared.to_mapping()
    assert "prepared_place" not in replace(bound, prepared_place=None).to_dict()
    for changes in (
        {"operation": WriteOperation.CANCEL},
        {"exchange_name": "other"},
        {"symbol": "other"},
        {"trading_day": "20261107"},
        {"session_generation": True},
        {"target_identity": prepared.identity},
        {"identity": NativeOrderIdentity("CTP", "other", {"trading_day": "20261108"}, 5)},
    ):
        with pytest.raises(ValueError):
            marker(prepared, **changes)
    object.__setattr__(prepared, "symbol", "other")
    with pytest.raises(PreparedPlaceError):
        bound.to_dict()
