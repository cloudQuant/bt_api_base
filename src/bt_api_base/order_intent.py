"""Provider-neutral position intent validation for typed order requests.

The request remains owned by its caller. This module does not authorize a
write, select an exchange, or derive a provider-native field.
"""

from __future__ import annotations

from typing import Any

from bt_api_base.exceptions import InvalidOrderError


def position_intent(request: Any) -> tuple[str, bool]:
    offset = request.offset or ("close" if request.reduce_only else "open")
    closing = offset in {"close", "close_today", "close_yesterday"}
    if request.reduce_only and not closing:
        raise InvalidOrderError("", request.symbol, "reduce_only contradicts an opening offset")
    side = request.position_side
    if request.position_mode == "dual_side" and side not in {"long", "short"}:
        raise InvalidOrderError(
            "", request.symbol, "dual_side orders require an explicit long or short position_side"
        )
    if side in {"long", "short"}:
        expected_buy = (side == "long") != closing
        if (request.side.value == "buy") != expected_buy:
            raise InvalidOrderError(
                "", request.symbol, "order side contradicts position_side and offset"
            )
    return offset, closing


__all__ = ("position_intent",)
