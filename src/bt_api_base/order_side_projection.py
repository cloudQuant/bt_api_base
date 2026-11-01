"""Legacy shared order-side field selection for declared provider routes."""

from __future__ import annotations


def legacy_order_side_candidates(row, native, *, position=False):
    """Return legacy common aliases; values remain untrusted provider input."""
    del native
    names = (
        ("position_side", "posSide", "positionSide")
        if position
        else ("side", "order_side", "trade_side")
    )
    return [row.get(name) for name in names]


__all__ = ("legacy_order_side_candidates",)
