---
title: Exceptions | bt_api_base
---

<!-- English -->
# Exceptions

The `exceptions` module defines a **comprehensive exception hierarchy** with 20+ exception types and **predicate functions** for error classification.

## Exception Hierarchy

```
BtApiError (base)
├── ExchangeNotFoundError
├── AuthenticationError
│   ├── InvalidApiKeyError
│   ├── InvalidSignatureError
│   └── PermissionDeniedError
├── RateLimitError
├── OrderError
│   ├── OrderNotFoundError
│   ├── InsufficientBalanceError
│   ├── PriceOutOfRangeError
│   └── OrderRejectError
├── MarketDataError
│   ├── SymbolNotFoundError
│   └── MarketClosedError
├── WebSocketError
│   ├── ConnectionError
│   ├── SubscriptionError
│   └── ReconnectError
├── NetworkError
│   ├── TimeoutError
│   └── ProxyError
├── ConfigError
│   ├── InvalidConfigError
│   └── ConfigNotFoundError
├── ValidationError
├── CacheError
└── PluginError
```

## Exception Types

### BtApiError

Base exception for all bt_api errors.

```python
class BtApiError(Exception):
    def __init__(self, message: str = "", code: Optional[str] = None):
```

### RateLimitError

Raised when exchange API rate limit is exceeded.

```python
class RateLimitError(BtApiError):
    retry_after: Optional[float]  # Seconds to wait before retrying
```

### AuthenticationError

Raised for authentication failures.

```python
class AuthenticationError(BtApiError):
    ...
```

### OrderError

Base class for order-related errors.

```python
class OrderError(BtApiError):
    order_id: Optional[str]
    symbol: Optional[str]
```

## Predicate Functions

Predicate functions enable **error classification** for programmatic error handling:

```python
from bt_api_base.exceptions import (
    is_network_error,
    is_auth_error,
    is_rate_limit_error,
    is_order_error,
    is_user_recoverable,
    is_exchange_error,
)

try:
    feed.make_order(...)
except Exception as e:
    if is_rate_limit_error(e):
        wait_time = e.retry_after
    elif is_network_error(e):
        retry_with_backoff()
    elif is_auth_error(e):
        alert_ops_team()
    elif is_user_recoverable(e):
        log_and_continue()
```

| Predicate | Return True for |
|-----------|-----------------|
| `is_network_error(e)` | NetworkError, TimeoutError, ProxyError |
| `is_auth_error(e)` | AuthenticationError, InvalidApiKeyError, InvalidSignatureError |
| `is_rate_limit_error(e)` | RateLimitError |
| `is_order_error(e)` | OrderError and subclasses |
| `is_market_data_error(e)` | MarketDataError and subclasses |
| `is_websocket_error(e)` | WebSocketError and subclasses |
| `is_user_recoverable(e)` | RateLimitError, NetworkError (can retry) |
| `is_exchange_error(e)` | Any error originating from exchange API |

---

## 中文

### 概述

`exceptions` 模块定义了**完整的异常层次结构**，包含 20+ 异常类型和**谓词函数**用于错误分类。

### 异常层次

```
BtApiError (基类)
├── ExchangeNotFoundError       # 交易所未找到
├── AuthenticationError         # 认证失败
│   ├── InvalidApiKeyError      # API Key 无效
│   ├── InvalidSignatureError   # 签名无效
│   └── PermissionDeniedError   # 权限不足
├── RateLimitError              # 速率限制
├── OrderError                  # 订单错误
│   ├── OrderNotFoundError      # 订单未找到
│   ├── InsufficientBalanceError # 余额不足
│   └── OrderRejectError        # 订单被拒绝
├── MarketDataError             # 市场数据错误
├── WebSocketError              # WebSocket 错误
├── NetworkError                # 网络错误
├── ConfigError                 # 配置错误
└── PluginError                 # 插件错误
```

### 谓词函数

| 函数 | 返回 True 的情况 |
|------|-----------------|
| `is_network_error(e)` | NetworkError, TimeoutError, ProxyError |
| `is_auth_error(e)` | AuthenticationError 及其子类 |
| `is_rate_limit_error(e)` | RateLimitError |
| `is_order_error(e)` | OrderError 及其子类 |
| `is_user_recoverable(e)` | RateLimitError, NetworkError（可重试） |

### 使用示例

```python
from bt_api_base.exceptions import (
    BtApiError, RateLimitError, OrderError,
    is_rate_limit_error, is_network_error
)

try:
    feed.make_order(...)
except RateLimitError as e:
    sleep(e.retry_after)
except OrderError as e:
    log.error(f"订单失败: {e}")
```
