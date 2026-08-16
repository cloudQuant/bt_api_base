""",。"""

from __future__ import annotations

from typing import Any

from bt_api_base._compat import Self
from bt_api_base.containers.auto_init_mixin import AutoInitMixin


class AccountData(AutoInitMixin):
    """,。"""

    def __init__(
        self,
        account_info: dict[str, Any] | str,
        has_been_json_encoded: bool = False,
    ) -> None:
        """__init__ method"""
        self.event = "AccountEvent"
        self.account_info = account_info
        self.has_been_json_encoded = has_been_json_encoded
        self.exchange_name: str | None = None
        self.symbol_name: str | None = None
        self.asset_type: str | None = None
        self.account_data: dict[str, Any] | str | None = (
            account_info if has_been_json_encoded else None
        )
        self.local_update_time: float | int | None = None
        self.server_time: float | int | None = None
        self.account_id: str | None = None
        self.account_type: str | None = None
        self.can_deposit: bool | None = None
        self.can_trade: bool | None = None
        self.can_withdraw: bool | None = None
        self.fee_tier: int | str | None = None
        self.max_withdraw_amount: float | None = None
        self.total_margin: float | None = None
        self.total_used_margin: float | None = None
        self.total_maintain_margin: float | None = None
        self.total_available_margin: float | None = None
        self.total_open_order_initial_margin: float | None = None
        self.total_position_initial_margin: float | None = None
        self.total_unrealized_profit: float | None = None
        self.total_wallet_balance: float | None = None
        self.balances: list[Any] = []
        self.positions: list[Any] = []
        self.spot_maker_commission_rate: float | None = None
        self.spot_taker_commission_rate: float | None = None
        self.future_maker_commission_rate: float | None = None
        self.future_taker_commission_rate: float | None = None
        self.option_maker_commission_rate: float | None = None
        self.option_taker_commission_rate: float | None = None
        self.all_data: dict[str, Any] | None = None

    def get_event(self) -> str:
        """。"""
        return self.event

    def init_data(self) -> None | Self:
        """。"""
        raise NotImplementedError

    def get_all_data(self) -> dict[str, Any]:
        """get_all_data method"""
        if self.all_data is None:
            self.all_data = {
                "exchange_name": self.exchange_name,
                "symbol_name": self.symbol_name,
                "asset_type": self.asset_type,
                "server_time": self.server_time,
                "local_update_time": self.local_update_time,
                "account_id": self.account_id,
                "account_type": self.account_type,
                "can_deposit": self.can_deposit,
                "can_trade": self.can_trade,
                "can_withdraw": self.can_withdraw,
                "fee_tier": self.fee_tier,
                "max_withdraw_amount": self.max_withdraw_amount,
                "total_margin": self.total_margin,
                "total_used_margin": self.total_used_margin,
                "total_maintain_margin": self.total_maintain_margin,
                "total_available_margin": self.total_available_margin,
                "total_open_order_initial_margin": self.total_open_order_initial_margin,
                "total_position_initial_margin": self.total_position_initial_margin,
                "total_unrealized_profit": self.total_unrealized_profit,
                "total_wallet_balance": self.total_wallet_balance,
                "balances": self.balances,
                "positions": self.positions,
                "spot_maker_commission_rate": self.spot_maker_commission_rate,
                "spot_taker_commission_rate": self.spot_taker_commission_rate,
                "future_maker_commission_rate": self.future_maker_commission_rate,
                "future_taker_commission_rate": self.future_taker_commission_rate,
                "option_maker_commission_rate": self.option_maker_commission_rate,
                "option_taker_commission_rate": self.option_taker_commission_rate,
            }
        return self.all_data

    def get_exchange_name(self) -> str:
        """get_exchange_name method"""
        raise NotImplementedError

    def get_asset_type(self) -> str | None:
        """get_asset_type method"""
        raise NotImplementedError

    def get_server_time(self) -> int | float | None:
        """get_server_time method"""
        raise NotImplementedError

    def get_local_update_time(self) -> int | float | None:
        """get_local_update_time method"""
        raise NotImplementedError

    def get_account_id(self) -> str | None:
        """get_account_id method"""
        raise NotImplementedError

    def get_account_type(self) -> str | None:
        """get_account_type method"""
        raise NotImplementedError

    def get_can_deposit(self) -> bool | None:
        """get_can_deposit method"""
        raise NotImplementedError

    def get_can_trade(self) -> bool | None:
        """get_can_trade method"""
        raise NotImplementedError

    def get_can_withdraw(self) -> bool | None:
        """get_can_withdraw method"""
        raise NotImplementedError

    def get_fee_tier(self) -> int | str | None:
        """get_fee_tier method"""
        raise NotImplementedError

    def get_max_withdraw_amount(self) -> float | None:
        """get_max_withdraw_amount method"""
        raise NotImplementedError

    def get_total_margin(self) -> float | None:
        """get_total_margin method"""
        raise NotImplementedError

    def get_total_used_margin(self) -> float | None:
        """get_total_used_margin method"""
        raise NotImplementedError

    def get_total_maintain_margin(self) -> float | None:
        """get_total_maintain_margin method"""
        raise NotImplementedError

    def get_total_available_margin(self) -> float | None:
        """get_total_available_margin method"""
        raise NotImplementedError

    def get_total_open_order_initial_margin(self) -> float | None:
        """get_total_open_order_initial_margin method"""
        raise NotImplementedError

    def get_total_position_initial_margin(self) -> float | None:
        """get_total_position_initial_margin method"""
        raise NotImplementedError

    def get_total_unrealized_profit(self) -> float | None:
        """get_total_unrealized_profit method"""
        raise NotImplementedError

    def get_total_wallet_balance(self) -> float | None:
        """get_total_wallet_balance method"""
        raise NotImplementedError

    def get_balances(self) -> list[Any]:
        """get_balances method"""
        raise NotImplementedError

    def get_positions(self) -> list[Any]:
        """get_positions method"""
        raise NotImplementedError

    def get_spot_maker_commission_rate(self) -> float | None:
        """get_spot_maker_commission_rate method"""
        raise NotImplementedError

    def get_spot_taker_commission_rate(self) -> float | None:
        """get_spot_taker_commission_rate method"""
        raise NotImplementedError

    def get_future_maker_commission_rate(self) -> float | None:
        """get_future_maker_commission_rate method"""
        raise NotImplementedError

    def get_future_taker_commission_rate(self) -> float | None:
        """get_future_taker_commission_rate method"""
        raise NotImplementedError

    def get_option_maker_commission_rate(self) -> float | None:
        """get_option_maker_commission_rate method"""
        raise NotImplementedError

    def get_option_taker_commission_rate(self) -> float | None:
        """get_option_taker_commission_rate method"""
        raise NotImplementedError

    def __str__(self) -> str:
        raise NotImplementedError

    def __repr__(self) -> str:
        raise NotImplementedError
