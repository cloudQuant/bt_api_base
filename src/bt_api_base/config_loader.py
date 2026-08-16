"""
 —  pydantic  Schema 

 YAML /，。
"""

from __future__ import annotations

import warnings
from contextlib import suppress
from enum import unique
from importlib import resources
from pathlib import Path
from typing import Any

from bt_api_base._compat import StrEnum

try:
    from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator
except ImportError:
    raise ImportError(
        "pydantic is required for config_loader. Install with: pip install pydantic"
    ) from None

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from bt_api_base.exceptions import ConfigurationError
from bt_api_base.logging_factory import get_logger

__all__ = [
    "VenueType",
    "AuthType",
    "ConnectionType",
    "BaseUrlsConfig",
    "ConnectionConfig",
    "AuthConfig",
    "RateLimitRuleConfig",
    "AssetTypeConfig",
    "ExchangeConfig",
    "get_exchange_config_path",
    "load_exchange_config",
    "load_all_exchange_configs",
]


# ──  ──────────────────────────────────────────────────


@unique
class VenueType(StrEnum):
    """Class VenueType"""
    CEX = "cex"
    DEX = "dex"
    BROKER = "broker"


@unique
class AuthType(StrEnum):
    """Class AuthType"""
    NONE = "none"
    API_KEY = "api_key"
    HMAC_SHA256 = "hmac_sha256"
    HMAC_SHA256_JWT = "hmac_sha256_jwt"
    HMAC_SHA384 = "hmac_sha384"
    HMAC_SHA512 = "hmac_sha512"
    OAUTH = "oauth"
    CERTIFICATE = "certificate"
    PASSWORD = "password"


@unique
class ConnectionType(StrEnum):
    """Class ConnectionType"""
    HTTP = "http"
    WEBSOCKET = "websocket"
    SPI = "spi"
    TWS = "tws"
    LOCAL_TERMINAL = "local_terminal"
    RPC = "rpc"


# ──  ────────────────────────────────────────────────


class BaseUrlsConfig(BaseModel):
    """Class BaseUrlsConfig"""
    rest: dict[str, str] = Field(default_factory=dict)
    wss: dict[str, str] = Field(default_factory=dict)
    acct_wss: dict[str, str] = Field(default_factory=dict)


class ConnectionConfig(BaseModel):
    """Class ConnectionConfig"""
    type: ConnectionType
    timeout: int = Field(default=10, ge=1, le=120)
    max_retries: int = Field(default=3, ge=0, le=10)

    # SPI/ 
    md_front: str | None = None
    td_front: str | None = None
    exe_path: str | None = None
    session_id: int | None = None

    # TWS 
    host: str | None = None
    port: int | None = None
    client_id: int | None = None


class AuthConfig(BaseModel):
    """Class AuthConfig"""
    type: AuthType
    header_name: str | None = None
    timestamp_key: str | None = None
    signature_key: str | None = None
    api_key_param: str | None = None


class RateLimitRuleConfig(BaseModel):
    """Class RateLimitRuleConfig"""
    name: str
    type: str = Field(..., pattern="^(sliding_window|fixed_window|token_bucket)$")
    interval: int = Field(..., gt=0)
    limit: int = Field(..., gt=0)
    scope: str = Field(default="global", pattern="^(global|endpoint|ip)$")
    endpoint: str | None = None
    weight: int = Field(default=1, ge=1)
    weight_map: dict[str, int] | None = None


class AssetTypeConfig(BaseModel):
    """Class AssetTypeConfig"""
    exchange_name: str | None = Field(default=None, description=",  binance_swap")
    rest_url: str | None = Field(default=None, description="REST API base URL for this asset type")
    wss_url: str | None = Field(default=None, description="WebSocket URL for this asset type")
    symbol_format: str = Field(..., description=" {base}{quote}  {base}-{quote}")
    rest_paths: dict[str, str] = Field(default_factory=dict)
    wss_paths: dict[str, Any] = Field(default_factory=dict)
    wss_channels: dict[str, str] = Field(default_factory=dict)
    kline_periods: dict[str, str] | None = None
    legal_currency: list[str] | None = None
    symbols: list[str] | None = None
    trading_symbols: dict[str, str] | None = Field(
        default=None, description="， BTC/USDC: BTC"
    )


# ──  ────────────────────────────────────────────────


class ExchangeConfig(BaseModel):
    """/"""

    id: str = Field(..., min_length=2, max_length=30)
    display_name: str
    venue_type: VenueType
    website: str | None = None
    api_doc: str | None = None

    base_urls: BaseUrlsConfig | None = None
    connection: ConnectionConfig
    authentication: AuthConfig | None = None
    rate_limits: list[RateLimitRuleConfig] = Field(default_factory=list)
    asset_types: dict[str, AssetTypeConfig] = Field(default_factory=dict)

    # DEX 
    chains: list[str] | None = None
    router_address: str | dict[str, str] | None = None
    factory_address: str | dict[str, str] | None = None

    # 
    kline_periods: dict[str, str] | None = None
    legal_currency: list[str] | None = None
    status_dict: dict[str, str] | None = None
    exchange_id_map: dict[str, str] | None = None

    # Broker 
    broker_id: str | None = None
    app_id: str | None = None

    model_config = {"extra": "ignore"}

    @field_validator("base_urls")
    @classmethod
    def validate_base_urls(
        cls, v: BaseUrlsConfig | None, info: ValidationInfo
    ) -> BaseUrlsConfig | None:
        """validate_base_urls method"""
        venue_type = info.data.get("venue_type")
        # CEX  base_urls
        if venue_type == VenueType.CEX and not v:
            raise ValueError("CEX must have base_urls")
        # DEX  Broker  base_urls（ Hyperliquid CEX DEX、IB Web API）
        return v

    @field_validator("connection")
    @classmethod
    def validate_connection(cls, v: ConnectionConfig, info: ValidationInfo) -> ConnectionConfig:
        """validate_connection method"""
        venue_type = info.data.get("venue_type")
        conn_type = v.type
        # CEX  HTTP、WEBSOCKET  SPI（ CTP）
        if venue_type == VenueType.CEX and conn_type not in (
            ConnectionType.HTTP,
            ConnectionType.WEBSOCKET,
            ConnectionType.SPI,
        ):
            raise ValueError("CEX must use HTTP, WEBSOCKET or SPI connection")
        return v


# ──  ──────────────────────────────────────────────────


def get_exchange_config_path(filename: str) -> Path:
    """Return Path to a config file in bt_api_base/configs/.

    Use pathlib for cross-platform path handling and cleaner code.
    """
    binance_filename = "binance.yaml"
    if filename == binance_filename:
        with suppress(Exception):
            plugin_path = Path(resources.files("bt_api_binance").joinpath("configs", filename))
            if plugin_path.exists():
                warnings.warn(
                    (
                        "Loading Binance config from bt_api_binance plugin package. "
                        "bt_api_base bundled Binance configs are deprecated."
                    ),
                    DeprecationWarning,
                    stacklevel=2,
                )
                return plugin_path

    return Path(__file__).resolve().parent / "configs" / filename


def load_exchange_config(config_path: str) -> ExchangeConfig:
    """ YAML 

    :param config_path: YAML 
    :return: ExchangeConfig
    :raises FileNotFoundError: 
    :raises ValueError: 
    """
    if yaml is None:
        raise ImportError(
            "PyYAML is required to load config files. Install with: pip install PyYAML"
        )

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        raise ConfigurationError(f"Config file is empty: {config_path}")
    if not isinstance(data, dict):
        raise ConfigurationError(f"Config file must contain a mapping object: {config_path}")

    return ExchangeConfig(**data)


def load_all_exchange_configs(config_dir: str) -> dict[str, ExchangeConfig]:
    """

    :param config_dir: 
    :return: {exchange_id: ExchangeConfig}
    """
    configs: dict[str, ExchangeConfig] = {}
    path = Path(config_dir)
    if not path.is_dir():
        return configs

    load_errors: tuple[type[Exception], ...] = (
        ConfigurationError,
        FileNotFoundError,
        ValidationError,
    )
    if yaml is not None:
        load_errors = (*load_errors, yaml.YAMLError)

    logger = get_logger("config_loader")

    for filepath in sorted(path.iterdir(), key=lambda item:
        item.name):
        if filepath.suffix in (".yaml", ".yml") and not filepath.name.startswith("_"):
            try:
                config = load_exchange_config(str(filepath))
                configs[config.id] = config
            except load_errors as e:
                logger.warning(f"Failed to load config {filepath!s}: {e}")

    return configs
