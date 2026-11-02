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
    container = _SlowContainer().freeze()
    before = container_fingerprint(container)
    container.get_pair()
    assert container_fingerprint(container) == before
    container.b = 99
    assert container_fingerprint(container) != before


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
