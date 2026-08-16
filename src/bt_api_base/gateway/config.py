"""Gateway runtime configuration."""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_TCP_PORT_ASSIGNMENTS: dict[str, int] = {}
_TCP_RESERVED_BASE_PORTS: set[int] = set()


@dataclass
class GatewayConfig:
    """Configuration for a gateway runtime.

    Field set is the union of the standalone gateway runtime config
    (transport, ctp env selection, broker addressing) and the upstream
    gateway config (base_dir, poll_timeout_ms) so both runtime engines can
    be driven from a single config object.
    """

    runtime_name: str = ""
    exchange_type: str = "CTP"
    asset_type: str = "FUTURE"
    account_id: str = "default"
    command_endpoint: str = ""
    event_endpoint: str = ""
    market_endpoint: str = ""
    transport: str = "tcp"
    startup_timeout_sec: float = 30.0
    command_timeout_sec: float = 10.0
    broker_id: str = ""
    td_address: str = ""
    md_address: str = ""
    selected_ctp_env: str = ""
    selection_reason: str = ""
    base_dir: str = ""
    poll_timeout_ms: int = 100
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.exchange_type = str(self.exchange_type or "CTP").strip().upper()
        self.asset_type = str(self.asset_type or "FUTURE").strip().upper()
        self.account_id = str(self.account_id or "default").strip()
        self.transport = str(self.transport or "tcp").strip().lower() or "tcp"
        if self.transport == "ipc" and sys.platform.startswith("win"):
            self.transport = "tcp"
        if not self.base_dir:
            self.base_dir = str(Path(tempfile.gettempdir()) / "btgw")
        if not self.runtime_name:
            self.runtime_name = _runtime_name(
                "", self.exchange_type, self.asset_type, self.account_id
            )
        endpoints = _resolve_endpoints(
            self.runtime_name,
            self.transport,
            {
                "command_endpoint": self.command_endpoint,
                "event_endpoint": self.event_endpoint,
                "market_endpoint": self.market_endpoint,
                "base_dir": self.base_dir,
            },
        )
        self.command_endpoint = endpoints["command_endpoint"]
        self.event_endpoint = endpoints["event_endpoint"]
        self.market_endpoint = endpoints["market_endpoint"]

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
        base_dir = str(kwargs.get("gateway_base_dir") or kwargs.get("base_dir") or "")
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
            "gateway_base_dir",
            "base_dir",
            "gateway_poll_timeout_ms",
            "poll_timeout_ms",
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
            base_dir=base_dir,
            poll_timeout_ms=_coerce_int(
                kwargs.get("gateway_poll_timeout_ms") or kwargs.get("poll_timeout_ms"),
                100,
            ),
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
                "base_dir": self.base_dir,
            }
        )
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "exchange_type": self.exchange_type,
            "asset_type": self.asset_type,
            "account_id": self.account_id,
            "transport": self.transport,
            "base_dir": self.base_dir,
            "runtime_name": self.runtime_name,
            "command_endpoint": self.command_endpoint,
            "event_endpoint": self.event_endpoint,
            "market_endpoint": self.market_endpoint,
            "command_timeout_sec": self.command_timeout_sec,
            "startup_timeout_sec": self.startup_timeout_sec,
            "poll_timeout_ms": self.poll_timeout_ms,
        }

    def _build_runtime_name(self) -> str:
        safe_account = "".join(ch if ch.isalnum() else "-" for ch in self.account_id.lower()).strip(
            "-"
        )
        safe_account = safe_account or "default"
        return f"{self.exchange_type.lower()}-{self.asset_type.lower()}-{safe_account}"

    def _build_endpoints(self) -> tuple[str, str, str]:
        if self.transport == "tcp":
            base_port = self._tcp_base_port()
            host = "127.0.0.1"
            return (
                f"tcp://{host}:{base_port}",
                f"tcp://{host}:{base_port + 1}",
                f"tcp://{host}:{base_port + 2}",
            )

        root = Path(self.base_dir)
        root.mkdir(parents=True, exist_ok=True)
        runtime_root = root / self.runtime_name
        runtime_root.mkdir(parents=True, exist_ok=True)
        return (
            f"ipc://{runtime_root / 'command.sock'}",
            f"ipc://{runtime_root / 'event.sock'}",
            f"ipc://{runtime_root / 'market.sock'}",
        )

    def _tcp_base_port(self) -> int:
        seed_input = self.runtime_name
        worker_id = os.environ.get("PYTEST_XDIST_WORKER", "")
        if worker_id:
            seed_input = f"{worker_id}:{seed_input}"
        assigned = _TCP_PORT_ASSIGNMENTS.get(seed_input)
        if assigned is not None:
            return assigned

        seed = zlib.crc32(seed_input.encode("utf-8")) % 10000
        for offset in range(10000):
            slot = (seed + offset) % 10000
            candidate = 32000 + slot * 3
            if candidate not in _TCP_RESERVED_BASE_PORTS and _tcp_port_triplet_available(candidate):
                _TCP_RESERVED_BASE_PORTS.add(candidate)
                _TCP_PORT_ASSIGNMENTS[seed_input] = candidate
                return candidate

        raise RuntimeError("no available TCP gateway ports")


def _tcp_port_triplet_available(base_port: int, host: str = "127.0.0.1") -> bool:
    sockets: list[socket.socket] = []
    try:
        for port in range(base_port, base_port + 3):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(sock)
            sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        for sock in sockets:
            sock.close()


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


def _coerce_int(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
