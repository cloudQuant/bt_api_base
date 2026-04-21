---
title: Containers | bt_api_base
---

<!-- English -->
# Containers

The `containers` module provides **standardized data containers** for all exchange data types. These are the canonical data structures used across the bt_api ecosystem.

## Overview

Containers ensure **consistent field semantics** across all exchange plugins. Whether you connect to Binance, OKX, or CTP, the `Order`, `Position`, and `Balance` containers always have the same field structure.

## Container Types

### Market Data Containers

| Container | Description |
|-----------|-------------|
| `Instrument` | Trading instrument/symbol metadata |
| `Ticker` | 24hr ticker statistics |
| `OrderBook` | Order book depth (bids/asks) |
| `Bar` | OHLCV candlestick/k-line |
| `MarkPrice` | Mark price for futures |
| `FundingRate` | Perpetual funding rate |
| `Trade` | Individual trade tick |
| `Liquidation` | Liquidation order |
| `Greek` | Options Greeks (delta, gamma, etc.) |

### Account Containers

| Container | Description |
|-----------|-------------|
| `Order` | Order with status, fills, fees |
| `Position` | Open position with PnL |
| `Balance` | Asset balance |
| `Account` | Full account information |
| `Income` | Transaction/income history |
| `FundingRate` | Funding payment |

### Request Containers

| Container | Description |
|-----------|-------------|
| `OrderRequest` | Order placement request |
| `CancelRequest` | Order cancellation request |
| `SubscribeRequest` | WebSocket subscription request |

## Common Container Fields

### Order

```python
@dataclass
class Order:
    exchange_name: str
    symbol: str
    order_id: str
    client_order_id: Optional[str]
    order_type: str          # "limit", "market", "stop_limit", etc.
    side: str                 # "buy" or "sell"
    price: float
    volume: float
    filled_volume: float
    avg_fill_price: float
    status: str               # "pending", "filled", "partial", "cancelled"
    create_time: datetime
    update_time: datetime
```

### Position

```python
@dataclass
class Position:
    exchange_name: str
    symbol: str
    side: str                 # "long" or "short"
    volume: float
    open_price: float
    mark_price: float
    unrealized_pnl: float
    realized_pnl: float
    leverage: int
    margin: float
```

### Balance

```python
@dataclass
class Balance:
    exchange_name: str
    asset: str
    free: float               # Available balance
    locked: float              # Locked in orders
    total: float              # Total = free + locked
```

---

## 中文

### 概述

`containers` 模块提供**标准化数据容器**，用于所有交易所数据类型。这些是 bt_api 生态系统中使用的规范数据结构。

### 市场数据容器

| 容器 | 说明 |
|------|------|
| `Instrument` | 交易标的元数据 |
| `Ticker` | 24小时行情统计 |
| `OrderBook` | 订单簿深度 |
| `Bar` | K线/蜡烛图 |
| `MarkPrice` | 合约标记价格 |
| `FundingRate` | 资金费率 |
| `Trade` | 逐笔成交 |
| `Liquidation` | 强平订单 |

### 账户容器

| 容器 | 说明 |
|------|------|
| `Order` | 订单（状态、成交、手续费） |
| `Position` | 持仓（盈亏、杠杆） |
| `Balance` | 资产余额 |
| `Account` | 完整账户信息 |
| `Income` | 资金流水 |

### 通用字段

所有容器都包含 `exchange_name` 字段，确保跨交易所字段语义一致。
