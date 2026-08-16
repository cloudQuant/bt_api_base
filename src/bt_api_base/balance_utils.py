"""

 balance_handler 
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bt_api_base.containers.accounts.account import AccountData
    from bt_api_base.containers.balances.balance import BalanceData


def _to_float(value: float | int | None) -> float:
    """Coerce numeric balance fields while tolerating missing values."""
    return float(value) if value is not None else 0.0


def _currency_key(value: str | None) -> str:
    """Normalize currency keys used in aggregated balance maps."""
    return value or ""


def _apply_balance_values(
    value_result: dict[str, dict[str, float]],
    cash_result: dict[str, dict[str, float]],
    currency: str,
    margin: float | int | None,
    available_margin: float | int | None,
    unrealized_profit: float | int | None,
) -> None:
    cash_result[currency] = {"cash": _to_float(available_margin)}
    value_result[currency] = {"value": _to_float(margin) + _to_float(unrealized_profit)}


def simple_balance_handler(
    account_list: list[AccountData],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """（ Binance/CTP/IB ）。

    Args: account_list: ， get_account_type、get_available_margin 。

    Returns: (value_result, cash_result): value_result  {currency: {"value": float}}，
        cash_result  {currency: {"cash": float}}。
    """
    value_result: dict[str, dict[str, float]] = {}
    cash_result: dict[str, dict[str, float]] = {}
    for account in account_list:
        account.init_data()
        currency = _currency_key(account.get_account_type())
        _apply_balance_values(
            value_result,
            cash_result,
            currency,
            account.get_margin(),
            account.get_available_margin(),
            account.get_unrealized_profit(),
        )
    return value_result, cash_result


def nested_balance_handler(
    account_list: list[AccountData],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """（ OKX ）。

    Args: account_list: ， account  get_balances()  balance 。

    Returns: (value_result, cash_result):  simple_balance_handler。
    """
    value_result: dict[str, dict[str, float]] = {}
    cash_result: dict[str, dict[str, float]] = {}
    for account in account_list:
        account.init_data()
        for balance in account.get_balances():
            balance.init_data()
            _update_nested_balance(value_result, cash_result, balance)
    return value_result, cash_result


def _update_nested_balance(
    value_result: dict[str, dict[str, float]],
    cash_result: dict[str, dict[str, float]],
    balance: BalanceData,
) -> None:
    currency = _currency_key(balance.get_symbol_name())
    _apply_balance_values(
        value_result,
        cash_result,
        currency,
        balance.get_margin(),
        balance.get_available_margin(),
        balance.get_unrealized_profit(),
    )
