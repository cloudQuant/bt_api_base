---
title: WebSocketManager | bt_api_base
---

<!-- English -->
# WebSocketManager

The `WebSocketManager` provides **WebSocket connection pooling** with built-in features: auto-reconnect, heartbeat, backpressure handling, and subscription management.

## Overview

Each exchange feed gets its own `WebSocketManager` instance managing multiple concurrent connections. The manager handles connection lifecycle, automatic reconnection with exponential backoff, and dispatches incoming messages to registered callbacks.

## Configuration

### WebSocketConfig

```python
@dataclass
class WebSocketConfig:
    url: str                              # WebSocket endpoint URL
    exchange_name: str                     # Exchange identifier
    max_connections: int = 5               # Max concurrent connections
    heartbeat_interval: float = 30.0        # Heartbeat interval (seconds)
    reconnect_interval: float = 5.0        # Base reconnect interval (seconds)
    max_reconnect_attempts: int = 10       # Max reconnection tries
    connect_timeout: float = 10.0          # Connection timeout (seconds)
    subscription_limit: int = 100           # Max subscriptions per connection
    auto_reconnect: bool = True            # Enable auto-reconnect
```

## Class Reference

### WebSocketManager

```python
class WebSocketManager:
```

#### Methods

##### `add_exchange(config: WebSocketConfig) -> WebSocketConnection`

Add and connect an exchange with the given configuration.

```python
config = WebSocketConfig(
    url="wss://stream.binance.com:9443/ws",
    exchange_name="BINANCE___SPOT",
    max_connections=5,
)
conn = await manager.add_exchange(config)
```

##### `remove_exchange(exchange_name: str) -> None`

Disconnect and remove an exchange.

```python
await manager.remove_exchange("BINANCE___SPOT")
```

##### `subscribe(exchange_name: str, topic: str, symbol: str, callback: Callable) -> str`

Subscribe to an exchange topic. Returns a subscription ID.

```python
sub_id = await manager.subscribe(
    exchange_name="BINANCE___SPOT",
    topic="ticker",
    symbol="BTCUSDT",
    callback=on_ticker,
)
```

##### `unsubscribe(subscription_id: str) -> None`

Unsubscribe by subscription ID.

```python
await manager.unsubscribe(sub_id)
```

##### `is_connected(exchange_name: str) -> bool`

Check if an exchange is connected.

```python
if manager.is_connected("BINANCE___SPOT"):
    ...
```

##### `get_connection(exchange_name: str) -> Optional[WebSocketConnection]`

Get the connection object for an exchange.

```python
conn = manager.get_connection("BINANCE___SPOT")
```

##### `close() -> None`

Close all connections and shut down the manager.

```python
await manager.close()
```

## Connection Lifecycle

```
DISCONNECTED → CONNECTING → CONNECTED → (RECONNECTING) → CLOSED
```

- **CONNECTING**: Establishing TCP + TLS handshake
- **CONNECTED**: WebSocket ready, heartbeats active
- **RECONNECTING**: Lost connection, attempting reconnect with backoff
- **CLOSED**: All connections closed, manager shut down

## Backpressure Handling

When the incoming message rate exceeds processing capacity, the manager applies backpressure by dropping the oldest buffered messages, preventing memory exhaustion.

```python
config = WebSocketConfig(
    url="...",
    exchange_name="BINANCE___SPOT",
    max_connections=5,
    # Backpressure is handled automatically
)
```

---

## 中文

### 概述

`WebSocketManager` 提供 **WebSocket 连接池**，内置自动重连、心跳、背压处理和订阅管理功能。

### WebSocketConfig 配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `url` | str | — | WebSocket 端点 URL |
| `exchange_name` | str | — | 交易所标识符 |
| `max_connections` | int | 5 | 最大并发连接数 |
| `heartbeat_interval` | float | 30.0 | 心跳间隔（秒） |
| `reconnect_interval` | float | 5.0 | 基础重连间隔（秒） |
| `max_reconnect_attempts` | int | 10 | 最大重连次数 |
| `auto_reconnect` | bool | True | 启用自动重连 |

### 主要方法

| 方法 | 说明 |
|------|------|
| `add_exchange(config)` | 添加并连接交易所 |
| `remove_exchange(name)` | 断开并移除交易所 |
| `subscribe(name, topic, symbol, cb)` | 订阅主题 |
| `unsubscribe(sub_id)` | 取消订阅 |
| `is_connected(name)` | 检查连接状态 |
| `get_connection(name)` | 获取连接对象 |
| `close()` | 关闭所有连接 |

### 使用示例

```python
from bt_api_base.websocket_manager import WebSocketManager, WebSocketConfig

config = WebSocketConfig(
    url="wss://stream.binance.com:9443/ws",
    exchange_name="BINANCE___SPOT",
    max_connections=5,
)

manager = WebSocketManager()
await manager.add_exchange(config)

sub_id = await manager.subscribe(
    exchange_name="BINANCE___SPOT",
    topic="ticker",
    symbol="BTCUSDT",
    callback=on_ticker,
)
```
