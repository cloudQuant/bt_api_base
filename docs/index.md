---
title: Home | bt_api_base
---

<!-- English -->
# bt_api_base Documentation

[![PyPI Version](https://img.shields.io/pypi/v/bt_api_base.svg)](https://pypi.org/project/bt_api_base/)
[![Python Versions](https://img.shields.io/pypi/pyversions/bt_api_base.svg)](https://pypi.org/project/bt_api_base/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/cloudQuant/bt_api_base/actions/workflows/ci.yml/badge.svg)](https://github.com/cloudQuant/bt_api_base/actions)
[![Docs](https://readthedocs.org/projects/bt-api-base/badge/?version=latest)](https://bt-api-base.readthedocs.io/)

## Overview

`bt_api_base` is the **canonical shared base package** for the [bt_api](https://github.com/cloudQuant/bt_api_py) plugin ecosystem. It provides the standardized foundation that all exchange plugins — Binance, OKX, HTX, CTP, Interactive Brokers, and 60+ others — depend on.

This package is the **core runtime dependency** for every `bt_api_xx` exchange plugin. It abstracts multi-exchange integration complexity, enabling plugin authors to focus purely on exchange-specific API semantics.

## Key Benefits

- **Plugin Architecture**: Registry-based plug-and-play exchange support via `ExchangeRegistry`
- **Event-Driven**: Pub/sub event dispatcher (`EventBus`) with Queue and Callback modes
- **WebSocket Infrastructure**: Connection pooling, auto-reconnect, backpressure handling, subscription management
- **Caching**: Three-tier cache (SimpleCache, ExchangeInfoCache, MarketDataCache) with TTL support
- **Rate Limiting**: Sliding window, fixed window, and token bucket algorithms with endpoint-level glob matching
- **Exception Hierarchy**: 20+ typed exceptions with predicate functions for error classification
- **Type-Safe Config**: Pydantic-based YAML validation for exchange configuration
- **Feed Protocol**: Standardized `AbstractVenueFeed` ensuring consistent interface across all exchange plugins

## Architecture Overview

```
bt_api_base/
├── registry.py          # ExchangeRegistry — plugin registration system
├── event_bus.py         # EventBus — pub/sub event dispatcher
├── websocket_manager.py # WebSocketManager — connection pooling & auto-reconnect
├── cache.py             # SimpleCache, ExchangeInfoCache, MarketDataCache
├── rate_limiter.py      # SlidingWindowLimiter, FixedWindowLimiter, RateLimiter
├── exceptions.py        # 20+ exception types with predicate functions
├── config_loader.py     # Pydantic-based YAML config validation
├── security.py          # Authentication & request signing utilities
├── balance_utils.py     # Balance normalization helpers
├── logging_factory.py   # Structured logging setup
├── feeds/               # AbstractVenueFeed protocol & AsyncWrapperMixin
├── containers/          # Instrument, Tick, OrderBook, Bar, Order, Position, Balance...
├── gateway/             # BaseGatewayAdapter, PluginGatewayAdapter
├── plugins/             # PluginInfo, PluginLoader, PluginProtocol
└── core/                # AsyncTaskGroup, DependencyInjection, Interfaces, Services
```

## Quick Start

### Installation

```bash
pip install bt_api_base
```

### Exchange Registry

```python
from bt_api_base.registry import ExchangeRegistry

# Global singleton (backward compatible)
ExchangeRegistry.register_feed("BINANCE___SPOT", BinanceSpotFeed)
feed = ExchangeRegistry.create_feed("BINANCE___SPOT", data_queue)

# Isolated instance (for testing)
registry = ExchangeRegistry.create_isolated()
registry.register_feed("TEST___SPOT", MockFeed)
```

### Event Bus

```python
from bt_api_base.event_bus import EventBus, ErrorHandlerMode

bus = EventBus(error_mode=ErrorHandlerMode.LOG)

bus.on("order_filled", lambda data: print(f"Order filled: {data}"))
errors = bus.emit("order_filled", {"order_id": "123", "filled": 0.5})
```

### WebSocket Manager

```python
from bt_api_base.websocket_manager import WebSocketManager, WebSocketConfig

config = WebSocketConfig(
    url="wss://stream.binance.com:9443/ws",
    exchange_name="BINANCE___SPOT",
    max_connections=5,
    heartbeat_interval=30.0,
)
manager = WebSocketManager()
await manager.add_exchange(config)
```

### Caching

```python
from bt_api_base.cache import SimpleCache, cached

cache = SimpleCache(default_ttl=300.0, max_size=10000)
cache.set("key", value, ttl=60)

@cached(ttl=60)
def fetch_exchange_info():
    return requests.get("/api/v3/exchangeInfo").json()
```

## API Reference

- [Registry](api/registry.md) — Plugin registration system
- [Event Bus](api/event_bus.md) — Pub/sub event dispatcher
- [WebSocket Manager](api/websocket_manager.md) — Connection pooling & auto-reconnect
- [Cache](api/cache.md) — Three-tier caching with TTL
- [Rate Limiter](api/rate_limiter.md) — Rate limiting algorithms
- [Exceptions](api/exceptions.md) — Exception hierarchy & predicates
- [Config Loader](api/config_loader.md) — Pydantic YAML validation
- [Feeds](api/feeds.md) — AbstractVenueFeed protocol
- [Containers](api/containers.md) — Data containers
- [Gateway](api/gateway.md) — Gateway adapters
- [Plugins](api/plugins.md) — Plugin system

## Supported Exchange Plugins

All exchange plugins in the bt_api ecosystem depend on bt_api_base:

| Exchange | Plugin | Status |
|----------|--------|--------|
| Binance | [bt_api_binance](https://github.com/cloudQuant/bt_api_binance) | ✅ |
| OKX | [bt_api_okx](https://github.com/cloudQuant/bt_api_okx) | ✅ |
| HTX | [bt_api_htx](https://github.com/cloudQuant/bt_api_htx) | ✅ |
| CTP | [bt_api_ctp](https://github.com/cloudQuant/bt_api_ctp) | ✅ |
| Interactive Brokers | [bt_api_ib_web](https://github.com/cloudQuant/bt_api_ib_web) | ✅ |
| Bybit | [bt_api_bybit](https://github.com/cloudQuant/bt_api_bybit) | ✅ |
| Gate.io | [bt_api_gateio](https://github.com/cloudQuant/bt_api_gateio) | ✅ |
| Gemini | [bt_api_gemini](https://github.com/cloudQuant/bt_api_gemini) | ✅ |
| MetaTrader 5 | [bt_api_mt5](https://github.com/cloudQuant/bt_api_mt5) | ✅ |

*And 54+ more exchange plugins...*

## Online Documentation

| Resource | Link |
|----------|------|
| English Docs | https://bt-api-base.readthedocs.io/ |
| Chinese Docs | https://bt-api-base.readthedocs.io/zh/latest/ |
| GitHub Repository | https://github.com/cloudQuant/bt_api_base |
| Issue Tracker | https://github.com/cloudQuant/bt_api_base/issues |
| PyPI Package | https://pypi.org/project/bt_api_base/ |

---

## 中文

### 概述

`bt_api_base` 是 [bt_api](https://github.com/cloudQuant/bt_api_py) 插件生态系统的**标准共享基础包**。它为所有交易所插件（Binance、OKX、HTX、CTP、Interactive Brokers 等）提供标准化的基础依赖，让插件作者无需从主应用包导入，即可获得所有核心功能。

这个包是**每个 `bt_api_xx` 交易所插件的核心运行时依赖**。

### 核心功能

- **插件架构**: 基于 `ExchangeRegistry` 的注册表模式，支持插件式接入
- **事件驱动**: 支持 Queue 模式和 Callback 模式的发布/订阅事件分发器
- **WebSocket 基础设施**: 连接池、自动重连、背压处理、订阅管理
- **三级缓存**: SimpleCache、ExchangeInfoCache、MarketDataCache，支持 TTL
- **限流器**: 滑动窗口、固定窗口、令牌桶算法，端点级 glob 匹配
- **异常层次结构**: 20+ 异常类型，带错误分类谓词函数
- **类型安全配置**: 基于 Pydantic 的 YAML 配置验证
- **Feed 协议**: 标准化的 `AbstractVenueFeed`，确保所有交易所插件接口一致

### 快速开始

```bash
pip install bt_api_base
```

```python
from bt_api_base.registry import ExchangeRegistry

# 全局单例（向后兼容）
ExchangeRegistry.register_feed("BINANCE___SPOT", BinanceSpotFeed)
feed = ExchangeRegistry.create_feed("BINANCE___SPOT", data_queue)
```

### API 参考

- [注册表](api/registry.md) — 插件注册系统
- [事件总线](api/event_bus.md) — 发布/订阅事件分发器
- [WebSocket 管理器](api/websocket_manager.md) — 连接池与自动重连
- [缓存](api/cache.md) — 三级缓存与 TTL
- [限流器](api/rate_limiter.md) — 限流算法
- [异常](api/exceptions.md) — 异常层次结构与谓词
- [配置加载器](api/config_loader.md) — Pydantic YAML 验证
- [Feeds](api/feeds.md) — AbstractVenueFeed 协议
- [容器](api/containers.md) — 数据容器
- [网关](api/gateway.md) — 网关适配器
- [插件](api/plugins.md) — 插件系统

### 在线文档

| 资源 | 链接 |
|----------|------|
| 英文文档 | https://bt-api-base.readthedocs.io/ |
| 中文文档 | https://bt-api-base.readthedocs.io/zh/latest/ |
| GitHub 仓库 | https://github.com/cloudQuant/bt_api_base |
| PyPI 包 | https://pypi.org/project/bt_api_base/ |
