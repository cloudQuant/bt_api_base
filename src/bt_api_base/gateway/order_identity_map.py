"""Bidirectional order ID mapping."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OrderEntry:
    request_id: str
    strategy_id: str
    client_order_id: str | None = None
    venue_order_id: str | None = None
    symbol: str | None = None
    status: str = "pending"
    extra: dict[str, Any] = field(default_factory=dict)


class OrderIdentityMap:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_request: dict[str, OrderEntry] = {}
        self._by_client_oid: dict[str, OrderEntry] = {}
        self._by_venue_oid: dict[str, OrderEntry] = {}

    def register(
        self,
        request_id: str,
        strategy_id: str,
        *,
        client_order_id: str | None = None,
        venue_order_id: str | None = None,
        symbol: str | None = None,
        **extra: Any,
    ) -> OrderEntry:
        entry = OrderEntry(
            request_id=request_id,
            strategy_id=strategy_id,
            client_order_id=client_order_id,
            venue_order_id=venue_order_id,
            symbol=symbol,
            extra=dict(extra),
        )
        with self._lock:
            self._by_request[request_id] = entry
            if client_order_id:
                self._by_client_oid[client_order_id] = entry
            if venue_order_id:
                self._by_venue_oid[venue_order_id] = entry
        return entry

    def set_client_order_id(self, request_id: str, client_order_id: str) -> OrderEntry | None:
        with self._lock:
            entry = self._by_request.get(request_id)
            if entry is None:
                return None
            entry.client_order_id = client_order_id
            self._by_client_oid[client_order_id] = entry
        return entry

    def set_venue_order_id(self, request_id: str, venue_order_id: str) -> OrderEntry | None:
        with self._lock:
            entry = self._by_request.get(request_id)
            if entry is None:
                return None
            entry.venue_order_id = venue_order_id
            self._by_venue_oid[venue_order_id] = entry
        return entry

    def set_venue_order_id_by_client(
        self, client_order_id: str, venue_order_id: str
    ) -> OrderEntry | None:
        with self._lock:
            entry = self._by_client_oid.get(client_order_id)
            if entry is None:
                return None
            entry.venue_order_id = venue_order_id
            self._by_venue_oid[venue_order_id] = entry
        return entry

    def update_status(self, request_id: str, status: str) -> OrderEntry | None:
        with self._lock:
            entry = self._by_request.get(request_id)
            if entry is not None:
                entry.status = status
        return entry

    def by_request(self, request_id: str) -> OrderEntry | None:
        with self._lock:
            return self._by_request.get(request_id)

    def by_client(self, client_order_id: str) -> OrderEntry | None:
        with self._lock:
            return self._by_client_oid.get(client_order_id)

    def by_venue(self, venue_order_id: str) -> OrderEntry | None:
        with self._lock:
            return self._by_venue_oid.get(venue_order_id)

    def strategy_for_request(self, request_id: str) -> str | None:
        entry = self.by_request(request_id)
        return entry.strategy_id if entry else None

    def strategy_for_venue(self, venue_order_id: str) -> str | None:
        entry = self.by_venue(venue_order_id)
        return entry.strategy_id if entry else None

    def remove(self, request_id: str) -> OrderEntry | None:
        with self._lock:
            entry = self._by_request.pop(request_id, None)
            if entry is None:
                return None
            if entry.client_order_id:
                self._by_client_oid.pop(entry.client_order_id, None)
            if entry.venue_order_id:
                self._by_venue_oid.pop(entry.venue_order_id, None)
        return entry

    def orders_for_strategy(self, strategy_id: str) -> list[OrderEntry]:
        with self._lock:
            return [entry for entry in self._by_request.values() if entry.strategy_id == strategy_id]

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._by_request)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "request_id": entry.request_id,
                    "strategy_id": entry.strategy_id,
                    "client_order_id": entry.client_order_id,
                    "venue_order_id": entry.venue_order_id,
                    "symbol": entry.symbol,
                    "status": entry.status,
                }
                for entry in self._by_request.values()
            ]
