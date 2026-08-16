"""Shared gateway contracts exposed from :mod:`bt_api_base`."""

from __future__ import annotations

from bt_api_base.gateway.adapters import BaseGatewayAdapter, PluginGatewayAdapter
from bt_api_base.gateway.config import GatewayConfig
from bt_api_base.gateway.models import GatewayTick
from bt_api_base.gateway.protocol import CHANNEL_EVENT, CHANNEL_MARKET, dumps_message
from bt_api_base.gateway.registrar import GatewayRuntimeRegistrar
from bt_api_base.gateway.runtime import GatewayRuntime

# Keep aliases stable for projects expecting these legacy names.
ChannelMarket = CHANNEL_MARKET
ChannelEvent = CHANNEL_EVENT

__all__ = [
    "BaseGatewayAdapter",
    "CHANNEL_EVENT",
    "CHANNEL_MARKET",
    "ChannelEvent",
    "ChannelMarket",
    "GatewayConfig",
    "GatewayRuntime",
    "GatewayRuntimeRegistrar",
    "GatewayTick",
    "PluginGatewayAdapter",
    "dumps_message",
]
