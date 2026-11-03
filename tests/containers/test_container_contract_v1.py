"""Container contract v1 (iteration 60, step 60.02).

Covers thread-safe initialization, the publication (freeze) flag, the
fingerprint helper used to verify read-only consumption, the shared semantic
vocabulary and the "unknown" defaults of the TickerData semantic getters.
"""

from __future__ import annotations

import threading
import time

import pytest

from bt_api_base.containers.auto_init_mixin import AutoInitMixin, container_fingerprint
from bt_api_base.containers.semantics import (
    CONTAINER_CONTRACT_VERSION,
    VOLUME_SEMANTICS,
    VOLUME_UNKNOWN,
    normalize_position_side,
)
from bt_api_base.containers.tickers.ticker import TickerData


class _SlowContainer(AutoInitMixin):
    """init_data() sleeps between field writes to expose half-initialized reads."""

    calls = 0

    def __init__(self):
        self.a = None
        self.b = None

    def init_data(self):
        type(self).calls += 1
        self.a = 1
        time.sleep(0.05)
        self.b = 2
        # Re-entrant accessor call during init must not deadlock or recurse.
        assert self.get_a() == 1

    def get_a(self):
        return self.a

    def get_pair(self):
        return (self.a, self.b)


def test_concurrent_first_access_sees_fully_initialized_container():
    _SlowContainer.calls = 0
    container = _SlowContainer()
    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(container.get_pair())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [(1, 2)] * 8
    assert _SlowContainer.calls == 1


def test_failed_init_is_retried_on_next_access():
    class _Flaky(AutoInitMixin):
        def __init__(self):
            self.attempts = 0
            self.value = None

        def init_data(self):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("transient")
            self.value = 5

        def get_value(self):
            return self.value

    container = _Flaky()
    with pytest.raises(RuntimeError):
        container.get_value()
    assert container.get_value() == 5
    assert container.attempts == 2


def test_freeze_initializes_and_marks_published():
    _SlowContainer.calls = 0
    container = _SlowContainer()
    assert container.is_frozen() is False
    assert container.freeze() is container
    assert container.is_frozen() is True
    assert (container.a, container.b) == (1, 2)
    assert _SlowContainer.calls == 1


def test_fingerprint_detects_consumer_mutation():
    container = _SlowContainer()
    before = container_fingerprint(container)
    container.b = 99  # still being built: writes are allowed
    assert container_fingerprint(container) != before
    container.freeze()
    before = container_fingerprint(container)
    container.get_pair()
    assert container_fingerprint(container) == before


# -- acceptance report 2026-11-03 F1: published means read-only -------------------


class _Payload(AutoInitMixin):
    def __init__(self, raw):
        self.raw = raw
        self.levels = [1, 2]
        self.tags = {"a"}
        self.price_val = None
        self.all_data = None

    def init_data(self):
        self.price_val = self.raw["price"]

    def get_price(self):
        return self.price_val

    def get_raw(self):
        return self.raw

    def get_all_data(self):
        if self.all_data is None:
            self.all_data = {"price": self.price_val, "raw": self.raw}
        return self.all_data


def test_frozen_container_rejects_attribute_writes_and_deletes():
    from bt_api_base.containers.auto_init_mixin import FrozenContainerError

    container = _Payload({"price": 1500}).freeze()
    with pytest.raises(FrozenContainerError):
        container.price_val = 42  # the report's reproduction
    with pytest.raises(FrozenContainerError):
        del container.price_val
    with pytest.raises(FrozenContainerError):
        container.new_attribute = 1
    assert container.get_price() == 1500 and container.is_frozen()


def test_frozen_container_detaches_existing_instance_dict_and_exposes_read_only_view():
    from bt_api_base.containers.auto_init_mixin import FrozenContainerError

    container = _Payload({"price": 1500})
    previous_state = container.__dict__
    container.freeze()
    previous_state["price_val"] = 42
    previous_state["_initialized"] = False
    assert container.get_price() == 1500
    assert container.is_frozen()
    with pytest.raises(TypeError):
        container.__dict__["price_val"] = 43
    with pytest.raises(TypeError):
        vars(container)["price_val"] = 44
    with pytest.raises(FrozenContainerError):
        container.__dict__ = {"price_val": 45}
    with pytest.raises(FrozenContainerError):
        container.all_data = {"price": 46}


def test_cyclic_nested_state_refuses_to_freeze_without_partial_publication():
    from bt_api_base.containers.auto_init_mixin import FrozenContainerError

    raw = {"price": 1500}
    raw["cycle"] = raw
    container = _Payload(raw)
    original_state = container.__dict__
    with pytest.raises(FrozenContainerError, match="nesting"):
        container.freeze()
    assert container.__dict__ is original_state
    assert not container.is_frozen()
    assert container.get_price() == 1500


def test_freeze_snapshots_bytearrays_and_builtin_container_subclasses():
    class PayloadDict(dict):
        pass

    class PayloadList(list):
        pass

    values = bytearray(b"ok")
    raw = PayloadDict(price=1500, nested=PayloadList([values]))
    container = _Payload(raw).freeze()
    values[0] = ord("X")
    raw["nested"].append(9)
    assert container.get_raw()["nested"] == (b"ok",)


def test_freeze_rejects_unrecognized_public_objects_without_partial_publication():
    from bt_api_base.containers.auto_init_mixin import FrozenContainerError

    class Mutable:
        pass

    raw = {"price": 1500, "nested": Mutable()}
    container = _Payload(raw)
    with pytest.raises(FrozenContainerError, match="unsupported"):
        container.freeze()
    assert container.get_raw() is raw
    assert not container.is_frozen()


def test_frozen_container_detaches_and_locks_nested_values():
    raw = {"price": 1500, "book": {"bids": [1, 2]}}
    container = _Payload(raw).freeze()
    raw["price"] = 1  # the producer's dict no longer reaches the container
    raw["book"]["bids"].append(3)
    assert container.get_raw()["price"] == 1500
    assert tuple(container.get_raw()["book"]["bids"]) == (1, 2)
    with pytest.raises(TypeError):
        container.get_raw()["price"] = 2
    with pytest.raises(AttributeError):
        container.levels.append(3)
    with pytest.raises(AttributeError):
        container.tags.add("b")


def test_get_all_data_memoizes_once_and_returns_private_plain_copies():
    import json

    container = _Payload({"price": 1500, "book": {"bids": [1]}}).freeze()
    first = container.get_all_data()
    assert type(first) is dict and type(first["raw"]) is dict
    first["price"] = "corrupted"
    first["raw"]["book"]["bids"].append(9)
    second = container.get_all_data()
    assert second == {"price": 1500, "raw": {"price": 1500, "book": {"bids": [1]}}}
    json.dumps(second)  # still serializable
    from bt_api_base.containers.auto_init_mixin import FrozenContainerError

    with pytest.raises(FrozenContainerError):
        container.all_data = {"forged": True}  # the cache is set only once


def test_container_class_is_stable_and_cannot_be_forged():
    from bt_api_base.containers.auto_init_mixin import container_class

    container = _Payload({"price": 1})
    assert container_class(container) is _Payload
    container.freeze()
    assert type(container) is not _Payload and isinstance(container, _Payload)
    assert container_class(container) is _Payload and type(container).__name__ == "_Payload"

    class _Forged(_Payload):
        _frozen_variant_of = _Payload

    assert container_class(_Forged({"price": 1})) is _Forged


def test_frozen_container_survives_pickle_and_deepcopy_read_only():
    import copy
    import pickle

    from bt_api_base.containers.auto_init_mixin import FrozenContainerError

    container = _Payload({"price": 7, "book": {"bids": [1]}}).freeze()
    for clone in (pickle.loads(pickle.dumps(container)), copy.deepcopy(container)):
        assert clone.get_price() == 7 and clone.is_frozen()
        assert type(clone) is type(container)
        with pytest.raises(FrozenContainerError):
            clone.price_val = 1


def test_freeze_is_idempotent_and_safe_concurrently():
    container = _Payload({"price": 3})
    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(container.freeze())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(item is container for item in results) and container.get_price() == 3


def test_semantic_vocabulary():
    assert CONTAINER_CONTRACT_VERSION.endswith(".containers.v1")
    expected = {"delta", "cumulative", "last_trade", "rolling_24h", "unknown"}
    assert set(VOLUME_SEMANTICS) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("long", "long"),
        ("LONG", "long"),
        ("Buy", "long"),
        ("short", "short"),
        ("SELL", "short"),
        ("net", "net"),
        ("BOTH", "net"),
        ("", None),
        ("sideways", None),
        (None, None),
        (2, None),
    ],
)
def test_normalize_position_side(raw, expected):
    assert normalize_position_side(raw) == expected


class _MinimalTicker(TickerData):
    def init_data(self):
        return self


def test_ticker_semantic_getters_default_to_unknown():
    ticker = _MinimalTicker({})
    assert ticker.get_volume_semantics() == VOLUME_UNKNOWN
    assert ticker.get_cumulative_volume() is None
    assert ticker.get_delta_volume() is None
    assert ticker.get_volume_complete() is None
    assert ticker.get_continuity_status() is None
    assert ticker.get_execution_eligible() is None
    assert ticker.get_quality_flags() == ()
    assert ticker.get_event_time_source() is None
