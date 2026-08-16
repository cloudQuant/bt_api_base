"""Module-level docstring."""
from __future__ import annotations

import queue
from abc import ABC, abstractmethod
from typing import Any

from bt_api_base.logging_factory import get_logger


class BaseGatewayAdapter(ABC):
    """Class BaseGatewayAdapter"""
    def __init__(self, **kwargs: Any) -> None:
        """__init__ method"""
        self.kwargs = dict(kwargs)
        self.output_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.logger = get_logger("gateway")

    @abstractmethod
    def connect(self) -> None:
        """connect method"""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """disconnect method"""
        ...

    @abstractmethod
    def subscribe_symbols(self, symbols: list[str]) -> dict[str, Any]:
        """subscribe_symbols method"""
        ...

    @abstractmethod
    def get_balance(self) -> dict[str, Any]:
        """get_balance method"""
        ...

    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]:
        """get_positions method"""
        ...

    @abstractmethod
    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        """place_order method"""
        ...

    @abstractmethod
    def cancel_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        """cancel_order method"""
        ...

    def get_bars(self, symbol: str, timeframe: str, count: int) -> list[dict[str, Any]]:
        """Fetch historical OHLCV bars. Optional — default returns empty list."""
        return []

    def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        """Fetch contract/symbol specifications. Optional — default returns empty dict."""
        return {}

    def get_open_orders(self) -> list[dict[str, Any]]:
        """Fetch current pending orders. Optional — default returns empty list."""
        return []

    def get_trades(self, symbol: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch recent account trades/fills. Optional — default returns empty list."""
        return []

    def poll_output(self) -> tuple[str, Any] | None:
        """poll_output method"""
        try: return self.output_queue.get_nowait()
        except queue.Empty:
            return None

    def emit(self, channel: str, payload: Any) -> None:
        """emit method"""
        self.output_queue.put((channel, payload))
