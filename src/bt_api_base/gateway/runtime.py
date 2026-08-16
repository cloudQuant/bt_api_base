"""Standalone gateway runtime."""

from __future__ import annotations

import importlib
import queue
import threading
import time
from dataclasses import asdict, is_dataclass
from typing import Any

from bt_api_base.gateway.config import GatewayConfig
from bt_api_base.gateway.registrar import GatewayRuntimeRegistrar
from bt_api_base.logging_factory import get_logger
from bt_api_base.registry import ExchangeRegistry

logger = get_logger("gateway.runtime")


class GatewayRuntime:
    """Run a registered gateway adapter behind ZeroMQ endpoints."""

    def __init__(self, config: GatewayConfig, **kwargs: Any) -> None:
        self.config = config
        self.kwargs = config.to_kwargs()
        self.kwargs.update(kwargs)
        self.adapter = None
        self.health = GatewayRuntimeHealth(self)
        self._state = "stopped"
        self._adapter_connected = False
        self._stop = threading.Event()
        self._pump_thread: threading.Thread | None = None
        self._command_server = None
        self._event_publisher = None
        self._market_publisher = None
        self._started_at = 0.0
        self._last_heartbeat = 0.0
        self._last_tick_time = 0.0
        self._last_order_time = 0.0
        self._tick_count = 0
        self._order_count = 0
        self._subscriptions: set[str] = set()
        self._recent_errors: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    @property
    def is_running(self) -> bool:
        return self._state == "running"

    def start_in_thread(self) -> None:
        if self.is_running:
            return
        bridge = _load_forwarding_bridge()
        adapter_cls = _resolve_adapter(self.config.exchange_type)
        self._stop.clear()
        self._state = "starting"
        self._started_at = time.time()
        self._last_heartbeat = self._started_at
        try:
            self._event_publisher = bridge.ZmqEventPublisher(self.config.event_endpoint)
            self._market_publisher = bridge.ZmqEventPublisher(self.config.market_endpoint)
            self._command_server = bridge.ZmqCommandServer(
                self.config.command_endpoint, self._handle_command
            )
            self._command_server.start()
            self.adapter = adapter_cls(**self.kwargs)
            self.adapter.connect()
            self._adapter_connected = True
            self._state = "running"
            self._pump_thread = threading.Thread(target=self._pump_adapter_output, daemon=True)
            self._pump_thread.start()
        except Exception as exc:
            self._record_error("startup", exc)
            self._state = "error"
            self._cleanup()
            raise

    def stop(self) -> None:
        if self._state == "stopped" and not self._adapter_connected:
            return
        self._state = "stopping"
        self._cleanup()
        self._state = "stopped"

    def _cleanup(self) -> None:
        self._stop.set()
        if self._pump_thread is not None:
            self._pump_thread.join(timeout=2.0)
            self._pump_thread = None
        if self._command_server is not None:
            self._command_server.stop()
            self._command_server = None
        if self._event_publisher is not None:
            self._event_publisher.close()
            self._event_publisher = None
        if self._market_publisher is not None:
            self._market_publisher.close()
            self._market_publisher = None
        if self.adapter is not None and self._adapter_connected:
            try:
                self.adapter.disconnect()
            except Exception as exc:
                self._record_error("disconnect", exc)
        self._adapter_connected = False

    def _handle_command(self, command: Any) -> Any:
        bridge = _load_forwarding_bridge()
        command_type = str(getattr(command, "command_type", "") or "").lower()
        try:
            if command_type == "get_account":
                payload = self.adapter.get_balance() if self.adapter is not None else {}
                return self._ack(command, bridge, True, "ok", payload=payload)
            if command_type == "list_positions":
                positions = self.adapter.get_positions() if self.adapter is not None else []
                return self._ack(command, bridge, True, "ok", payload={"positions": positions})
            if command_type == "list_orders":
                getter = getattr(self.adapter, "get_open_orders", None)
                orders = getter() if callable(getter) else []
                return self._ack(command, bridge, True, "ok", payload={"orders": orders})
            if command_type == "place_order":
                payload = self._payload_from_order_command(command)
                result = self.adapter.place_order(payload)
                self._order_count += 1
                self._last_order_time = time.time()
                return self._ack(
                    command,
                    bridge,
                    True,
                    str(result.get("status") or "accepted"),
                    order_id=str(result.get("id") or result.get("order_id") or ""),
                    payload=result,
                )
            if command_type == "cancel_order":
                payload = self._payload_from_order_command(command)
                result = self.adapter.cancel_order(payload)
                return self._ack(
                    command,
                    bridge,
                    True,
                    str(result.get("status") or "canceled"),
                    order_id=str(result.get("id") or result.get("order_id") or ""),
                    payload=result,
                )
            if command_type == "subscribe":
                symbols = list(getattr(command, "extra", {}).get("symbols") or [])
                if getattr(command, "symbol", ""):
                    symbols.append(str(command.symbol))
                result = self.adapter.subscribe_symbols(symbols)
                self._subscriptions.update(str(symbol) for symbol in symbols)
                return self._ack(command, bridge, True, "ok", payload=result)
            return self._ack(command, bridge, False, "rejected", reason=f"unsupported command: {command_type}")
        except Exception as exc:
            self._record_error("command", exc)
            return self._ack(command, bridge, False, "rejected", reason=str(exc))

    def _payload_from_order_command(self, command: Any) -> dict[str, Any]:
        payload = dict(getattr(command, "extra", {}) or {})
        payload.update(
            {
                "strategy_id": getattr(command, "strategy_id", ""),
                "account_id": getattr(command, "account_id", self.config.account_id),
                "symbol": getattr(command, "symbol", ""),
                "data_name": payload.get("data_name") or getattr(command, "symbol", ""),
                "side": getattr(command, "side", ""),
                "size": getattr(command, "size", 0.0),
                "order_type": getattr(command, "order_type", ""),
                "price": getattr(command, "price", None),
                "time_in_force": getattr(command, "time_in_force", ""),
                "client_order_id": getattr(command, "client_order_id", ""),
                "idempotency_key": getattr(command, "idempotency_key", ""),
                "order_id": getattr(command, "order_id", None),
                "exchange": getattr(command, "exchange", self.config.exchange_type),
                "market_type": getattr(command, "market_type", self.config.asset_type),
            }
        )
        return payload

    def _ack(
        self,
        command: Any,
        bridge: Any,
        accepted: bool,
        status: str,
        *,
        order_id: str = "",
        payload: dict[str, Any] | None = None,
        reason: str = "",
    ) -> Any:
        return bridge.CommandAck(
            command_id=str(getattr(command, "command_id", "") or "unknown"),
            idempotency_key=str(getattr(command, "idempotency_key", "") or "unknown"),
            accepted=accepted,
            status=status,
            account_id=str(getattr(command, "account_id", self.config.account_id) or ""),
            strategy_id=str(getattr(command, "strategy_id", "") or ""),
            order_id=order_id or None,
            reason=reason,
            payload=dict(payload or {}),
        )

    def _pump_adapter_output(self) -> None:
        while not self._stop.is_set():
            poll_output = getattr(self.adapter, "poll_output", None)
            if not callable(poll_output):
                time.sleep(0.05)
                continue
            try:
                item = poll_output()
            except queue.Empty:
                item = None
            except Exception as exc:
                self._record_error("adapter_output", exc)
                time.sleep(0.1)
                continue
            if item is None:
                time.sleep(0.01)
                continue
            try:
                self._publish_adapter_item(item)
            except Exception as exc:
                self._record_error("publish", exc)

    def _publish_adapter_item(self, item: Any) -> None:
        bridge = _load_forwarding_bridge()
        channel, payload = item
        channel_text = str(channel or "").lower()
        if channel_text == "market":
            event = _to_market_event(payload, bridge, self.config)
            if self._market_publisher is not None:
                self._market_publisher.publish(event)
            self._tick_count += 1
            self._last_tick_time = time.time()
            return
        event = _to_private_event(payload, bridge, self.config)
        if self._event_publisher is not None:
            self._event_publisher.publish(event)
        self._order_count += 1
        self._last_order_time = time.time()

    def _session_state(self) -> dict[str, Any]:
        getter = getattr(self.adapter, "get_session_state", None)
        if callable(getter):
            try:
                state = getter()
            except Exception as exc:
                self._record_error("session_state", exc)
                return {}
            return dict(state or {}) if isinstance(state, dict) else {}
        return {}

    def _record_error(self, source: str, exc: Exception) -> None:
        entry = {
            "source": source,
            "message": str(exc),
            "timestamp": int(time.time()),
        }
        logger.warning("Gateway runtime %s error: %s", source, exc)
        with self._lock:
            self._recent_errors.append(entry)
            self._recent_errors = self._recent_errors[-20:]


class GatewayRuntimeHealth:
    """Health snapshot facade for GatewayRuntime."""

    def __init__(self, runtime: GatewayRuntime) -> None:
        self._runtime = runtime

    def snapshot(self) -> dict[str, Any]:
        runtime = self._runtime
        config = runtime.config
        now = time.time()
        session = runtime._session_state()
        connected = runtime._adapter_connected and runtime._state == "running"
        auth_state = str(session.get("auth_state") or "unknown")
        login_state = str(session.get("login_state") or "unknown")
        is_failed = auth_state == "failed" or login_state in {"failed", "blocked"}
        return {
            "state": runtime._state,
            "is_healthy": bool(connected and not is_failed),
            "exchange": config.exchange_type,
            "asset_type": config.asset_type,
            "account_id": config.account_id,
            "market_connection": "connected" if connected else runtime._state,
            "trade_connection": "connected" if connected else runtime._state,
            "uptime_sec": int(now - runtime._started_at) if runtime._started_at else 0,
            "last_heartbeat": int(runtime._last_heartbeat or now),
            "heartbeat_age_sec": int(max(now - (runtime._last_heartbeat or now), 0)),
            "last_tick_time": int(runtime._last_tick_time) if runtime._last_tick_time else None,
            "last_order_time": int(runtime._last_order_time) if runtime._last_order_time else None,
            "strategy_count": 0,
            "symbol_count": len(runtime._subscriptions),
            "tick_count": runtime._tick_count,
            "order_count": runtime._order_count,
            "selected_ctp_env": config.selected_ctp_env,
            "td_front": config.td_address,
            "md_front": config.md_address,
            "selection_reason": config.selection_reason,
            "auth_state": auth_state,
            "login_state": login_state,
            "front_id": session.get("front_id", ""),
            "session_id": session.get("session_id", ""),
            "trading_day": session.get("trading_day", ""),
            "recent_errors": list(runtime._recent_errors),
        }


class _ForwardingBridge:
    def __init__(self) -> None:
        schema = importlib.import_module("bt_api_py.forwarding.schema")
        transport = importlib.import_module("bt_api_py.forwarding.transport")
        self.CommandAck = schema.CommandAck
        self.MarketEvent = schema.MarketEvent
        self.PrivateEvent = schema.PrivateEvent
        self.ZmqCommandServer = transport.ZmqCommandServer
        self.ZmqEventPublisher = transport.ZmqEventPublisher


_BRIDGE: _ForwardingBridge | None = None


def _load_forwarding_bridge() -> _ForwardingBridge:
    global _BRIDGE
    if _BRIDGE is None:
        try:
            _BRIDGE = _ForwardingBridge()
        except ImportError as exc:
            raise RuntimeError("bt_api_py.forwarding is required for GatewayRuntime") from exc
    return _BRIDGE


def _resolve_adapter(exchange_type: str) -> type[Any]:
    exchange = str(exchange_type or "").strip().upper()
    adapter_cls = GatewayRuntimeRegistrar.get_adapter(exchange)
    if adapter_cls is not None:
        return adapter_cls
    _load_default_plugin(exchange)
    adapter_cls = GatewayRuntimeRegistrar.get_adapter(exchange)
    if adapter_cls is None:
        raise RuntimeError(f"No gateway adapter registered for {exchange}")
    return adapter_cls


def _load_default_plugin(exchange_type: str) -> None:
    module_names = {
        "CTP": "bt_api_ctp.plugin",
        "IB_WEB": "bt_api_ib_web.plugin",
        "MT5": "bt_api_mt5.plugin",
        "BINANCE": "bt_api_binance.plugin",
        "OKX": "bt_api_okx.plugin",
    }
    module_name = module_names.get(exchange_type)
    if not module_name:
        return
    module = importlib.import_module(module_name)
    register = getattr(module, "register_plugin", None)
    if callable(register):
        register(ExchangeRegistry, GatewayRuntimeRegistrar)


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        return dict(data or {}) if isinstance(data, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _to_market_event(payload: Any, bridge: Any, config: GatewayConfig) -> Any:
    if isinstance(payload, bridge.MarketEvent):
        return payload
    data = _to_dict(payload)
    symbol = str(
        data.get("symbol")
        or data.get("instrument")
        or data.get("instrument_id")
        or data.get("data_name")
        or ""
    )
    return bridge.MarketEvent(
        event_type=str(data.get("event_type") or data.get("kind") or "tick"),
        exchange=str(data.get("exchange") or data.get("exchange_id") or config.exchange_type),
        market_type=str(data.get("market_type") or data.get("asset_type") or config.asset_type),
        symbol=symbol,
        payload=data,
        source="gateway",
    )


def _to_private_event(payload: Any, bridge: Any, config: GatewayConfig) -> Any:
    if isinstance(payload, bridge.PrivateEvent):
        return payload
    data = _to_dict(payload)
    event_type = str(data.get("event_type") or data.get("kind") or "event")
    return bridge.PrivateEvent(
        event_type=event_type,
        account_id=str(data.get("account_id") or config.account_id),
        strategy_id=str(data.get("strategy_id") or ""),
        client_order_id=str(data.get("client_order_id") or ""),
        order_ref=str(data.get("order_ref") or ""),
        external_order_id=str(data.get("external_order_id") or data.get("order_id") or ""),
        order_sys_id=str(data.get("order_sys_id") or ""),
        trade_id=str(data.get("trade_id") or ""),
        id_source=str(data.get("id_source") or ""),
        raw_fields=dict(data.get("raw_fields") or {}),
        payload=data,
    )
