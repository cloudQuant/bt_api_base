"""Gateway runtime configuration."""

from __future__ import annotations

import socket
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_TCP_PORT_ASSIGNMENTS: dict[str, int] = {}
_TCP_RESERVED_BASE_PORTS: set[int] = set()


@dataclass
class GatewayConfig:
    """Configuration for a standalone gateway runtime."""

    runtime_name: str
    exchange_type: str
    asset_type: str
    account_id: str
    command_endpoint: str
    event_endpoint: str
    market_endpoint: str
    transport: str = "tcp"
    startup_timeout_sec: float = 30.0
    command_timeout_sec: float = 10.0
    broker_id: str = ""
    td_address: str = ""
    md_address: str = ""
    selected_ctp_env: str = ""
    selection_reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_kwargs(cls, **kwargs: Any) -> "GatewayConfig":
        """Build a config object from launch-builder keyword arguments."""
        exchange_type = str(kwargs.get("exchange_type") or "CTP").strip().upper()
        asset_type = str(kwargs.get("asset_type") or "FUTURE").strip().upper()
        account_id = str(
            kwargs.get("account_id")
            or kwargs.get("investor_id")
            or kwargs.get("user_id")
            or "default"
        ).strip()
        runtime_name = _runtime_name(
            kwargs.get("gateway_runtime_name") or kwargs.get("runtime_name"),
            exchange_type,
            asset_type,
            account_id,
        )
        transport = str(kwargs.get("transport") or "tcp").strip().lower() or "tcp"
        endpoints = _resolve_endpoints(runtime_name, transport, kwargs)
        known = {
            "runtime_name",
            "gateway_runtime_name",
            "exchange_type",
            "asset_type",
            "account_id",
            "investor_id",
            "user_id",
            "command_endpoint",
            "event_endpoint",
            "market_endpoint",
            "gateway_command_endpoint",
            "gateway_event_endpoint",
            "gateway_market_endpoint",
            "transport",
            "gateway_startup_timeout_sec",
            "startup_timeout_sec",
            "gateway_command_timeout_sec",
            "command_timeout_sec",
            "broker_id",
            "td_address",
            "td_front",
            "md_address",
            "md_front",
            "selected_ctp_env",
            "selection_reason",
        }
        return cls(
            runtime_name=runtime_name,
            exchange_type=exchange_type,
            asset_type=asset_type,
            account_id=account_id,
            command_endpoint=endpoints["command_endpoint"],
            event_endpoint=endpoints["event_endpoint"],
            market_endpoint=endpoints["market_endpoint"],
            transport=transport,
            startup_timeout_sec=_coerce_float(
                kwargs.get("gateway_startup_timeout_sec")
                if kwargs.get("gateway_startup_timeout_sec") not in (None, "")
                else kwargs.get("startup_timeout_sec"),
                30.0,
            ),
            command_timeout_sec=_coerce_float(
                kwargs.get("gateway_command_timeout_sec")
                if kwargs.get("gateway_command_timeout_sec") not in (None, "")
                else kwargs.get("command_timeout_sec"),
                10.0,
            ),
            broker_id=str(kwargs.get("broker_id") or ""),
            td_address=str(kwargs.get("td_address") or kwargs.get("td_front") or ""),
            md_address=str(kwargs.get("md_address") or kwargs.get("md_front") or ""),
            selected_ctp_env=str(kwargs.get("selected_ctp_env") or ""),
            selection_reason=str(kwargs.get("selection_reason") or ""),
            extra={key: value for key, value in kwargs.items() if key not in known},
        )

    def to_kwargs(self) -> dict[str, Any]:
        """Return a keyword payload suitable for adapter construction."""
        payload = dict(self.extra)
        payload.update(
            {
                "runtime_name": self.runtime_name,
                "exchange_type": self.exchange_type,
                "asset_type": self.asset_type,
                "account_id": self.account_id,
                "command_endpoint": self.command_endpoint,
                "event_endpoint": self.event_endpoint,
                "market_endpoint": self.market_endpoint,
                "transport": self.transport,
                "gateway_startup_timeout_sec": self.startup_timeout_sec,
                "gateway_command_timeout_sec": self.command_timeout_sec,
                "broker_id": self.broker_id,
                "td_address": self.td_address,
                "td_front": self.td_address,
                "md_address": self.md_address,
                "md_front": self.md_address,
                "selected_ctp_env": self.selected_ctp_env,
                "selection_reason": self.selection_reason,
            }
        )
        return payload


def _runtime_name(value: Any, exchange_type: str, asset_type: str, account_id: str) -> str:
    raw = str(value or "").strip()
    if raw:
        return raw
    exchange = exchange_type.lower().replace("_", "-")
    asset = asset_type.lower().replace("_", "-")
    account = account_id or "default"
    return f"{exchange}-{asset}-{account}"


def _resolve_endpoints(
    runtime_name: str, transport: str, kwargs: dict[str, Any]
) -> dict[str, str]:
    command = kwargs.get("command_endpoint") or kwargs.get("gateway_command_endpoint") or ""
    event = kwargs.get("event_endpoint") or kwargs.get("gateway_event_endpoint") or ""
    market = kwargs.get("market_endpoint") or kwargs.get("gateway_market_endpoint") or ""
    if command and event and market:
        return {
            "command_endpoint": str(command),
            "event_endpoint": str(event),
            "market_endpoint": str(market),
        }
    if transport == "ipc":
        base_dir = Path(kwargs.get("base_dir") or tempfile.gettempdir())
        base_dir.mkdir(parents=True, exist_ok=True)
        stem = _safe_name(runtime_name)
        return {
            "command_endpoint": str(command or f"ipc://{base_dir / (stem + '-command.ipc')}"),
            "event_endpoint": str(event or f"ipc://{base_dir / (stem + '-event.ipc')}"),
            "market_endpoint": str(market or f"ipc://{base_dir / (stem + '-market.ipc')}"),
        }
    ports = _reserve_tcp_ports(runtime_name, 3)
    return {
        "command_endpoint": str(command or f"tcp://127.0.0.1:{ports[0]}"),
        "event_endpoint": str(event or f"tcp://127.0.0.1:{ports[1]}"),
        "market_endpoint": str(market or f"tcp://127.0.0.1:{ports[2]}"),
    }


def _reserve_tcp_ports(runtime_name: str, count: int) -> list[int]:
    cached = _TCP_PORT_ASSIGNMENTS.get(runtime_name)
    if cached is not None and cached not in _TCP_RESERVED_BASE_PORTS:
        _TCP_RESERVED_BASE_PORTS.add(cached)
        return [cached + idx for idx in range(count)]
    sockets: list[socket.socket] = []
    try:
        for _ in range(count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        ports = [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()
    _TCP_PORT_ASSIGNMENTS[runtime_name] = ports[0]
    _TCP_RESERVED_BASE_PORTS.add(ports[0])
    return ports


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)


def _coerce_float(value: Any, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
