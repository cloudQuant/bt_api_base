"""WebSocket adapter contracts shared by plugin exchange packages."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from bt_api_base.websocket.exchange_adapters import (
    AuthenticationType,
    ExchangeCredentials,
    ExchangeType,
    ExchangeWebSocketAdapter,
    OKXWebSocketAdapter,
    RateLimitConfig,
    WebSocketAdapterFactory,
    GenericWebSocketAdapter,
)


def __getattr__(name: str) -> Any:
    if name == "BinanceWebSocketAdapter":
        try:
            module = import_module("bt_api_binance.websocket.exchange_adapters")
        except ModuleNotFoundError as exc:
            raise AttributeError(
                "BinanceWebSocketAdapter is only available after installing bt_api_binance"
            ) from exc
        return getattr(module, "BinanceWebSocketAdapter")
    raise AttributeError(name)


__all__ = [
    "AuthenticationType",
    "ExchangeCredentials",
    "ExchangeType",
    "ExchangeWebSocketAdapter",
    "OKXWebSocketAdapter",
    "RateLimitConfig",
    "WebSocketAdapterFactory",
    "GenericWebSocketAdapter",
]
