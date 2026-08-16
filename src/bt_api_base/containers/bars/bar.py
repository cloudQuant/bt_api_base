# """
# K
# k
# Bar，json
# """

"""Module-level docstring."""
from __future__ import annotations

from typing import Any

from bt_api_base.containers.auto_init_mixin import AutoInitMixin


class BarData(AutoInitMixin):
    """Class BarData"""
    def __init__(self, bar_info: Any, has_been_json_encoded: bool = False) -> None:
        """__init__ method"""
        self.event = "BarEvent"
        self.bar_info = bar_info
        self.has_been_json_encoded = has_been_json_encoded

    def init_data(self) -> BarData:
        """init_data method"""
        raise NotImplementedError

    def get_event(self) -> str:
        """get_event method"""
        return self.event

    def get_exchange_name(self) -> str:
        """get_exchange_name method"""
        raise NotImplementedError

    def get_symbol_name(self) -> str:
        """get_symbol_name method"""
        raise NotImplementedError

    def get_asset_type(self) -> str:
        """get_asset_type method"""
        raise NotImplementedError

    def get_server_time(self) -> float | int | None:
        """get_server_time method"""
        raise NotImplementedError

    def get_local_update_time(self) -> float | int | None:
        """get_local_update_time method"""
        raise NotImplementedError

    def get_open_time(self) -> float | int:
        """get_open_time method"""
        raise NotImplementedError

    def get_open_price(self) -> float | int:
        """get_open_price method"""
        raise NotImplementedError

    def get_high_price(self) -> float | int:
        """get_high_price method"""
        raise NotImplementedError

    def get_low_price(self) -> float | int:
        """get_low_price method"""
        raise NotImplementedError

    def get_close_price(self) -> float | int:
        """get_close_price method"""
        raise NotImplementedError

    def get_volume(self) -> float | int:
        """get_volume method"""
        raise NotImplementedError

    def get_amount(self) -> float | int:
        """get_amount method"""
        raise NotImplementedError

    def get_close_time(self) -> float | int:
        """get_close_time method"""
        raise NotImplementedError

    def get_quote_asset_volume(self) -> float | int:
        """get_quote_asset_volume method"""
        raise NotImplementedError

    def get_base_asset_volume(self) -> float | int:
        """get_base_asset_volume method"""
        raise NotImplementedError

    def get_num_trades(self) -> int:
        """get_num_trades method"""
        raise NotImplementedError

    def get_taker_buy_base_asset_volume(self) -> float | int:
        """get_taker_buy_base_asset_volume method"""
        raise NotImplementedError

    def get_taker_buy_quote_asset_volume(self) -> float | int:
        """get_taker_buy_quote_asset_volume method"""
        raise NotImplementedError

    def get_bar_status(self) -> bool | int:
        """get_bar_status method"""
        raise NotImplementedError

    def get_all_data(self) -> Any:
        """get_all_data method"""
        raise NotImplementedError

    def __str__(self) -> str:
        raise NotImplementedError

    def __repr__(self) -> str:
        raise NotImplementedError
