"""，, ，,"""

from __future__ import annotations

from typing import Any

from bt_api_base.containers.auto_init_mixin import AutoInitMixin


class SymbolData(AutoInitMixin):
    """Class SymbolData"""
    def __init__(self, symbol_info: Any, has_been_json_encoded: bool) -> None:
        """__init__ method"""
        self.event = "SymbolEvent"
        self.symbol_info = symbol_info
        self.has_been_json_encoded = has_been_json_encoded

    def get_event(self) -> str:
        """get_event method"""
        return self.event

    def get_all_data(self) -> dict[str, Any]:
        """get_all_data method"""
        raise NotImplementedError

    def init_data(self) -> SymbolData:
        """init_data method"""
        raise NotImplementedError

    def get_exchange_name(self) -> str:
        """"""
        raise NotImplementedError

    def get_server_time(self) -> float | None:
        """"""
        raise NotImplementedError

    def get_local_update_time(self) -> float | None:
        """"""
        raise NotImplementedError

    def get_symbol_name(self) -> str:
        """"""
        raise NotImplementedError

    def get_asset_type(self) -> str | None:
        """"""
        raise NotImplementedError

    def get_maintain_margin_percent(self) -> float | None:
        """"""
        raise NotImplementedError

    def get_required_margin_percent(self) -> float | None:
        """"""
        raise NotImplementedError

    def get_base_asset(self) -> str | None:
        """"""
        raise NotImplementedError

    def get_quote_asset(self) -> str | None:
        """"""
        raise NotImplementedError

    def get_contract_multiplier(self) -> float | int | None:
        """"""
        raise NotImplementedError

    def get_price_unit(self) -> float | int | None:
        """"""
        raise NotImplementedError

    def get_price_digital(self) -> int | None:
        """"""
        raise NotImplementedError

    def get_max_price(self) -> float | int | None:
        """"""
        raise NotImplementedError

    def get_min_price(self) -> float | int | None:
        """"""
        raise NotImplementedError

    def get_qty_unit(self) -> float | int | None:
        """"""
        raise NotImplementedError

    def get_qty_digital(self) -> int | None:
        """"""
        raise NotImplementedError

    def get_min_qty(self) -> float | int | None:
        """"""
        raise NotImplementedError

    def get_max_qty(self) -> float | int | None:
        """"""
        raise NotImplementedError

    def get_base_asset_digital(self) -> int | None:
        """"""
        raise NotImplementedError

    def get_quote_asset_digital(self) -> int | None:
        """"""
        raise NotImplementedError

    def get_order_types(self) -> Any:
        """symbol"""
        raise NotImplementedError

    def get_time_in_force(self) -> Any:
        """"""
        raise NotImplementedError

    def get_fee_digital(self) -> int | None:
        """"""
        raise NotImplementedError

    def get_fee_currency(self) -> str | None:
        """"""
        raise NotImplementedError

    def __str__(self) -> str:
        raise NotImplementedError

    def __repr__(self) -> str:
        raise NotImplementedError
