---
title: ConfigLoader | bt_api_base
---

<!-- English -->
# ConfigLoader

The `config_loader` module provides **Pydantic-based YAML configuration validation** for exchange configurations.

## Overview

All exchange configurations are defined in YAML files and validated against Pydantic models at runtime. This ensures type safety and provides clear error messages for invalid configurations.

## Configuration Schema

### ExchangeConfig

```python
class ExchangeConfig(BaseModel):
    exchange_name: str
    venue_type: VenueType
    auth_type: AuthType
    api_key: Optional[str] = None
    secret: Optional[str] = None
    passphrase: Optional[str] = None
    testnet: bool = False
    proxy: Optional[Dict[str, Any]] = None
    timeout: float = 30.0
    rate_limit: Optional[Dict[str, Any]] = None
```

### VenueType

```python
class VenueType(Enum):
    SPOT = "spot"              # Spot trading
    MARGIN = "margin"          # Margin trading
    USDT_SWAP = "usdt_swap"   # USDT-margined perpetual
    COIN_SWAP = "coin_swap"    # Coin-margined perpetual
    FUTURE = "future"          # Delivery futures
    OPTION = "option"          # Options
    STK = "stk"               # Stocks
```

### AuthType

```python
class AuthType(Enum):
    NONE = "none"              # No authentication (public endpoints)
    API_KEY = "api_key"        # API Key + Secret
    MARGIN_KEY = "margin_key"  # Margin trading auth
    FUTURES_KEY = "futures_key" # Futures auth
    OPTION_KEY = "option_key"  # Options auth
```

## Usage

### Loading Configuration from File

```python
from bt_api_base.config_loader import load_exchange_config

config = load_exchange_config("binance.yaml")
# Returns ExchangeConfig with validated fields
```

### Loading Multiple Configurations

```python
from bt_api_base.config_loader import load_all_configs

configs = load_all_configs("configs/exchanges/")
for name, config in configs.items():
    print(f"{name}: {config.exchange_name}")
```

### Programmatic Configuration

```python
from bt_api_base.config_loader import ExchangeConfig, VenueType, AuthType

config = ExchangeConfig(
    exchange_name="BINANCE___SPOT",
    venue_type=VenueType.SPOT,
    auth_type=AuthType.API_KEY,
    api_key="your_api_key",
    secret="your_secret",
    testnet=True,
)
```

---

## 中文

### 概述

`config_loader` 模块提供**基于 Pydantic 的 YAML 配置验证**，用于交易所配置。

### VenueType（交易场所类型）

| 类型 | 说明 |
|------|------|
| `SPOT` | 现货交易 |
| `MARGIN` | 杠杆交易 |
| `USDT_SWAP` | USDT 永续合约 |
| `COIN_SWAP` | 币本位永续合约 |
| `FUTURE` | 交割合约 |
| `OPTION` | 期权 |
| `STK` | 股票 |

### AuthType（认证类型）

| 类型 | 说明 |
|------|------|
| `NONE` | 无认证（公开接口） |
| `API_KEY` | API Key + Secret |
| `MARGIN_KEY` | 杠杆交易认证 |
| `FUTURES_KEY` | 合约认证 |
| `OPTION_KEY` | 期权认证 |

### 主要方法

| 方法 | 说明 |
|------|------|
| `load_exchange_config(path)` | 从文件加载单个配置 |
| `load_all_configs(dir)` | 从目录加载所有配置 |
| `validate_config(config)` | 验证配置对象 |

### 使用示例

```python
from bt_api_base.config_loader import load_exchange_config

config = load_exchange_config("binance.yaml")
print(config.exchange_name, config.venue_type)
```
