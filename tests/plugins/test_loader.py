from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bt_api_base.gateway.registrar import GatewayRuntimeRegistrar
from bt_api_base.plugins.loader import PluginLoader
from bt_api_base.plugins.protocol import PluginInfo
from bt_api_base.registry import ExchangeRegistry


class _DummyFeed:
    def __init__(self, data_queue: Any, **kwargs: Any) -> None:
        self.data_queue = data_queue
        self.kwargs = kwargs


class _DummyExchangeData:
    pass


class _DummyAdapter:
    pass


@dataclass
class _FakeEntryPoint:
    name: str
    module: str
    loader: Any

    def load(self) -> Any:
        if isinstance(self.loader, BaseException):
            raise self.loader
        if callable(self.loader):
            return self.loader
        raise TypeError("invalid loader")


def _plugin_info(name: str, exchanges: tuple[str, ...]) -> PluginInfo:
    return PluginInfo(
        name=name,
        version="1.2.3",
        core_requires=">=0.1,<1.0",
        supported_exchanges=exchanges,
        supported_asset_types=("SPOT",),
    )


def setup_function() -> None:
    ExchangeRegistry.clear()
    GatewayRuntimeRegistrar.clear()


def teardown_function() -> None:
    ExchangeRegistry.clear()
    GatewayRuntimeRegistrar.clear()


def test_plugin_loader_loads_plugin_successfully(monkeypatch):
    def register_plugin(registry: Any, runtime_registrar: Any) -> PluginInfo:
        registry.register_feed("DEMO___SPOT", _DummyFeed)
        registry.register_exchange_data("DEMO___SPOT", _DummyExchangeData)
        registry.register_balance_handler("DEMO___SPOT", lambda accounts: ({}, {}))
        registry.register_stream("DEMO___SPOT", "subscribe", lambda *args: None)
        runtime_registrar.register_adapter("DEMO", _DummyAdapter)
        return _plugin_info("demo_plugin", ("DEMO___SPOT",))

    entry_point = _FakeEntryPoint("demo", "demo.plugin", register_plugin)
    loader = PluginLoader(ExchangeRegistry, GatewayRuntimeRegistrar)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [entry_point])

    loader.load_all()

    assert "demo_plugin" in loader.loaded
    assert loader.loaded["demo_plugin"].plugin_module == "demo.plugin"
    assert ExchangeRegistry.get_feed_class("DEMO___SPOT") is _DummyFeed
    assert ExchangeRegistry.get_exchange_data_class("DEMO___SPOT") is _DummyExchangeData
    assert GatewayRuntimeRegistrar.get_adapter("DEMO") is _DummyAdapter


def test_plugin_loader_skips_import_error(monkeypatch):
    entry_point = _FakeEntryPoint("broken", "broken.plugin", ImportError("missing dependency"))
    loader = PluginLoader(ExchangeRegistry, GatewayRuntimeRegistrar)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [entry_point])

    loader.load_all()

    assert "broken" in loader.failed
    assert loader.loaded == {}


def test_plugin_loader_skips_version_mismatch(monkeypatch):
    def register_plugin(registry: Any, runtime_registrar: Any) -> PluginInfo:
        registry.register_feed("OLD___SPOT", _DummyFeed)
        runtime_registrar.register_adapter("OLD", _DummyAdapter)
        return PluginInfo(
            name="old_plugin",
            version="1.0.0",
            core_requires=">=9.0",
            supported_exchanges=("OLD___SPOT",),
            supported_asset_types=("SPOT",),
        )

    entry_point = _FakeEntryPoint("old", "old.plugin", register_plugin)
    loader = PluginLoader(ExchangeRegistry, GatewayRuntimeRegistrar)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [entry_point])

    loader.load_all()

    assert "old_plugin" in loader.failed
    assert ExchangeRegistry.get_feed_class("OLD___SPOT") is None
    assert GatewayRuntimeRegistrar.get_adapter("OLD") is None


def test_plugin_loader_skips_duplicate_registration(monkeypatch):
    def register_first(registry: Any, runtime_registrar: Any) -> PluginInfo:
        registry.register_feed("DUP___SPOT", _DummyFeed)
        runtime_registrar.register_adapter("DUP", _DummyAdapter)
        return _plugin_info("first_plugin", ("DUP___SPOT",))

    class _SecondDummyFeed(_DummyFeed):
        pass

    class _SecondDummyAdapter:
        pass

    def register_second(registry: Any, runtime_registrar: Any) -> PluginInfo:
        registry.register_feed("DUP___SPOT", _SecondDummyFeed)
        runtime_registrar.register_adapter("DUP", _SecondDummyAdapter)
        return _plugin_info("second_plugin", ("DUP___SPOT",))

    entry_points = [
        _FakeEntryPoint("first", "first.plugin", register_first),
        _FakeEntryPoint("second", "second.plugin", register_second),
    ]
    loader = PluginLoader(ExchangeRegistry, GatewayRuntimeRegistrar)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: entry_points)

    loader.load_all()

    assert "first_plugin" in loader.loaded
    assert "second_plugin" in loader.failed
    assert ExchangeRegistry.get_feed_class("DUP___SPOT") is _DummyFeed
    assert GatewayRuntimeRegistrar.get_adapter("DUP") is _DummyAdapter


def test_plugin_loader_handles_no_plugins(monkeypatch, caplog):
    loader = PluginLoader(ExchangeRegistry, GatewayRuntimeRegistrar)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [])

    with caplog.at_level("INFO"):
        loader.load_all()

    assert loader.loaded == {}
    assert "discovered 0 entry points" in caplog.text


def test_plugin_loader_records_unexpected_registration_error(monkeypatch):
    def register_plugin(registry: Any, runtime_registrar: Any) -> PluginInfo:
        raise RuntimeError("boom")

    entry_point = _FakeEntryPoint("explodes", "explodes.plugin", register_plugin)
    loader = PluginLoader(ExchangeRegistry, GatewayRuntimeRegistrar)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [entry_point])

    loader.load_all()

    assert "explodes" in loader.failed
    assert isinstance(loader.failed["explodes"], RuntimeError)
