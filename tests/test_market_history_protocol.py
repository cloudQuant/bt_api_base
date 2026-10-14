"""Focused tests for fixed-duration, bounded historical market bars."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bt_api_base.market_history_protocol import (
    MAX_MARKET_HISTORY_PAGE_BYTES,
    MarketBar,
    MarketHistoryPage,
    MarketHistoryRequest,
)
from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey

_START = "2026-10-13T04:00:00Z"
_END = "2026-10-13T04:10:00Z"
_OBSERVED = "2026-10-13T04:10:00Z"


def _key(**updates: object) -> MarketSubscriptionKey:
    values: dict[str, object] = {
        "source_ref": "market-source-a",
        "entitlement_ref": "history-entitlement",
        "instrument": MarketInstrumentKey(
            provider="alpha",
            venue="alpha-futures",
            environment="paper",
            product_type="linear-perpetual",
            instrument_id="BTC-USD-PERP",
            native_symbol="BTCUSD_PERP",
        ),
        "channel": "bar",
        "depth": None,
        "timeframe": "1m",
    }
    values.update(updates)
    return MarketSubscriptionKey(**values)  # type: ignore[arg-type]


def _request(**updates: object) -> MarketHistoryRequest:
    values: dict[str, object] = {
        "key": _key(),
        "start_time_utc": _START,
        "end_time_utc": _END,
        "limit": 100,
    }
    values.update(updates)
    return MarketHistoryRequest(**values)  # type: ignore[arg-type]


def _bar(
    opened: str = _START,
    closed: str = "2026-10-13T04:01:00Z",
    **updates: object,
) -> MarketBar:
    values: dict[str, object] = {
        "open_time_utc": opened,
        "close_time_utc": closed,
        "open": "100.00",
        "high": "110.00",
        "low": "90.00",
        "close": "105.00",
        "volume": "12.500",
        "open_interest": "450.0",
    }
    values.update(updates)
    return MarketBar(**values)  # type: ignore[arg-type]


def _page(**updates: object) -> MarketHistoryPage:
    values: dict[str, object] = {
        "request": _request(),
        "bars": (_bar(),),
        "complete": True,
        "next_start_time_utc": None,
        "observed_at_utc": _OBSERVED,
    }
    values.update(updates)
    return MarketHistoryPage(**values)  # type: ignore[arg-type]


def test_bar_request_page_round_trip_and_hashing() -> None:
    bar = _bar()
    request = _request()
    page = _page()

    assert MarketBar.from_dict(json.loads(json.dumps(bar.to_dict()))) == bar
    assert MarketHistoryRequest.from_dict(json.loads(json.dumps(request.to_dict()))) == request
    restored = MarketHistoryPage.from_dict(json.loads(json.dumps(page.to_dict())))
    assert restored == page
    assert hash(restored) == hash(page)
    assert restored.bars[0].volume == "12.500"
    assert restored.bars[0].open_interest == "450.0"
    assert request.bar_duration_seconds == 60

    with pytest.raises(FrozenInstanceError):
        bar.close = "99"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        request.limit = 1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        page.complete = False  # type: ignore[misc]


@pytest.mark.parametrize(
    "timeframe",
    [None, "0m", "01m", "1M", "1mo", "1ms", "1.5m", "-1m", "m1", "1month"],
)
def test_request_rejects_non_fixed_or_noncanonical_timeframes(timeframe: str | None) -> None:
    with pytest.raises(ValueError):
        _request(key=_key(timeframe=timeframe))


@pytest.mark.parametrize(
    "timeframe,seconds", [("1s", 1), ("5m", 300), ("2h", 7200), ("1d", 86400), ("1w", 604800)]
)
def test_request_exposes_only_explicit_fixed_duration_units(timeframe: str, seconds: int) -> None:
    request = _request(key=_key(timeframe=timeframe))
    assert request.bar_duration_seconds == seconds


@pytest.mark.parametrize("channel", ["ticker", "orderbook", "public_trade"])
def test_request_requires_bar_channel(channel: str) -> None:
    with pytest.raises(ValueError):
        _request(key=_key(channel=channel))


@pytest.mark.parametrize("limit", [True, False, 0, -1, 1001, 1.0, "10"])
def test_request_limit_is_bounded_exact_integer(limit: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _request(limit=limit)


def test_request_uses_explicit_utc_half_open_interval() -> None:
    assert _request(start_time_utc=_START, end_time_utc=_END).start_time_utc == _START
    with pytest.raises(ValueError):
        _request(start_time_utc=_END, end_time_utc=_END)
    with pytest.raises(ValueError):
        _request(start_time_utc=_END, end_time_utc=_START)
    with pytest.raises(ValueError):
        _request(start_time_utc="2026-10-13T04:00:00+00:00")


@pytest.mark.parametrize(
    "field,value",
    [
        ("open", 100.0),
        ("high", "NaN"),
        ("low", "Infinity"),
        ("close", "1e3"),
        ("volume", "-0.01"),
        ("volume", 1),
        ("open_interest", "-1"),
    ],
)
def test_bar_rejects_invalid_decimal_and_negative_volume_fields(field: str, value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _bar(**{field: value})


def test_bar_validates_ohlc_envelope_but_allows_negative_prices() -> None:
    negative_market = _bar(
        open="-5",
        high="-3",
        low="-8",
        close="-4",
        volume="0",
        open_interest=None,
    )
    assert negative_market.open == "-5"
    with pytest.raises(ValueError):
        _bar(high="99")
    with pytest.raises(ValueError):
        _bar(low="101")


def test_bar_requires_valid_closed_utc_interval() -> None:
    with pytest.raises(ValueError):
        _bar(closed=_START)
    with pytest.raises(ValueError):
        _bar(opened="2026-10-13T04:00:00", closed="2026-10-13T04:01:00Z")


def test_complete_means_interval_exhausted_and_no_trade_gaps_are_allowed() -> None:
    first = _bar()
    second = _bar(
        opened="2026-10-13T04:05:00Z",
        closed="2026-10-13T04:06:00Z",
    )
    page = _page(bars=(first, second), complete=True)
    empty_complete = _page(bars=(), complete=True)

    assert page.complete
    assert len(page.bars) == 2
    assert empty_complete.complete
    assert empty_complete.bars == ()


def test_incomplete_page_requires_advancing_exact_continuation() -> None:
    page = _page(
        complete=False,
        next_start_time_utc="2026-10-13T04:01:00.000Z",
    )
    assert not page.complete
    assert page.next_start_time_utc is not None

    with pytest.raises(ValueError):
        _page(complete=False, bars=(), next_start_time_utc="2026-10-13T04:01:00Z")
    with pytest.raises(ValueError):
        _page(complete=False, next_start_time_utc=None)
    with pytest.raises(ValueError):
        _page(complete=True, next_start_time_utc="2026-10-13T04:01:00Z")
    with pytest.raises(ValueError):
        _page(complete=False, next_start_time_utc="2026-10-13T04:02:00Z")
    with pytest.raises(ValueError):
        _page(complete=False, next_start_time_utc="2026-10-13T04:00:00Z")


def test_page_checks_end_observation_window_and_closed_bar_duration() -> None:
    # A bar closing exactly at the exclusive request endpoint is accepted as a closed interval.
    request = _request(end_time_utc="2026-10-13T04:01:00Z")
    at_end = _bar(closed="2026-10-13T04:01:00Z")
    assert _page(request=request, bars=(at_end,), observed_at_utc="2026-10-13T04:01:00Z")

    with pytest.raises(ValueError):
        _page(request=request, bars=(replace(at_end, open_time_utc="2026-10-13T03:59:00Z"),))
    with pytest.raises(ValueError):
        _page(observed_at_utc="2026-10-13T04:00:59Z")
    with pytest.raises(ValueError):
        _page(request=_request(end_time_utc="2026-10-13T04:11:00Z"))
    with pytest.raises(ValueError):
        _page(bars=(_bar(closed="2026-10-13T04:02:00Z"),))


def test_page_requires_sorted_unique_nonoverlapping_bars_but_allows_gaps() -> None:
    first = _bar()
    later = _bar(
        opened="2026-10-13T04:02:00Z",
        closed="2026-10-13T04:03:00Z",
    )
    assert _page(bars=(first, later)).bars == (first, later)

    duplicate = _bar()
    with pytest.raises(ValueError):
        _page(bars=(first, duplicate))
    overlap = _bar(
        opened="2026-10-13T04:00:30Z",
        closed="2026-10-13T04:01:30Z",
    )
    with pytest.raises(ValueError):
        _page(bars=(first, overlap))
    with pytest.raises(ValueError):
        _page(bars=(later, first))


def test_page_bars_must_match_requested_timeframe_and_limit() -> None:
    with pytest.raises(ValueError):
        _page(
            request=_request(limit=1),
            bars=(_bar(), _bar("2026-10-13T04:01:00Z", "2026-10-13T04:02:00Z")),
        )
    with pytest.raises(ValueError):
        _page(
            request=_request(key=_key(timeframe="5m")),
            bars=(_bar(),),
        )


def test_page_requires_plain_tuples_and_boolean_completion() -> None:
    with pytest.raises(TypeError):
        _page(bars=[_bar()])
    with pytest.raises(TypeError):
        _page(complete=1)


def test_from_dict_rejects_unknown_missing_and_numeric_json_fields() -> None:
    page = _page().to_dict()

    extra = {**page, "cursor": 10}
    with pytest.raises(ValueError):
        MarketHistoryPage.from_dict(extra)
    missing = dict(page)
    del missing["observed_at_utc"]
    with pytest.raises(ValueError):
        MarketHistoryPage.from_dict(missing)

    numeric_bar = json.loads(json.dumps(page))
    numeric_bar["bars"][0]["volume"] = 1.5
    with pytest.raises(TypeError):
        MarketHistoryPage.from_dict(numeric_bar)

    wrong_request = json.loads(json.dumps(page))
    wrong_request["request"]["key"]["channel"] = "ticker"
    with pytest.raises(ValueError):
        MarketHistoryPage.from_dict(wrong_request)


def test_page_message_size_is_bounded() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = tuple(
        _bar(
            opened=(start + timedelta(minutes=index)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            closed=(start + timedelta(minutes=index + 1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            open="9" * 128,
            high="9" * 128,
            low="9" * 128,
            close="9" * 128,
            volume="9" * 128,
            open_interest="9" * 128,
        )
        for index in range(1000)
    )
    end = (start + timedelta(minutes=1000)).strftime("%Y-%m-%dT%H:%M:%SZ")
    request = _request(
        start_time_utc=start.strftime("%Y-%m-%dT%H:%M:%SZ"), end_time_utc=end, limit=1000
    )
    with pytest.raises(ValueError, match="byte limit"):
        _page(
            request=request,
            bars=bars,
            observed_at_utc=end,
        )
    assert MAX_MARKET_HISTORY_PAGE_BYTES == 512 * 1024


def test_import_does_not_load_gateway_transport_or_zmq_modules() -> None:
    source_root = Path(__file__).parents[1] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(source_root), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    script = """
import importlib
import json
import sys

before = set(sys.modules)
importlib.import_module('bt_api_base.market_history_protocol')
added = set(sys.modules) - before
forbidden = sorted(
    name for name in added
    if name.startswith(('bt_api_gateway', 'bt_api_transport', 'zmq'))
)
print(json.dumps({'forbidden_modules': forbidden}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert json.loads(result.stdout)["forbidden_modules"] == []
