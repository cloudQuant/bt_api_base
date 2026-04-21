"""Shared gateway contracts exposed from :mod:`bt_api_base`."""

from __future__ import annotations

from bt_api_base.gateway.adapters import BaseGatewayAdapter, PluginGatewayAdapter
from bt_api_base.gateway.models import GatewayTick
from bt_api_base.gateway.protocol import CHANNEL_EVENT, CHANNEL_MARKET, dumps_message

# Keep aliases stable for projects expecting these legacy names.
ChannelMarket = CHANNEL_MARKET
ChannelEvent = CHANNEL_EVENT

__all__ = [
    "BaseGatewayAdapter",
    "PluginGatewayAdapter",
    "GatewayTick",
    "CHANNEL_EVENT",
    "CHANNEL_MARKET",
    "ChannelEvent",
    "ChannelMarket",
    "dumps_message",
]
