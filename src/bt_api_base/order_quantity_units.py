"""Provider-declared generic validation for direct order quantity units."""

from __future__ import annotations

from typing import Any

from bt_api_base.contract_errors import CapabilityNotSupportedError


def validate_generic_order_quantity_units(exchange_name: str, request: Any) -> None:
    """Preserve the former generic direct-backend unit restrictions."""
    del exchange_name
    if request.quantity_unit == "contracts":
        raise CapabilityNotSupportedError(
            "make_order",
            detail="explicit contract units require a contract-based venue",
            definite_reject=True,
        )
    if request.quantity_unit == "lots":
        raise CapabilityNotSupportedError(
            "make_order",
            detail="lots require a supported lot-based backend",
            definite_reject=True,
        )


__all__ = ("validate_generic_order_quantity_units",)
