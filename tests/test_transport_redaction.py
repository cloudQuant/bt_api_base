"""Transport failures must never expose signed URLs or user-stream tokens."""

from __future__ import annotations

import asyncio
import logging
import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import websocket
from websocket import _app as websocket_app_module

import bt_api_base.feeds.http_client as http_client_module
from bt_api_base.exceptions import RequestError, RequestFailedError
from bt_api_base.feeds.feed import Feed
from bt_api_base.feeds.http_client import HttpClient
from bt_api_base.feeds.my_websocket_app import MyWebsocketApp
from bt_api_base.feeds.transport_safety import (
    sanitize_text,
    sanitize_url,
    sanitize_value,
)
from bt_api_base.logging_factory import _LoggerProxy

SIGNATURE = "signed-value-that-must-not-leak"
API_KEY = "api-key-that-must-not-leak"
PRIVATE_SECRET = "private-secret-that-must-not-leak"
LISTEN_KEY = "listen-key-that-must-not-leak"
TIMESTAMP = "1700000000123"
SIGNED_URL = (
    "https://demo-fapi.binance.com/fapi/v1/order?symbol=BTCUSDT"
    f"&timestamp={TIMESTAMP}&signature={SIGNATURE}"
)
HEADERS = {"X-MBX-APIKEY": API_KEY}


def _assert_secrets_absent(value) -> None:
    rendered = str(value)
    for secret in (SIGNATURE, API_KEY, PRIVATE_SECRET, LISTEN_KEY, TIMESTAMP):
        assert secret not in rendered


def _client_with_sync_failure(error: Exception) -> HttpClient:
    client = object.__new__(HttpClient)
    client._venue = "BINANCE___SWAP"
    client._sync_client = Mock()
    client._sync_client.request.side_effect = error
    return client


def test_sanitizers_cover_query_headers_embedded_urls_and_listen_key_paths() -> None:
    websocket_url = f"wss://demo-fstream.binance.com/ws/{LISTEN_KEY}"
    message = (
        f"failed {SIGNED_URL}; X-MBX-APIKEY={API_KEY}; "
        f"secret='{PRIVATE_SECRET}'; user_stream={websocket_url}"
    )

    _assert_secrets_absent(sanitize_url(SIGNED_URL))
    _assert_secrets_absent(sanitize_url(websocket_url))
    _assert_secrets_absent(sanitize_text(message))
    _assert_secrets_absent(
        sanitize_value({"headers": HEADERS, "url": SIGNED_URL, "nested": [message]})
    )


def test_websocket_failure_uses_stream_credentials_as_literal_redaction_values() -> None:
    app = object.__new__(MyWebsocketApp)
    app.public_key = API_KEY
    app.private_key = PRIVATE_SECRET
    app.listen_key = LISTEN_KEY
    app.passphrase = "passphrase-that-must-not-leak"
    app._params = None

    rendered = app._safe_failure(
        RuntimeError(
            f"opaque values {API_KEY} {PRIVATE_SECRET} {LISTEN_KEY} {app.passphrase}"
        )
    )

    for secret in (API_KEY, PRIVATE_SECRET, LISTEN_KEY, app.passphrase):
        assert secret not in rendered


def test_websocket_requires_certificate_and_hostname_verification() -> None:
    params = SimpleNamespace(exchange_name="BINANCE___SWAP")
    app = MyWebsocketApp(wss_url="wss://example.invalid/ws", exchange_data=params)

    assert app.sslopt["cert_reqs"] == ssl.CERT_REQUIRED
    assert app.sslopt["check_hostname"] is True

    with pytest.raises(ValueError, match="TLS certificate and hostname"):
        MyWebsocketApp(
            wss_url="wss://example.invalid/ws",
            exchange_data=params,
            sslopt={"cert_reqs": ssl.CERT_NONE},
        )
    with pytest.raises(ValueError, match="TLS certificate and hostname"):
        MyWebsocketApp(
            wss_url="wss://example.invalid/ws",
            exchange_data=params,
            sslopt={"cert_reqs": ssl.CERT_REQUIRED, "check_hostname": False},
        )


@pytest.mark.parametrize(
    "redirect_target",
    [
        "wss://ws.okx.com:8443/ws/v5/private",
        "wss://evil.invalid/ws/private",
    ],
)
def test_websocket_transport_rejects_redirect_before_open_callback(
    monkeypatch, redirect_target
) -> None:
    connect_options = []
    socket_close = Mock()

    def fake_connect(transport, _url, **options):
        connect_options.append(options)
        transport.sock = SimpleNamespace(close=socket_close)
        transport.connected = True
        transport.handshake_response = SimpleNamespace(
            status=302,
            headers={"location": redirect_target},
        )

    monkeypatch.setattr(websocket.WebSocket, "connect", fake_connect)
    transport = object.__new__(websocket_app_module.WebSocket)

    with pytest.raises(websocket.WebSocketException, match="redirects are disabled"):
        transport.connect("wss://wspap.okx.com:8443/ws/v5/private")

    assert connect_options == [{"redirect_limit": 0}]
    assert transport.connected is False
    assert transport.sock is None
    socket_close.assert_called_once_with()


def test_json_4xx_log_redacts_signed_url_and_echoed_credentials(
    monkeypatch, caplog
) -> None:
    test_logger = logging.getLogger("test.transport.http.response")
    monkeypatch.setattr(http_client_module, "logger", test_logger)
    request = httpx.Request("POST", SIGNED_URL, headers=HEADERS)
    response = httpx.Response(
        400,
        request=request,
        json={
            "code": -2015,
            "msg": (
                f"invalid apiKey={API_KEY}; secret={PRIVATE_SECRET}; "
                f"signature={SIGNATURE}; timestamp={TIMESTAMP}"
            ),
        },
    )
    client = object.__new__(HttpClient)
    client._venue = "BINANCE___SWAP"

    with caplog.at_level(logging.WARNING, logger=test_logger.name):
        result = client._process_response(response)

    assert result["code"] == -2015
    _assert_secrets_absent(caplog.text)


def test_json_401_survives_real_spdlog_one_string_call_shape(monkeypatch) -> None:
    messages = []

    class StrictSpdLogger:
        def warn(self, message: str) -> None:
            messages.append(message)

    monkeypatch.setattr(
        http_client_module,
        "logger",
        _LoggerProxy(StrictSpdLogger()),
    )
    request = httpx.Request("GET", SIGNED_URL, headers=HEADERS)
    response = httpx.Response(
        401,
        request=request,
        json={
            "code": -2015,
            "msg": f"invalid apiKey={API_KEY}; secret={PRIVATE_SECRET}",
        },
    )
    client = object.__new__(HttpClient)
    client._venue = "BINANCE___SWAP"

    result = client._process_response(response)

    assert result["code"] == -2015
    assert len(messages) == 1
    _assert_secrets_absent(messages)


def test_json_401_survives_logging_sink_failure(monkeypatch) -> None:
    class FailingSpdLogger:
        @staticmethod
        def warn(_message: str) -> None:
            raise OSError("log volume unavailable")

    monkeypatch.setattr(
        http_client_module,
        "logger",
        _LoggerProxy(FailingSpdLogger()),
    )
    request = httpx.Request("GET", SIGNED_URL, headers=HEADERS)
    response = httpx.Response(
        401,
        request=request,
        json={
            "code": -2015,
            "msg": f"invalid apiKey={API_KEY}; secret={PRIVATE_SECRET}",
        },
    )
    client = object.__new__(HttpClient)
    client._venue = "BINANCE___SWAP"

    result = client._process_response(response)

    assert result["code"] == -2015


def test_sync_client_does_not_follow_signed_cross_host_redirect() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "demo-fapi.binance.com":
            return httpx.Response(
                307,
                headers={"Location": "https://fapi.binance.com/fapi/v1/order"},
            )
        return httpx.Response(200, json={"orderId": "should-not-be-reached"})

    client = HttpClient(venue="BINANCE___SWAP")
    assert client._sync_client.follow_redirects is False
    client._sync_client.close()
    client._sync_client = httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )
    try:
        with pytest.raises(RequestFailedError):
            client.request("POST", SIGNED_URL, headers=HEADERS)
    finally:
        client.close()

    assert len(requests) == 1
    assert requests[0].url.host == "demo-fapi.binance.com"


def test_async_client_does_not_follow_signed_cross_host_redirect() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "demo-fapi.binance.com":
            return httpx.Response(
                307,
                headers={"Location": "https://fapi.binance.com/fapi/v1/order"},
            )
        return httpx.Response(200, json={"orderId": "should-not-be-reached"})

    client = HttpClient(venue="BINANCE___SWAP")
    assert client._async_kwargs["follow_redirects"] is False
    client._async_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )

    async def request() -> None:
        try:
            await client.async_request("POST", SIGNED_URL, headers=HEADERS)
        finally:
            await client.aclose()

    with pytest.raises(RequestFailedError):
        asyncio.run(request())

    assert len(requests) == 1
    assert requests[0].url.host == "demo-fapi.binance.com"


@pytest.mark.parametrize(
    "error_type",
    [httpx.TimeoutException, httpx.ConnectError, httpx.RequestError],
)
def test_sync_httpx_exception_and_cause_do_not_retain_signed_url(error_type) -> None:
    request = httpx.Request("POST", SIGNED_URL, headers=HEADERS)
    raw_error = error_type(
        f"failed {SIGNED_URL}; X-MBX-APIKEY={API_KEY}; secret={PRIVATE_SECRET}",
        request=request,
    )
    client = _client_with_sync_failure(raw_error)

    with pytest.raises(RequestFailedError) as caught:
        client.request("POST", SIGNED_URL, headers=HEADERS)

    _assert_secrets_absent(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_async_httpx_exception_does_not_retain_signed_url() -> None:
    request = httpx.Request("POST", SIGNED_URL, headers=HEADERS)
    raw_error = httpx.ConnectError(
        f"failed {SIGNED_URL}; X-MBX-APIKEY={API_KEY}; secret={PRIVATE_SECRET}",
        request=request,
    )
    client = object.__new__(HttpClient)
    client._venue = "BINANCE___SWAP"
    async_client = SimpleNamespace(request=AsyncMock(side_effect=raw_error))
    client._get_async_client = lambda: async_client

    async def request() -> None:
        await client.async_request("POST", SIGNED_URL, headers=HEADERS)

    with pytest.raises(RequestFailedError) as caught:
        asyncio.run(request())

    _assert_secrets_absent(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_feed_404_error_does_not_retain_signed_url() -> None:
    feed = object.__new__(Feed)
    feed.exchange_name = "BINANCE___SWAP"
    feed._http_client = SimpleNamespace(
        request=Mock(
            side_effect=RequestFailedError(
                venue="BINANCE___SWAP",
                message="missing endpoint",
                status_code=404,
            )
        )
    )

    with pytest.raises(RequestError) as caught:
        feed.http_request("POST", SIGNED_URL, headers=HEADERS, max_retries=1)

    _assert_secrets_absent(caught.value)
    assert caught.value.__context__ is None


class _EventBus:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event_type, payload) -> None:
        self.events.append((event_type, payload))


def test_websocket_logs_and_events_redact_listen_key_and_error_urls(caplog) -> None:
    event_bus = _EventBus()
    websocket_url = f"wss://demo-fstream.binance.com/ws/{LISTEN_KEY}"
    app = MyWebsocketApp(
        wss_url=websocket_url,
        wss_name="binance_account",
        exchange_data=SimpleNamespace(exchange_name="BINANCE___SWAP"),
        event_bus=event_bus,
    )
    test_logger = logging.getLogger("test.transport.websocket")
    app.wss_logger = test_logger
    error = RuntimeError(
        f"socket failure at {websocket_url}; signature={SIGNATURE}; "
        f"X-MBX-APIKEY={API_KEY}; secret={PRIVATE_SECRET}; timestamp={TIMESTAMP}"
    )

    with caplog.at_level(logging.WARNING, logger=test_logger.name):
        app.on_error(None, error)
        app._emit_event("ws.test", wss_url=websocket_url, error=str(error))

    _assert_secrets_absent(caplog.text)
    _assert_secrets_absent(event_bus.events)
    assert event_bus.events[-1][1]["wss_url"].endswith("/ws/***")


def test_websocket_callback_traceback_is_redacted(caplog) -> None:
    websocket_url = f"wss://demo-fstream.binance.com/ws/{LISTEN_KEY}"
    app = MyWebsocketApp(
        wss_url=websocket_url,
        exchange_data=SimpleNamespace(exchange_name="BINANCE___SWAP"),
    )
    test_logger = logging.getLogger("test.transport.websocket.callback")
    app.wss_logger = test_logger

    def fail() -> None:
        raise RuntimeError(f"failed {SIGNED_URL}; listenKey={LISTEN_KEY}")

    app.open_rsp = fail
    with caplog.at_level(logging.WARNING, logger=test_logger.name):
        app.on_open(None)

    _assert_secrets_absent(caplog.text)
