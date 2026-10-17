---
title: Plugins | bt_api_base
---

# Plugins

`bt_api_base.plugins.PluginLoader` discovers the `bt_api.plugins` entry-point
group. Each entry point must resolve to a one-argument
`register_plugin(registry)` callable. The loader gives it an isolated
`ExchangeRegistry`, checks the returned metadata against the registrations,
then commits valid feed registrations to the configured registry.

## Metadata

```python
from bt_api_base.plugins import PluginInfo

PluginInfo(
    name="example",
    version="1.0.0",
    core_requires=">=0.15,<1",
    supported_exchanges=("EXAMPLE___SPOT",),
    supported_asset_types=("spot",),
)
```

`PluginInfo` also accepts the optional `plugin_module` and `capabilities`
fields. `supported_exchanges` must exactly match the feeds registered in the
isolated registry.

## Register a feed

Declare the callback as an entry point in the exchange package:

```toml
[project.entry-points."bt_api.plugins"]
example = "bt_api_example.plugin:register_plugin"
```

Implement the callback with the isolated registry supplied by the loader:

```python
from bt_api_base.plugins import PluginInfo

def register_plugin(registry):
    registry.register_feed("EXAMPLE___SPOT", ExampleSpotFeed)
    return PluginInfo(
        name="example",
        version="1.0.0",
        core_requires=">=0.15,<1",
        supported_exchanges=("EXAMPLE___SPOT",),
        supported_asset_types=("spot",),
    )
```

Load discovered feeds into a registry:

```python
from bt_api_base.plugins import PluginLoader
from bt_api_base.registry import ExchangeRegistry

registry = ExchangeRegistry.create_isolated()
loader = PluginLoader(registry)
loader.load_all()
```

Plugin registration provides exchange feed and data contracts. The retired
`PluginProtocol.get_gateway()` and Base gateway adapter integration are not
part of the current plugin interface.

## 插件

`bt_api_base.plugins.PluginLoader` 会发现 `bt_api.plugins` entry point 组。每个入口必须指向
一个单参数 `register_plugin(registry)` 函数。Loader 会提供隔离的 `ExchangeRegistry`，核对
返回的元数据与实际注册项，再将有效 feed 注册提交到目标 registry。

`PluginInfo` 字段为 `name`、`version`、`core_requires`、`supported_exchanges`、
`supported_asset_types`，以及可选的 `plugin_module` 和 `capabilities`。声明的
`supported_exchanges` 必须与隔离 registry 中注册的 feed 完全一致。

```toml
[project.entry-points."bt_api.plugins"]
example = "bt_api_example.plugin:register_plugin"
```

```python
def register_plugin(registry):
    registry.register_feed("EXAMPLE___SPOT", ExampleSpotFeed)
    return PluginInfo(
        name="example",
        version="1.0.0",
        core_requires=">=0.15,<1",
        supported_exchanges=("EXAMPLE___SPOT",),
        supported_asset_types=("spot",),
    )
```

插件注册提供交易所 feed 与数据契约。已退役的
`PluginProtocol.get_gateway()` 和 Base gateway adapter 集成不属于当前插件接口。