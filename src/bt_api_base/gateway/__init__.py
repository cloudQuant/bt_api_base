"""Shared gateway contracts exposed from :mod:`bt_api_base`."""

from __future__ import annotations

from bt_api_base.gateway.adapters import BaseGatewayAdapter, PluginGatewayAdapter
from bt_api_base.gateway.config import GatewayConfig
from bt_api_base.gateway.health import ConnectionState, GatewayHealth, GatewayState
from bt_api_base.gateway.models import GatewayTick
from bt_api_base.gateway.order_identity_map import OrderIdentityMap
from bt_api_base.gateway.order_ref_allocator import OrderRefAllocator
from bt_api_base.gateway.protocol import CHANNEL_EVENT, CHANNEL_MARKET, dumps_message
from bt_api_base.gateway.registrar import GatewayRuntimeRegistrar
from bt_api_base.gateway.runtime import GatewayRuntime
from bt_api_base.gateway.storage.tick_writer import TickWriter
from bt_api_base.gateway.subscription_manager import SubscriptionManager

# Keep aliases stable for projects expecting these legacy names.
ChannelMarket = CHANNEL_MARKET
ChannelEvent = CHANNEL_EVENT

__all__ = [
    "BaseGatewayAdapter",
    "PluginGatewayAdapter",
    "GatewayConfig",
    "GatewayRuntime",
    "GatewayHealth",
    "GatewayState",
    "ConnectionState",
    "SubscriptionManager",
    "OrderIdentityMap",
    "OrderRefAllocator",
    "TickWriter",
    "GatewayRuntimeRegistrar",
    "GatewayTick",
    "CHANNEL_EVENT",
    "CHANNEL_MARKET",
    "ChannelEvent",
    "ChannelMarket",
    "dumps_message",
]
