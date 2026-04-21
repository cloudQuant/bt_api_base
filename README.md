# bt_api_base

[![PyPI Version](https://img.shields.io/pypi/v/bt_api_base.svg)](https://pypi.org/project/bt_api_base/)
[![Python Versions](https://img.shields.io/pypi/pyversions/bt_api_base.svg)](https://pypi.org/project/bt_api_base/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/cloudQuant/bt_api_base/actions/workflows/ci.yml/badge.svg)](https://github.com/cloudQuant/bt_api_base/actions)
[![Docs](https://readthedocs.org/projects/bt-api-base/badge/?version=latest)](https://bt-api-base.readthedocs.io/)

---

## English | [中文](#中文)

### Overview

`bt_api_base` is the **canonical shared base package** for the [bt_api](https://github.com/cloudQuant/bt_api_py) plugin ecosystem. It provides a standardized foundation that all exchange plugins (Binance, OKX, HTX, CTP, Interactive Brokers, etc.) depend on — without needing to import from the main application.

This package is the **core runtime dependency** for every `bt_api_xx` exchange plugin. It abstracts away the complexity of multi-exchange integration, letting plugin authors focus purely on exchange-specific API semantics.

### Architecture

```
bt_api_base/
├── src/bt_api_base/
│   ├── registry.py          # ExchangeRegistry — plugin registration system
│   ├── event_bus.py         # EventBus — pub/sub event dispatcher
│   ├── websocket_manager.py # WebSocketManager — connection pooling & auto-reconnect
│   ├── cache.py             # SimpleCache, ExchangeInfoCache, MarketDataCache
│   ├── rate_limiter.py     # SlidingWindowLimiter, FixedWindowLimiter, RateLimiter
│   ├── exceptions.py         # Full exception hierarchy (20+ exception types)
│   ├── config_loader.py     # Pydantic-based YAML config validation
│   ├── security.py          # Authentication & request signing utilities
│   ├── balance_utils.py    # Balance normalization helpers
│   ├── logging_factory.py   # Structured logging setup
│   ├── feeds/              # AbstractVenueFeed protocol & AsyncWrapperMixin
│   ├── containers/          # Instrument, Tick, OrderBook, Bar, Order, Position, Balance...
│   ├── gateway/            # BaseGatewayAdapter, PluginGatewayAdapter
│   ├── plugins/             # PluginInfo, PluginLoader, PluginProtocol
│   └── core/               # AsyncTaskGroup, DependencyInjection, Interfaces, Services
├── tests/                  # Comprehensive unit & integration tests
└── docs/                  # API documentation
```

### Core Features

#### 1. Exchange Registry (Plugin System)

The `ExchangeRegistry` implements a **Registry Pattern** for plug-and-play exchange support:

```python
from bt_api_base.registry import ExchangeRegistry

# Global singleton (backward compatible)
ExchangeRegistry.register_feed("BINANCE___SPOT", BinanceSpotFeed)
feed = ExchangeRegistry.create_feed("BINANCE___SPOT", data_queue)

# Isolated instance (for testing)
registry = ExchangeRegistry.create_isolated()
registry.register_feed("TEST___SPOT", MockFeed)
```

#### 2. Event Bus

Publish/subscribe event dispatcher with **Queue mode** (existing behavior) and **Callback mode** (for CTP SPI / IB EWrapper callback-driven APIs):

```python
from bt_api_base.event_bus import EventBus, ErrorHandlerMode

bus = EventBus(error_mode=ErrorHandlerMode.LOG)

bus.on("order_filled", lambda data: print(f"Order filled: {data}"))
bus.on("tick_update", lambda data: update_chart(data))

errors = bus.emit("order_filled", {"order_id": "123", "filled": 0.5})
```

#### 3. WebSocket Manager

Connection pooling with **auto-reconnect**, **backpressure handling**, and **subscription limiting**:

```python
from bt_api_base.websocket_manager import WebSocketManager, WebSocketConfig

config = WebSocketConfig(
    url="wss://stream.binance.com:9443/ws",
    exchange_name="BINANCE___SPOT",
    max_connections=5,
    heartbeat_interval=30.0,
    reconnect_interval=5.0,
    max_reconnect_attempts=10,
)

manager = WebSocketManager()
await manager.add_exchange(config)

subscription_id = await manager.subscribe(
    exchange_name="BINANCE___SPOT",
    topic="ticker",
    symbol="BTCUSDT",
    callback=on_ticker_update,
)
```

#### 4. Caching System

Three-tier caching with TTL support and thread-safe operations:

```python
from bt_api_base.cache import SimpleCache, ExchangeInfoCache, MarketDataCache, cached

# Manual cache
cache = SimpleCache(default_ttl=300.0, max_size=10000)
cache.set("key", value, ttl=60)
value = cache.get("key")

# Decorator-based caching
@cached(ttl=60)
def fetch_exchange_info():
    return requests.get("/api/v3/exchangeInfo").json()
```

#### 5. Rate Limiter

Supports **sliding window**, **fixed window**, and **token bucket** rate limiting with endpoint-level glob matching and weight mapping:

```python
from bt_api_base.rate_limiter import RateLimiter, RateLimitRule, RateLimitType, RateLimitScope

rules = [
    RateLimitRule(name="global", type=RateLimitType.SLIDING_WINDOW,
                  interval=60, limit=1200, scope=RateLimitScope.GLOBAL),
    RateLimitRule(name="order", type=RateLimitType.FIXED_WINDOW,
                  interval=1, limit=10, scope=RateLimitScope.ENDPOINT,
                  endpoint="/api/v3/order*",
                  weight_map={"POST": 10, "DELETE": 5, "GET": 1}),
]

limiter = RateLimiter(rules)

with limiter:
    # Rate-limited request
    response = requests.post("/api/v3/order", json=order_data)
```

#### 6. Configuration System

Pydantic-based YAML config validation with full schema checking:

```python
from bt_api_base.config_loader import load_exchange_config, ExchangeConfig

config = load_exchange_config("binance.yaml")
# Returns ExchangeConfig with validated fields
```

#### 7. Comprehensive Exception Hierarchy

20+ exception types with predicate functions for error classification:

```python
from bt_api_base.exceptions import (
    BtApiError, ExchangeNotFoundError, AuthenticationError,
    RateLimitError, OrderError, is_network_error, is_user_recoverable
)

try:
    feed.make_order(...)
except RateLimitError as e:
    wait_time = e.retry_after
except OrderError as e:
    log.error(f"Order failed: {e}")
```

#### 8. Feed Protocol & Async Wrapper

Standardized `AbstractVenueFeed` protocol ensuring all exchange plugins implement a consistent interface:

```python
from bt_api_base.feeds.abstract_feed import AbstractVenueFeed, AsyncWrapperMixin

# All exchange feeds implement:
# - get_tick, get_depth, get_kline, make_order, cancel_order, get_balance, get_position...
# - async_* versions for each operation
# - connect, disconnect, is_connected
# - capabilities property
```

### Supported Exchanges

All exchange plugins in the bt_api ecosystem depend on bt_api_base:

| Exchange Plugin | Repository | Status |
|----------------|------------|--------|
| Binance | [bt_api_binance](https://github.com/cloudQuant/bt_api_binance) | ✅ |
| OKX | [bt_api_okx](https://github.com/cloudQuant/bt_api_okx) | ✅ |
| HTX | [bt_api_htx](https://github.com/cloudQuant/bt_api_htx) | ✅ |
| CTP (China Futures) | [bt_api_ctp](https://github.com/cloudQuant/bt_api_ctp) | ✅ |
| Interactive Brokers | [bt_api_ib_web](https://github.com/cloudQuant/bt_api_ib_web) | ✅ |
| Gemini | [bt_api_gemini](https://github.com/cloudQuant/bt_api_gemini) | ✅ |
| Bybit | [bt_api_bybit](https://github.com/cloudQuant/bt_api_bybit) | ✅ |
| Gate.io | [bt_api_gateio](https://github.com/cloudQuant/bt_api_gateio) | ✅ |
| MetaTrader 5 | [bt_api_mt5](https://github.com/cloudQuant/bt_api_mt5) | ✅ |

*And 54+ more exchange plugins...*

### Installation

```bash
pip install bt_api_base
```

Or install from source:

```bash
git clone https://github.com/cloudQuant/bt_api_base
cd bt_api_base
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
```

### Requirements

- Python 3.9+
- pydantic >= 2.0
- numpy >= 1.26
- requests >= 2.31
- websocket-client >= 1.6
- aiohttp >= 3.9
- websockets >= 12.0
- pyyaml >= 6.0

### Online Documentation

| Resource | Link |
|----------|------|
| English Docs | https://bt-api-base.readthedocs.io/ |
| Chinese Docs | https://bt-api-base.readthedocs.io/zh/latest/ |
| GitHub Repository | https://github.com/cloudQuant/bt_api_base |
| Issue Tracker | https://github.com/cloudQuant/bt_api_base/issues |
| PyPI Package | https://pypi.org/project/bt_api_base/ |
| Main Project (bt_api_py) | https://github.com/cloudQuant/bt_api_py |

### License

MIT License - see [LICENSE](LICENSE) for details.

### Support

- Report bugs via [GitHub Issues](https://github.com/cloudQuant/bt_api_base/issues)
- Email: yunjinqi@gmail.com

---

## 中文

### 概述

`bt_api_base` 是 [bt_api](https://github.com/cloudQuant/bt_api_py) 插件生态系统的**标准共享基础包**。它为所有交易所插件（Binance、OKX、HTX、CTP、Interactive Brokers 等）提供标准化的基础依赖，让插件作者无需从主应用包导入，即可获得所有核心功能。

这个包是**每个 `bt_api_xx` 交易所插件的核心运行时依赖**。它将多交易所集成的复杂性抽象化，让插件作者专注于交易所特定的 API 语义。

### 架构

```
bt_api_base/
├── src/bt_api_base/
│   ├── registry.py          # ExchangeRegistry — 插件注册系统
│   ├── event_bus.py         # EventBus — 发布/订阅事件分发器
│   ├── websocket_manager.py # WebSocketManager — 连接池与自动重连
│   ├── cache.py             # SimpleCache, ExchangeInfoCache, MarketDataCache
│   ├── rate_limiter.py     # SlidingWindowLimiter, FixedWindowLimiter, RateLimiter
│   ├── exceptions.py         # 完整异常层次结构（20+ 异常类型）
│   ├── config_loader.py     # 基于 Pydantic 的 YAML 配置验证
│   ├── security.py          # 认证与请求签名工具
│   ├── balance_utils.py    # 余额规范化辅助函数
│   ├── logging_factory.py   # 结构化日志配置
│   ├── feeds/              # AbstractVenueFeed 协议和 AsyncWrapperMixin
│   ├── containers/          # Instrument, Tick, OrderBook, Bar, Order, Position, Balance...
│   ├── gateway/            # BaseGatewayAdapter, PluginGatewayAdapter
│   ├── plugins/             # PluginInfo, PluginLoader, PluginProtocol
│   └── core/               # AsyncTaskGroup, DependencyInjection, Interfaces, Services
├── tests/                  # 综合单元测试和集成测试
└── docs/                  # API 文档
```

### 核心功能

#### 1. 交易所注册表（插件系统）

`ExchangeRegistry` 实现**注册表模式**，支持插件式交易所接入：

```python
from bt_api_base.registry import ExchangeRegistry

# 全局单例（向后兼容）
ExchangeRegistry.register_feed("BINANCE___SPOT", BinanceSpotFeed)
feed = ExchangeRegistry.create_feed("BINANCE___SPOT", data_queue)

# 隔离实例（用于测试）
registry = ExchangeRegistry.create_isolated()
registry.register_feed("TEST___SPOT", MockFeed)
```

#### 2. 事件总线

支持 **Queue 模式**（现有行为）和 **Callback 模式**（适配 CTP SPI / IB EWrapper 等回调驱动 API）的发布/订阅事件分发器：

```python
from bt_api_base.event_bus import EventBus, ErrorHandlerMode

bus = EventBus(error_mode=ErrorHandlerMode.LOG)

bus.on("order_filled", lambda data: print(f"订单成交: {data}"))
bus.on("tick_update", lambda data: update_chart(data))

errors = bus.emit("order_filled", {"order_id": "123", "filled": 0.5})
```

#### 3. WebSocket 管理器

支持**自动重连**、**背压处理**和**订阅限制**的连接池：

```python
from bt_api_base.websocket_manager import WebSocketManager, WebSocketConfig

config = WebSocketConfig(
    url="wss://stream.binance.com:9443/ws",
    exchange_name="BINANCE___SPOT",
    max_connections=5,
    heartbeat_interval=30.0,
    reconnect_interval=5.0,
    max_reconnect_attempts=10,
)

manager = WebSocketManager()
await manager.add_exchange(config)

subscription_id = await manager.subscribe(
    exchange_name="BINANCE___SPOT",
    topic="ticker",
    symbol="BTCUSDT",
    callback=on_ticker_update,
)
```

#### 4. 缓存系统

三层缓存系统，支持 TTL 和线程安全操作：

```python
from bt_api_base.cache import SimpleCache, ExchangeInfoCache, MarketDataCache, cached

# 手动缓存
cache = SimpleCache(default_ttl=300.0, max_size=10000)
cache.set("key", value, ttl=60)
value = cache.get("key")

# 装饰器缓存
@cached(ttl=60)
def fetch_exchange_info():
    return requests.get("/api/v3/exchangeInfo").json()
```

#### 5. 限流器

支持**滑动窗口**、**固定窗口**和**令牌桶**限流，端点级 glob 匹配和权重映射：

```python
from bt_api_base.rate_limiter import RateLimiter, RateLimitRule, RateLimitType, RateLimitScope

rules = [
    RateLimitRule(name="global", type=RateLimitType.SLIDING_WINDOW,
                  interval=60, limit=1200, scope=RateLimitScope.GLOBAL),
    RateLimitRule(name="order", type=RateLimitType.FIXED_WINDOW,
                  interval=1, limit=10, scope=RateLimitScope.ENDPOINT,
                  endpoint="/api/v3/order*",
                  weight_map={"POST": 10, "DELETE": 5, "GET": 1}),
]

limiter = RateLimiter(rules)

with limiter:
    # 限流请求
    response = requests.post("/api/v3/order", json=order_data)
```

#### 6. 配置系统

基于 Pydantic 的 YAML 配置验证，支持完整 Schema 检查：

```python
from bt_api_base.config_loader import load_exchange_config, ExchangeConfig

config = load_exchange_config("binance.yaml")
# 返回经过字段验证的 ExchangeConfig
```

#### 7. 完整异常层次结构

20+ 异常类型，带错误分类谓词函数：

```python
from bt_api_base.exceptions import (
    BtApiError, ExchangeNotFoundError, AuthenticationError,
    RateLimitError, OrderError, is_network_error, is_user_recoverable
)

try:
    feed.make_order(...)
except RateLimitError as e:
    wait_time = e.retry_after
except OrderError as e:
    log.error(f"订单失败: {e}")
```

#### 8. Feed 协议和异步封装

标准化的 `AbstractVenueFeed` 协议，确保所有交易所插件实现一致接口：

```python
from bt_api_base.feeds.abstract_feed import AbstractVenueFeed, AsyncWrapperMixin

# 所有交易所 feeds 都实现:
# - get_tick, get_depth, get_kline, make_order, cancel_order, get_balance, get_position...
# - 各操作的 async_* 版本
# - connect, disconnect, is_connected
# - capabilities 属性
```

### 支持的交易所

bt_api 生态系统中所有交易所插件都依赖 bt_api_base：

| 交易所插件 | 仓库 | 状态 |
|----------------|------------|--------|
| Binance | [bt_api_binance](https://github.com/cloudQuant/bt_api_binance) | ✅ |
| OKX | [bt_api_okx](https://github.com/cloudQuant/bt_api_okx) | ✅ |
| HTX (火币) | [bt_api_htx](https://github.com/cloudQuant/bt_api_htx) | ✅ |
| CTP (中国期货) | [bt_api_ctp](https://github.com/cloudQuant/bt_api_ctp) | ✅ |
| Interactive Brokers | [bt_api_ib_web](https://github.com/cloudQuant/bt_api_ib_web) | ✅ |
| Gemini | [bt_api_gemini](https://github.com/cloudQuant/bt_api_gemini) | ✅ |
| Bybit | [bt_api_bybit](https://github.com/cloudQuant/bt_api_bybit) | ✅ |
| Gate.io | [bt_api_gateio](https://github.com/cloudQuant/bt_api_gateio) | ✅ |
| MetaTrader 5 | [bt_api_mt5](https://github.com/cloudQuant/bt_api_mt5) | ✅ |

*以及 54+ 更多交易所插件...*

### 安装

```bash
pip install bt_api_base
```

或从源码安装：

```bash
git clone https://github.com/cloudQuant/bt_api_base
cd bt_api_base
pip install -e .
```

开发安装：

```bash
pip install -e ".[dev]"
```

### 系统要求

- Python 3.9+
- pydantic >= 2.0
- numpy >= 1.26
- requests >= 2.31
- websocket-client >= 1.6
- aiohttp >= 3.9
- websockets >= 12.0
- pyyaml >= 6.0

### 在线文档

| 资源 | 链接 |
|----------|------|
| 英文文档 | https://bt-api-base.readthedocs.io/ |
| 中文文档 | https://bt-api-base.readthedocs.io/zh/latest/ |
| GitHub 仓库 | https://github.com/cloudQuant/bt_api_base |
| 问题反馈 | https://github.com/cloudQuant/bt_api_base/issues |
| PyPI 包 | https://pypi.org/project/bt_api_base/ |
| 主项目 (bt_api_py) | https://github.com/cloudQuant/bt_api_py |

### 许可证

MIT 许可证 - 详见 [LICENSE](LICENSE)。

### 技术支持

- 通过 [GitHub Issues](https://github.com/cloudQuant/bt_api_base/issues) 反馈问题
- 邮箱: yunjinqi@gmail.com
