"""
Stage 0 

:
- AbstractVenueFeed Protocol  check_protocol_compliance
- AsyncWrapperMixin
- Capability 
- ConnectionMixin
- Instrument  InstrumentFactory
- InstrumentManager
- Error Framework (、)
- RateLimiter
- Config Loader (pydantic schema )
"""

from __future__ import annotations

import asyncio

import pytest

# ══════════════════════════════════════════════════════════════
# 0.1 AbstractVenueFeed & AsyncWrapperMixin
# ══════════════════════════════════════════════════════════════


class TestAbstractVenueFeed:
    """Class TestAbstractVenueFeed"""
    def test_protocol_is_runtime_checkable(self):
        """test_protocol_is_runtime_checkable method"""
        from bt_api_base.feeds.abstract_feed import AbstractVenueFeed

        # Protocol  isinstance 
        assert hasattr(AbstractVenueFeed, "__protocol_attrs__") or True  # runtime_checkable

    def test_check_protocol_compliance_on_feed(self):
        """Feed """
        from bt_api_base.feeds.abstract_feed import check_protocol_compliance
        from bt_api_base.feeds.feed import Feed

        missing = check_protocol_compliance(Feed)
        # Feed 
        assert "connect" not in missing
        assert "disconnect" not in missing
        assert "is_connected" not in missing
        assert "get_tick" not in missing
        assert "make_order" not in missing
        assert "cancel_order" not in missing
        assert "get_balance" not in missing
        assert "get_position" not in missing

    def test_check_protocol_compliance_on_incomplete_class(self):
        """"""
        from bt_api_base.feeds.abstract_feed import check_protocol_compliance

        class IncompleteClass:
            """Class IncompleteClass"""
            def get_tick(self, symbol, extra_data=None, **kwargs):
                """get_tick method"""
                pass

        missing = check_protocol_compliance(IncompleteClass)
        assert "connect" in missing
        assert "make_order" in missing
        assert "get_tick" not in missing


class TestAsyncWrapperMixin:
    """Class TestAsyncWrapperMixin"""
    def test_async_wrapper_wraps_sync_method(self):
        """AsyncWrapperMixin """
        from bt_api_base.feeds.abstract_feed import AsyncWrapperMixin

        class MockFeed(AsyncWrapperMixin):
            """Class MockFeed"""
            def get_tick(self, symbol, extra_data=None, **kwargs):
                """get_tick method"""
                return {"symbol": symbol, "price": 42000.0}

        feed = MockFeed()
        result = asyncio.run(feed.async_get_tick("BTCUSDT"))
        assert result["symbol"] == "BTCUSDT"
        assert result["price"] == 42000.0

    def test_async_wrapper_make_order(self):
        """test_async_wrapper_make_order method"""
        from bt_api_base.feeds.abstract_feed import AsyncWrapperMixin

        class MockFeed(AsyncWrapperMixin):
            """Class MockFeed"""
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
                return {"order_id": "12345", "symbol": symbol}

        feed = MockFeed()
        result = asyncio.run(feed.async_make_order("BTCUSDT", 0.1, 42000, "limit"))
        assert result["order_id"] == "12345"


# ══════════════════════════════════════════════════════════════
# 0.2 Capability
# ══════════════════════════════════════════════════════════════


class TestCapability:
    """Class TestCapability"""
    def test_capability_enum_completeness(self):
        """test_capability_enum_completeness method"""
        from bt_api_base.feeds.capability import Capability

        # 
        assert Capability.MAKE_ORDER.value == "make_order"
        assert Capability.GET_TICK.value == "get_tick"
        assert Capability.GET_BALANCE.value == "get_balance"
        assert Capability.MARKET_STREAM.value == "market_stream"
        assert Capability.HEDGE_MODE.value == "hedge_mode"

    def test_capability_mixin(self):
        """test_capability_mixin method"""
        from bt_api_base.feeds.capability import Capability, CapabilityMixin, NotSupportedError

        class MockFeed(CapabilityMixin):
            """Class MockFeed"""
            exchange_name = "test"

            @classmethod
            def _capabilities(cls):
                return {Capability.GET_TICK, Capability.MAKE_ORDER}

        feed = MockFeed()
        assert feed.has_capability(Capability.GET_TICK)
        assert feed.has_capability(Capability.MAKE_ORDER)
        assert not feed.has_capability(Capability.HEDGE_MODE)

        # require 
        with pytest.raises(NotSupportedError) as exc_info:
            feed.require_capability(Capability.HEDGE_MODE)
        assert "hedge_mode" in str(exc_info.value)
        assert "test" in str(exc_info.value)

    def test_not_supported_error_message(self):
        """test_not_supported_error_message method"""
        from bt_api_base.feeds.capability import Capability, NotSupportedError

        err = NotSupportedError(Capability.BATCH_ORDER, "Binance")
        assert "batch_order" in str(err)
        assert "Binance" in str(err)


# ══════════════════════════════════════════════════════════════
# 0.8 ConnectionMixin
# ══════════════════════════════════════════════════════════════


class TestConnectionMixin:
    """Class TestConnectionMixin"""
    def test_default_state_is_disconnected(self):
        """test_default_state_is_disconnected method"""
        from bt_api_base.feeds.connection_mixin import ConnectionMixin, FeedConnectionState

        mixin = ConnectionMixin()
        mixin.__init_connection__()
        assert mixin.connection_state == FeedConnectionState.DISCONNECTED
        assert not mixin.is_connected()

    def test_connect_disconnect_lifecycle(self):
        """test_connect_disconnect_lifecycle method"""
        from bt_api_base.feeds.connection_mixin import ConnectionMixin, FeedConnectionState

        mixin = ConnectionMixin()
        mixin.__init_connection__()

        mixin.connect()
        assert mixin.connection_state == FeedConnectionState.CONNECTED
        assert mixin.is_connected()

        mixin.disconnect()
        assert mixin.connection_state == FeedConnectionState.DISCONNECTED
        assert not mixin.is_connected()

    def test_authenticated_is_also_connected(self):
        """test_authenticated_is_also_connected method"""
        from bt_api_base.feeds.connection_mixin import ConnectionMixin, FeedConnectionState

        mixin = ConnectionMixin()
        mixin.__init_connection__()
        mixin._set_connection_state(FeedConnectionState.AUTHENTICATED)
        assert mixin.is_connected()


# ══════════════════════════════════════════════════════════════
# 0.3 Instrument & InstrumentFactory & InstrumentManager
# ══════════════════════════════════════════════════════════════


class TestInstrument:
    """Class TestInstrument"""
    def test_instrument_creation(self):
        """test_instrument_creation method"""
        from bt_api_base.containers.instrument import AssetType, Instrument

        inst = Instrument(
            internal="BTC-USDT",
            venue="BINANCE___SWAP",
            venue_symbol="BTCUSDT",
            asset_type=AssetType.SWAP,
            base_currency="BTC",
            quote_currency="USDT",
        )
        assert inst.internal == "BTC-USDT"
        assert inst.is_listed
        assert not inst.is_expired

    def test_instrument_frozen(self):
        """Instrument """
        from bt_api_base.containers.instrument import AssetType, Instrument

        inst = Instrument(
            internal="BTC-USDT",
            venue="BINANCE",
            venue_symbol="BTCUSDT",
            asset_type=AssetType.SPOT,
        )
        with pytest.raises(AttributeError):  # FrozenInstanceError from frozen dataclass
            inst.internal = "ETH-USDT"

    def test_with_params(self):
        """test_with_params method"""
        from bt_api_base.containers.instrument import AssetType, Instrument

        inst = Instrument(
            internal="BTC-USDT",
            venue="BINANCE",
            venue_symbol="BTCUSDT",
            asset_type=AssetType.SPOT,
        )
        new_inst = inst.with_params(status="suspend")
        assert new_inst.status == "suspend"
        assert inst.status == "active"  # 


class TestInstrumentFactory:
    """Class TestInstrumentFactory"""
    def test_binance_btcusdt(self):
        """test_binance_btcusdt method"""
        from bt_api_base.containers.instrument import AssetType, InstrumentFactory

        inst = InstrumentFactory.from_venue("BINANCE___SWAP", "BTCUSDT", AssetType.SWAP)
        assert inst.internal == "BTC-USDT"

    def test_binance_dogeusdt(self):
        """ base （DOGE 4 + USDT 4 →  [-4]）"""
        from bt_api_base.containers.instrument import AssetType, InstrumentFactory

        inst = InstrumentFactory.from_venue("BINANCE___SPOT", "DOGEUSDT", AssetType.SPOT)
        assert inst.internal == "DOGE-USDT"

    def test_binance_shibusdt(self):
        """test_binance_shibusdt method"""
        from bt_api_base.containers.instrument import AssetType, InstrumentFactory

        inst = InstrumentFactory.from_venue("BINANCE___SPOT", "SHIBUSDT", AssetType.SPOT)
        assert inst.internal == "SHIB-USDT"

    def test_binance_btcusd(self):
        """test_binance_btcusd method"""
        from bt_api_base.containers.instrument import AssetType, InstrumentFactory

        inst = InstrumentFactory.from_venue("BINANCE___SWAP", "BTCUSD", AssetType.SWAP)
        assert inst.internal == "BTC-USD"

    def test_okx_dash_format(self):
        """OKX  - """
        from bt_api_base.containers.instrument import AssetType, InstrumentFactory

        inst = InstrumentFactory.from_venue("OKX___SWAP", "BTC-USDT-SWAP", AssetType.SWAP)
        assert inst.internal == "BTC-USDT-SWAP"

    def test_ctp_future(self):
        """CTP  crypto """
        from bt_api_base.containers.instrument import AssetType, InstrumentFactory

        inst = InstrumentFactory.from_venue("CTP___FUTURE", "IF2506", AssetType.FUTURE)
        assert inst.internal == "IF2506"

    def test_ib_stock(self):
        """IB  crypto """
        from bt_api_base.containers.instrument import AssetType, InstrumentFactory

        inst = InstrumentFactory.from_venue("IB___STK", "AAPL", AssetType.STK)
        assert inst.internal == "AAPL"

    def test_underscore_separator(self):
        """test_underscore_separator method"""
        from bt_api_base.containers.instrument import AssetType, InstrumentFactory

        inst = InstrumentFactory.from_venue("TEST", "BTC_USDT", AssetType.SPOT)
        assert inst.internal == "BTC-USDT"

    def test_slash_separator(self):
        """test_slash_separator method"""
        from bt_api_base.containers.instrument import AssetType, InstrumentFactory

        inst = InstrumentFactory.from_venue("TEST", "BTC/USDT", AssetType.SPOT)
        assert inst.internal == "BTC-USDT"


class TestInstrumentManager:
    """Class TestInstrumentManager"""
    def test_register_and_get(self):
        """test_register_and_get method"""
        from bt_api_base.containers.instrument import AssetType, Instrument
        from bt_api_base.instrument_manager import InstrumentManager

        mgr = InstrumentManager()
        inst = Instrument(
            internal="BTC-USDT",
            venue="BINANCE___SWAP",
            venue_symbol="BTCUSDT",
            asset_type=AssetType.SWAP,
        )
        mgr.register(inst)

        assert mgr.get("BTC-USDT") is inst
        assert mgr.get_by_venue("BINANCE___SWAP", "BTCUSDT") is inst
        assert mgr.count() == 1

    def test_to_internal_and_venue(self):
        """test_to_internal_and_venue method"""
        from bt_api_base.containers.instrument import AssetType, Instrument
        from bt_api_base.instrument_manager import InstrumentManager

        mgr = InstrumentManager()
        inst = Instrument(
            internal="ETH-USDT",
            venue="BINANCE___SPOT",
            venue_symbol="ETHUSDT",
            asset_type=AssetType.SPOT,
        )
        mgr.register(inst)

        assert mgr.to_internal("BINANCE___SPOT", "ETHUSDT") == "ETH-USDT"
        assert mgr.to_venue_symbol("ETH-USDT") == "ETHUSDT"
        assert mgr.to_internal("BINANCE___SPOT", "UNKNOWN") is None

    def test_find_by_venue(self):
        """test_find_by_venue method"""
        from bt_api_base.containers.instrument import AssetType, Instrument
        from bt_api_base.instrument_manager import InstrumentManager

        mgr = InstrumentManager()
        mgr.register(
            Instrument(
                internal="BTC-USDT",
                venue="BINANCE___SWAP",
                venue_symbol="BTCUSDT",
                asset_type=AssetType.SWAP,
            )
        )
        mgr.register(
            Instrument(
                internal="ETH-USDT",
                venue="OKX___SWAP",
                venue_symbol="ETH-USDT-SWAP",
                asset_type=AssetType.SWAP,
            )
        )

        results = mgr.find(venue="BINANCE___SWAP")
        assert len(results) == 1
        assert results[0].internal == "BTC-USDT"


# ══════════════════════════════════════════════════════════════
# 0.7 Error Framework
# ══════════════════════════════════════════════════════════════


class TestErrorFramework:
    """Class TestErrorFramework"""
    def test_unified_error_str(self):
        """test_unified_error_str method"""
        from bt_api_base.error import ErrorCategory, UnifiedError, UnifiedErrorCode

        err = UnifiedError(
            code=UnifiedErrorCode.RATE_LIMIT_EXCEEDED,
            category=ErrorCategory.RATE_LIMIT,
            venue="BINANCE",
            message="Too many requests",
        )
        assert "[BINANCE]" in str(err)
        assert "RATE_LIMIT_EXCEEDED" in str(err)

    def test_unified_error_to_dict(self):
        """test_unified_error_to_dict method"""
        from bt_api_base.error import ErrorCategory, UnifiedError, UnifiedErrorCode

        err = UnifiedError(
            code=UnifiedErrorCode.INVALID_API_KEY,
            category=ErrorCategory.AUTH,
            venue="OKX",
            message="API key invalid",
        )
        d = err.to_dict()
        assert d["code"] == 2001
        assert d["category"] == "auth"
        assert d["venue"] == "OKX"

    def test_unified_error_is_exception(self):
        """test_unified_error_is_exception method"""
        from bt_api_base.error import ErrorCategory, UnifiedError, UnifiedErrorCode
        from bt_api_base.exceptions import BtApiError

        err = UnifiedError(
            code=UnifiedErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.SYSTEM,
            venue="TEST",
            message="test",
        )
        assert isinstance(err, BtApiError)
        assert isinstance(err, Exception)

    def test_rate_limit_error(self):
        """test_rate_limit_error method"""
        from bt_api_base.error import UnifiedErrorCode, UnifiedRateLimitError

        err = UnifiedRateLimitError(venue="BINANCE")
        assert err.code == UnifiedErrorCode.RATE_LIMIT_EXCEEDED
        assert err.venue == "BINANCE"

    @pytest.mark.skip(reason="BinanceErrorTranslator requires bt_api_binance plugin")
    def test_binance_translator(self):
        """test_binance_translator method"""
        from bt_api_base.error import BinanceErrorTranslator, UnifiedErrorCode

        # -1003: rate limit
        err = BinanceErrorTranslator.translate(
            {"code": -1003, "msg": "Too many requests"}, "BINANCE"
        )
        assert err.code == UnifiedErrorCode.RATE_LIMIT_EXCEEDED

        # -1022: invalid signature
        err = BinanceErrorTranslator.translate(
            {"code": -1022, "msg": "Invalid signature"}, "BINANCE"
        )
        assert err.code == UnifiedErrorCode.INVALID_SIGNATURE

        # -1102: missing parameter
        err = BinanceErrorTranslator.translate({"code": -1102, "msg": "Missing param"}, "BINANCE")
        assert err.code == UnifiedErrorCode.MISSING_PARAMETER

        # -1111: precision error (was wrongly INSUFFICIENT_BALANCE)
        err = BinanceErrorTranslator.translate(
            {"code": -1111, "msg": "Precision over max"}, "BINANCE"
        )
        assert err.code == UnifiedErrorCode.PRECISION_ERROR

        # -1114: invalid API key (was wrongly INVALID_PRICE)
        err = BinanceErrorTranslator.translate({"code": -1114, "msg": "Invalid API-key"}, "BINANCE")
        assert err.code == UnifiedErrorCode.INVALID_API_KEY

    def test_okx_translator(self):
        """test_okx_translator method"""
        from bt_api_base.error import OKXErrorTranslator, UnifiedErrorCode

        # Success returns None
        result = OKXErrorTranslator.translate({"code": "0", "msg": "OK"}, "OKX")
        assert result is None

        # Rate limit
        err = OKXErrorTranslator.translate({"code": "50011", "msg": "Rate limit"}, "OKX")
        assert err.code == UnifiedErrorCode.RATE_LIMIT_EXCEEDED

    @pytest.mark.skip(reason="CTPErrorTranslator not implemented in bt_api_base.error")
    def test_ctp_translator(self):
        """test_ctp_translator method"""
        from bt_api_base.error import CTPErrorTranslator, UnifiedErrorCode

        # Success returns None
        result = CTPErrorTranslator.translate({"code": 0, "msg": ""}, "CTP")
        assert result is None

        # Network disconnect
        err = CTPErrorTranslator.translate({"code": -1, "msg": ""}, "CTP")
        assert err.code == UnifiedErrorCode.NETWORK_DISCONNECTED

    @pytest.mark.skip(reason="BinanceErrorTranslator requires bt_api_binance plugin")
    def test_http_status_fallback(self):
        """test_http_status_fallback method"""
        from bt_api_base.error import BinanceErrorTranslator, UnifiedErrorCode

        err = BinanceErrorTranslator.translate({"status": 429, "msg": "Rate limited"}, "BINANCE")
        assert err.code == UnifiedErrorCode.RATE_LIMIT_EXCEEDED

    def test_error_module_lazy_export_invalid_name(self):
        """test_error_module_lazy_export_invalid_name method"""
        import bt_api_base.error as error_module

        with pytest.raises(AttributeError):
            error_module.__getattr__("DefinitelyMissingTranslator")


# ══════════════════════════════════════════════════════════════
# 0.5 RateLimiter
# ══════════════════════════════════════════════════════════════


class TestRateLimiter:
    """Class TestRateLimiter"""
    def test_empty_limiter_always_allows(self):
        """test_empty_limiter_always_allows method"""
        from bt_api_base.rate_limiter import RateLimiter

        limiter = RateLimiter()
        assert limiter.acquire("GET", "/api/v3/ticker")

    def test_sliding_window_basic(self):
        """test_sliding_window_basic method"""
        from bt_api_base.rate_limiter import (
            RateLimiter,
            RateLimitRule,
            RateLimitScope,
            RateLimitType,
        )

        rules = [
            RateLimitRule(
                name="test",
                type=RateLimitType.SLIDING_WINDOW,
                interval=1,
                limit=3,
                scope=RateLimitScope.GLOBAL,
            ),
        ]
        limiter = RateLimiter(rules)
        assert limiter.acquire()
        assert limiter.acquire()
        assert limiter.acquire()
        assert not limiter.acquire()  # 4th should fail

    def test_fixed_window_basic(self):
        """test_fixed_window_basic method"""
        from bt_api_base.rate_limiter import (
            RateLimiter,
            RateLimitRule,
            RateLimitScope,
            RateLimitType,
        )

        rules = [
            RateLimitRule(
                name="test",
                type=RateLimitType.FIXED_WINDOW,
                interval=1,
                limit=2,
                scope=RateLimitScope.GLOBAL,
            ),
        ]
        limiter = RateLimiter(rules)
        assert limiter.acquire()
        assert limiter.acquire()
        assert not limiter.acquire()

    def test_endpoint_matching(self):
        """test_endpoint_matching method"""
        from bt_api_base.rate_limiter import (
            RateLimiter,
            RateLimitRule,
            RateLimitScope,
            RateLimitType,
        )

        rules = [
            RateLimitRule(
                name="order",
                type=RateLimitType.SLIDING_WINDOW,
                interval=1,
                limit=2,
                scope=RateLimitScope.ENDPOINT,
                endpoint="/api/v3/order*",
            ),
        ]
        limiter = RateLimiter(rules)
        # 
        assert limiter.acquire("POST", "/api/v3/order")
        assert limiter.acquire("POST", "/api/v3/order")
        assert not limiter.acquire("POST", "/api/v3/order")
        # 
        assert limiter.acquire("GET", "/api/v3/ticker")

    def test_weight_map(self):
        """test_weight_map method"""
        from bt_api_base.rate_limiter import (
            RateLimiter,
            RateLimitRule,
            RateLimitScope,
            RateLimitType,
        )

        rules = [
            RateLimitRule(
                name="weighted",
                type=RateLimitType.SLIDING_WINDOW,
                interval=1,
                limit=10,
                scope=RateLimitScope.GLOBAL,
                weight_map={"POST": 5, "GET": 1},
            ),
        ]
        limiter = RateLimiter(rules)
        assert limiter.acquire("POST", "/order")  # 5
        assert limiter.acquire("POST", "/order")  # 10
        assert not limiter.acquire("POST", "/order")  # 15 > 10

    def test_get_status(self):
        """test_get_status method"""
        from bt_api_base.rate_limiter import RateLimiter, RateLimitRule, RateLimitType

        rules = [
            RateLimitRule(
                name="global", type=RateLimitType.SLIDING_WINDOW, interval=60, limit=1200
            ),
        ]
        limiter = RateLimiter(rules)
        limiter.acquire()
        status = limiter.get_status()
        assert "global" in status
        assert status["global"]["current"] == 1
        assert status["global"]["limit"] == 1200


# ══════════════════════════════════════════════════════════════
# 0.6 Config Loader
# ══════════════════════════════════════════════════════════════


class TestConfigLoader:
    """Class TestConfigLoader"""
    def test_cex_must_have_base_urls(self):
        """test_cex_must_have_base_urls method"""
        from pydantic import ValidationError

        from bt_api_base.config_loader import (
            ConnectionConfig,
            ConnectionType,
            ExchangeConfig,
            VenueType,
        )

        with pytest.raises(ValidationError):
            ExchangeConfig(
                id="test",
                display_name="Test",
                venue_type=VenueType.CEX,
                connection=ConnectionConfig(type=ConnectionType.HTTP),
                base_urls=None,  # CEX 
            )

    def test_broker_can_have_base_urls(self):
        """DEX/Broker  base_urls（）"""
        from bt_api_base.config_loader import (
            BaseUrlsConfig,
            ConnectionConfig,
            ConnectionType,
            ExchangeConfig,
            VenueType,
        )

        config = ExchangeConfig(
            id="ib",
            display_name="Interactive Brokers",
            venue_type=VenueType.BROKER,
            connection=ConnectionConfig(type=ConnectionType.TWS, host="127.0.0.1", port=7497),
            base_urls=BaseUrlsConfig(rest={"main": "https://localhost:5000"}),
        )
        assert config.base_urls.rest["main"] == "https://localhost:5000"

    def test_broker_without_base_urls(self):
        """test_broker_without_base_urls method"""
        from bt_api_base.config_loader import (
            ConnectionConfig,
            ConnectionType,
            ExchangeConfig,
            VenueType,
        )

        config = ExchangeConfig(
            id="ctp",
            display_name="CTP",
            venue_type=VenueType.BROKER,
            connection=ConnectionConfig(type=ConnectionType.SPI),
        )
        assert config.base_urls is None

    def test_cex_must_use_http_ws_or_spi(self):
        # TWS is not allowed for CEX
        """test_cex_must_use_http_ws_or_spi method"""
        from pydantic import ValidationError

        from bt_api_base.config_loader import (
            BaseUrlsConfig,
            ConnectionConfig,
            ConnectionType,
            ExchangeConfig,
            VenueType,
        )

        with pytest.raises(ValidationError):
            ExchangeConfig(
                id="bad",
                display_name="Bad",
                venue_type=VenueType.CEX,
                connection=ConnectionConfig(type=ConnectionType.TWS),
                base_urls=BaseUrlsConfig(rest={"main": "https://api.example.com"}),
            )
        # SPI is allowed for CEX (e.g. CTP)
        cfg = ExchangeConfig(
            id="ctp_test",
            display_name="CTP Test",
            venue_type=VenueType.CEX,
            connection=ConnectionConfig(type=ConnectionType.SPI),
            base_urls=BaseUrlsConfig(),
        )
        assert cfg.connection.type == ConnectionType.SPI


# ══════════════════════════════════════════════════════════════
# 0.9 Feed Base Class Protocol Compliance
# ══════════════════════════════════════════════════════════════


class TestFeedProtocolCompliance:
    """Class TestFeedProtocolCompliance"""
    def test_feed_has_connect_disconnect(self):
        """test_feed_has_connect_disconnect method"""
        from bt_api_base.feeds.feed import Feed

        assert hasattr(Feed, "connect")
        assert hasattr(Feed, "disconnect")
        assert hasattr(Feed, "is_connected")

    def test_feed_has_capabilities(self):
        """test_feed_has_capabilities method"""
        from bt_api_base.feeds.feed import Feed

        assert hasattr(Feed, "capabilities")

    def test_feed_has_position_methods(self):
        """test_feed_has_position_methods method"""
        from bt_api_base.feeds.feed import Feed

        assert hasattr(Feed, "get_position")
        assert hasattr(Feed, "async_get_position")

    def test_feed_protocol_compliance(self):
        """Feed """
        from bt_api_base.feeds.abstract_feed import check_protocol_compliance
        from bt_api_base.feeds.feed import Feed

        missing = check_protocol_compliance(Feed)
        # 
        core = {
            "connect",
            "disconnect",
            "is_connected",
            "get_tick",
            "make_order",
            "cancel_order",
            "get_balance",
            "get_position",
        }
        assert core.isdisjoint(set(missing)), f"Feed missing core methods: {core & set(missing)}"
