"""Legacy shared order-side field selection for declared provider routes."""

from __future__ import annotations


def legacy_order_side_candidates(row, *, position=False):
    """Return legacy common aliases; values remain untrusted provider input."""
    names = (
        ("position_side", "posSide", "positionSide")
        if position
        else ("side", "order_side", "trade_side")
    )
    return [row.get(name) for name in names]


def selected_order_side_candidates(row, *, position=False, side_fields, position_side_fields):
    """Read only the side aliases declared by the selected provider."""
    names = position_side_fields if position else side_fields
    return [row.get(name) for name in names]


__all__ = ("legacy_order_side_candidates", "selected_order_side_candidates")
