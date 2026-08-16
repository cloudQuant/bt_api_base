"""Module-level docstring."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GatewayRuntimeRegistrar:
    """Class GatewayRuntimeRegistrar"""
    _adapters: dict[str, type[Any]] = {}

    @classmethod
    def register_adapter(cls, exchange_type: str, adapter_cls: type[Any]) -> None:
        """register_adapter method"""
        normalized = str(exchange_type).strip().upper()
        existing = cls._adapters.get(normalized)
        if existing is adapter_cls:
            return
        if existing is not None:
            logger.warning(
                "GatewayRuntimeRegistrar duplicate adapter registration ignored for %s",
                normalized,
            )
            return
        cls._adapters[normalized] = adapter_cls

    @classmethod
    def get_adapter(cls, exchange_type: str) -> type[Any] | None:
        """get_adapter method"""
        normalized = str(exchange_type).strip().upper()
        return cls._adapters.get(normalized)

    @classmethod
    def list_adapters(cls) -> list[str]:
        """list_adapters method"""
        return list(cls._adapters.keys())

    @classmethod
    def clear(cls) -> None:
        """clear method"""
        cls._adapters.clear()
