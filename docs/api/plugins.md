---
title: Plugins | bt_api_base
---

<!-- English -->
# Plugins

The `plugins` module provides the **plugin system** for extending bt_api with exchange-specific implementations.

## Overview

Plugins follow a **discovery-based loading** pattern. Exchange plugins declare themselves via entry points, and the plugin loader discovers and loads them at runtime.

## PluginInfo

```python
@dataclass
class PluginInfo:
    """Metadata about a plugin."""
    name: str              # Plugin name (e.g., "binance")
    version: str           # Plugin version
    author: str            # Plugin author
    description: str        # Plugin description
    exchange_name: str      # Primary exchange name
    supported_venues: List[VenueType]  # Supported venue types
    dependencies: List[str]  # Required packages
```

## PluginProtocol

```python
class PluginProtocol(Protocol):
    """Protocol for exchange plugins."""

    @property
    def info(self) -> PluginInfo: ...

    def get_feed(self, venue_type: VenueType) -> AbstractVenueFeed: ...

    def get_gateway(self) -> Optional[BaseGatewayAdapter]: ...

    def validate_config(self, config: ExchangeConfig) -> bool: ...
```

## PluginLoader

```python
class PluginLoader:
    """Discovers and loads plugins at runtime."""

    @classmethod
    def load_plugin(cls, name: str) -> PluginProtocol:
        """Load a plugin by name."""
        ...

    @classmethod
    def load_all_plugins(cls) -> Dict[str, PluginProtocol]:
        """Discover and load all available plugins."""
        ...

    @classmethod
    def get_plugin_info(cls, name: str) -> Optional[PluginInfo]:
        """Get plugin metadata without loading."""
        ...
```

## Usage

### Loading a Plugin

```python
from bt_api_base.plugins import PluginLoader

# Load a specific plugin
binance = PluginLoader.load_plugin("bt_api_binance")
feed = binance.get_feed(VenueType.SPOT)

# Discover all available plugins
all_plugins = PluginLoader.load_all_plugins()
for name, plugin in all_plugins.items():
    print(f"{name}: {plugin.info.version}")
```

### Declaring a Plugin

In your exchange plugin's `pyproject.toml`:

```toml
[project.entry-points."bt_api.plugins"]
binance = "bt_api_binance.plugin: BinancePlugin"
```

Then in `bt_api_binance/plugin.py`:

```python
class BinancePlugin:
    @property
    def info(self) -> PluginInfo:
        return PluginInfo(
            name="binance",
            version="0.15.0",
            author="cloudQuant",
            description="Binance exchange plugin",
            exchange_name="BINANCE___SPOT",
            supported_venues=[VenueType.SPOT, VenueType.USDT_SWAP],
            dependencies=["requests", "websocket-client"],
        )

    def get_feed(self, venue_type: VenueType):
        return BinanceSpotFeed() if venue_type == VenueType.SPOT else BinanceSwapFeed()

    def validate_config(self, config: ExchangeConfig):
        return config.exchange_name.startswith("BINANCE")
```

---

## 中文

### 概述

`plugins` 模块提供**插件系统**，用于通过交易所特定实现扩展 bt_api。

### PluginInfo

| 字段 | 说明 |
|------|------|
| `name` | 插件名称 |
| `version` | 插件版本 |
| `author` | 插件作者 |
| `description` | 插件描述 |
| `exchange_name` | 主要交易所名称 |
| `supported_venues` | 支持的交易场所类型 |
| `dependencies` | 依赖包 |

### PluginLoader

| 方法 | 说明 |
|------|------|
| `load_plugin(name)` | 按名称加载插件 |
| `load_all_plugins()` | 发现并加载所有可用插件 |
| `get_plugin_info(name)` | 获取插件元数据（不加载） |

### 插件声明

在 `pyproject.toml` 中：

```toml
[project.entry-points."bt_api.plugins"]
binance = "bt_api_binance.plugin:BinancePlugin"
```

### 使用示例

```python
from bt_api_base.plugins import PluginLoader

binance = PluginLoader.load_plugin("bt_api_binance")
feed = binance.get_feed(VenueType.SPOT)
```
