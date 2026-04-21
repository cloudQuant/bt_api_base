"""
Connection pool management for WebSocket and HTTP connections.

Provides efficient connection reuse and management to improve performance
and reduce resource usage.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Generic, TypeVar

T = TypeVar("T")

_logger = logging.getLogger(__name__)


class ConnectionPool(Generic[T]):
    """
    Generic connection pool for managing reusable connections.

    Features:
    - Connection reuse
    - Automatic cleanup of idle connections
    - Thread-safe operations
    - Health checking
    """

    def __init__(
        self,
        factory: Callable[[], T],
        max_size: int = 10,
        min_size: int = 2,
        max_idle_time: float = 300.0,
        health_check: Callable[[T], bool] | None = None,
    ) -> None:
        self._factory = factory
        self._max_size = max_size
        self._min_size = min_size
        self._max_idle_time = max_idle_time
        self._health_check = health_check

        self._pool: deque[tuple[T, float]] = deque()
        self._in_use: set[T] = set()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._cleanup_thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return

        self._running = True

        with self._lock:
            for _ in range(self._min_size):
                conn = self._factory()
                self._pool.append((conn, time.time()))

        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def stop(self) -> None:
        self._running = False

        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5.0)

        with self._lock:
            while self._pool:
                conn, _ = self._pool.popleft()
                self._close_connection(conn)

            for conn in tuple(self._in_use):
                self._close_connection(conn)
            self._in_use.clear()

    def acquire(self, timeout: float | None = None) -> T:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while True:
                while self._pool:
                    conn, _ = self._pool.popleft()

                    if self._health_check and not self._health_check(conn):
                        self._close_connection(conn)
                        continue

                    self._in_use.add(conn)
                    return conn

                if len(self._in_use) < self._max_size:
                    conn = self._factory()
                    self._in_use.add(conn)
                    return conn

                if timeout is None:
                    raise RuntimeError("Connection pool exhausted")

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Connection pool acquire timeout")
                self._condition.wait(timeout=remaining)

    def release(self, conn: T) -> None:
        with self._condition:
            if conn not in self._in_use:
                return

            self._in_use.remove(conn)

            if self._health_check and not self._health_check(conn):
                self._close_connection(conn)
                return

            self._pool.append((conn, time.time()))
            self._condition.notify()

    def _cleanup_loop(self) -> None:
        while self._running:
            time.sleep(60)
            self._cleanup_idle_connections()

    def _cleanup_idle_connections(self) -> None:
        with self._condition:
            now = time.time()
            new_pool: deque[tuple[T, float]] = deque()

            for conn, last_used in self._pool:
                if now - last_used > self._max_idle_time:
                    self._close_connection(conn)
                else:
                    new_pool.append((conn, last_used))

            self._pool = new_pool

            while len(self._pool) < self._min_size:
                conn = self._factory()
                self._pool.append((conn, now))
            self._condition.notify_all()

    def _close_connection(self, conn: T) -> None:
        if hasattr(conn, "close"):
            try:
                conn.close()
            except (OSError, ConnectionError) as e:
                _logger.debug(f"Error closing connection: {e}")

    def size(self) -> tuple[int, int]:
        with self._lock:
            return len(self._pool), len(self._in_use)


class AsyncConnectionPool(Generic[T]):
    """Async version of connection pool for asyncio applications."""

    def __init__(
        self,
        factory: Callable[[], Any],
        max_size: int = 10,
        min_size: int = 2,
        max_idle_time: float = 300.0,
    ) -> None:
        self._factory = factory
        self._max_size = max_size
        self._min_size = min_size
        self._max_idle_time = max_idle_time

        self._pool: deque[tuple[T, float]] = deque()
        self._in_use: set[T] = set()
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_size)

    async def acquire(self) -> T:
        await self._semaphore.acquire()
        async with self._lock:
            while self._pool:
                conn, _ = self._pool.popleft()
                self._in_use.add(conn)
                return conn

            if asyncio.iscoroutinefunction(self._factory):
                conn = await self._factory()
            else:
                conn = self._factory()

            self._in_use.add(conn)
            return conn

    async def release(self, conn: T) -> None:
        async with self._lock:
            if conn not in self._in_use:
                _logger.warning("AsyncConnectionPool.release called with unknown connection")
                return
            self._in_use.remove(conn)
            self._pool.append((conn, time.time()))
            self._semaphore.release()


class PooledConnection(Generic[T]):
    """Context manager for pooled connections."""

    def __init__(self, pool: ConnectionPool[T]) -> None:
        self._pool = pool
        self._conn: T | None = None

    def __enter__(self) -> T:
        conn = self._pool.acquire()
        self._conn = conn
        return conn

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if self._conn:
            self._pool.release(self._conn)


class AsyncPooledConnection(Generic[T]):
    """Async context manager for pooled connections."""

    def __init__(self, pool: AsyncConnectionPool[T]) -> None:
        self._pool = pool
        self._conn: T | None = None

    async def __aenter__(self) -> T:
        conn = await self._pool.acquire()
        self._conn = conn
        return conn

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if self._conn:
            await self._pool.release(self._conn)
