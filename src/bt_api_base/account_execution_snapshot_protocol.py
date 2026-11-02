"""Typed provider account facts bound to one query receipt and freshness lease."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from bt_api_base.account_protocol import AccountBalance, AccountOpenOrder, AccountPosition
from bt_api_base.account_session_protocol import AccountSessionSnapshot
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.query_protocol import QueryBatchReceipt, QuerySnapshotLease


def _require_utc(value: object, field_name: str) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _require_exact_tuple(value: object, item_type: type, field_name: str) -> tuple:
    if type(value) is not tuple or any(type(item) is not item_type for item in value):
        raise TypeError(f"{field_name} must be a tuple of exact {item_type.__name__} values")
    return value


@dataclass(frozen=True)
class AccountExecutionSnapshot:
    """Provider account facts selected from one complete, leased query batch.

    The DTO carries provider facts only. It does not attribute positions or
    orders to a Backtrader Strategy, declare fees, or grant execution authority.
    Its receipt and lease must still be validated by the SDK before use.
    """

    receipt: QueryBatchReceipt = field(repr=False)
    lease: QuerySnapshotLease = field(repr=False)
    account_session_snapshot: AccountSessionSnapshot = field(repr=False)
    validated_at: datetime = field(repr=False)
    account: tuple[AccountBalance, ...] = field(repr=False)
    positions: tuple[AccountPosition, ...] = field(repr=False)
    open_orders: tuple[AccountOpenOrder, ...] = field(repr=False)
    instruments: tuple[MarketInstrumentKey, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.receipt) is not QueryBatchReceipt:
            raise TypeError("receipt must be an exact QueryBatchReceipt")
        if type(self.lease) is not QuerySnapshotLease:
            raise TypeError("lease must be an exact QuerySnapshotLease")
        if type(self.account_session_snapshot) is not AccountSessionSnapshot:
            raise TypeError("account_session_snapshot must be an exact AccountSessionSnapshot")
        _require_utc(self.validated_at, "validated_at")
        _require_exact_tuple(self.account, AccountBalance, "account")
        _require_exact_tuple(self.positions, AccountPosition, "positions")
        _require_exact_tuple(self.open_orders, AccountOpenOrder, "open_orders")
        _require_exact_tuple(self.instruments, MarketInstrumentKey, "instruments")

    @property
    def source_ref(self) -> str | None:
        return self.receipt.source_ref

    @property
    def generation(self) -> str | None:
        return self.receipt.generation

    @property
    def receipt_digest(self) -> str:
        return self.receipt.receipt_digest

    @property
    def session_ref(self) -> str | None:
        return self.account_session_snapshot.session_ref


__all__ = ["AccountExecutionSnapshot"]
