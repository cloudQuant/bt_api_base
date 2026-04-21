from __future__ import annotations

from typing import Any

from bt_api_base.gateway.adapters.base import BaseGatewayAdapter
from bt_api_base.gateway.models import GatewayTick
from bt_api_base.gateway.protocol import CHANNEL_MARKET


class PluginGatewayAdapter(BaseGatewayAdapter):
    """Bridge a plugin-owned direct client into the core gateway runtime."""

    direct_client_cls: type[Any] | None = None
    _LOCAL_ATTRS = {"client", "direct_client_cls", "kwargs", "logger", "output_queue"}

    def __init__(self, direct_client_cls: type[Any] | None = None, **kwargs: Any) -> None:
        client_cls = direct_client_cls or self.direct_client_cls
        if client_cls is None:
            raise ValueError("direct_client_cls must be provided")
        super().__init__(**kwargs)
        self.client = client_cls(**kwargs)
        self.kwargs = dict(getattr(self.client, "kwargs", kwargs))
        self.output_queue = getattr(self.client, "output_queue", self.output_queue)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    def __setattr__(self, name: str, value: Any) -> None:
        client = self.__dict__.get("client")
        if client is not None and name not in self._LOCAL_ATTRS and not hasattr(type(self), name):
            setattr(client, name, value)
            return
        super().__setattr__(name, value)

    def connect(self) -> None:
        self.client.connect()

    def disconnect(self) -> None:
        self.client.disconnect()

    def subscribe_symbols(self, symbols: list[str]) -> dict[str, Any]:
        return self.client.subscribe_symbols(symbols)

    def get_balance(self) -> dict[str, Any]:
        return self.client.get_balance()

    def get_positions(self) -> list[dict[str, Any]]:
        return self.client.get_positions()

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.place_order(payload)

    def cancel_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.cancel_order(payload)

    def get_bars(self, symbol: str, timeframe: str, count: int) -> list[dict[str, Any]]:
        getter = getattr(self.client, "get_bars", None)
        if getter is None:
            return []
        return getter(symbol, timeframe, count)

    def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        getter = getattr(self.client, "get_symbol_info", None)
        if getter is None:
            return {}
        return getter(symbol)

    def get_open_orders(self) -> list[dict[str, Any]]:
        getter = getattr(self.client, "get_open_orders", None)
        if getter is None:
            return []
        return getter()

    def poll_output(self) -> tuple[str, Any] | None:
        item = self.client.poll_output()
        if item is None:
            return None
        channel, payload = item
        if channel == CHANNEL_MARKET and isinstance(payload, dict):
            payload = GatewayTick.from_dict(payload)
        return channel, payload
