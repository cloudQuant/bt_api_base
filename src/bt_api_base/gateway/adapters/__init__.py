from __future__ import annotations

import warnings
from importlib import import_module

from bt_api_base.gateway.adapters.base import BaseGatewayAdapter
from bt_api_base.gateway.adapters.plugin_adapter import PluginGatewayAdapter

__all__ = [
    "BaseGatewayAdapter",
    "PluginGatewayAdapter",
]

_ADAPTER_IMPORTS = {}


class NoopGatewayAdapter(BaseGatewayAdapter):
    """Safe fallback for exchange-specific adapters not vendored in this package."""


def __getattr__(name: str):
    if name == "BaseGatewayAdapter":
        return BaseGatewayAdapter
    if name == "PluginGatewayAdapter":
        return PluginGatewayAdapter
    module_name = _ADAPTER_IMPORTS.get(name)
    if module_name is None:
        if name.endswith("GatewayAdapter"):
            warnings.warn(
                f"bt_api_base does not vendor {name}; returning NoopGatewayAdapter placeholder.",
                DeprecationWarning,
                stacklevel=2,
            )
            return NoopGatewayAdapter
        raise AttributeError(name)
    warnings.warn(
        f"bt_api_base.gateway.adapters.{name} is deprecated; import from {module_name} instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    module = import_module(module_name)
    return getattr(module, name)
