"""The retired standalone gateway fails closed before startup side effects."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from bt_api_base.exceptions import ConfigurationError
from bt_api_base.gateway import runtime as standalone_runtime
from bt_api_base.gateway.config import GatewayConfig
from bt_api_base.gateway.registrar import GatewayRuntimeRegistrar

_MIGRATION_MESSAGE = (
    "Configuration error: The legacy bt_api_base.gateway.GatewayRuntime is disabled; migrate startup to "
    "ServiceHost and configure service.order_entry."
)


class _Adapter:
    constructor_calls = 0

    def __init__(self) -> None:
        type(self).constructor_calls += 1

    def connect(self) -> None:
        raise AssertionError("legacy startup must not connect an adapter")


def test_standalone_constructor_refuses_even_registered_adapter_before_side_effects(
    monkeypatch,
):
    monkeypatch.setattr(GatewayRuntimeRegistrar, "_adapters", {})
    GatewayRuntimeRegistrar.register_adapter("UNITTEST_MIGRATION", _Adapter)
    _Adapter.constructor_calls = 0

    bridge_loader = Mock()
    adapter_resolver = Mock()
    thread_factory = Mock()
    monkeypatch.setattr(standalone_runtime, "_load_forwarding_bridge", bridge_loader)
    monkeypatch.setattr(standalone_runtime, "_resolve_adapter", adapter_resolver)
    monkeypatch.setattr(standalone_runtime.threading, "Thread", thread_factory)

    with pytest.raises(ConfigurationError) as raised:
        standalone_runtime.GatewayRuntime(GatewayConfig(exchange_type="UNITTEST_MIGRATION"))

    assert str(raised.value) == _MIGRATION_MESSAGE
    bridge_loader.assert_not_called()
    adapter_resolver.assert_not_called()
    thread_factory.assert_not_called()
    assert _Adapter.constructor_calls == 0


def test_standalone_start_method_refuses_without_runtime_state(monkeypatch):
    bridge_loader = Mock()
    adapter_resolver = Mock()
    thread_factory = Mock()
    monkeypatch.setattr(standalone_runtime, "_load_forwarding_bridge", bridge_loader)
    monkeypatch.setattr(standalone_runtime, "_resolve_adapter", adapter_resolver)
    monkeypatch.setattr(standalone_runtime.threading, "Thread", thread_factory)

    with pytest.raises(ConfigurationError) as raised:
        standalone_runtime.GatewayRuntime.start_in_thread(
            object.__new__(standalone_runtime.GatewayRuntime)
        )

    assert str(raised.value) == _MIGRATION_MESSAGE
    bridge_loader.assert_not_called()
    adapter_resolver.assert_not_called()
    thread_factory.assert_not_called()


def test_standalone_adapter_resolution_refuses_manual_registration(monkeypatch):
    monkeypatch.setattr(GatewayRuntimeRegistrar, "_adapters", {})
    GatewayRuntimeRegistrar.register_adapter("BINANCE", _Adapter)
    plugin_import = Mock()
    monkeypatch.setattr(standalone_runtime.importlib, "import_module", plugin_import)

    with pytest.raises(ConfigurationError) as raised:
        standalone_runtime._resolve_adapter("BINANCE")

    assert str(raised.value) == _MIGRATION_MESSAGE
    plugin_import.assert_not_called()


def test_default_plugin_loader_is_a_migration_error():
    with pytest.raises(ConfigurationError) as raised:
        standalone_runtime._load_default_plugin("BINANCE")

    assert str(raised.value) == _MIGRATION_MESSAGE
