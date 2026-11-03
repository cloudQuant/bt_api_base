"""Freeze dispatch keeps the previous value and error contract."""

import math
import random
from types import MappingProxyType

import pytest

from bt_api_base import service_protocol as protocol


def _prior_freeze(value, *, depth):
    """Original validation order, retained as an independent test oracle."""
    if depth > protocol.MAX_JSON_DEPTH:
        protocol._fail(protocol.WireErrorCode.INVALID_VALUE, protocol.WireField.PAYLOAD)
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            protocol._fail(protocol.WireErrorCode.NON_FINITE_NUMBER, protocol.WireField.PAYLOAD)
        return value
    if type(value) is str:
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            protocol._fail(protocol.WireErrorCode.INVALID_VALUE, protocol.WireField.PAYLOAD)
        return value
    if type(value) in (dict, MappingProxyType):
        frozen = {}
        for key, item in value.items():
            if type(key) is not str:
                protocol._fail(protocol.WireErrorCode.INVALID_TYPE, protocol.WireField.PAYLOAD)
            try:
                key.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                protocol._fail(protocol.WireErrorCode.INVALID_VALUE, protocol.WireField.PAYLOAD)
            frozen[key] = _prior_freeze(item, depth=depth + 1)
        return MappingProxyType(frozen)
    if type(value) in (list, tuple):
        return tuple(_prior_freeze(item, depth=depth + 1) for item in value)
    protocol._fail(protocol.WireErrorCode.INVALID_TYPE, protocol.WireField.PAYLOAD)


def _outcome(fn, value, depth=0):
    try:
        return ("ok", fn(value, depth=depth))
    except protocol.WireValidationError as exc:
        return ("error", exc.code, exc.field)


def _sample(rng, depth=0):
    scalars = [None, False, True, 0, -123, 2**100, 1.5, float("nan"), float("inf"),
               "", "ascii\x00\x7f", "é", "持仓", "\ud800", b"bytes", object()]
    if depth >= 4 or rng.randrange(4) == 0:
        return rng.choice(scalars)
    children = [_sample(rng, depth + 1) for _ in range(rng.randrange(4))]
    choice = rng.randrange(4)
    if choice == 0:
        return children
    if choice == 1:
        return tuple(children)
    keys = ["ascii", "é", "持仓", "\ud800", 123]
    result = {rng.choice(keys): child for child in children}
    return result if choice == 2 else MappingProxyType(result)


def test_freeze_matches_original_contract_for_random_and_adversarial_values():
    rng = random.Random(601103)
    for _ in range(1500):
        payload = _sample(rng)
        assert _outcome(protocol._freeze_json_value, payload) == _outcome(_prior_freeze, payload)


@pytest.mark.parametrize("depth", [0, protocol.MAX_JSON_DEPTH, protocol.MAX_JSON_DEPTH + 1])
@pytest.mark.parametrize("payload", ["ascii", "é", "\udfff", {"x": 1}, {"\udfff": 1}, {1: 1}])
def test_freeze_matches_original_depth_utf8_and_error_order(depth, payload):
    assert _outcome(protocol._freeze_json_value, payload, depth) == _outcome(_prior_freeze, payload, depth)


def test_freeze_retains_detached_nested_mappings():
    source = {"ascii": {"é": [1, "持仓"]}}
    frozen = protocol._freeze_json_value(source, depth=0)
    source["ascii"]["é"].append(2)
    assert frozen["ascii"]["é"] == (1, "持仓")
    with pytest.raises(TypeError):
        frozen["ascii"]["new"] = 3


def test_freeze_preserves_error_order_for_cycles_and_multiple_invalid_values():
    cyclic = []
    cyclic.append(cyclic)

    class TextSubclass(str):
        pass

    cases = [
        cyclic,
        {"first": float("nan"), "\ud800": b"invalid"},
        {"\ud800": float("nan"), 1: b"invalid"},
        {"first": b"invalid", TextSubclass("later"): None},
        {TextSubclass("first"): None, "later": float("inf")},
        {"value": TextSubclass("ascii")},
    ]
    for payload in cases:
        assert _outcome(protocol._freeze_json_value, payload) == _outcome(_prior_freeze, payload)
