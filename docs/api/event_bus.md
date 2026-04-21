---
title: EventBus | bt_api_base
---

<!-- English -->
# EventBus

The `EventBus` is a **pub/sub event dispatcher** that supports two operational modes:

1. **Queue mode** (default, backward compatible): Collects events into queues for later consumption
2. **Callback mode**: Directly invokes registered callbacks — essential for CTP SPI / IB EWrapper callback-driven APIs

## Overview

The `EventBus` is the backbone of the event-driven architecture in bt_api. All exchange feeds publish events (ticker updates, order fills, errors) through the bus, and consumers subscribe to specific event types.

## Error Handling Modes

```python
class ErrorHandlerMode(Enum):
    LOG = "log"        # Log errors and continue
    RAISE = "raise"    # Raise the first error
    COLLECT = "collect" # Collect all errors, return them
```

## Class Reference

### EventBus

```python
class EventBus:
    def __init__(
        self,
        error_mode: ErrorHandlerMode = ErrorHandlerMode.LOG,
        queue_class: Type[Queue] = Queue,
    ):
```

#### Methods

##### `on(event_type: str, callback: Callable, priority: int = 0) -> None`

Subscribe a callback to an event type. Higher priority callbacks execute first.

```python
bus.on("order_filled", lambda data: print(f"Order filled: {data}"))
bus.on("tick_update", update_chart, priority=10)
```

##### `off(event_type: str, callback: Callable) -> None`

Unsubscribe a callback from an event type.

```python
bus.off("order_filled", my_callback)
```

##### `emit(event_type: str, data: Any) -> List[Exception]`

Emit an event with data to all registered callbacks.

```python
errors = bus.emit("order_filled", {"order_id": "123", "filled": 0.5})
```

##### `clear(event_type: Optional[str] = None) -> None`

Clear all callbacks for an event type, or all callbacks if no type specified.

```python
bus.clear("order_filled")  # Clear specific event
bus.clear()                # Clear all events
```

##### `listener_count(event_type: str) -> int`

Return the number of listeners for an event type.

```python
count = bus.listener_count("tick_update")
```

## Queue Mode vs Callback Mode

**Queue mode** (default):
```python
bus = EventBus()  # Uses Queue internally
bus.on("tick", handler)
```

**Callback mode** (for CTP/IB):
```python
bus = EventBus(error_mode=ErrorHandlerMode.CALLBACK)
bus.on("order", ctp_spi.on_order)  # Directly calls the callback
```

---

## 中文

### 概述

`EventBus` 是支持两种操作模式的**发布/订阅事件分发器**：

1. **Queue 模式**（默认，向后兼容）：将事件收集到队列供后续消费
2. **Callback 模式**：直接调用注册的回调 — 对于 CTP SPI / IB EWrapper 回调驱动的 API 必不可少

### 错误处理模式

| 模式 | 说明 |
|------|------|
| `LOG` | 记录错误并继续 |
| `RAISE` | 抛出第一个错误 |
| `COLLECT` | 收集所有错误并返回 |

### 主要方法

| 方法 | 说明 |
|------|------|
| `on(event_type, callback, priority)` | 订阅事件回调 |
| `off(event_type, callback)` | 取消订阅 |
| `emit(event_type, data)` | 发布事件 |
| `clear(event_type)` | 清除回调 |
| `listener_count(event_type)` | 获取监听器数量 |

### 使用示例

```python
from bt_api_base.event_bus import EventBus, ErrorHandlerMode

bus = EventBus(error_mode=ErrorHandlerMode.LOG)

bus.on("order_filled", lambda data: print(f"订单成交: {data}"))
errors = bus.emit("order_filled", {"order_id": "123", "filled": 0.5})
```
