"""
Caching utilities for performance optimization.

Provides in-memory caching for frequently accessed data like exchange info,
trading pairs, and market data.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator
from functools import wraps
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])
_CACHE_MISSING = object()

__all__ = [
    "SimpleCache",
    "ExchangeInfoCache",
    "MarketDataCache",
    "cached",
    "get_exchange_info_cache",
    "get_market_data_cache",
]


class SimpleCache:
    """
    Simple in-memory cache with TTL (Time To Live) support.

    Features:
    - Key-value storage with expiration
    - Automatic cleanup of expired entries
    - Thread-safe operations (basic)
    """

    def __init__(self, default_ttl: float = 300.0, max_size: int | None = 10000) -> None:
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def _get_or_default(self, key: str, default: Any) -> Any:
        with self._lock:
            cached_entry = self._cache.get(key)
            if cached_entry is None:
                self._misses += 1
                return default

            value, expiry = cached_entry
            if time.time() > expiry:
                self._cache.pop(key, None)
                self._misses += 1
                return default

            self._hits += 1
            self._cache.move_to_end(key)
            return value

    def get(self, key: str) -> Any | None:
        return self._get_or_default(key, None)

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        if ttl is None:
            ttl = self._default_ttl

        expiry = time.time() + ttl
        with self._lock:
            if key in self._cache:
                self._cache.pop(key)
            self._cache[key] = (value, expiry)
            if self._max_size is not None and self._max_size > 0:
                while len(self._cache) > self._max_size:
                    self._cache.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def cleanup(self) -> int:
        with self._lock:
            now = time.time()
            active_cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
            removed = 0
            for key, entry in self._cache.items():
                if now > entry[1]:
                    removed += 1
                else:
                    active_cache[key] = entry
            self._cache = active_cache
            return removed

    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._cache.keys())

    def get_stats(self) -> dict[str, float]:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total else 0.0
            return {
                "size": float(len(self._cache)),
                "hits": float(self._hits),
                "misses": float(self._misses),
                "hit_rate": hit_rate,
            }


class ExchangeInfoCache:
    """Specialized cache for exchange information."""

    def __init__(self, ttl: float = 3600.0) -> None:
        self._cache = SimpleCache(default_ttl=ttl)

    def get_trading_pairs(self, exchange: str) -> list[str] | None:
        return self._cache.get(f"{exchange}:trading_pairs")

    def set_trading_pairs(self, exchange: str, pairs: list[str]) -> None:
        self._cache.set(f"{exchange}:trading_pairs", pairs)

    def get_exchange_info(self, exchange: str, symbol: str) -> dict[str, Any] | None:
        return self._cache.get(f"{exchange}:{symbol}:info")

    def set_exchange_info(self, exchange: str, symbol: str, info: dict[str, Any]) -> None:
        self._cache.set(f"{exchange}:{symbol}:info", info)

    def clear_exchange(self, exchange: str) -> None:
        keys_to_delete = [key for key in self._cache if key.startswith(f"{exchange}:")]
        for key in keys_to_delete:
            self._cache.delete(key)


class MarketDataCache:
    """Cache for market data with shorter TTL."""

    def __init__(self, ttl: float = 5.0) -> None:
        self._cache = SimpleCache(default_ttl=ttl)

    def get_ticker(self, exchange: str, symbol: str) -> Any | None:
        return self._cache.get(f"{exchange}:{symbol}:ticker")

    def set_ticker(self, exchange: str, symbol: str, ticker: Any) -> None:
        self._cache.set(f"{exchange}:{symbol}:ticker", ticker)

    def get_orderbook(self, exchange: str, symbol: str) -> Any | None:
        return self._cache.get(f"{exchange}:{symbol}:orderbook")

    def set_orderbook(self, exchange: str, symbol: str, orderbook: Any) -> None:
        self._cache.set(f"{exchange}:{symbol}:orderbook", orderbook)


def cached(
    ttl: float = 300.0,
    cache_instance: SimpleCache | None = None,
    maxsize: int | None = None,
) -> Callable[[F], F]:
    """Decorator for caching function results."""
    if cache_instance is None:
        cache_instance = SimpleCache(default_ttl=ttl, max_size=maxsize)

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key_parts = [func.__name__]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(key_parts)

            cached_value = cache_instance._get_or_default(cache_key, _CACHE_MISSING)
            if cached_value is not _CACHE_MISSING:
                return cached_value

            result = func(*args, **kwargs)
            cache_instance.set(cache_key, result, ttl)
            return result

        wrapper.cache = cache_instance  # type: ignore
        wrapper.clear_cache = cache_instance.clear  # type: ignore
        wrapper.cache_stats = cache_instance.get_stats  # type: ignore

        return wrapper  # type: ignore

    return decorator


# Global cache instances
_exchange_info_cache = ExchangeInfoCache()
_market_data_cache = MarketDataCache()


def get_exchange_info_cache() -> ExchangeInfoCache:
    return _exchange_info_cache


def get_market_data_cache() -> MarketDataCache:
    return _market_data_cache
