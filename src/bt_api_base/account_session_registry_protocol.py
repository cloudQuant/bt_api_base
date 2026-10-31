"""Provider-neutral selected-route and registration contracts.

The unified SDK owns route selection and the concrete registry. Provider
packages depend only on this small base contract so provider adapters never
need a reverse import from ``bt_api_py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from bt_api_base.account_session_protocol import (
    AccountSessionPort,
    SettlementConfirmationPort,
)


def _require_route_text(value: object, *, maximum: int) -> None:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.isprintable()
    ):
        raise ValueError("account_session_route_invalid")
    try:
        if len(value.encode("utf-8", errors="strict")) > maximum:
            raise ValueError("account_session_route_invalid")
    except UnicodeEncodeError:
        raise ValueError("account_session_route_invalid") from None


@dataclass(frozen=True)
class SelectedAccountSessionRoute:
    """SDK-selected provider inputs; never returned by account facade methods."""

    exchange_name: str
    client: object = field(repr=False, compare=False)
    environment: str | None = None
    settlement_context: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_route_text(self.exchange_name, maximum=256)
        if self.client is None:
            raise ValueError("account_session_route_invalid")
        if self.environment is not None:
            _require_route_text(self.environment, maximum=128)


AccountSessionFactory = Callable[[SelectedAccountSessionRoute], AccountSessionPort]
SettlementConfirmationFactory = Callable[
    [SelectedAccountSessionRoute], SettlementConfirmationPort
]


@runtime_checkable
class AccountSessionProviderRegistry(Protocol):
    """Neutral registration view supplied to one provider entry point."""

    def register(
        self,
        exchange_name: str,
        account_session_factory: AccountSessionFactory | None,
        settlement_factory: SettlementConfirmationFactory | None = None,
    ) -> None:
        """Register optional ports for one exact selected exchange route."""
        ...


__all__ = [
    "AccountSessionFactory",
    "AccountSessionProviderRegistry",
    "SelectedAccountSessionRoute",
    "SettlementConfirmationFactory",
]
