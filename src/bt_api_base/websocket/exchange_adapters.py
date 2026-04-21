"""
Exchange-specific WebSocket optimizations and message format handling.
Supports different connection strategies, rate limiting, and data synchronization for each exchange.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from importlib import import_module
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

from bt_api_base.exceptions import AuthenticationError, RateLimitError
from bt_api_base.logging_factory import get_logger


class ExchangeType(Enum):
    """Exchange type enumeration."""

    SPOT = "spot"
    FUTURES = "futures"
    SWAP = "swap"
    OPTIONS = "options"


class AuthenticationType(Enum):
    """Authentication type enumeration."""

    NONE = "none"
    API_KEY = "api_key"
    API_KEY_SECRET = "api_key_secret"
    JWT = "jwt"
    CUSTOM = "custom"


@dataclass
class ExchangeCredentials:
    """Exchange authentication credentials."""

    exchange_name: str
    auth_type: AuthenticationType
    api_key: str | None = None
    api_secret: str | None = None
    passphrase: str | None = None  # For exchanges like OKX
    jwt_token: str | None = None
    custom_params: dict[str, Any] | None = None

    def __post_init__(self):
        if self.custom_params is None:
            self.custom_params = {}


@dataclass
class RateLimitConfig:
    """Rate limiting configuration for exchange."""

    # WebSocket rate limits
    max_connections_per_ip: int = 5
    max_subscriptions_per_connection: int = 50
    messages_per_second_limit: int = 10
    reconnect_delay_seconds: float = 1.0

    # REST API rate limits (for token refresh)
    requests_per_second: int = 10
    requests_per_minute: int = 600

    # Exchange-specific limits
    exchange_specific_limits: dict[str, int] | None = None

    def __post_init__(self):
        if self.exchange_specific_limits is None:
            self.exchange_specific_limits = {}


class ExchangeWebSocketAdapter(ABC):
    """Abstract base class for exchange-specific WebSocket adapters."""

    def __init__(self, exchange_name: str, credentials: ExchangeCredentials | None = None):
        self.exchange_name = exchange_name
        self.credentials = credentials
        self.logger = get_logger(f"ws_adapter_{exchange_name}")

        # Rate limiting
        self._rate_limiter = None
        self._subscription_counts: dict[str, int] = {}

    @abstractmethod
    async def authenticate(self, websocket: Any) -> None:
        """Perform exchange-specific authentication."""

    @abstractmethod
    def format_subscription_message(
        self, subscription_id: str, topic: str, symbol: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Format subscription message for the exchange."""

    @abstractmethod
    def format_unsubscription_message(
        self, subscription_id: str, topic: str, symbol: str
    ) -> dict[str, Any]:
        """Format unsubscription message for the exchange."""

    @abstractmethod
    def extract_topic_symbol(self, message: dict[str, Any]) -> tuple[str | None, str | None]:
        """Extract topic and symbol from incoming message."""

    @abstractmethod
    def normalize_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Normalize message format to the standard bt_api_base shape."""

    @abstractmethod
    def get_rate_limit_config(self) -> RateLimitConfig:
        """Get rate limiting configuration for the exchange."""

    def get_endpoints(self, primary_url: str) -> list[str]:
        """Get failover endpoints for the exchange."""
        # Default implementation - override for specific exchanges
        return [primary_url]

    def get_subscription_limits(self) -> dict[str, int]:
        """Get subscription limits per topic."""
        return {"ticker": 100, "depth": 50, "trades": 100, "kline": 200, "orders": 50}

    async def check_rate_limits(self, topic: str) -> None:
        """Check if subscription request complies with rate limits."""
        limits = self.get_subscription_limits()
        current_count = self._subscription_counts.get(topic, 0)

        if current_count >= limits.get(topic, 100):
            raise RateLimitError(
                self.exchange_name,
                detail=f"Subscription limit exceeded for {topic}: {current_count}/{limits[topic]}",
            )

    def increment_subscription_count(self, topic: str) -> None:
        """Increment subscription count for topic."""
        self._subscription_counts[topic] = self._subscription_counts.get(topic, 0) + 1

    def decrement_subscription_count(self, topic: str) -> None:
        """Decrement subscription count for topic."""
        self._subscription_counts[topic] = max(0, self._subscription_counts.get(topic, 0) - 1)


_PLUGIN_ADAPTERS = {
    "BINANCE": ("bt_api_binance.websocket.exchange_adapters", "BinanceWebSocketAdapter"),
}


def _normalize_exchange_key(exchange_name: str) -> str:
    return str(exchange_name).strip().upper()


def _base_exchange_key(exchange_name: str) -> str:
    return _normalize_exchange_key(exchange_name).split("___", 1)[0]


def _infer_exchange_type(exchange_name: str) -> ExchangeType:
    parts = _normalize_exchange_key(exchange_name).split("___", 1)
    if len(parts) != 2:
        return ExchangeType.SPOT

    asset_type = parts[1]
    if asset_type in {"FUTURE", "FUTURES"}:
        return ExchangeType.FUTURES
    if asset_type == "SWAP":
        return ExchangeType.SWAP
    if asset_type in {"OPTION", "OPTIONS"}:
        return ExchangeType.OPTIONS
    return ExchangeType.SPOT


def _load_plugin_adapter(exchange_key: str) -> type[ExchangeWebSocketAdapter] | None:
    plugin_ref = _PLUGIN_ADAPTERS.get(exchange_key)
    if plugin_ref is None:
        return None

    module_name, attr_name = plugin_ref
    try:
        module = import_module(module_name)
    except ImportError:
        return None

    adapter_cls = getattr(module, attr_name, None)
    if not isinstance(adapter_cls, type) or not issubclass(adapter_cls, ExchangeWebSocketAdapter):
        return None
    return adapter_cls


class OKXWebSocketAdapter(ExchangeWebSocketAdapter):
    """OKX-specific WebSocket adapter."""

    def __init__(
        self,
        exchange_type: ExchangeType = ExchangeType.SPOT,
        credentials: ExchangeCredentials | None = None,
    ):
        super().__init__("OKX", credentials)
        self.exchange_type = exchange_type

    def get_endpoints(self, primary_url: str) -> list[str]:
        """Get OKX failover endpoints."""
        return [
            "wss://ws.okx.com:8443/ws/v5/public",
            "wss://ws.okx.com:8443/ws/v5/private",
            "wss://wsa.okx.com:8443/ws/v5/public",
            "wss://wsa.okx.com:8443/ws/v5/private",
        ]

    async def authenticate(self, websocket: Any) -> None:
        """Authenticate with OKX API."""
        if self.credentials and self.credentials.auth_type == AuthenticationType.API_KEY_SECRET:
            timestamp = str(int(time.time()))
            sign = self._generate_signature(timestamp, "GET", "/users/self/verify")

            message = {
                "op": "login",
                "args": [
                    {
                        "apiKey": self.credentials.api_key,
                        "passphrase": self.credentials.passphrase,
                        "timestamp": timestamp,
                        "sign": sign,
                    }
                ],
            }

            await websocket.send(json.dumps(message))
            self.logger.info("OKX authentication sent")

    def _generate_signature(self, timestamp: str, method: str, path: str) -> str:
        """Generate OKX API signature."""
        if not self.credentials or not self.credentials.api_secret:
            raise AuthenticationError(self.exchange_name, detail="Missing API credentials")

        message = timestamp + method + path
        signature = hmac.new(
            self.credentials.api_secret.encode(), message.encode(), hashlib.sha256
        ).digest()

        return base64.b64encode(signature).decode()

    def format_subscription_message(
        self, subscription_id: str, topic: str, symbol: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Format OKX subscription message."""
        channel = self._get_okx_channel(topic, params)
        inst_id = symbol  # OKX uses instrument ID directly

        return {"op": "subscribe", "args": [{"channel": channel, "instId": inst_id}]}

    def format_unsubscription_message(
        self, subscription_id: str, topic: str, symbol: str
    ) -> dict[str, Any]:
        """Format OKX unsubscription message."""
        return {"op": "unsubscribe", "args": [{"channel": topic, "instId": symbol}]}

    def _get_okx_channel(self, topic: str, params: dict[str, Any]) -> str:
        """Convert generic topic to OKX channel."""
        mapping = {
            "ticker": "tickers",
            "depth": "books",
            "trades": "trades",
            "kline": "candle" + params.get("interval", "1m"),
            "orders": "orders",
            "positions": "positions",
            "account": "account",
        }

        return str(mapping.get(topic, topic))

    def extract_topic_symbol(self, message: dict[str, Any]) -> tuple[str | None, str | None]:
        """Extract topic and symbol from OKX message."""
        if "arg" in message:
            arg = message["arg"]
            channel = arg.get("channel")
            inst_id = arg.get("instId")

            # Convert OKX channel back to generic topic
            topic = self._convert_okx_channel_to_generic(channel)
            symbol = inst_id

            return topic, symbol

        return None, None

    def _convert_okx_channel_to_generic(self, channel: str) -> str:
        """Convert OKX channel to generic topic."""
        if channel == "tickers":
            return "ticker"
        elif channel == "books":
            return "depth"
        elif channel == "trades":
            return "trades"
        elif channel.startswith("candle"):
            return "kline"
        elif channel == "orders":
            return "orders"
        elif channel == "positions":
            return "positions"
        elif channel == "account":
            return "account"

        return channel

    def normalize_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Normalize OKX message format."""
        if "data" in message and "arg" in message:
            message["arg"]
            data = message["data"]

            # Handle array data (most OKX messages)
            if isinstance(data, list) and data:
                data = data[0]

            topic, symbol = self.extract_topic_symbol(message)

            normalized = {
                "exchange": "OKX",
                "symbol": symbol,
                "topic": topic,
                "data": data,
                "timestamp": int(
                    float(data.get("ts", time.time() * 1000))
                    if isinstance(data, dict)
                    else int(time.time() * 1000)
                ),
            }

            # Add topic-specific fields
            if topic == "ticker" and isinstance(data, dict):
                normalized.update(
                    {
                        "last_price": float(data.get("last", 0)),
                        "volume": float(data.get("vol24h", 0)),
                        "high_24h": float(data.get("high24h", 0)),
                        "low_24h": float(data.get("low24h", 0)),
                        "change_24h": float(data.get("chg", 0)),
                    }
                )
            elif topic == "depth" and isinstance(data, dict):
                normalized.update(
                    {
                        "bids": [[float(p), float(s)] for p, s in data.get("bids", [])],
                        "asks": [[float(p), float(s)] for p, s in data.get("asks", [])],
                        "checksum": data.get("checksum"),
                    }
                )
            elif topic == "trades" and isinstance(data, dict):
                normalized.update(
                    {
                        "price": float(data.get("px", 0)),
                        "quantity": float(data.get("sz", 0)),
                        "trade_time": int(data.get("ts", 0)),
                        "side": data.get("side"),
                    }
                )
            elif topic == "kline" and isinstance(data, dict):
                normalized.update(
                    {
                        "open_time": int(data.get("ts", 0)),
                        "open": float(data.get("o", 0)),
                        "high": float(data.get("h", 0)),
                        "low": float(data.get("l", 0)),
                        "close": float(data.get("c", 0)),
                        "volume": float(data.get("vol", 0)),
                    }
                )

            return normalized

        return message

    def get_rate_limit_config(self) -> RateLimitConfig:
        """Get OKX rate limiting configuration."""
        return RateLimitConfig(
            max_connections_per_ip=4,
            max_subscriptions_per_connection=240,
            messages_per_second_limit=20,
            requests_per_second=20,
            requests_per_minute=600,
        )


class WebSocketAdapterFactory:
    """Factory for creating exchange-specific WebSocket adapters."""

    _adapters: dict[str, type[ExchangeWebSocketAdapter]] = {
        "OKX": OKXWebSocketAdapter,
        # Add more exchanges as needed
    }

    @classmethod
    def create_adapter(
        cls,
        exchange_name: str,
        exchange_type: ExchangeType = ExchangeType.SPOT,
        credentials: ExchangeCredentials | None = None,
    ) -> ExchangeWebSocketAdapter:
        """Create exchange-specific adapter."""
        normalized = _normalize_exchange_key(exchange_name)
        base_name = _base_exchange_key(exchange_name)
        adapter_class = cls._adapters.get(normalized) or cls._adapters.get(base_name)

        if adapter_class is None:
            adapter_class = _load_plugin_adapter(base_name)
            if adapter_class is not None:
                cls._adapters.setdefault(base_name, adapter_class)

        if not adapter_class:
            # Use generic adapter if exchange not supported
            return GenericWebSocketAdapter(exchange_name, credentials)

        resolved_exchange_type = exchange_type
        inferred_exchange_type = _infer_exchange_type(exchange_name)
        if (
            resolved_exchange_type == ExchangeType.SPOT
            and inferred_exchange_type != ExchangeType.SPOT
        ):
            resolved_exchange_type = inferred_exchange_type

        if adapter_class.__init__ is ExchangeWebSocketAdapter.__init__:
            return adapter_class(exchange_name, credentials)
        return adapter_class(resolved_exchange_type, credentials)  # type: ignore[arg-type]

    @classmethod
    def register_adapter(
        cls, exchange_name: str, adapter_class: type[ExchangeWebSocketAdapter]
    ) -> None:
        """Register a new adapter class."""
        cls._adapters[exchange_name.upper()] = adapter_class


class GenericWebSocketAdapter(ExchangeWebSocketAdapter):
    """Generic WebSocket adapter for unsupported exchanges."""

    async def authenticate(self, websocket: Any) -> None:
        """No authentication for generic adapter."""

    def format_subscription_message(
        self, subscription_id: str, topic: str, symbol: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Generic subscription message format."""
        return {
            "action": "subscribe",
            "topic": topic,
            "symbol": symbol,
            "params": params,
            "id": subscription_id,
        }

    def format_unsubscription_message(
        self, subscription_id: str, topic: str, symbol: str
    ) -> dict[str, Any]:
        """Generic unsubscription message format."""
        return {"action": "unsubscribe", "topic": topic, "symbol": symbol, "id": subscription_id}

    def extract_topic_symbol(self, message: dict[str, Any]) -> tuple[str | None, str | None]:
        """Generic topic/symbol extraction."""
        return message.get("topic"), message.get("symbol")

    def normalize_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Generic message normalization."""
        return {
            "exchange": self.exchange_name,
            "symbol": message.get("symbol"),
            "topic": message.get("topic"),
            "data": message.get("data"),
            "timestamp": message.get("timestamp", time.time() * 1000),
        }

    def get_rate_limit_config(self) -> RateLimitConfig:
        """Generic rate limiting configuration."""
        return RateLimitConfig()


def __getattr__(name: str) -> Any:
    if name == "BinanceWebSocketAdapter":
        adapter_cls = _load_plugin_adapter("BINANCE")
        if adapter_cls is None:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        return adapter_cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
