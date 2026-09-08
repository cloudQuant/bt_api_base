"""Async transport and public error objects must not retain credentials."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import traceback
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import bt_api_base.functions.async_base as async_base_module
from bt_api_base.error import ErrorCategory, UnifiedError, UnifiedErrorCode
from bt_api_base.exceptions import ConfigurationError, RequestFailedError
from bt_api_base.functions.async_base import AsyncBase

SIGNATURE = "signed-value-that-must-not-leak"
API_KEY = "api-key-that-must-not-leak"
PRIVATE_SECRET = "private-secret-that-must-not-leak"
TIMESTAMP = "1700000000123"
SIGNED_URL = (
    "https://demo-fapi.binance.com/fapi/v1/order?symbol=BTCUSDT"
    f"&timestamp={TIMESTAMP}&signature={SIGNATURE}"
)
SECRETS = (SIGNATURE, API_KEY, PRIVATE_SECRET, TIMESTAMP)


def _assert_secrets_absent(value) -> None:
    rendered = str(value)
    for secret in SECRETS:
        assert secret not in rendered


def test_async_session_uses_system_ca_and_hostname_verification(monkeypatch) -> None:
    captured = {}

    class Connector:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    class Session:
        def __init__(self, *, connector) -> None:
            self.connector = connector

    monkeypatch.setattr(async_base_module, "TCPConnector", Connector)
    monkeypatch.setattr(async_base_module, "ClientSession", Session)
    transport = object.__new__(AsyncBase)
    transport.keepalive_timeout = 30
    transport.limit = 100
    transport._ssl_context = AsyncBase._resolve_ssl_context({})

    transport.get_session()

    context = captured["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert captured["limit"] == 100


@pytest.mark.parametrize(
    "options",
    [
        {"ssl": False},
        {"async_ssl": False},
        {"verify_ssl": False},
        {"ssl_verify": False},
        {"ssl_context": ssl._create_unverified_context()},
    ],
)
def test_async_transport_rejects_explicit_tls_verification_opt_out(options) -> None:
    with pytest.raises(ConfigurationError, match="TLS|certificate"):
        AsyncBase._resolve_ssl_context(options)


def test_async_aiohttp_failure_logs_and_raises_only_sanitized_data(caplog) -> None:
    raw_error = RuntimeError(
        f"request failed for {SIGNED_URL}; X-MBX-APIKEY={API_KEY}; secret={PRIVATE_SECRET}"
    )
    transport = object.__new__(AsyncBase)
    request_method = Mock(side_effect=raw_error)
    transport.session = SimpleNamespace(closed=False, post=request_method)
    transport.async_proxy = None
    transport.exchange_name = "BINANCE___SWAP"
    test_logger = logging.getLogger("test.async.transport.redaction")
    transport.async_base_logger = test_logger

    async def request() -> None:
        await transport.async_http_request(
            "POST",
            SIGNED_URL,
            headers={"X-MBX-APIKEY": API_KEY},
            body={"secret": PRIVATE_SECRET},
        )

    with (
        caplog.at_level(logging.INFO, logger=test_logger.name),
        pytest.raises(RequestFailedError) as caught,
    ):
        asyncio.run(request())

    _assert_secrets_absent(caplog.text)
    _assert_secrets_absent(caught.value)
    _assert_secrets_absent(caught.value.args)
    _assert_secrets_absent("".join(traceback.format_exception(caught.value)))
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert request_method.call_args.kwargs["allow_redirects"] is False


def test_unified_error_sanitizes_every_public_serialization_surface() -> None:
    raw_response = {
        "code": -2015,
        "msg": (
            f"failed {SIGNED_URL}; echo {API_KEY}; echo {PRIVATE_SECRET}; timestamp={TIMESTAMP}"
        ),
        "signature": SIGNATURE,
        "timestamp": TIMESTAMP,
        "api_key": API_KEY,
        "secret": PRIVATE_SECRET,
        "nested": [{"safe_field": "preserved", "request_url": SIGNED_URL}],
    }
    error = UnifiedError(
        code=UnifiedErrorCode.PERMISSION_DENIED,
        category=ErrorCategory.AUTH,
        venue="BINANCE___SWAP",
        message=raw_response["msg"],
        original_error=f"-2015: {raw_response['msg']}",
        context={"raw_response": raw_response, "safe_context": {"attempt": 2}},
    )

    for surface in (
        error.message,
        error.original_error,
        error.context,
        error.raw_response,
        error.args,
        str(error),
        repr(error),
        error.to_dict(),
        json.dumps(error.to_dict()),
    ):
        _assert_secrets_absent(surface)

    assert error.raw_response["code"] == -2015
    assert error.raw_response["nested"][0]["safe_field"] == "preserved"
    assert error.context["safe_context"] == {"attempt": 2}
    assert raw_response["signature"] == SIGNATURE


def test_to_dict_resanitizes_context_after_external_mutation() -> None:
    error = UnifiedError(
        code=UnifiedErrorCode.INTERNAL_ERROR,
        category=ErrorCategory.SYSTEM,
        venue="BINANCE___SWAP",
        message="request failed",
    )
    error.context["raw_response"] = {"signature": SIGNATURE, "safe": "preserved"}

    _assert_secrets_absent(error.raw_response)
    _assert_secrets_absent(error.to_dict())
    assert error.raw_response["safe"] == "preserved"
