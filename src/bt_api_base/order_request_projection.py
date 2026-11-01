"""Explicit marker for a provider's legacy generic order-request mapping."""

from __future__ import annotations


def legacy_order_request_projection() -> None:
    """Mark the pre-existing direct-feed projection selected by a provider.

    The SDK checks this function by identity; it is not an order mapper and
    does not itself establish that a provider supports a request or operation.
    """


__all__ = ("legacy_order_request_projection",)
