from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PluginInfo:
    name: str
    version: str
    core_requires: str
    supported_exchanges: tuple[str, ...]
    supported_asset_types: tuple[str, ...]
    plugin_module: str = ""


__all__ = ["PluginInfo"]
