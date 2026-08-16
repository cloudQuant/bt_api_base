"""Reference-counted symbol subscription tracker."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any


class SubscriptionManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._strategy_symbols: dict[str, set[str]] = defaultdict(set)
        self._ref_counts: dict[str, int] = defaultdict(int)

    def add(self, strategy_id: str, symbols: list[str] | set[str]) -> set[str]:
        newly_subscribed: set[str] = set()
        with self._lock:
            for symbol in symbols:
                if symbol not in self._strategy_symbols[strategy_id]:
                    self._strategy_symbols[strategy_id].add(symbol)
                    self._ref_counts[symbol] += 1
                    if self._ref_counts[symbol] == 1:
                        newly_subscribed.add(symbol)
        return newly_subscribed

    def remove(self, strategy_id: str, symbols: list[str] | set[str]) -> set[str]:
        to_unsubscribe: set[str] = set()
        with self._lock:
            strategy_symbols = self._strategy_symbols.get(strategy_id)
            if strategy_symbols is None:
                return to_unsubscribe
            for symbol in symbols:
                if symbol in strategy_symbols:
                    strategy_symbols.discard(symbol)
                    self._ref_counts[symbol] -= 1
                    if self._ref_counts[symbol] <= 0:
                        self._ref_counts.pop(symbol, None)
                        to_unsubscribe.add(symbol)
            if not strategy_symbols:
                del self._strategy_symbols[strategy_id]
        return to_unsubscribe

    def remove_strategy(self, strategy_id: str) -> set[str]:
        with self._lock:
            strategy_symbols = self._strategy_symbols.pop(strategy_id, set())
            to_unsubscribe: set[str] = set()
            for symbol in strategy_symbols:
                self._ref_counts[symbol] -= 1
                if self._ref_counts[symbol] <= 0:
                    self._ref_counts.pop(symbol, None)
                    to_unsubscribe.add(symbol)
        return to_unsubscribe

    def get_active_symbols(self) -> set[str]:
        with self._lock:
            return set(self._ref_counts.keys())

    def get_strategy_symbols(self, strategy_id: str) -> set[str]:
        with self._lock:
            return set(self._strategy_symbols.get(strategy_id, set()))

    def get_strategies(self) -> list[str]:
        with self._lock:
            return list(self._strategy_symbols.keys())

    def ref_count(self, symbol: str) -> int:
        with self._lock:
            return self._ref_counts.get(symbol, 0)

    @property
    def symbol_count(self) -> int:
        with self._lock:
            return len(self._ref_counts)

    @property
    def strategy_count(self) -> int:
        with self._lock:
            return len(self._strategy_symbols)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "strategy_count": len(self._strategy_symbols),
                "symbol_count": len(self._ref_counts),
                "strategies": {
                    strategy_id: sorted(symbols)
                    for strategy_id, symbols in self._strategy_symbols.items()
                },
                "ref_counts": dict(self._ref_counts),
            }
