"""Module-level docstring."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bt_api_base.plugins import loader as loader_module
from bt_api_base.plugins.errors import PluginOptionalDependencyError
from bt_api_base.plugins.loader import PluginLoader
from bt_api_base.plugins.protocol import PluginInfo
from bt_api_base.registry import ExchangeRegistry


class _DummyFeed:
    def __init__(self, data_queue: Any, **kwargs: Any) -> None:
        """__init__ method"""
        self.data_queue = data_queue
        self.kwargs = kwargs


class _DummyExchangeData:
    pass


@dataclass
class _FakeEntryPoint:
    name: str
    module: str
    loader: Any
    group: str = "bt_api.plugins"
    value: str = ""

    def load(self) -> Any:
        """load method"""
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
    """setup_function function"""
    ExchangeRegistry.clear()


def teardown_function() -> None:
    """teardown_function function"""
    ExchangeRegistry.clear()


def test_plugin_loader_loads_plugin_successfully(monkeypatch):
    """test_plugin_loader_loads_plugin_successfully function"""
    def register_plugin(registry: Any) -> PluginInfo:
        registry.register_feed("DEMO___SPOT", _DummyFeed)
        registry.register_exchange_data("DEMO___SPOT", _DummyExchangeData)
        registry.register_balance_handler("DEMO___SPOT", lambda accounts: ({}, {}))
        registry.register_stream("DEMO___SPOT", "subscribe", lambda *args: None)
        return _plugin_info("demo_plugin", ("DEMO___SPOT",))

    entry_point = _FakeEntryPoint("demo", "demo.plugin", register_plugin)
    loader = PluginLoader(ExchangeRegistry)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [entry_point])

    loader.load_all()

    assert "demo_plugin" in loader.loaded
    assert loader.loaded["demo_plugin"].plugin_module == "demo.plugin"
    assert ExchangeRegistry.get_feed_class("DEMO___SPOT") is _DummyFeed
    assert ExchangeRegistry.get_exchange_data_class("DEMO___SPOT") is _DummyExchangeData


def test_plugin_loader_skips_import_error(monkeypatch):
    """test_plugin_loader_skips_import_error function"""
    entry_point = _FakeEntryPoint("broken", "broken.plugin", ImportError("missing dependency"))
    loader = PluginLoader(ExchangeRegistry)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [entry_point])

    loader.load_all()

    assert "broken" in loader.failed
    assert loader.loaded == {}


def test_plugin_loader_records_optional_dependency_skip(monkeypatch, caplog):
    def register_plugin(registry: Any) -> PluginInfo:
        registry.register_feed("OPTIONAL___SPOT", _DummyFeed)
        raise PluginOptionalDependencyError("optional dependency missing: eth-account")

    entry_point = _FakeEntryPoint("optional", "optional.plugin", register_plugin)
    loader = PluginLoader(ExchangeRegistry)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [entry_point])

    with caplog.at_level("INFO"):
        loader.load_all()

    assert "optional" in loader.skipped
    assert loader.failed == {}
    assert loader.loaded == {}
    assert "plugin optional skipped" in caplog.text
    assert ExchangeRegistry.get_feed_class("OPTIONAL___SPOT") is None


def test_plugin_loader_skips_version_mismatch(monkeypatch):
    """test_plugin_loader_skips_version_mismatch function"""
    def register_plugin(registry: Any) -> PluginInfo:
        registry.register_feed("OLD___SPOT", _DummyFeed)
        return PluginInfo(
            name="old_plugin",
            version="1.0.0",
            core_requires=">=9.0",
            supported_exchanges=("OLD___SPOT",),
            supported_asset_types=("SPOT",),
        )

    entry_point = _FakeEntryPoint("old", "old.plugin", register_plugin)
    loader = PluginLoader(ExchangeRegistry)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [entry_point])

    loader.load_all()

    assert "old_plugin" in loader.failed
    assert ExchangeRegistry.get_feed_class("OLD___SPOT") is None


def test_plugin_loader_skips_duplicate_registration(monkeypatch):
    """test_plugin_loader_skips_duplicate_registration function"""
    def register_first(registry: Any) -> PluginInfo:
        registry.register_feed("DUP___SPOT", _DummyFeed)
        return _plugin_info("first_plugin", ("DUP___SPOT",))

    class _SecondDummyFeed(_DummyFeed):
        pass

    def register_second(registry: Any) -> PluginInfo:
        registry.register_feed("DUP___SPOT", _SecondDummyFeed)
        return _plugin_info("second_plugin", ("DUP___SPOT",))

    entry_points = [
        _FakeEntryPoint("first", "first.plugin", register_first),
        _FakeEntryPoint("second", "second.plugin", register_second),
    ]
    loader = PluginLoader(ExchangeRegistry)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: entry_points)

    loader.load_all()

    assert "first_plugin" in loader.loaded
    assert "second_plugin" in loader.failed
    assert ExchangeRegistry.get_feed_class("DUP___SPOT") is _DummyFeed


def test_plugin_loader_handles_no_plugins(monkeypatch, caplog):
    """test_plugin_loader_handles_no_plugins function"""
    loader = PluginLoader(ExchangeRegistry)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [])

    with caplog.at_level("INFO"):
        loader.load_all()

    assert loader.loaded == {}
    assert "discovered 0 entry points" in caplog.text


def test_plugin_loader_falls_back_when_aggregate_metadata_is_malformed(monkeypatch):
    entry_point = _FakeEntryPoint(
        "demo", "demo.plugin", lambda: None, value="demo.plugin:register_plugin"
    )
    duplicate_entry_point = _FakeEntryPoint(
        "legacy-demo", "demo.plugin", lambda: None, value="demo.plugin:register_plugin"
    )

    class _Distribution:
        entry_points = [entry_point, duplicate_entry_point]

    def raise_malformed_metadata() -> None:
        raise TypeError("expected string or bytes-like object, got 'NoneType'")

    loader = PluginLoader(ExchangeRegistry)
    monkeypatch.setattr(loader_module.importlib_metadata, "entry_points", raise_malformed_metadata)
    monkeypatch.setattr(loader_module.importlib_metadata, "distributions", lambda: [_Distribution()])

    assert loader._discover_entry_points("bt_api.plugins") == [entry_point]


def test_plugin_loader_records_unexpected_registration_error(monkeypatch):
    """test_plugin_loader_records_unexpected_registration_error function"""
    def register_plugin(registry: Any) -> PluginInfo:
        raise RuntimeError("boom")

    entry_point = _FakeEntryPoint("explodes", "explodes.plugin", register_plugin)
    loader = PluginLoader(ExchangeRegistry)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [entry_point])

    loader.load_all()

    assert "explodes" in loader.failed
    assert isinstance(loader.failed["explodes"], RuntimeError)


def test_plugin_loader_does_not_support_legacy_two_argument_callbacks(monkeypatch):
    def register_plugin(registry: Any, runtime_registrar: Any) -> PluginInfo:
        registry.register_feed("LEGACY___SPOT", _DummyFeed)
        return _plugin_info("legacy_plugin", ("LEGACY___SPOT",))

    entry_point = _FakeEntryPoint("legacy", "legacy.plugin", register_plugin)
    loader = PluginLoader(ExchangeRegistry)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [entry_point])

    loader.load_all()

    assert "legacy" in loader.failed
    assert isinstance(loader.failed["legacy"], TypeError)
    assert ExchangeRegistry.get_feed_class("LEGACY___SPOT") is None


def test_plugin_loader_does_not_mark_metadata_without_feed_registration_as_loaded(
    monkeypatch,
):
    def register_plugin(registry: Any) -> PluginInfo:
        return _plugin_info("unregistered_plugin", ("UNREGISTERED___SPOT",))

    entry_point = _FakeEntryPoint("unregistered", "unregistered.plugin", register_plugin)
    loader = PluginLoader(ExchangeRegistry)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [entry_point])

    loader.load_all()

    assert loader.loaded == {}
    assert "unregistered_plugin" in loader.failed
    assert "declared exchanges without feeds: UNREGISTERED___SPOT" in str(
        loader.failed["unregistered_plugin"]
    )
    assert ExchangeRegistry.get_feed_class("UNREGISTERED___SPOT") is None


def test_plugin_loader_rejects_plugins_that_declare_no_available_exchange(monkeypatch):
    def register_plugin(registry: Any) -> PluginInfo:
        return PluginInfo(
            name="not_migrated_plugin",
            version="1.2.3",
            core_requires=">=0.1,<1.0",
            supported_exchanges=(),
            supported_asset_types=(),
            capabilities=frozenset({"unavailable"}),
        )

    entry_point = _FakeEntryPoint("not-migrated", "not_migrated.plugin", register_plugin)
    loader = PluginLoader(ExchangeRegistry)
    monkeypatch.setattr(loader, "_discover_entry_points", lambda group: [entry_point])

    loader.load_all()

    assert loader.loaded == {}
    assert "not_migrated_plugin" in loader.failed
    assert "unavailable: it declares no supported exchanges" in str(
        loader.failed["not_migrated_plugin"]
    )
