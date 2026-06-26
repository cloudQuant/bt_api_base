from __future__ import annotations

from typing import Any

from bt_api_base.gateway.adapters.base import BaseGatewayAdapter
from bt_api_base.gateway.config import GatewayConfig
from bt_api_base.gateway.protocol import CHANNEL_EVENT, dumps_message, loads_message
from bt_api_base.gateway.registrar import GatewayRuntimeRegistrar
from bt_api_base.gateway.runtime import GatewayRuntime


class _OrderMapAdapter(BaseGatewayAdapter):
    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def subscribe_symbols(self, symbols: list[str]) -> dict[str, Any]:
        return {"accepted": symbols}

    def get_balance(self) -> dict[str, Any]:
        return {}

    def get_positions(self) -> list[dict[str, Any]]:
        return []

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.last_payload = dict(payload)
        return {
            "order_id": "venue-1",
            "external_order_id": "venue-1",
            "order_ref": payload.get("client_order_id") or "client-1",
            "details": {
                "request_id": payload.get("request_id"),
                "client_order_id": payload.get("client_order_id"),
            },
        }

    def cancel_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {}


class _RawAliasOrderMapAdapter(BaseGatewayAdapter):
    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def subscribe_symbols(self, symbols: list[str]) -> dict[str, Any]:
        return {"accepted": symbols}

    def get_balance(self) -> dict[str, Any]:
        return {}

    def get_positions(self) -> list[dict[str, Any]]:
        return []

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.last_payload = dict(payload)
        return {
            "ordId": "okx-venue-1",
            "clOrdId": payload.get("client_order_id"),
        }

    def cancel_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {}


def setup_function() -> None:
    GatewayRuntime.ADAPTER_REGISTRY.pop("UNITTEST_ORDERMAP", None)
    GatewayRuntime.ADAPTER_REGISTRY.pop("UNITTEST_RAW_ALIAS_ORDERMAP", None)
    GatewayRuntimeRegistrar.clear()


def teardown_function() -> None:
    GatewayRuntime.ADAPTER_REGISTRY.pop("UNITTEST_ORDERMAP", None)
    GatewayRuntime.ADAPTER_REGISTRY.pop("UNITTEST_RAW_ALIAS_ORDERMAP", None)
    GatewayRuntimeRegistrar.clear()


def test_place_order_records_adapter_client_and_venue_order_ids(tmp_path):
    GatewayRuntime.register_adapter("UNITTEST_ORDERMAP", _OrderMapAdapter)
    config = GatewayConfig(
        exchange_type="UNITTEST_ORDERMAP",
        asset_type="SPOT",
        account_id="acct-1",
        base_dir=str(tmp_path),
    )
    runtime = GatewayRuntime(config)
    runtime._adapter_connected = True

    result = runtime._dispatch(
        "place_order",
        {
            "request_id": "req-1",
            "strategy_id": "strategy-1",
            "symbol": "BTCUSDT",
            "client_order_id": "client-1",
        },
    )

    assert result["external_order_id"] == "venue-1"
    assert runtime.order_map.strategy_for_request("req-1") == "strategy-1"
    assert runtime.order_map.by_client("client-1").strategy_id == "strategy-1"
    assert runtime.order_map.strategy_for_venue("venue-1") == "strategy-1"


def test_place_order_promotes_bt_order_ref_and_records_raw_exchange_aliases(tmp_path):
    GatewayRuntime.register_adapter("UNITTEST_RAW_ALIAS_ORDERMAP", _RawAliasOrderMapAdapter)
    config = GatewayConfig(
        exchange_type="UNITTEST_RAW_ALIAS_ORDERMAP",
        asset_type="SWAP",
        account_id="acct-1",
        base_dir=str(tmp_path),
    )
    runtime = GatewayRuntime(config)
    runtime._adapter_connected = True

    result = runtime._dispatch(
        "place_order",
        {
            "request_id": "req-raw-1",
            "strategy_id": "strategy-raw",
            "symbol": "BTC-USDT-SWAP",
            "bt_order_ref": "bt-7",
        },
    )

    assert result["ordId"] == "okx-venue-1"
    assert runtime.adapter.last_payload["client_order_id"] == "bt-7"
    assert runtime.order_map.by_client("bt-7").strategy_id == "strategy-raw"
    assert runtime.order_map.strategy_for_venue("okx-venue-1") == "strategy-raw"


def test_handle_commands_uses_command_request_id_for_order_map(tmp_path):
    class FakeSocket:
        def __init__(self) -> None:
            self.sent: list[list[bytes]] = []
            self._payload = {
                "request_id": "cmd-1",
                "command": "place_order",
                "payload": {
                    "strategy_id": "strategy-1",
                    "symbol": "BTCUSDT",
                    "client_order_id": "client-1",
                },
            }

        def recv_multipart(self) -> list[bytes]:
            return [b"identity", dumps_message(self._payload)]

        def send_multipart(self, parts: list[bytes]) -> None:
            self.sent.append(parts)

    class FakePoller:
        def __init__(self, socket: FakeSocket) -> None:
            self.socket = socket

        def poll(self, timeout: int = 0) -> list[tuple[FakeSocket, int]]:
            return [(self.socket, 1)]

    GatewayRuntime.register_adapter("UNITTEST_ORDERMAP", _OrderMapAdapter)
    config = GatewayConfig(
        exchange_type="UNITTEST_ORDERMAP",
        asset_type="SPOT",
        account_id="acct-1",
        base_dir=str(tmp_path),
    )
    runtime = GatewayRuntime(config)
    runtime._adapter_connected = True
    socket = FakeSocket()
    runtime.command_socket = socket  # type: ignore[assignment]
    runtime.poller = FakePoller(socket)  # type: ignore[assignment]

    runtime._handle_commands()

    response = loads_message(socket.sent[0][-1])
    assert response["request_id"] == "cmd-1"
    assert response["status"] == "ok"
    assert runtime.adapter.last_payload["request_id"] == "cmd-1"
    assert runtime.order_map.strategy_for_request("cmd-1") == "strategy-1"


def test_event_payload_is_enriched_from_order_map(tmp_path):
    GatewayRuntime.register_adapter("UNITTEST_ORDERMAP", _OrderMapAdapter)
    config = GatewayConfig(
        exchange_type="UNITTEST_ORDERMAP",
        asset_type="SPOT",
        account_id="acct-1",
        base_dir=str(tmp_path),
    )
    runtime = GatewayRuntime(config)
    runtime.order_map.register(
        "req-1",
        "strategy-1",
        client_order_id="client-1",
        symbol="BTCUSDT",
    )

    event = runtime._enrich_event_payload(
        {
            "kind": "trade",
            "order_ref": "client-1",
            "external_order_id": "venue-2",
            "trade_id": "fill-1",
            "status": "completed",
        }
    )

    assert event["strategy_id"] == "strategy-1"
    assert event["request_id"] == "req-1"
    assert event["client_order_id"] == "client-1"
    assert event["symbol"] == "BTCUSDT"
    assert event["data_name"] == "BTCUSDT"
    assert runtime.order_map.strategy_for_venue("venue-2") == "strategy-1"


def test_runtime_caches_recent_trade_events_by_symbol(tmp_path):
    GatewayRuntime.register_adapter("UNITTEST_ORDERMAP", _OrderMapAdapter)
    config = GatewayConfig(
        exchange_type="UNITTEST_ORDERMAP",
        asset_type="SPOT",
        account_id="acct-1",
        base_dir=str(tmp_path),
    )
    runtime = GatewayRuntime(config)
    runtime._adapter_connected = True

    runtime.adapter.emit(
        CHANNEL_EVENT,
        {
            "kind": "trade",
            "symbol": "BTCUSDT",
            "trade_id": "fill-1",
            "side": "BUY",
            "volume": 0.02,
            "trade_commission": 0.5,
        },
    )
    runtime._flush_adapter_output()

    rows = runtime._dispatch("get_trades", {"symbol": "BTC-USDT", "limit": 10})

    assert rows == [
        {
            "kind": "trade",
            "symbol": "BTCUSDT",
            "trade_id": "fill-1",
            "side": "BUY",
            "volume": 0.02,
            "trade_commission": 0.5,
        }
    ]


def test_event_payload_is_enriched_from_raw_exchange_order_aliases(tmp_path):
    GatewayRuntime.register_adapter("UNITTEST_ORDERMAP", _OrderMapAdapter)
    config = GatewayConfig(
        exchange_type="UNITTEST_ORDERMAP",
        asset_type="SWAP",
        account_id="acct-1",
        base_dir=str(tmp_path),
    )
    runtime = GatewayRuntime(config)
    runtime.order_map.register(
        "req-raw-2",
        "strategy-raw",
        client_order_id="bt-8",
        venue_order_id="okx-venue-2",
        symbol="BTC-USDT-SWAP",
    )

    event = runtime._enrich_event_payload(
        {
            "kind": "trade",
            "ordId": "okx-venue-2",
            "tradeId": "fill-raw-1",
            "status": "completed",
        }
    )

    assert event["strategy_id"] == "strategy-raw"
    assert event["request_id"] == "req-raw-2"
    assert event["client_order_id"] == "bt-8"
    assert event["venue_order_id"] == "okx-venue-2"
    assert event["symbol"] == "BTC-USDT-SWAP"
