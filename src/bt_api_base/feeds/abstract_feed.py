""" (AbstractVenueFeed)  (AsyncWrapperMixin).

：
1.  Feed （extra_data + **kwargs ）
2.  run_in_executor ，HTTP 
3. connect/disconnect  HTTP  no-op
"""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Protocol, TypeVar, cast, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class AbstractVenueFeed(Protocol):
    """.

     Feed（CEX/DEX/CTP/IB/QMT）。
     Protocol  ABC， Feed 。
    """

    def connect(self) -> None:
        """（HTTP  no-op）."""
        ...

    def disconnect(self) -> None:
        """."""
        ...

    def is_connected(self) -> bool:
        """."""
        ...

    def get_tick(self, symbol: str, extra_data: Any = None, **kwargs: Any) -> Any:
        """."""
        ...

    def get_depth(self, symbol: str, count: int = 20, extra_data: Any = None, **kwargs: Any) -> Any:
        """."""
        ...

    def get_kline(
        self,
        symbol: str,
        period: str,
        count: int = 20,
        extra_data: Any = None,
        **kwargs: Any,
    ) -> Any:
        """K."""
        ...

    def make_order(
        self,
        symbol: str,
        volume: float,
        price: float,
        order_type: str,
        offset: str = "open",
        post_only: bool = False,
        client_order_id: str | None = None,
        extra_data: Any = None,
        **kwargs: Any,
    ) -> Any:
        """."""
        ...

    def cancel_order(
        self, symbol: str, order_id: str, extra_data: Any = None, **kwargs: Any
    ) -> Any:
        """."""
        ...

    def cancel_all(self, symbol: str | None = None, extra_data: Any = None, **kwargs: Any) -> Any:
        """（）."""
        ...

    def query_order(self, symbol: str, order_id: str, extra_data: Any = None, **kwargs: Any) -> Any:
        """."""
        ...

    def get_open_orders(
        self, symbol: str | None = None, extra_data: Any = None, **kwargs: Any
    ) -> Any:
        """."""
        ...

    def get_balance(self, symbol: Any = None, extra_data: Any = None, **kwargs: Any) -> Any:
        """."""
        ...

    def get_account(self, symbol: str = "ALL", extra_data: Any = None, **kwargs: Any) -> Any:
        """."""
        ...

    def get_position(self, symbol: str | None = None, extra_data: Any = None, **kwargs: Any) -> Any:
        """（/）."""
        ...

    def async_get_tick(self, symbol: str, extra_data: Any = None, **kwargs: Any) -> Any:
        """async_get_tick method"""
        ...

    def async_make_order(
        self,
        symbol: str,
        volume: float,
        price: float,
        order_type: str,
        offset: str = "open",
        post_only: bool = False,
        client_order_id: str | None = None,
        extra_data: Any = None,
        **kwargs: Any,
    ) -> Any:
        """async_make_order method"""
        ...

    def async_cancel_order(
        self, symbol: str, order_id: str, extra_data: Any = None, **kwargs: Any
    ) -> Any:
        """async_cancel_order method"""
        ...

    def async_get_balance(
        self, symbol: Any = None, extra_data: Any = None, **kwargs: Any
    ) -> Any:
        """async_get_balance method"""
        ...

    @property
    def capabilities(self) -> set[str]:
        """ Feed ."""
        ...


class AsyncWrapperMixin:
    """ HTTP （CTP/IB/QMT）.

    HTTP  httpx 。
     HTTP  Mixin，。
    """

    def _sync_feed(self) -> AbstractVenueFeed:
        return cast("AbstractVenueFeed", self)

    async def async_get_tick(self, symbol: str, extra_data: Any = None, **kwargs: Any) -> Any:
        """async_get_tick method"""
        loop = asyncio.get_running_loop()
        feed = self._sync_feed()
        return await loop.run_in_executor(
            None, functools.partial(feed.get_tick, symbol, extra_data=extra_data, **kwargs)
        )

    async def async_get_depth(
        self, symbol: str, count: int = 20, extra_data: Any = None, **kwargs: Any
    ) -> Any:
        """async_get_depth method"""
        loop = asyncio.get_running_loop()
        feed = self._sync_feed()
        return await loop.run_in_executor(
            None,
            functools.partial(feed.get_depth, symbol, count=count, extra_data=extra_data, **kwargs),
        )

    async def async_get_kline(
        self,
        symbol: str,
        period: str,
        count: int = 20,
        extra_data: Any = None,
        **kwargs: Any,
    ) -> Any:
        """async_get_kline method"""
        loop = asyncio.get_running_loop()
        feed = self._sync_feed()
        return await loop.run_in_executor(
            None,
            functools.partial(
                feed.get_kline, symbol, period, count=count, extra_data=extra_data, **kwargs
            ),
        )

    async def async_make_order(
        self,
        symbol: str,
        volume: float,
        price: float,
        order_type: str,
        offset: str = "open",
        post_only: bool = False,
        client_order_id: str | None = None,
        extra_data: Any = None,
        **kwargs: Any,
    ) -> Any:
        """async_make_order method"""
        loop = asyncio.get_running_loop()
        feed = self._sync_feed()
        return await loop.run_in_executor(
            None,
            functools.partial(
                feed.make_order,
                symbol,
                volume,
                price,
                order_type,
                offset=offset,
                post_only=post_only,
                client_order_id=client_order_id,
                extra_data=extra_data,
                **kwargs,
            ),
        )

    async def async_cancel_order(
        self, symbol: str, order_id: str, extra_data: Any = None, **kwargs: Any
    ) -> Any:
        """async_cancel_order method"""
        loop = asyncio.get_running_loop()
        feed = self._sync_feed()
        return await loop.run_in_executor(
            None,
            functools.partial(feed.cancel_order, symbol, order_id, extra_data=extra_data, **kwargs),
        )

    async def async_cancel_all(
        self, symbol: str | None = None, extra_data: Any = None, **kwargs: Any
    ) -> Any:
        """async_cancel_all method"""
        loop = asyncio.get_running_loop()
        feed = self._sync_feed()
        return await loop.run_in_executor(
            None, functools.partial(feed.cancel_all, symbol, extra_data=extra_data, **kwargs)
        )

    async def async_query_order(
        self, symbol: str, order_id: str, extra_data: Any = None, **kwargs: Any
    ) -> Any:
        """async_query_order method"""
        loop = asyncio.get_running_loop()
        feed = self._sync_feed()
        return await loop.run_in_executor(
            None,
            functools.partial(feed.query_order, symbol, order_id, extra_data=extra_data, **kwargs),
        )

    async def async_get_open_orders(
        self, symbol: str | None = None, extra_data: Any = None, **kwargs: Any
    ) -> Any:
        """async_get_open_orders method"""
        loop = asyncio.get_running_loop()
        feed = self._sync_feed()
        return await loop.run_in_executor(
            None, functools.partial(feed.get_open_orders, symbol, extra_data=extra_data, **kwargs)
        )

    async def async_get_balance(
        self, symbol: Any = None, extra_data: Any = None, **kwargs: Any
    ) -> Any:
        """async_get_balance method"""
        loop = asyncio.get_running_loop()
        feed = self._sync_feed()
        return await loop.run_in_executor(
            None, functools.partial(feed.get_balance, symbol, extra_data=extra_data, **kwargs)
        )

    async def async_get_account(
        self, symbol: str = "ALL", extra_data: Any = None, **kwargs: Any
    ) -> Any:
        """async_get_account method"""
        loop = asyncio.get_running_loop()
        feed = self._sync_feed()
        return await loop.run_in_executor(
            None, functools.partial(feed.get_account, symbol, extra_data=extra_data, **kwargs)
        )

    async def async_get_position(
        self, symbol: str | None = None, extra_data: Any = None, **kwargs: Any
    ) -> Any:
        """async_get_position method"""
        loop = asyncio.get_running_loop()
        feed = self._sync_feed()
        return await loop.run_in_executor(
            None, functools.partial(feed.get_position, symbol, extra_data=extra_data, **kwargs)
        )


def check_protocol_compliance(feed_class: type[Any]) -> list[str]:
    """ feed_class  AbstractVenueFeed .

    :param feed_class: Feed （）
    :return: ，
    """
    required_methods = [
        "connect",
        "disconnect",
        "is_connected",
        "get_tick",
        "get_depth",
        "get_kline",
        "make_order",
        "cancel_order",
        "cancel_all",
        "query_order",
        "get_open_orders",
        "get_balance",
        "get_account",
        "get_position",
        "async_get_tick",
        "async_make_order",
        "async_cancel_order",
        "async_get_balance",
    ]
    missing = [
        method_name
        for method_name in required_methods
        if not hasattr(feed_class, method_name)
        or not callable(getattr(feed_class, method_name, None))
    ]
    return missing
