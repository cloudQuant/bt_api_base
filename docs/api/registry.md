---
title: ExchangeRegistry | bt_api_base
---

<!-- English -->
# ExchangeRegistry

The `ExchangeRegistry` is the **central plugin registration system** for the bt_api ecosystem. It implements the **Registry Pattern**, providing both a global singleton (backward compatible) and isolated instances (for testing and multi-tenant scenarios).

## Overview

The registry maps exchange name strings (e.g., `"BINANCE___SPOT"`) to concrete feed class implementations. All exchange plugins register themselves at import time, and the `BtApi` main class delegates to the registry at runtime.

## Key Design: Dual-Mode Descriptor

`ExchangeRegistry` uses a custom descriptor `_ClassMethodOrInstance` that adapts behavior based on call context:

- **Class call** (`ExchangeRegistry.register_feed(...)`): Class-level registration
- **Instance call** (`registry.register_feed(...)`): Instance-level isolated registration

This allows the same API to work both as a global singleton and as isolated instances.

## Class Reference

### ExchangeRegistry

```python
class ExchangeRegistry:
```

#### Methods

##### `register_feed(exchange_name: str, feed_class: Type[AbstractVenueFeed]) -> None`

Register a feed class to an exchange name.

```python
ExchangeRegistry.register_feed("BINANCE___SPOT", BinanceSpotFeed)
```

##### `unregister_feed(exchange_name: str) -> None`

Unregister a feed class from an exchange name.

```python
ExchangeRegistry.unregister_feed("BINANCE___SPOT")
```

##### `create_feed(exchange_name: str, data_queue: Queue, **kwargs) -> AbstractVenueFeed`

Create an instance of the registered feed class.

```python
feed = ExchangeRegistry.create_feed("BINANCE___SPOT", data_queue)
```

##### `get_registered_feed(exchange_name: str) -> Optional[Type[AbstractVenueFeed]]`

Retrieve the registered feed class without instantiation.

```python
feed_class = ExchangeRegistry.get_registered_feed("BINANCE___SPOT")
```

##### `is_registered(exchange_name: str) -> bool`

Check if an exchange name is registered.

```python
if ExchangeRegistry.is_registered("BINANCE___SPOT"):
    ...
```

##### `list_registered() -> List[str]`

List all registered exchange names.

```python
exchanges = ExchangeRegistry.list_registered()
```

##### `create_isolated() -> "ExchangeRegistry"`

Factory method to create an isolated registry instance.

```python
registry = ExchangeRegistry.create_isolated()
registry.register_feed("TEST___SPOT", MockFeed)
```

#### Singleton vs Isolated

**Global singleton** (backward compatible):
```python
from bt_api_base.registry import ExchangeRegistry

ExchangeRegistry.register_feed("BINANCE___SPOT", BinanceSpotFeed)
feed = ExchangeRegistry.create_feed("BINANCE___SPOT", data_queue)
```

**Isolated instance** (for testing):
```python
registry = ExchangeRegistry.create_isolated()
registry.register_feed("TEST___SPOT", MockFeed)
feed = registry.create_feed("TEST___SPOT", data_queue)
```

---

## 中文

### 概述

`ExchangeRegistry` 是 bt_api 生态系统的**中央插件注册系统**。它实现了**注册表模式**，同时提供全局单例（向后兼容）和隔离实例（用于测试和多租户场景）。

### 核心设计：双模式描述符

`ExchangeRegistry` 使用自定义描述符 `_ClassMethodOrInstance`，根据调用上下文自适应行为：

- **类调用** (`ExchangeRegistry.register_feed(...)`): 类级注册
- **实例调用** (`registry.register_feed(...)`): 实例级隔离注册

### 主要方法

| 方法 | 说明 |
|------|------|
| `register_feed(name, cls)` | 注册 feed 类到交易所名称 |
| `unregister_feed(name)` | 取消注册 |
| `create_feed(name, queue, **kwargs)` | 创建 feed 实例 |
| `get_registered_feed(name)` | 获取已注册的 feed 类 |
| `is_registered(name)` | 检查是否已注册 |
| `list_registered()` | 列出所有已注册名称 |
| `create_isolated()` | 创建隔离的注册表实例 |

### 使用示例

```python
from bt_api_base.registry import ExchangeRegistry

# 全局单例
ExchangeRegistry.register_feed("BINANCE___SPOT", BinanceSpotFeed)
feed = ExchangeRegistry.create_feed("BINANCE___SPOT", data_queue)

# 隔离实例
registry = ExchangeRegistry.create_isolated()
registry.register_feed("TEST___SPOT", MockFeed)
```
