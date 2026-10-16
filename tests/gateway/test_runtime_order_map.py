"""The retired remote gateway refuses startup before transport side effects."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from bt_api_base.exceptions import ConfigurationError
from bt_api_base.gateway import runtime_remote
from bt_api_base.gateway.config import GatewayConfig
from bt_api_base.gateway.registrar import GatewayRuntimeRegistrar
from bt_api_base.gateway.runtime_remote import GatewayRuntime

_MIGRATION_MESSAGE = (
    "Configuration error: The legacy bt_api_base.gateway.runtime_remote.GatewayRuntime is disabled; "
    "migrate startup to ServiceHost and configure service.order_entry."
)


class _Adapter:
    constructor_calls = 0

    def __init__(self, **kwargs):
        type(self).constructor_calls += 1

    def connect(self) -> None:
        raise AssertionError("legacy startup must not connect an adapter")


@pytest.fixture
def isolated_registries(monkeypatch):
    monkeypatch.setattr(GatewayRuntime, "ADAPTER_REGISTRY", {})
    monkeypatch.setattr(GatewayRuntimeRegistrar, "_adapters", {})


def test_remote_constructor_refuses_even_registered_adapter_before_side_effects(
    monkeypatch, isolated_registries
):
    _Adapter.constructor_calls = 0
    GatewayRuntime.register_adapter("UNITTEST_MIGRATION", _Adapter)

    zmq = Mock()
    plugin_import = Mock()
    thread_factory = Mock()
    monkeypatch.setattr(runtime_remote, "zmq", zmq)
    monkeypatch.setattr(runtime_remote, "import_module", plugin_import)
    monkeypatch.setattr(runtime_remote.threading, "Thread", thread_factory)

    config = GatewayConfig(exchange_type="UNITTEST_MIGRATION")
    with pytest.raises(ConfigurationError) as raised:
        GatewayRuntime(config)

    assert str(raised.value) == _MIGRATION_MESSAGE
    zmq.Context.instance.assert_not_called()
    zmq.Poller.assert_not_called()
    zmq.socket.assert_not_called()
    plugin_import.assert_not_called()
    thread_factory.assert_not_called()
    assert _Adapter.constructor_calls == 0


@pytest.mark.parametrize("method_name", ["start", "start_in_thread"])
def test_remote_start_methods_refuse_before_side_effects(monkeypatch, method_name):
    zmq = Mock()
    plugin_import = Mock()
    thread_factory = Mock()
    monkeypatch.setattr(runtime_remote, "zmq", zmq)
    monkeypatch.setattr(runtime_remote, "import_module", plugin_import)
    monkeypatch.setattr(runtime_remote.threading, "Thread", thread_factory)

    runtime = object.__new__(GatewayRuntime)
    with pytest.raises(ConfigurationError) as raised:
        getattr(runtime, method_name)()

    assert str(raised.value) == _MIGRATION_MESSAGE
    zmq.Context.instance.assert_not_called()
    zmq.Poller.assert_not_called()
    zmq.socket.assert_not_called()
    plugin_import.assert_not_called()
    thread_factory.assert_not_called()


def test_remote_resolution_and_plugin_loader_hooks_refuse_manual_registration(
    isolated_registries,
):
    GatewayRuntime.register_adapter("UNITTEST_MIGRATION", _Adapter)

    with pytest.raises(ConfigurationError) as load_error:
        GatewayRuntime._ensure_plugins_loaded()
    with pytest.raises(ConfigurationError) as resolve_error:
        GatewayRuntime.get_adapter_class("UNITTEST_MIGRATION")

    assert str(load_error.value) == _MIGRATION_MESSAGE
    assert str(resolve_error.value) == _MIGRATION_MESSAGE
