"""Shared legacy projection for provider-declared direct order identity."""

from __future__ import annotations

from typing import Any


def project_legacy_order_identity(
    operation: str, request: Any, kwargs: dict[str, Any], default_order_id: Any
) -> Any:
    """Keep a provider's existing generic order-ID field mapping.

    This projection preserves the former SDK direct-backend mapping; it does
    not establish that a provider supports client IDs or a given operation.
    """
    del operation, request, kwargs
    return default_order_id


__all__ = ("project_legacy_order_identity",)
