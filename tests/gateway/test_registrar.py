from __future__ import annotations

from bt_api_base.gateway.registrar import GatewayRuntimeRegistrar


class _AdapterOne:
    pass


class _AdapterTwo:
    pass


def setup_function() -> None:
    GatewayRuntimeRegistrar.clear()


def teardown_function() -> None:
    GatewayRuntimeRegistrar.clear()


def test_gateway_runtime_registrar_register_get_list_and_clear():
    GatewayRuntimeRegistrar.register_adapter("binance", _AdapterOne)

    assert GatewayRuntimeRegistrar.get_adapter("BINANCE") is _AdapterOne
    assert GatewayRuntimeRegistrar.get_adapter("binance") is _AdapterOne
    assert GatewayRuntimeRegistrar.list_adapters() == ["BINANCE"]

    GatewayRuntimeRegistrar.clear()

    assert GatewayRuntimeRegistrar.get_adapter("BINANCE") is None
    assert GatewayRuntimeRegistrar.list_adapters() == []


def test_gateway_runtime_registrar_ignores_conflicting_duplicate_registration(caplog):
    with caplog.at_level("WARNING"):
        GatewayRuntimeRegistrar.register_adapter("okx", _AdapterOne)
        GatewayRuntimeRegistrar.register_adapter("OKX", _AdapterTwo)

    assert GatewayRuntimeRegistrar.get_adapter("okx") is _AdapterOne
    assert "duplicate adapter registration ignored" in caplog.text
