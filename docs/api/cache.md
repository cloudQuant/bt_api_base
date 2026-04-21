---
title: Cache | bt_api_base
---

<!-- English -->
# Cache

The `cache` module provides **three-tier caching** with TTL support and thread-safe operations:

1. `SimpleCache` — General-purpose in-memory cache
2. `ExchangeInfoCache` — Exchange metadata cache
3. `MarketDataCache` — Market data cache with hit rate tracking

## SimpleCache

General-purpose thread-safe cache with TTL and size limits.

```python
class SimpleCache:
    def __init__(
        self,
        default_ttl: float = 300.0,
        max_size: int = 10000,
        on_evict: Optional[Callable[[str, Any], None]] = None,
    ):
```

#### Methods

##### `get(key: str, default: Any = None) -> Any`

Retrieve a value. Returns `default` if not found or expired.

```python
value = cache.get("BTCUSDT_ticker", default=None)
```

##### `set(key: str, value: Any, ttl: Optional[float] = None) -> None`

Store a value with optional TTL override.

```python
cache.set("BTCUSDT_ticker", ticker_data, ttl=60.0)
```

##### `delete(key: str) -> bool`

Delete a key. Returns True if found and deleted.

```python
deleted = cache.delete("BTCUSDT_ticker")
```

##### `clear() -> None`

Clear all entries.

```python
cache.clear()
```

##### `stats() -> Dict[str, Any]`

Return cache statistics (hits, misses, size, hit rate).

```python
stats = cache.stats()
# {"hits": 150, "misses": 10, "size": 42, "hit_rate": 0.937}
```

## ExchangeInfoCache

Cache for exchange metadata (trading rules, symbol info, etc.).

```python
cache = ExchangeInfoCache(default_ttl=3600.0)
cache.set_exchange_info("BINANCE", exchange_info)
info = cache.get_exchange_info("BINANCE")
```

## MarketDataCache

Cache for market data with hit rate tracking per symbol.

```python
cache = MarketDataCache(default_ttl=5.0)
cache.set_market_data("BTCUSDT", "ticker", ticker)
data = cache.get_market_data("BTCUSDT", "ticker")
```

## Decorator: `@cached`

Function-level cache decorator.

```python
from bt_api_base.cache import cached

@cached(ttl=60)
def fetch_exchange_info():
    return requests.get("/api/v3/exchangeInfo").json()
```

---

## 中文

### 概述

`cache` 模块提供**三级缓存**，支持 TTL 和线程安全操作：

1. `SimpleCache` — 通用内存缓存
2. `ExchangeInfoCache` — 交易所元数据缓存
3. `MarketDataCache` — 市场数据缓存，带命中率追踪

### SimpleCache

| 方法 | 说明 |
|------|------|
| `get(key, default)` | 获取值，不存在或过期返回 default |
| `set(key, value, ttl)` | 存储值，可选 TTL 覆盖 |
| `delete(key)` | 删除键 |
| `clear()` | 清空所有条目 |
| `stats()` | 返回缓存统计（命中、未命中、大小、命中率） |

### @cached 装饰器

```python
@cached(ttl=60)
def fetch_exchange_info():
    return requests.get("/api/v3/exchangeInfo").json()
```

### 使用示例

```python
from bt_api_base.cache import SimpleCache

cache = SimpleCache(default_ttl=300.0, max_size=10000)
cache.set("key", value, ttl=60)
value = cache.get("key")
stats = cache.stats()
```
