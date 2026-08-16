"""
Capability  — 

 Feed  capabilities() 。
 require_capability() ， NotSupportedError。
"""

from __future__ import annotations

from enum import unique

from bt_api_base._compat import StrEnum


@unique
class Capability(StrEnum):
    """ — """

    # ──  ──
    GET_TICK = "get_tick"
    GET_DEPTH = "get_depth"
    GET_KLINE = "get_kline"
    GET_FUNDING_RATE = "get_funding_rate"
    GET_MARK_PRICE = "get_mark_price"
    GET_CLEAR_PRICE = "get_clear_price"

    # ──  ──
    MAKE_ORDER = "make_order"
    CANCEL_ORDER = "cancel_order"
    CANCEL_ALL = "cancel_all"
    CANCEL_ALL_SYMBOL = "cancel_all_symbol"
    QUERY_ORDER = "query_order"
    QUERY_OPEN_ORDERS = "query_open_orders"
    GET_DEALS = "get_deals"

    # ──  ──
    GET_BALANCE = "get_balance"
    GET_ACCOUNT = "get_account"
    GET_POSITION = "get_position"

    # ──  ──
    MARKET_STREAM = "market_stream"
    ACCOUNT_STREAM = "account_stream"

    # ──  ──
    CROSS_MARGIN = "cross_margin"
    ISOLATED_MARGIN = "isolated_margin"

    # ──  ──
    HEDGE_MODE = "hedge_mode"
    BATCH_ORDER = "batch_order"
    CONDITIONAL_ORDER = "conditional_order"
    TRAILING_STOP = "trailing_stop"
    OCO_ORDER = "oco_order"

    # ──  ──
    GET_EXCHANGE_INFO = "get_exchange_info"
    GET_SERVER_TIME = "get_server_time"


class NotSupportedError(Exception):
    """"""

    def __init__(self, capability: Capability | str, venue: str = "") -> None:
        """__init__ method"""
        self.capability = capability
        self.venue = venue
        cap_name = capability.value if isinstance(capability, Capability) else str(capability)
        msg = f"Capability '{cap_name}' is not supported"
        if venue:
            msg += f" by {venue}"
        super().__init__(msg)


class CapabilityMixin:
    """Capability 

     _capabilities() 。

    ::

        class BinanceSwapFeed(Feed, CapabilityMixin):
            @classmethod
            def _capabilities(cls) -> Set[Capability]:
                return {
                    Capability.MAKE_ORDER,
                    Capability.CANCEL_ORDER,
                    Capability.GET_TICK,
                    ...
                }
    """

    @classmethod
    def _capabilities(cls) -> set[Capability]:
        """"""
        return set()

    @property
    def capabilities(self) -> set[Capability]:
        """ Feed """
        return self._capabilities()

    def has_capability(self, cap: Capability) -> bool:
        """"""
        return cap in self.capabilities

    def require_capability(self, cap: Capability) -> None:
        """， NotSupportedError"""
        if not self.has_capability(cap):
            venue = getattr(self, "exchange_name", self.__class__.__name__)
            raise NotSupportedError(cap, venue)
