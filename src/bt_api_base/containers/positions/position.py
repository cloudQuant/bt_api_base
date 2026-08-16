"""，。"""

from __future__ import annotations

from typing import Any

from bt_api_base._compat import Self
from bt_api_base.containers.auto_init_mixin import AutoInitMixin


class PositionData(AutoInitMixin):
    """"""

    def __init__(self, position_info: Any, has_been_json_encoded: bool = False) -> None:
        """__init__ method"""
        self.event = "PositionEvent"
        self.position_info = position_info
        self.has_been_json_encoded = has_been_json_encoded
        self.exchange_name: str | None = None
        self.symbol_name: str | None = None
        self.asset_type: str | None = None
        self.position_data: Any = position_info if has_been_json_encoded else None
        self.local_update_time: float | None = None
        self.server_time: float | None = None
        self.account_id: str | None = None
        self.position_id: str | None = None
        self.is_isolated: bool | None = None
        self.margin_type: str | None = None
        self.is_auto_add_margin: bool | None = None
        self.leverage: float | None = None
        self.max_notional_value: float | None = None
        self.position_symbol_name: str | None = None
        self.position_volume: float | None = None
        self.position_side: str | None = None
        self.trade_num: float | None = None
        self.avg_price: float | None = None
        self.mark_price: float | None = None
        self.liquidation_price: float | None = None
        self.initial_margin: float | None = None
        self.maintain_margin: float | None = None
        self.open_order_initial_margin_value: float | None = None
        self.position_initial_margin: float | None = None
        self.position_fee: float | None = None
        self.position_realized_pnl: float | None = None
        self.position_unrealized_pnl: float | None = None
        self.position_funding_value: float | None = None
        self.all_data: dict[str, Any] | None = None

    def init_data(self) -> None | Self:
        """init_data method"""
        raise NotImplementedError

    def get_event(self) -> str:
        """# """
        return self.event

    def get_all_data(self) -> dict[str, Any]:
        """get_all_data method"""
        if self.all_data is None:
            self.all_data = {
                "exchange_name": self.exchange_name,
                "symbol_name": self.symbol_name,
                "asset_type": self.asset_type,
                "local_update_time": self.local_update_time,
                "server_time": self.server_time,
                "account_id": self.account_id,
                "position_id": self.position_id,
                "is_isolated": self.is_isolated,
                "margin_type": self.margin_type,
                "is_auto_add_margin": self.is_auto_add_margin,
                "leverage": self.leverage,
                "max_notional_value": self.max_notional_value,
                "position_symbol_name": self.position_symbol_name,
                "position_volume": self.position_volume,
                "position_side": self.position_side,
                "trade_num": self.trade_num,
                "avg_price": self.avg_price,
                "mark_price": self.mark_price,
                "liquidation_price": self.liquidation_price,
                "initial_margin": self.initial_margin,
                "maintain_margin": self.maintain_margin,
                "open_order_initial_margin": self.open_order_initial_margin_value,
                "position_initial_margin": self.position_initial_margin,
                "position_fee": self.position_fee,
                "position_realized_pnl": self.position_realized_pnl,
                "position_unrealized_pnl": self.position_unrealized_pnl,
                "position_funding_value": self.position_funding_value,
            }
        return self.all_data

    def get_exchange_name(self) -> str:
        """# """
        raise NotImplementedError

    def get_asset_type(self) -> str | None:
        """# """
        raise NotImplementedError

    def get_server_time(self) -> float | None:
        """# """
        raise NotImplementedError

    def get_local_update_time(self) -> float | None:
        """# """
        raise NotImplementedError

    def get_account_id(self) -> str | None:
        """# id"""
        raise NotImplementedError

    def get_position_id(self) -> str | None:
        """# id"""
        raise NotImplementedError

    def get_is_isolated(self) -> bool | None:
        """# """
        raise NotImplementedError

    def get_margin_type(self) -> str | None:
        """# """
        raise NotImplementedError

    def get_is_auto_add_margin(self) -> bool | None:
        """# """
        raise NotImplementedError

    def get_leverage(self) -> float | None:
        """# """
        raise NotImplementedError

    def get_max_notional_value(self) -> float | None:
        """# """
        raise NotImplementedError

    def get_position_symbol_name(self) -> str | None:
        """# """
        raise NotImplementedError

    def get_position_volume(self) -> float | None:
        """# """
        raise NotImplementedError

    def get_position_side(self) -> str | None:
        """# """
        raise NotImplementedError

    def get_trade_num(self) -> float | None:
        """# trade"""
        raise NotImplementedError

    def get_avg_price(self) -> float | None:
        """# """
        raise NotImplementedError

    def get_mark_price(self) -> float | None:
        """# """
        raise NotImplementedError

    def get_liquidation_price(self) -> float | None:
        """# """
        raise NotImplementedError

    def get_initial_margin(self) -> float | None:
        """# ()"""
        raise NotImplementedError

    def get_maintain_margin(self) -> float | None:
        """# """
        raise NotImplementedError

    def open_order_initial_margin(self) -> float | None:
        """# ()"""
        raise NotImplementedError

    def get_position_initial_margin(self) -> float | None:
        """# ()"""
        raise NotImplementedError

    def get_position_fee(self) -> float | None:
        """# position"""
        raise NotImplementedError

    def get_position_realized_pnl(self) -> float | None:
        """# """
        raise NotImplementedError

    def get_position_unrealized_pnl(self) -> float | None:
        """# """
        raise NotImplementedError

    def get_position_funding_value(self) -> float | None:
        """# """
        raise NotImplementedError

    def __str__(self) -> str:
        raise NotImplementedError

    def __repr__(self) -> str:
        raise NotImplementedError
