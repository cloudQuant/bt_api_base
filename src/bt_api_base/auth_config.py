"""认证配置 — 统一管理不同交易所的认证方式。

加密货币交易所使用 API Key，CTP 使用 Broker/User/Password，IB 使用 TWS 连接参数.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

__all__ = [
    "AuthConfig",
    "CryptoAuthConfig",
    "CtpAuthConfig",
    "IbAuthConfig",
    "IbWebAuthConfig",
]


def _require_non_empty_str(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _validate_port(port: int, field_name: str = "port") -> int:
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError(f"{field_name} must be in range 1-65535")
    return port


def _validate_url(value: str, field_name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be a valid http/https URL")
    return value


def _validate_tcp_front(value: str, field_name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "tcp" or not parsed.hostname or parsed.port is None:
        raise ValueError(f"{field_name} must be a valid tcp://host:port address")
    return value


class AuthConfig:
    """认证配置基类."""

    def __init__(self, exchange: str, asset_type: str = "SWAP", **kwargs: Any) -> None:
        self.exchange = _require_non_empty_str(exchange, "exchange")
        self.asset_type = _require_non_empty_str(asset_type, "asset_type")

    def get_exchange_name(self) -> str:
        return f"{self.exchange}___{self.asset_type}"

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


class CryptoAuthConfig(AuthConfig):
    """加密货币交易所认证配置（Binance, OKX 等）."""

    def __init__(
        self,
        exchange: str,
        asset_type: str = "SWAP",
        public_key: str | None = None,
        private_key: str | None = None,
        passphrase: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(exchange, asset_type, **kwargs)
        if public_key is not None:
            public_key = _require_non_empty_str(public_key, "public_key")
        if private_key is not None:
            private_key = _require_non_empty_str(private_key, "private_key")
        if public_key is None and private_key is not None:
            raise ValueError("public_key is required when private_key is provided")
        if private_key is None and public_key is not None:
            raise ValueError("private_key is required when public_key is provided")
        self.public_key = public_key
        self.private_key = private_key
        self.passphrase = (
            _require_non_empty_str(passphrase, "passphrase") if passphrase is not None else None
        )


class CtpAuthConfig(AuthConfig):
    """CTP 认证配置."""

    def __init__(
        self,
        exchange: str = "CTP",
        asset_type: str = "FUTURE",
        broker_id: str = "",
        user_id: str = "",
        password: str = "",
        auth_code: str = "",
        app_id: str = "",
        md_front: str = "",
        td_front: str = "",
        product_info: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(exchange, asset_type, **kwargs)
        self.broker_id = _require_non_empty_str(broker_id, "broker_id")
        self.user_id = _require_non_empty_str(user_id, "user_id")
        self.password = _require_non_empty_str(password, "password")
        self.auth_code = auth_code
        self.app_id = app_id
        self.md_front = _validate_tcp_front(md_front, "md_front")
        self.td_front = _validate_tcp_front(td_front, "td_front")
        self.product_info = product_info


class IbAuthConfig(AuthConfig):
    """Interactive Brokers 认证配置."""

    def __init__(
        self,
        exchange: str = "IB",
        asset_type: str = "STK",
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 1,
        **kwargs: Any,
    ) -> None:
        super().__init__(exchange, asset_type, **kwargs)
        self.host = _require_non_empty_str(host, "host")
        self.port = _validate_port(port, "port")
        if not isinstance(client_id, int) or client_id < 0:
            raise ValueError("client_id must be a non-negative integer")
        self.client_id = client_id


class IbWebAuthConfig(AuthConfig):
    """Interactive Brokers Web API 认证配置."""

    def __init__(
        self,
        exchange: str = "IB_WEB",
        asset_type: str = "STK",
        base_url: str = "https://localhost:5000",
        account_id: str | None = None,
        access_token: str | None = None,
        client_id: str | None = None,
        private_key_path: str | None = None,
        verify_ssl: bool = False,
        proxies: dict[str, str] | None = None,
        timeout: int = 10,
        cookies: dict[str, str] | None = None,
        cookie_source: str | None = None,
        cookie_browser: str = "chrome",
        cookie_path: str = "/sso",
        **kwargs: Any,
    ) -> None:
        super().__init__(exchange, asset_type, **kwargs)
        self.base_url = _validate_url(base_url, "base_url")
        self.account_id = account_id
        self.access_token = access_token
        self.client_id = client_id
        self.private_key_path = private_key_path
        self.verify_ssl = verify_ssl
        self.proxies = proxies
        if not isinstance(timeout, int) or timeout <= 0:
            raise ValueError("timeout must be a positive integer")
        self.timeout = timeout
        self.cookies = cookies
        self.cookie_source = cookie_source
        self.cookie_browser = cookie_browser
        self.cookie_path = cookie_path
