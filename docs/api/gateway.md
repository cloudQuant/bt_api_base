---
title: Gateway | bt_api_base
---

<!-- English -->
# Gateway

The `gateway` module provides **adapter layer** for translating between exchange-specific APIs and the standardized bt_api interface.

## Overview

Each exchange has its own request/response format. The gateway adapters normalize these differences, providing a unified interface to the rest of the system.

## BaseGatewayAdapter

```python
class BaseGatewayAdapter:
    """Base class for all gateway adapters."""

    def __init__(self, exchange_name: str):
        self.exchange_name = exchange_name

    def normalize_order_request(self, request: OrderRequest) -> Dict[str, Any]:
        """Convert OrderRequest to exchange-specific format."""
        ...

    def denormalize_order_response(self, response: Any) -> Order:
        """Convert exchange response to Order container."""
        ...

    def normalize_subscription(self, topic: str, symbol: str) -> Dict[str, Any]:
        """Convert subscription request to exchange-specific format."""
        ...

    def denormalize_message(self, message: Any) -> Optional[Container]:
        """Convert exchange WebSocket message to container."""
        ...
```

## PluginGatewayAdapter

For exchange plugins that implement the `PluginProtocol`:

```python
class PluginGatewayAdapter(BaseGatewayAdapter):
    """Gateway adapter for PluginProtocol-based feeds."""

    def __init__(self, feed: AbstractVenueFeed, exchange_name: str):
        ...
```

## Request Models

### NormalizedRequest

```python
@dataclass
class NormalizedRequest:
    method: str           # "GET", "POST", "DELETE"
    endpoint: str         # "/api/v3/order"
    params: Dict[str, Any]
    headers: Dict[str, str]
    body: Optional[Dict[str, Any]]
    timestamp: int
    signature: Optional[str]
```

### NormalizedResponse

```python
@dataclass
class NormalizedResponse:
    status_code: int
    headers: Dict[str, str]
    body: Any
    request: NormalizedRequest
    elapsed_ms: float
```

---

## 中文

### 概述

`gateway` 模块提供**适配器层**，用于在交易所特定 API 和标准化 bt_api 接口之间进行转换。

### BaseGatewayAdapter

| 方法 | 说明 |
|------|------|
| `normalize_order_request()` | 将 OrderRequest 转换为交易所特定格式 |
| `denormalize_order_response()` | 将交易所响应转换为 Order 容器 |
| `normalize_subscription()` | 将订阅请求转换为交易所特定格式 |
| `denormalize_message()` | 将交易所 WebSocket 消息转换为容器 |

### Request Models

```python
# 规范化请求
@dataclass
class NormalizedRequest:
    method: str       # "GET", "POST", "DELETE"
    endpoint: str     # "/api/v3/order"
    params: Dict
    headers: Dict
    body: Optional[Dict]
    timestamp: int
    signature: Optional[str]

# 规范化响应
@dataclass
class NormalizedResponse:
    status_code: int
    headers: Dict
    body: Any
    request: NormalizedRequest
    elapsed_ms: float
```

### 作用

- **标准化**: 将所有交易所的格式统一
- **隔离**: 交易所 API 变化不会影响核心逻辑
- **可扩展**: 新增交易所只需实现新的适配器
