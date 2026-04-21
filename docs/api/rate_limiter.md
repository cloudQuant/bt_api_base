---
title: RateLimiter | bt_api_base
---

<!-- English -->
# RateLimiter

The `rate_limiter` module provides **multi-algorithm rate limiting** with endpoint-level glob matching and weight mapping.

## Algorithms

### SlidingWindowLimiter

Uses a **sliding window** algorithm — the most accurate but most memory-intensive. Tracks requests in a rolling time window.

```python
limiter = SlidingWindowLimiter(interval=60, limit=1200)
# Allows 1200 requests per 60-second rolling window
```

### FixedWindowLimiter

Uses a **fixed window** algorithm — less accurate at window boundaries but memory-efficient.

```python
limiter = FixedWindowLimiter(interval=1, limit=10)
# Allows 10 requests per 1-second fixed window
```

### TokenBucketLimiter

Uses a **token bucket** algorithm — allows burst traffic up to bucket capacity, then refills at steady rate.

```python
limiter = TokenBucketLimiter(bucket_size=100, refill_rate=50)
```

## RateLimiter (High-Level Interface)

```python
class RateLimiter:
    def __init__(self, rules: List[RateLimitRule]):
```

### RateLimitRule

```python
@dataclass
class RateLimitRule:
    name: str
    type: RateLimitType
    interval: float
    limit: Union[int, float]
    scope: RateLimitScope
    endpoint: Optional[str] = None   # Glob pattern for endpoint matching
    weight_map: Optional[Dict[str, int]] = None  # Request weight by method
```

### RateLimitType

```python
class RateLimitType(Enum):
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"
    TOKEN_BUCKET = "token_bucket"
```

### RateLimitScope

```python
class RateLimitScope(Enum):
    GLOBAL = "global"           # Across all endpoints
    ENDPOINT = "endpoint"       # Per individual endpoint
    USER = "user"              # Per user (requires user_id)
```

## Usage

### Context Manager

```python
from bt_api_base.rate_limiter import RateLimiter, RateLimitRule, RateLimitType, RateLimitScope

rules = [
    RateLimitRule(
        name="global",
        type=RateLimitType.SLIDING_WINDOW,
        interval=60,
        limit=1200,
        scope=RateLimitScope.GLOBAL,
    ),
    RateLimitRule(
        name="order",
        type=RateLimitType.FIXED_WINDOW,
        interval=1,
        limit=10,
        scope=RateLimitScope.ENDPOINT,
        endpoint="/api/v3/order*",
        weight_map={"POST": 10, "DELETE": 5, "GET": 1},
    ),
]

limiter = RateLimiter(rules)

with limiter:
    response = requests.post("/api/v3/order", json=order_data)
```

### Endpoint Glob Matching

The `endpoint` field supports glob patterns:

```python
RateLimitRule(
    name="market",
    type=RateLimitType.FIXED_WINDOW,
    interval=1,
    limit=10,
    scope=RateLimitScope.ENDPOINT,
    endpoint="/api/v3/order*",  # Matches /api/v3/order, /api/v3/order/test
)
```

### Weight Mapping

Different HTTP methods consume different weights:

```python
RateLimitRule(
    name="order",
    type=RateLimitType.FIXED_WINDOW,
    interval=1,
    limit=10,
    scope=RateLimitScope.ENDPOINT,
    weight_map={"POST": 10, "DELETE": 5, "GET": 1},
)
# A POST to /api/v3/order consumes 10 units
# A GET to /api/v3/order consumes 1 unit
```

---

## 中文

### 概述

`rate_limiter` 模块提供**多算法限流**，支持端点级 glob 匹配和权重映射。

### 算法

| 算法 | 说明 | 特点 |
|------|------|------|
| `SlidingWindowLimiter` | 滑动窗口 | 最精确，内存消耗较高 |
| `FixedWindowLimiter` | 固定窗口 | 边界处精度较低，内存高效 |
| `TokenBucketLimiter` | 令牌桶 | 支持突发流量 |

### RateLimitRule

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | 规则名称 |
| `type` | RateLimitType | 限流算法 |
| `interval` | float | 时间窗口（秒） |
| `limit` | int/float | 限制数量 |
| `scope` | RateLimitScope | 作用范围 |
| `endpoint` | str | glob 模式匹配端点 |
| `weight_map` | dict | 请求方法权重映射 |

### 使用示例

```python
from bt_api_base.rate_limiter import RateLimiter, RateLimitRule, RateLimitType, RateLimitScope

rules = [
    RateLimitRule(name="global", type=RateLimitType.SLIDING_WINDOW,
                  interval=60, limit=1200, scope=RateLimitScope.GLOBAL),
    RateLimitRule(name="order", type=RateLimitType.FIXED_WINDOW,
                  interval=1, limit=10, scope=RateLimitScope.ENDPOINT,
                  endpoint="/api/v3/order*", weight_map={"POST": 10}),
]

limiter = RateLimiter(rules)
with limiter:
    response = requests.post("/api/v3/order", json=order_data)
```
