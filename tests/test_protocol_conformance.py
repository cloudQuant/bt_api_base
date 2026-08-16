"""
Tests for AbstractVenueFeed protocol conformance validation
"""

from __future__ import annotations

import pytest

from bt_api_base.feeds.abstract_feed import (
    AbstractVenueFeed,
    AsyncWrapperMixin,
    check_protocol_compliance,
)


class _CompleteFeed(AsyncWrapperMixin):
    """A complete feed implementation for testing"""

    def connect(self) -> None:
        """connect method"""
        pass

    def disconnect(self) -> None:
        """disconnect method"""
        pass

    def is_connected(self) -> bool:
        """is_connected method"""
        return True

    def get_tick(self, symbol: str, extra_data=None, **kwargs):
        """get_tick method"""
        return {"symbol": symbol}

    def get_depth(self, symbol: str, count: int = 20, extra_data=None, **kwargs):
        """get_depth method"""
        return {"bids": [], "asks": []}

    def get_kline(self, symbol: str, period: str, count: int = 20, extra_data=None, **kwargs):
        """get_kline method"""
        return []

    def make_order(
        self,
        symbol: str,
        volume: float,
        price: float,
        order_type: str,
        offset: str = "open",
        post_only: bool = False,
        client_order_id=None,
        extra_data=None,
        **kwargs,
    ):
        """make_order method"""
        return {"orderId": "123"}

    def cancel_order(self, symbol: str, order_id: str, extra_data=None, **kwargs):
        """cancel_order method"""
        return True

    def cancel_all(self, symbol=None, extra_data=None, **kwargs):
        """cancel_all method"""
        return True

    def query_order(self, symbol: str, order_id: str, extra_data=None, **kwargs):
        """query_order method"""
        return {}

    def get_open_orders(self, symbol=None, extra_data=None, **kwargs):
        """get_open_orders method"""
        return []

    def get_balance(self, symbol=None, extra_data=None, **kwargs):
        """get_balance method"""
        return {}

    def get_account(self, symbol: str = "ALL", extra_data=None, **kwargs):
        """get_account method"""
        return {}

    def get_position(self, symbol=None, extra_data=None, **kwargs):
        """get_position method"""
        return {}

    @property
    def capabilities(self) -> set:
        """capabilities method"""
        return {"tick", "depth", "kline", "order"}


class _IncompleteFeed:
    """An incomplete feed missing required methods"""

    def connect(self) -> None:
        """connect method"""
        pass

    def disconnect(self) -> None:
        """disconnect method"""
        pass

    def is_connected(self) -> bool:
        """is_connected method"""
        return False


class _MinimalFeed(AsyncWrapperMixin):
    """Minimal feed with only sync methods (async from mixin)"""

    def connect(self) -> None:
        """connect method"""
        pass

    def disconnect(self) -> None:
        """disconnect method"""
        pass

    def is_connected(self) -> bool:
        """is_connected method"""
        return True

    def get_tick(self, symbol: str, extra_data=None, **kwargs):
        """get_tick method"""
        return None

    def get_depth(self, symbol: str, count: int = 20, extra_data=None, **kwargs):
        """get_depth method"""
        return None

    def get_kline(self, symbol: str, period: str, count: int = 20, extra_data=None, **kwargs):
        """get_kline method"""
        return None

    def make_order(
        self,
        symbol: str,
        volume: float,
        price: float,
        order_type: str,
        offset: str = "open",
        post_only: bool = False,
        client_order_id=None,
        extra_data=None,
        **kwargs,
    ):
        """make_order method"""
        return None

    def cancel_order(self, symbol: str, order_id: str, extra_data=None, **kwargs):
        """cancel_order method"""
        return None

    def cancel_all(self, symbol=None, extra_data=None, **kwargs):
        """cancel_all method"""
        return None

    def query_order(self, symbol: str, order_id: str, extra_data=None, **kwargs):
        """query_order method"""
        return None

    def get_open_orders(self, symbol=None, extra_data=None, **kwargs):
        """get_open_orders method"""
        return None

    def get_balance(self, symbol=None, extra_data=None, **kwargs):
        """get_balance method"""
        return None

    def get_account(self, symbol: str = "ALL", extra_data=None, **kwargs):
        """get_account method"""
        return None

    def get_position(self, symbol=None, extra_data=None, **kwargs):
        """get_position method"""
        return None

    @property
    def capabilities(self) -> set:
        """capabilities method"""
        return set()


class TestProtocolConformance:
    """Class TestProtocolConformance"""

    def test_complete_feed_passes(self):
        """test_complete_feed_passes method"""
        assert check_protocol_compliance(_CompleteFeed) == []

    def test_incomplete_feed_fails(self):
        """test_incomplete_feed_fails method"""
        missing = check_protocol_compliance(_IncompleteFeed)
        assert len(missing) > 0
        assert "get_tick" in missing
        assert "make_order" in missing
        assert "cancel_order" in missing

    def test_minimal_feed_with_mixin_passes(self):
        """test_minimal_feed_with_mixin_passes method"""
        missing = check_protocol_compliance(_MinimalFeed)
        assert missing == []

    def test_missing_capabilities_property(self):
        """test_missing_capabilities_property method"""
        class NoCapabilitiesFeed(AsyncWrapperMixin):
            """Class NoCapabilitiesFeed"""
            def connect(self):
                """connect method"""
                pass

            def disconnect(self):
                """disconnect method"""
                pass

            def is_connected(self):
                """is_connected method"""
                return True

            def get_tick(self, symbol, extra_data=None, **kwargs):
                """get_tick method"""
                pass

            def get_depth(self, symbol, count=20, extra_data=None, **kwargs):
                """get_depth method"""
                pass

            def get_kline(self, symbol, period, count=20, extra_data=None, **kwargs):
                """get_kline method"""
                pass

            def make_order(
                self,
                symbol,
                volume,
                price,
                order_type,
                offset="open",
                post_only=False,
                client_order_id=None,
                extra_data=None,
                **kwargs,
            ):
                """make_order method"""
                pass

            def cancel_order(self, symbol, order_id, extra_data=None, **kwargs):
                """cancel_order method"""
                pass

            def cancel_all(self, symbol=None, extra_data=None, **kwargs):
                """cancel_all method"""
                pass

            def query_order(self, symbol, order_id, extra_data=None, **kwargs):
                """query_order method"""
                pass

            def get_open_orders(self, symbol=None, extra_data=None, **kwargs):
                """get_open_orders method"""
                pass

            def get_balance(self, symbol=None, extra_data=None, **kwargs):
                """get_balance method"""
                pass

            def get_account(self, symbol="ALL", extra_data=None, **kwargs):
                """get_account method"""
                pass

            def get_position(self, symbol=None, extra_data=None, **kwargs):
                """get_position method"""
                pass

        missing = check_protocol_compliance(NoCapabilitiesFeed)
        assert "capabilities" not in missing


class TestProtocolRuntimeCheck:
    """Test Protocol runtime_checkable behavior"""

    def test_complete_feed_is_instance_of_protocol(self):
        """test_complete_feed_is_instance_of_protocol method"""
        feed = _CompleteFeed()
        assert isinstance(feed, AbstractVenueFeed)

    def test_minimal_feed_is_instance_of_protocol(self):
        """test_minimal_feed_is_instance_of_protocol method"""
        feed = _MinimalFeed()
        assert isinstance(feed, AbstractVenueFeed)


class TestAsyncWrapperMixin:
    """Test AsyncWrapperMixin behavior"""

    @pytest.mark.asyncio
    async def test_async_get_tick_delegates_to_sync(self):
        """test_async_get_tick_delegates_to_sync method"""
        feed = _CompleteFeed()
        result = await feed.async_get_tick("BTCUSDT")
        assert result == {"symbol": "BTCUSDT"}

    @pytest.mark.asyncio
    async def test_async_get_depth_with_count(self):
        """test_async_get_depth_with_count method"""
        feed = _CompleteFeed()
        result = await feed.async_get_depth("BTCUSDT", count=5)
        assert result == {"bids": [], "asks": []}

    @pytest.mark.asyncio
    async def test_async_make_order_passes_all_params(self):
        """test_async_make_order_passes_all_params method"""
        feed = _CompleteFeed()
        result = await feed.async_make_order(
            symbol="BTCUSDT",
            volume=0.1,
            price=50000.0,
            order_type="limit",
            offset="open",
            post_only=True,
            client_order_id="test123",
        )
        assert result == {"orderId": "123"}

    @pytest.mark.asyncio
    async def test_async_cancel_order(self):
        """test_async_cancel_order method"""
        feed = _CompleteFeed()
        result = await feed.async_cancel_order("BTCUSDT", "order123")
        assert result is True

    @pytest.mark.asyncio
    async def test_async_get_balance(self):
        """test_async_get_balance method"""
        feed = _CompleteFeed()
        result = await feed.async_get_balance()
        assert result == {}
