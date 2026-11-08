# bt_api_base

Position-mode acknowledgement codes are provider declarations: the Base default is unspecified. Binance, CTP and non-swap OKX preserve the previous `200`; OKX swap preserves `0`, and ten historical policies retain `200`. These inherited values do not prove venue capability. Third-party Base subclasses no longer receive a default; dynamic policies, packaging and behavior remain unvalidated.

Binance/OKX bound read-only runtime registration and exact owner/config checks live in their providers; Base carries the SDK-injected API type, and SDK owns composition and finite error mapping. The two SDK-specific registration modules and `compose_binance_read_only_runtime` / `compose_okx_read_only_runtime` are removed. `compose_read_only_runtime` creates a new owner and differs from reusing an existing one. Entry points, thread/cleanup and behavior remain unaccepted.

Execution-ledger identity format is declared per provider via `bt_api_base.execution_ledger_identity_policy`, not hard-coded venue names. The 13 built-in providers retain their prior format choices; this does not prove identity. Missing or undiscoverable declarations fail, including historical/custom providers, and successful selections are process-cached. Migration, packaging and behavior remain unaccepted. A separate provider `account_risk_source_policy` declares whether native account binding is still required for neutral risk reads. CTP remains unavailable; the other 12 retain the old branch, not proof of source. Undeclared providers fail and discovery/behavior are unaccepted.

CTP managed Risk order payload construction and cancel-target matching live in `bt_api_ctp.risk_dispatch_binding`; Base declares the optional provider contract, while SDK retains evidence selection, claims and journal fencing. Target orders with a schema now require a matching provider declaration: undeclared schemas fail, a breaking change. Journal compatibility and behavior remain unvalidated.

Order-status and trade-fee field candidates are selected by provider policy. All 13 providers explicitly declare order-status candidates: Binance, OKX and CTP retain their existing declarations, while the other ten each declare `status`, `order_status` and `state`; the Base legacy policy no longer declares these candidates. Trade-fee candidates remain policy-selected. A policy without declarations fails explicitly. This field ownership move does not establish native status coverage; third-party policies and behavior remain unvalidated. Placement position-mode fencing is also provider-declared: OKX/Binance retain the existing guard, other built-in routes retain the previous unguarded behavior, and undeclared routes reject placement. This breaking change does not prove venue capability.

All 13 providers explicitly declare `trade_id_fields` using neutral names and native fields confirmed in their container source; Base defaults to `None` and the SDK reads the selected fields. Bybit, dYdX and Kraken declare no additional native trade-ID fields. Unconfirmed generic `id`/`tradeId` aliases are no longer assumed across venues; narrowing and additions are breaking changes. The `group_fill` provenance alias contract is separate: IDs including Gateio, HTX and MEXC still require verification and normalization does not prove them. Dynamic inputs and behavior remain unvalidated.

Order-identity aliases have neutral and explicit historical contracts. The SDK rejects known aliases outside the selected provider policy; this does not establish source authenticity and remains unvalidated.

Base tick trading-day and action-day defaults are `None`; CTP explicitly selects `TradingDay` and `ActionDay` alongside neutral names, while the other 12 providers explicitly select neutral names only. The former uppercase candidates for the other ten have been removed; dynamic input coverage remains unvalidated. Base order-book audit/sequence defaults exclude Binance native aliases, while the explicit historical policy retains those order-book aliases for legacy providers. Permission, position-mode, event-identity and instrument-symbol defaults are also neutral. Selected Binance/OKX/CTP aliases in balance, position, order, trade, status and mode defaults now reside in the explicit legacy policy; four dependent provider mappings were switched to that policy. Other listed static declarations retain their previous fields for the 13 built-in providers. Third-party Base subclasses change behavior and coverage remains unaccepted. The working tree defines neutral order-source fields; providers explicitly declare their native fields and aliases and select scoped v5/v6 schemas. This selection is not source attestation and remains unvalidated.

The working tree builds provider-scoped candidate alias maps from neutral aliases and each provider’s declarations, using v5/v6; the v1–v4 contracts have been removed. Risk/group proofs use only v6. Bybit, dYdX and Kraken currently declare no native fill aliases and their coverage requires review. Current provider coverage and proof behavior remain unvalidated.

The working-tree order provenance projection also checks source snapshot shape and digest with caller-selected schema and hashing. The caller remains responsible for source authenticity; behavior remains unvalidated.

Provider policies declare any nested order-identity shape; the Base default no longer treats Binance user-stream fields as universal. Other providers and behavior remain unvalidated.

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

### Role in the trading-system architecture

The working-tree `order_provenance_projection` projects finite source fields and a digest using SDK-selected field contracts; it does not authenticate the provider. Source and distribution remain unaccepted.

The working-tree `execution_identity_projection` also compares explicit ledger order identity fields using caller-supplied provider unit resolution; it does not establish source authenticity. Behavior and distribution remain unaccepted.

`bt_api_base` supplies reusable, provider-neutral contracts and shared primitives to the SDK packages. It defines common data shapes and interfaces; it does not establish that supplied account or provider facts are trusted or authorize a live order. Those authorities come from the trusted runtime composition and the component that owns each fact.

`risk_dispatch_evidence` defines a provider declaration for venue-specific risk evidence validation; it provides no provider authority or Risk permit. Its source and distribution have not been validated.

Neutral normalized order-observation and finite source-projection types reside in `order_observation_contracts`; the SDK normalization module imports those same types. These shapes do not establish provider truth and have not passed behavior or distribution acceptance.

The working-tree legacy order-side helper accepts a full row and selects its historical aliases without inspecting provider-specific nested data. Its projector entry-point signature changed and remains unvalidated.

The working-tree `logging_context` owns shared context-local log identifiers for SDK and Monitor consumers; `logging_setup` owns their shared explicit process-logging configuration. These identifiers are diagnostics, not account or authorization evidence; distribution and behavior remain unvalidated.

[Trading system architecture overview](https://github.com/cloudQuant/backtrader/blob/dev/docs/TRADING_SYSTEM_ARCHITECTURE.md).

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
│   ├── plugins/             # PluginInfo, PluginLoader, isolated feed registration
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

The default install uses Python's standard logging fallback. To enable the
native `spdlog` backend and daily-rotating file sink, install the optional extra:

```bash
pip install "bt_api_base[spdlog]"
```

Without this extra, file and optional console logging still work, but log files
do not rotate daily.

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

### 本项目在交易系统架构中的职责

`bt_api_base` 为 SDK 子包提供可复用、provider-neutral 的公共契约和基础组件，定义通用数据结构与接口；它本身不验证外部账户或行情事实的可信性，也不授权实盘订单。可信事实与运行权限由受信运行时组装和相应权威组件负责。

[交易系统架构总览](https://github.com/cloudQuant/backtrader/blob/dev/docs/TRADING_SYSTEM_ARCHITECTURE.md)。

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
│   ├── plugins/             # PluginInfo, PluginLoader, 隔离 feed 注册
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

默认安装使用 Python 标准日志后端。如需启用原生 `spdlog` 和按日轮转的文件
日志，请安装可选依赖：

```bash
pip install "bt_api_base[spdlog]"
```

不安装此可选依赖时，文件日志和可选控制台日志仍可使用，但日志文件不会按日轮转。

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

## Iteration 63 settlement observation contracts

`direct_write_protocol` adds immutable `SettlementObservation` and
`SettlementWriteBinding` values. A settlement grant binds the original
UNCONFIRMED observation to its durable marker. Providers explicitly declare
`settlement_required`; the conditional `SettlementRequiredProvider` contract
adds observation validation and confirmation only for required routes.
These values describe a binding; the provider must establish and validate
query provenance, current account/session identity and expiry. The SDK's trusted
verifier and commit port retain authorization and durability responsibilities.
This is a breaking development contract, not account or release acceptance.

## Iteration 63 normalized execution returns

`gateway_execution_protocol.GatewayReturnFact` is an immutable schema-v1 value
for trusted local adapters. Its strict mapping codec retains missing fields,
uses canonical decimal strings and separates full fact identity from trade
economics. Digests support durable comparison; they do not authenticate provider
provenance, account access or trading permission. The Gateway owns persistence
and attribution; provider/SDK code must establish native identity, trading-day
and query completeness before supplying these values.

## Iteration 63 public execution stream values

`gateway_execution_stream_protocol` defines strict schema-v1 observations,
events, pages and progress values for authenticated strategy delivery. Pages
allow gaps in the account-wide sequence. Command attribution is supplied by the
Gateway ledger; the values themselves grant no permission. Native identity and
association keys are exposed only as deterministic SHA-256 correlation labels,
not as source authentication or anonymization. Source labels and arbitrary
native identity fields are not included. The original command identity remains
available through the separately authorized command-status contract.


### Iteration 63: prepared cancel contract (R15)

`direct_cancel_protocol.PreparedCancelRequest` records an immutable, bounded native cancellation preparation, including the original target identity, the separate dispatch day/generation, exact request fields and sorted unique attempt keys. Version 1 mapping and canonical digest checks do not authenticate a provider or authorize a write. `PreDispatchRecord.prepared_cancel` is optional and appears in serialized records only when supplied; its operation, route, target, symbol and dispatch scope must match. `DirectSubmitResult.sent` may be `None` for an uncertain synchronous result. Existing unprepared cancellation remains a separate API path. Provider support and complete Gateway behavior require independent verification.


### Iteration 63 R16: public cancellation observations

`gateway_cancel_protocol.GatewayCancelRecord` is a strict, bounded version-1 observation of a single cancellation attempt. It binds the journal, account, strategy, principal and original command, exposes only finite public error categories, and carries no prepared native fields. `SENT` describes submission of the cancellation request, not cancellation of the venue order. Authentication and venue facts remain separate responsibilities.


### Iteration 63 R17: versioned cancel sources and error observations

PreparedCancelRequest optionally seals provider source labels in schema v2; None retains the exact v1 mapping and digest. Source labels do not authorize a request. CANCEL_ERROR facts may use explicit v2 with a cancel_request_key included in their digest, separating repeated cancellation attempts for one order. Existing v1 fact digests remain unchanged. New execution pages encode v2 with optional operation/attempt/prepared-digest attribution; old v1 pages are strictly decoded, and public observations retain their redacted v1 shape.


### Iteration 63 R19 protocol additions

`PreparedPlaceRequest` is a bounded immutable value for an explicitly selected prepared native placement. It binds the identity, day/generation, request fields, source labels and operation-specific keys; these values do not grant authority. `PreDispatchRecord.prepared_place` is optional and restricted to PLACE. Its absence preserves the prior marker encoding.

Return fact v3 is restricted to source-associated ORDER_ERROR with a place request key and no order status; v1/v2 encodings and digests remain unchanged. Public execution event/page v3 adds `GatewayPlaceErrorAttribution(prepared_digest)` without exposing native request/source fields, and still decodes exact v1/v2 input. The common canonical payload format still rejects binary floats; providers choose an explicit representation for native values.
