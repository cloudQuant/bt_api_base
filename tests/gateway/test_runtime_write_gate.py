"""Server-side write-gate tests for the standalone gateway runtime."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from bt_api_base.gateway import runtime as standalone_runtime
from bt_api_base.gateway.config import GatewayConfig


class _Adapter:
    def __init__(self) -> None:
        self.place_count = 0
        self.cancel_count = 0

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.place_count += 1
        return {"id": "venue-place"}

    def cancel_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.cancel_count += 1
        return {"id": "venue-cancel"}


class _Ack:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class _Bridge:
    CommandAck = _Ack


def _command(command_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        command_type=command_type,
        command_id=f"command-{command_type}",
        idempotency_key=f"idempotency-{command_type}",
        account_id="acct-1",
        strategy_id="strategy-1",
        symbol="BTCUSDT",
        side="BUY",
        size=1,
        order_type="LIMIT",
        price=100.0,
        time_in_force="GTC",
        client_order_id="client-1",
        order_id="venue-1",
        exchange="TEST",
        market_type="SPOT",
        extra={},
    )


def test_standalone_runtime_rejects_all_existing_write_commands_by_default(monkeypatch):
    adapter = _Adapter()
    runtime = standalone_runtime.GatewayRuntime(GatewayConfig())
    runtime.adapter = adapter
    monkeypatch.setattr(standalone_runtime, "_load_forwarding_bridge", lambda: _Bridge)

    place_ack = runtime._handle_command(_command("place_order"))
    cancel_ack = runtime._handle_command(_command("cancel_order"))

    assert place_ack.accepted is False
    assert place_ack.status == "rejected"
    assert place_ack.reason == "gateway trading is disabled"
    assert cancel_ack.accepted is False
    assert cancel_ack.status == "rejected"
    assert cancel_ack.reason == "gateway trading is disabled"
    assert adapter.place_count == 0
    assert adapter.cancel_count == 0


def test_standalone_runtime_requires_explicit_write_opt_in(monkeypatch):
    adapter = _Adapter()
    runtime = standalone_runtime.GatewayRuntime(GatewayConfig(enable_trading=True))
    runtime.adapter = adapter
    monkeypatch.setattr(standalone_runtime, "_load_forwarding_bridge", lambda: _Bridge)

    place_ack = runtime._handle_command(_command("place_order"))
    cancel_ack = runtime._handle_command(_command("cancel_order"))

    assert place_ack.accepted is True
    assert cancel_ack.accepted is True
    assert adapter.place_count == 1
    assert adapter.cancel_count == 1
