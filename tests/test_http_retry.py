"""HTTP 重试（429/Retry-After）测试。"""

from __future__ import annotations

import bt_api_base.feeds.feed as feed_module
from bt_api_base.error import UnifiedRateLimitError
from bt_api_base.feeds.feed import Feed


def test_http_client_429_sets_retry_after() -> None:
    """429 响应应读取 Retry-After 头并设置到 UnifiedRateLimitError.retry_after。"""
    from bt_api_base.feeds.http_client import HttpClient

    client = HttpClient(venue="TEST")

    class FakeResponse:
        status_code = 429
        headers = {"Retry-After": "2"}

        def json(self):
            return {"code": 429}

    err = client._handle_error(FakeResponse())
    assert isinstance(err, UnifiedRateLimitError)
    assert err.retry_after == 2.0


def test_http_request_uses_retry_after_for_429(monkeypatch) -> None:
    """429 重试应按 Retry-After 等待，而非固定指数退避。"""
    feed = Feed(exchange_name="TEST")
    calls = []
    sleep_args = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            err = UnifiedRateLimitError(venue="TEST", response={"code": 429})
            err.retry_after = 1.5
            raise err
        return {"ok": True}

    monkeypatch.setattr(feed._http_client, "request", fake_request)
    monkeypatch.setattr(feed_module._time, "sleep", lambda s: sleep_args.append(s))

    result = feed.http_request("GET", "https://example.com/api")

    assert result == {"ok": True}
    assert len(calls) == 2  # 第一次 429，第二次成功
    assert sleep_args == [1.5]  # 按 Retry-After 等待
