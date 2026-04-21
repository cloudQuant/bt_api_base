---
title: Feeds | bt_api_base
---

<!-- English -->
# Feeds

The `feeds` module defines the **AbstractVenueFeed protocol** — the standardized interface that all exchange plugins must implement.

## Overview

`AbstractVenueFeed` is a **Protocol** (structural subtyping in Python) that defines the contract every exchange feed must fulfill. This ensures consistent behavior across all exchange plugins regardless of their underlying API differences.

## AbstractVenueFeed Protocol

```python
class AbstractVenueFeed(Protocol):
    """Protocol defining the interface for all exchange feeds."""

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def is_connected(self) -> bool: ...

    # Market Data
    async def get_tick(self, symbol: str) -> Optional[Ticker]: ...
    async def get_depth(self, symbol: str, count: int = 20) -> Optional[OrderBook]: ...
    async def get_kline(self, symbol: str, period: str, count: int = 100) -> Optional[List[Bar]]: ...

    # Trading
    async def make_order(self, order_request: OrderRequest) -> Order: ...
    async def cancel_order(self, symbol: str, order_id: str) -> bool: ...
    async def get_order(self, symbol: str, order_id: str) -> Optional[Order]: ...
    async def get_orders(self, symbol: str, limit: int = 100) -> List[Order]: ...

    # Account
    async def get_balance(self, asset: Optional[str] = None) -> List[Balance]: ...
    async def get_position(self, symbol: Optional[str] = None) -> List[Position]: ...

    @property
    def capabilities(self) -> FeedCapabilities: ...
```

## AsyncWrapperMixin

Provides async method wrappers around sync methods for feeds that only implement sync interfaces.

```python
class AsyncWrapperMixin:
    """Mixin providing async wrappers for sync methods."""

    async def async_get_tick(self, symbol: str) -> Optional[Ticker]:
        """Async wrapper for get_tick."""
        return self.get_tick(symbol)

    async def async_make_order(self, order_request: OrderRequest) -> Order:
        """Async wrapper for make_order."""
        return self.make_order(order_request)
```

## FeedCapabilities

```python
@dataclass
class FeedCapabilities:
    """Describes what a feed can do."""
    support_spot: bool = False
    support_margin: bool = False
    support_swap: bool = False
    support_future: bool = False
    support_option: bool = False
    support_order: bool = False
    support_cancel: bool = False
    support_balance: bool = False
    support_position: bool = False
    support_kline: bool = False
    support_depth: bool = False
```

---

## 中文

### 概述

`feeds` 模块定义了 **AbstractVenueFeed 协议** — 所有交易所插件必须实现的标准接口。

### AbstractVenueFeed 协议

`AbstractVenueFeed` 是一个 **Protocol**（Python 结构子类型），定义了每个交易所 feed 必须履行的契约。

### 主要方法

| 类别 | 方法 | 说明 |
|------|------|------|
| 连接 | `connect()`, `disconnect()`, `is_connected()` | 连接管理 |
| 行情 | `get_tick()`, `get_depth()`, `get_kline()` | 市场数据 |
| 交易 | `make_order()`, `cancel_order()`, `get_order()` | 订单操作 |
| 账户 | `get_balance()`, `get_position()` | 账户查询 |

### FeedCapabilities

描述 feed 的能力：

| 字段 | 说明 |
|------|------|
| `support_spot` | 支持现货 |
| `support_swap` | 支持合约 |
| `support_future` | 支持期货 |
| `support_option` | 支持期权 |
| `support_order` | 支持下单 |

### AsyncWrapperMixin

为仅实现同步接口的 feed 提供异步方法包装：

```python
class MyFeed(AsyncWrapperMixin):
    def get_tick(self, symbol: str):
        return self.fetch_tick_sync(symbol)
    # AsyncWrapperMixin provides async_get_tick() automatically
```
