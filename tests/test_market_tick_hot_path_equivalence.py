"""R2-A (iteration 60): the market tick hot path keeps the 62fcb89 semantics.

``MarketTickPayload.from_dict`` now validates through one shared normalizer
and installs the result without the dataclass constructor; ``bind`` assembles
the bound objects directly; text/date/enum checks memoize positive results;
the instrument key of the last tick is reused. These randomized differential
tests compare every outcome (normalized values and their types, or the error
type and code) with a frozen copy of the previous module.
"""

from __future__ import annotations

import dataclasses
import math
import random
from collections.abc import Mapping
from types import MappingProxyType

import pytest
from r2a_reference import market_tick_protocol_62fcb89 as ref

from bt_api_base import market_tick_protocol as new
from bt_api_base.market_protocol import (
    MarketInstrumentKey,
    MarketSourceDescriptor,
    MarketSubscriptionKey,
)

INSTRUMENT = MarketInstrumentKey(
    provider="ctp",
    venue="CZCE",
    environment="simulation",
    product_type="future",
    instrument_id="SA609",
    native_symbol="SA609",
)
KEY = MarketSubscriptionKey(
    source_ref="ctp.md.front",
    entitlement_ref="test-entitlement",
    instrument=INSTRUMENT,
    channel="tick",
)
SOURCE = MarketSourceDescriptor(
    key=KEY,
    stream_id=KEY.stream_id,
    epoch="epoch-1",
    provider="ctp",
    source="ctp.native.md",
    connection_generation=1,
    clock_domain_id="clock-domain-1",
    clock_source_session_id="clock-session-1",
    clock_source="ctp.exchange",
)


def _valid_raw(sequence: int = 1) -> dict:
    return {
        "schema": "sdk.market.tick",
        "schema_version": 2,
        "instrument": INSTRUMENT.to_dict(),
        "last_price": 1500.0,
        "bid_price": 1499.0,
        "ask_price": 1501.0,
        "bid_size": 10.0,
        "ask_size": 12.0,
        "lower_limit": 1400.0,
        "upper_limit": 1600.0,
        "turnover": 1.0e8,
        "open_interest": 5000.0,
        "delta_volume": 3.0,
        "cumulative_volume": 12345.0,
        "volume_complete": True,
        "volume_quality": "CONTINUOUS",
        "continuity_status": "continuous",
        "trading_date": "2026-11-02",
        "event_session_date": "2026-11-02",
        "provider_event_time_utc": "2026-11-02T02:00:00.500000Z",
        "event_time_provenance": "provider_reported",
        "received_at_utc": "2026-11-02T02:00:00.600000Z",
        "received_monotonic_ns": 123456789,
        "provider_source": "ctp.native.md",
        "quality_contract_ref": "rules-1",
        "provider_connection_generation": 1,
        "provider_sequence": sequence,
        "provider_subscription_epoch": 1,
        "clock_domain_id": "clock-domain-1",
        "clock_source_session_id": "clock-session-1",
        "clock_source": "ctp.exchange",
        "source_clock_quality": "verified",
        "receive_clock_quality": "verified",
        "source_clock_error_ms": 0.5,
        "receive_clock_error_ms": 0.25,
        "freshness_status": "fresh",
        "freshness_reason_codes": [],
        "execution_eligible": True,
        "quality_flags": [],
    }


class _StrSub(str):
    pass


class _OddMapping(Mapping):
    def __init__(self, data):
        self._data = dict(data)

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)


_VALUE_POOL = (
    None,
    0,
    1,
    -1,
    2,
    10**400,
    True,
    False,
    0.0,
    -0.0,
    -1.5,
    1500.0,
    math.nan,
    math.inf,
    -math.inf,
    "",
    " x",
    "x ",
    "ok",
    "verified",
    "unknown",
    "fresh",
    "stale",
    "unavailable",
    "provider_reported",
    "\x00",
    "\ud800",
    "été",
    "x" * 5000,
    _StrSub("verified"),
    _StrSub("CONTINUOUS"),
    "2026-11-02",
    "2026-13-01",
    "2026-11-02T02:00:00Z",
    "2026-11-02T10:00:00+08:00",
    "2026-11-02T02:00:00",
    "2026-11-02T02:00:00.123Z",
    "not-a-time",
    [],
    ["A"],
    [""],
    [1],
    ("GENERIC_EVENT_TIME_NOT_BOUND",),
    {},
    MappingProxyType({}),
    INSTRUMENT.to_dict(),
)


def _mutate(rng: random.Random, raw: dict) -> object:
    raw = dict(raw)
    for _ in range(rng.choice((1, 1, 1, 2, 3))):
        action = rng.random()
        if action < 0.8:
            raw[rng.choice(sorted(raw))] = rng.choice(_VALUE_POOL)
        elif action < 0.87:
            del raw[rng.choice(sorted(raw))]
        elif action < 0.92:
            raw["extra"] = 1
        else:
            instrument = dict(INSTRUMENT.to_dict())
            instrument[rng.choice(sorted(instrument))] = rng.choice(_VALUE_POOL)
            raw["instrument"] = instrument
    container = rng.random()
    if container < 0.4:
        return MappingProxyType(
            {
                key: (
                    tuple(value)
                    if type(value) is list
                    else MappingProxyType(value) if type(value) is dict else value
                )
                for key, value in raw.items()
            }
        )
    if container < 0.45:
        return _OddMapping(raw)
    if container < 0.48:
        return list(raw.items())
    return raw


def _outcome(module, raw):
    try:
        payload = module.MarketTickPayload.from_dict(raw)
    except Exception as exc:  # noqa: BLE001 -- the oracle compares any failure
        return ("error", type(exc).__name__, getattr(exc, "code", None))
    values = []
    for field in dataclasses.fields(payload):
        value = getattr(payload, field.name)
        kind = type(value)
        if isinstance(value, (ref.MarketClockQuality, ref.MarketFreshnessStatus)):
            value, kind = value.value, "enum:" + type(value).__name__
        elif isinstance(value, (new.MarketClockQuality, new.MarketFreshnessStatus)):
            value, kind = value.value, "enum:" + type(value).__name__
        else:
            kind = kind.__name__
        if type(value) is float and math.isnan(value):
            value = "nan"
        values.append((field.name, kind, value))
    return ("ok", tuple(values))


def test_from_dict_matches_the_previous_implementation_on_randomized_inputs() -> None:
    rng = random.Random(20261104)
    seen_ok = seen_error = 0
    for index in range(6000):
        raw = _mutate(rng, _valid_raw(index + 1)) if index % 7 else _valid_raw(index + 1)
        expected = _outcome(ref, raw)
        actual = _outcome(new, raw)
        assert actual == expected, (index, raw)
        if expected[0] == "ok":
            seen_ok += 1
        else:
            seen_error += 1
    assert seen_ok > 500 and seen_error > 2000


def test_from_dict_interleaved_caches_never_change_an_outcome() -> None:
    """Memo hits after a valid tick must not accept a later invalid variant."""

    rng = random.Random(7)
    valid = _valid_raw()
    for index in range(3000):
        raw = valid if index % 2 == 0 else _mutate(rng, valid)
        assert _outcome(new, raw) == _outcome(ref, raw), (index, raw)
    # Equal-valued but non-exact str values in the cached instrument are refused.
    assert _outcome(new, valid)[0] == "ok"
    instrument = dict(INSTRUMENT.to_dict())
    instrument["venue"] = _StrSub(instrument["venue"])
    sneaky = dict(valid, instrument=instrument)
    assert _outcome(new, sneaky) == _outcome(ref, sneaky)
    assert _outcome(new, sneaky)[0] == "error"
    sneaky_text = dict(valid, volume_quality=_StrSub("CONTINUOUS"))
    assert _outcome(new, sneaky_text) == _outcome(ref, sneaky_text) == (
        "error",
        "MarketTickContractError",
        "MARKET_TICK_VALUE_INVALID",
    )


def test_direct_construction_matches_the_previous_implementation() -> None:
    rng = random.Random(99)
    names = [field.name for field in dataclasses.fields(new.MarketTickPayload)]
    for index in range(3000):
        raw = _valid_raw(index + 1)
        values = {name: raw[name] for name in names if name != "instrument"}
        for _ in range(rng.choice((0, 1, 2))):
            values[rng.choice(sorted(values))] = rng.choice(_VALUE_POOL)

        def build(module):
            try:
                payload = module.MarketTickPayload(instrument=INSTRUMENT, **values)
            except Exception as exc:  # noqa: BLE001
                return ("error", type(exc).__name__, getattr(exc, "code", None))
            return ("ok", _outcome(module, payload.to_dict()))

        assert build(new) == build(ref), (index, values)


def test_subclass_keeps_the_constructor_path() -> None:
    calls = []

    class Recording(new.MarketTickPayload):
        def __post_init__(self) -> None:
            calls.append(True)
            super().__post_init__()

    payload = Recording.from_dict(_valid_raw())
    assert type(payload) is Recording and calls == [True]


def _cursor(module, sequence):
    return module.MarketEventCursor(stream_id=SOURCE.stream_id, epoch=SOURCE.epoch, sequence=sequence)


def test_bind_equals_constructor_built_event_and_previous_bind() -> None:
    rng = random.Random(5)
    for index in range(2000):
        raw = _valid_raw(index + 1)
        if index % 3:
            raw = dict(raw)
            raw["freshness_status"] = rng.choice(("fresh", "stale", "unavailable"))
            raw["freshness_reason_codes"] = rng.choice(([], ["A"], ["A", "B"]))
            raw["source_clock_quality"] = rng.choice(("verified", "unknown"))
            raw["execution_eligible"] = rng.choice((True, False))
            raw["provider_event_time_utc"] = rng.choice(
                ("2026-11-02T10:00:00.5+08:00", "2026-11-02T02:00:00Z")
            )
        expected = _outcome(ref, raw)
        if expected[0] != "ok":
            assert _outcome(new, raw) == expected
            continue
        payload = new.MarketTickPayload.from_dict(raw)
        cursor = _cursor(new, index + 1)
        event = new.bind_market_tick_event(payload, SOURCE, cursor)
        constructed = new.MarketTickEvent(
            source=SOURCE,
            cursor=cursor,
            data=payload,
            clock=new.DataClockBinding(
                source=SOURCE,
                cursor=cursor,
                provider_event_time_utc=payload.provider_event_time_utc,
                received_at_utc=payload.received_at_utc,
                received_monotonic_ns=payload.received_monotonic_ns,
                source_clock_quality=payload.source_clock_quality,
                receive_clock_quality=payload.receive_clock_quality,
                source_clock_error_ms=payload.source_clock_error_ms,
                receive_clock_error_ms=payload.receive_clock_error_ms,
                freshness_status=payload.freshness_status,
                freshness_reason_codes=payload.freshness_reason_codes,
            ),
        )
        assert event == constructed
        assert hash(event) == hash(constructed)
        assert type(event.clock) is new.DataClockBinding
        for field in dataclasses.fields(new.DataClockBinding):
            assert type(getattr(event.clock, field.name)) is type(
                getattr(constructed.clock, field.name)
            )
        old_event = ref.bind_market_tick_event(
            ref.MarketTickPayload.from_dict(raw), SOURCE, _cursor(ref, index + 1)
        )
        assert old_event.clock.provider_event_time_utc == event.clock.provider_event_time_utc
        assert old_event.clock.freshness_reason_codes == event.clock.freshness_reason_codes
        assert event.data_clock_qualified == old_event.data_clock_qualified
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.data = payload  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.clock.received_at_utc = None  # type: ignore[misc]


def test_bind_rejections_are_unchanged() -> None:
    payload = new.MarketTickPayload.from_dict(_valid_raw())
    old_payload = ref.MarketTickPayload.from_dict(_valid_raw())
    other_epoch = dataclasses.replace(SOURCE, epoch="epoch-2")
    other_source = dataclasses.replace(SOURCE, source="other")
    cases = (
        (SOURCE, lambda m: m.MarketEventCursor(stream_id=SOURCE.stream_id, epoch="x", sequence=1)),
        (other_epoch, lambda m: _cursor(m, 1)),
        (other_source, lambda m: _cursor(m, 1)),
        ("not-a-source", lambda m: _cursor(m, 1)),
        (SOURCE, lambda m: "not-a-cursor"),
    )
    for source, cursor in cases:
        outcomes = []
        for module, data in ((new, payload), (ref, old_payload)):
            with pytest.raises(Exception) as caught:
                module.bind_market_tick_event(data, source, cursor(module))
            outcomes.append((type(caught.value).__name__, caught.value.code))
        assert outcomes[0] == outcomes[1]
    with pytest.raises(new.MarketTickContractError):
        new.bind_market_tick_event(old_payload, SOURCE, _cursor(new, 1))


def test_text_memo_is_bounded_and_refuses_subclasses() -> None:
    new._TEXT_OK.clear()
    for index in range(new._MEMO_LIMIT + 10):
        new._text(f"value-{index}", "field")
    assert len(new._TEXT_OK) <= new._MEMO_LIMIT
    new._text("CONTINUOUS", "field")
    with pytest.raises(new.MarketTickContractError):
        new._text(_StrSub("CONTINUOUS"), "field")
    # Unique per-tick timestamps do not enter the text memo.
    before = set(new._TEXT_OK)
    new._utc_text("2026-11-02T02:00:00.777777Z", "t")
    assert new._TEXT_OK == before
